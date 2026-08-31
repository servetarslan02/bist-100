"""
ALPHA BIST — Central State Store v1.0

Tüm in-memory state'lerin DuckDB tabanlı persistansı.
Restart sonrası kaybolan tüm kritik state'ler burada saklanır.

Kapsanan bileşenler:
- Circuit Breaker durumları
- Provider Reliability skorları
- Rate Limiter token'ları
- Learning Loop tahmin geçmişi ve accuracy
- Signal Fusion adaptive ağırlıklar
- Correlation Tracker geçmişi
- Champion Challenger geçmişi

SSD dostu: WAL mode, batched writes, minimal I/O

Kullanım:
    from services.core.state_store import state_store

    # Circuit breaker
    state_store.save_circuit_state("yfinance", "CLOSED", 0)
    state = state_store.load_circuit_state("yfinance")

    # Learning loop
    state_store.save_learning_state({...})
    state = state_store.load_learning_state()

    # Signal fusion weights
    state_store.save_fusion_weights({"momentum": 0.3, ...})
    weights = state_store.load_fusion_weights()
"""

import atexit
import signal
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    duckdb = None
    HAS_DUCKDB = False

import functools

import structlog
from opentelemetry import trace

try:
    import orjson
except ImportError:
    raise ImportError("orjson is required") from None

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.state_store")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class _DummyDuckDBConn:
    """Otomatik eklendi."""
    def execute(self, *args, **kwargs) -> Any:
        """Otomatik eklendi."""
        return self

    def fetchall(self) -> Any:
        """Otomatik eklendi."""
        return []

    def fetchone(self) -> Any:
        """Otomatik eklendi."""
        return None

    def commit(self) -> Any:
        """Otomatik eklendi."""
        return None

    def close(self) -> Any:
        """Otomatik eklendi."""
        return None


class CentralStateStore:
    """Merkezi state store — tüm in-memory state'ler için DuckDB."""

    def __init__(self, db_path: str = "data/central_state.db"):
        """Otomatik eklendi."""
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, Any] = {}
        if HAS_DUCKDB:
            self._init_db()
        self._write_buffer: list[tuple] = []
        self._buffer_lock = threading.Lock()
        self._buffer_size = 10  # Küçük buffer — crash safety için
        self._last_flush = time.time()
        self._flush_interval = 30.0  # saniye
        self._periodic_thread: threading.Thread | None = None
        self._stop_periodic = threading.Event()
        self._start_periodic_flush()

    def _init_db(self) -> Any:
        """Tabloları oluştur."""
        try:
            with self._connect() as conn:
                if isinstance(conn, _DummyDuckDBConn):
                    return
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS circuit_breakers (
                        name TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        failure_count INTEGER DEFAULT 0,
                        last_failure_at TEXT,
                        last_success_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS provider_reliability (
                        name TEXT PRIMARY KEY,
                        total_calls INTEGER DEFAULT 0,
                        total_failures INTEGER DEFAULT 0,
                        recent_results TEXT DEFAULT '[]',
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS rate_limiters (
                        name TEXT PRIMARY KEY,
                        tokens REAL NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE SEQUENCE IF NOT EXISTS learning_pred_seq START 1")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_predictions (
                        id INTEGER PRIMARY KEY DEFAULT nextval('learning_pred_seq'),
                        ticker TEXT NOT NULL,
                        predicted_direction TEXT,
                        predicted_return REAL,
                        confidence REAL,
                        regime TEXT,
                        features TEXT,
                        outcome TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS fusion_weights (
                        key TEXT PRIMARY KEY,
                        weights TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS correlation_history (
                        var1 TEXT NOT NULL,
                        var2 TEXT NOT NULL,
                        corr_values TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (var1, var2)
                    )
                """)
                conn.execute("CREATE SEQUENCE IF NOT EXISTS champion_history_seq START 1")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS champion_history (
                        id INTEGER PRIMARY KEY DEFAULT nextval('champion_history_seq'),
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_ticker ON learning_predictions(ticker)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_created ON learning_predictions(created_at)")
                if hasattr(conn, "commit"):
                    conn.commit()
        except Exception as e:
            logger.debug("State store init skipped", error=str(e))

    @contextmanager
    def _connect(self, read_only: bool = False) -> Any:
        """DuckDB bağlantısı oluşturur, kilit durumunda read_only veya dummy fallback sağlar."""
        if not HAS_DUCKDB or duckdb is None:
            yield _DummyDuckDBConn()
            return

        conn = None
        try:
            conn = duckdb.connect(str(self._db_path), read_only=read_only)
        except Exception:
            try:
                conn = duckdb.connect(str(self._db_path), read_only=True)
            except Exception:
                conn = _DummyDuckDBConn()

        # SSD write reduction: DuckDB WAL ayarları
        if not read_only and hasattr(conn, "execute"):
            try:
                from services.core.debounce import configure_duckdb_wal
                configure_duckdb_wal(conn)
            except Exception:
                pass

        try:
            yield conn
        finally:
            if conn is not None and hasattr(conn, "close") and not isinstance(conn, _DummyDuckDBConn):
                try:
                    conn.close()
                except Exception as exc:
                    logger.debug("DuckDB connection close notice", error=str(exc))

    def _flush_buffer(self) -> Any:
        """Write buffer'ı flush et (batched write — SSD dostu)."""
        with self._buffer_lock:
            if not self._write_buffer:
                return
            batch = self._write_buffer.copy()
            self._write_buffer.clear()

        try:
            with self._connect() as conn:
                if isinstance(conn, _DummyDuckDBConn):
                    return
                for query, params in batch:
                    conn.execute(query, params)
                if hasattr(conn, "commit"):
                    conn.commit()
            self._last_flush = time.time()
        except Exception as e:
            logger.debug("State store buffer flush note", error=str(e))
            with self._buffer_lock:
                self._write_buffer = batch + self._write_buffer  # Re-queue on failure

    def _buffered_write(self, query: str, params: tuple) -> Any:
        """Buffered write — toplu yaz (SSD dostu)."""
        with self._buffer_lock:
            self._write_buffer.append((query, params))
            should_flush = len(self._write_buffer) >= self._buffer_size
        if should_flush:
            self._flush_buffer()

    def _start_periodic_flush(self) -> None:
        """Arka planda periyodik flush başlat."""
        def _loop() -> None:
            while not self._stop_periodic.wait(self._flush_interval):
                try:
                    self.periodic_flush()
                except Exception as e:
                    logger.debug("State store periodic flush error", error=str(e))
        self._periodic_thread = threading.Thread(target=_loop, daemon=True, name="state-periodic-flush")
        self._periodic_thread.start()

    def periodic_flush(self) -> Any:
        """Periyodik flush (scheduler tarafından çağrılır)."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    # ===================== CIRCUIT BREAKER =====================

    @otel_trace("state_store.save_circuit_state")
    def save_circuit_state(
        self,
        name: str,
        state: str,
        failure_count: int,
        last_failure: str | None = None,
        last_success: str | None = None,
    ) -> Any:
        """Circuit breaker durumunu kaydet."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO circuit_breakers
            (name, state, failure_count, last_failure_at, last_success_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (name, state, failure_count, last_failure, last_success, now),
        )

    @otel_trace("state_store.load_circuit_state")
    def load_circuit_state(self, name: str) -> dict[str, Any] | None:
        """Circuit breaker durumunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM circuit_breakers WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                return dict(zip(cols, row, strict=False))
        return None

    def load_all_circuit_states(self) -> dict[str, dict]:
        """Tüm circuit breaker durumlarını yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM circuit_breakers")
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            name_idx = cols.index("name")
            return {row[name_idx]: dict(zip(cols, row, strict=False)) for row in rows}

    # ===================== PROVIDER RELIABILITY =====================

    def save_provider_reliability(self, name: str, total_calls: int, total_failures: int, recent_results: list) -> Any:
        """Provider reliability skorunu kaydet."""
        now = datetime.now(UTC).isoformat()
        results_json = orjson.dumps(recent_results[-100:]).decode()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO provider_reliability
            (name, total_calls, total_failures, recent_results, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (name, total_calls, total_failures, results_json, now),
        )

    def load_provider_reliability(self, name: str) -> dict[str, Any] | None:
        """Provider reliability skorunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM provider_reliability WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                result = dict(zip(cols, row, strict=False))
                result["recent_results"] = orjson.loads(result["recent_results"])
                return result
        return None

    # ===================== RATE LIMITERS =====================

    def save_rate_limiter(self, name: str, tokens: float) -> Any:
        """Rate limiter token durumunu kaydet."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO rate_limiters (name, tokens, updated_at)
            VALUES (?, ?, ?)
        """,
            (name, tokens, now),
        )

    def load_rate_limiter(self, name: str) -> float | None:
        """Rate limiter token durumunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            row = conn.execute("SELECT tokens FROM rate_limiters WHERE name = ?", (name,)).fetchone()
            return row[0] if row else None

    # ===================== LEARNING LOOP =====================

    @otel_trace("state_store.save_learning_state")
    def save_learning_state(self, state: dict[str, Any]) -> Any:
        """Learning loop durumunu kaydet (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        for key, value in state.items():
            value = orjson.dumps(value, default=str).decode() if isinstance(value, (dict, list)) else str(value)
            self._buffered_write(
                """
                INSERT OR REPLACE INTO learning_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """,
                (key, value, now),
            )

    @otel_trace("state_store.load_learning_state")
    def load_learning_state(self) -> dict[str, Any]:
        """Learning loop durumunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM learning_state").fetchall()
            state = {}
            for row in rows:
                try:
                    state[row[0]] = orjson.loads(row[1])
                except Exception:
                    state[row[0]] = row[1]
            return state

    def save_prediction(
        self,
        ticker: str,
        predicted_direction: str,
        predicted_return: float,
        confidence: float,
        regime: str,
        features: dict,
    ) -> Any:
        """Tahmin kaydet (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        features_json = orjson.dumps(features, default=str).decode()
        self._buffered_write(
            """
            INSERT INTO learning_predictions
            (ticker, predicted_direction, predicted_return, confidence,
             regime, features, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (ticker, predicted_direction, predicted_return, confidence, regime, features_json, now),
        )

    def update_prediction_outcome(self, ticker: str, outcome: dict) -> Any:
        """Tahmin sonucunu güncelle (buffered — SSD dostu)."""
        outcome_json = orjson.dumps(outcome, default=str).decode()
        self._buffered_write(
            """
            UPDATE learning_predictions SET outcome = ?
            WHERE ticker = ? AND outcome IS NULL
            AND id = (SELECT id FROM learning_predictions
                      WHERE ticker = ? AND outcome IS NULL
                      ORDER BY created_at DESC LIMIT 1)
        """,
            (outcome_json, ticker, ticker),
        )

    def load_recent_predictions(self, limit: int = 100) -> list[dict]:
        """Son tahminleri yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM learning_predictions
                ORDER BY created_at DESC LIMIT ?
            """,
                (limit,),
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description] if cursor.description else []
            results = []
            for row in rows:
                d = dict(zip(cols, row, strict=False))
                if d.get("features"):
                    try:
                        d["features"] = orjson.loads(d["features"])
                    except Exception:
                        pass
                if d.get("outcome"):
                    try:
                        d["outcome"] = orjson.loads(d["outcome"])
                    except Exception:
                        pass
                results.append(d)
            return results

    def cleanup_old_predictions(self, keep_days: int = 30) -> Any:
        """Eski tahminleri temizle (SSD dostu)."""
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM learning_predictions
                WHERE created_at < (current_date - INTERVAL '1 day' * ?)
            """,
                (keep_days,),
            )
            conn.commit()

    # ===================== SIGNAL FUSION =====================

    def save_fusion_weights(self, weights: dict[str, float]) -> Any:
        """Signal fusion ağırlıklarını kaydet (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        weights_json = orjson.dumps(weights).decode()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO fusion_weights (key, weights, updated_at)
            VALUES ('adaptive', ?, ?)
        """,
            (weights_json, now),
        )

    def load_fusion_weights(self) -> dict[str, float] | None:
        """Signal fusion ağırlıklarını yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            row = conn.execute("SELECT weights FROM fusion_weights WHERE key = 'adaptive'").fetchone()
            if row:
                return orjson.loads(row[0])
        return None

    # ===================== CORRELATION TRACKER =====================

    def save_correlation_history(self, var1: str, var2: str, values: list[float]) -> Any:
        """Korelasyon geçmişini kaydet.

        Not: var1/var2 normalize edilerek (küçük, büyük) sırasıyla saklanır,
        böylece (A,B) ve (B,A) aynı kayıt olarak eşlenir.
        """
        now = datetime.now(UTC).isoformat()
        values_json = orjson.dumps(values).decode()
        norm_v1, norm_v2 = min(var1, var2), max(var1, var2)
        self._buffered_write(
            """
            INSERT OR REPLACE INTO correlation_history
            (var1, var2, corr_values, updated_at)
            VALUES (?, ?, ?, ?)
        """,
            (norm_v1, norm_v2, values_json, now),
        )

    def load_correlation_history(self, var1: str, var2: str) -> list[float] | None:
        """Korelasyon geçmişini yükle."""
        self._flush_buffer()
        norm_v1, norm_v2 = min(var1, var2), max(var1, var2)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT corr_values FROM correlation_history
                WHERE var1 = ? AND var2 = ?
            """,
                (norm_v1, norm_v2),
            ).fetchone()
            if row:
                return orjson.loads(row["corr_values"])
        return None

    # ===================== CHAMPION CHALLENGER =====================

    def save_champion_entry(self, data: dict) -> Any:
        """Champion challenger kaydı ekle (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        data_json = orjson.dumps(data, default=str).decode()
        self._buffered_write(
            """
            INSERT INTO champion_history (data, created_at)
            VALUES (?, ?)
        """,
            (data_json, now),
        )

    def load_champion_history(self, limit: int = 100) -> list[dict]:
        """Champion challenger geçmişini yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM champion_history
                ORDER BY created_at DESC LIMIT ?
            """,
                (limit,),
            ).fetchall()
            return [orjson.loads(row["data"]) for row in rows]

    # ===================== GENEL =====================

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        with self._connect() as conn:
            tables = [
                "circuit_breakers",
                "provider_reliability",
                "rate_limiters",
                "learning_state",
                "learning_predictions",
                "fusion_weights",
                "correlation_history",
                "champion_history",
            ]
            stats = {}
            for table in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()["cnt"]
                    stats[table] = count
                except Exception:
                    stats[table] = 0

        return {
            "db_path": str(self._db_path),
            "db_size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "buffer_size": len(self._write_buffer),  # len() is atomic on CPython
            "table_counts": stats,
        }

    def flush(self) -> Any:
        """Manuel flush."""
        self._flush_buffer()


# Singleton
state_store = CentralStateStore()


# =====================================================
# GRACEFUL SHUTDOWN: Signal handler + atexit
# Elektrik kesintisi veya SIGTERM/SIGINT'te buffer'ı flush et
# =====================================================


def _flush_on_exit() -> Any:
    """Otomatik eklendi."""
    try:
        state_store.flush()
    except Exception:
        logger.warning("Caught Exception in _flush_on_exit", exc_info=True)


def _flush_on_signal(signum, frame) -> Any:
    """Otomatik eklendi."""
    try:
        logger.info(f"Signal {signum} received, flushing state store buffer...")
        state_store.flush()
    except Exception:
        logger.warning("Caught Exception in _flush_on_signal", exc_info=True)


atexit.register(_flush_on_exit)
try:
    signal.signal(signal.SIGTERM, _flush_on_signal)
    signal.signal(signal.SIGINT, _flush_on_signal)
except (ValueError, OSError):
    logger.warning("Error in _flush_on_signal: (ValueError, OSError)", exc_info=True)
