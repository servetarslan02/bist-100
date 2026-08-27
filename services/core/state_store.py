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
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import structlog

try:
    import orjson
except ImportError:
    raise ImportError("orjson is required") from None

logger = structlog.get_logger()


class CentralStateStore:
    """Merkezi state store — tüm in-memory state'ler için DuckDB."""

    def __init__(self, db_path: str = "data/central_state.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._write_buffer: list[tuple] = []
        self._buffer_size = 10  # Küçük buffer — crash safety için
        self._last_flush = time.time()
        self._flush_interval = 30.0  # saniye

    def _init_db(self):
        """Tabloları oluştur."""
        with self._connect() as conn:
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_predictions (
                    id INTEGER PRIMARY KEY,
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS champion_history (
                    id INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_ticker ON learning_predictions(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_created ON learning_predictions(created_at)")
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = duckdb.connect(str(self._db_path))
        try:
            yield conn
        finally:
            conn.close()

    def _flush_buffer(self):
        """Write buffer'ı flush et (batched write — SSD dostu)."""
        if not self._write_buffer:
            return

        with self._connect() as conn:
            for query, params in self._write_buffer:
                conn.execute(query, params)
            conn.commit()

        self._write_buffer.clear()
        self._last_flush = time.time()

    def _buffered_write(self, query: str, params: tuple):
        """Buffered write — toplu yaz (SSD dostu)."""
        self._write_buffer.append((query, params))
        if len(self._write_buffer) >= self._buffer_size:
            self._flush_buffer()

    def periodic_flush(self):
        """Periyodik flush (scheduler tarafından çağrılır)."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    # ===================== CIRCUIT BREAKER =====================

    def save_circuit_state(
        self,
        name: str,
        state: str,
        failure_count: int,
        last_failure: str | None = None,
        last_success: str | None = None,
    ):
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

    def load_circuit_state(self, name: str) -> dict[str, Any] | None:
        """Circuit breaker durumunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM circuit_breakers WHERE name = ?", (name,)).fetchone()
            if row:
                return dict(row)
        return None

    def load_all_circuit_states(self) -> dict[str, dict]:
        """Tüm circuit breaker durumlarını yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM circuit_breakers").fetchall()
            return {row["name"]: dict(row) for row in rows}

    # ===================== PROVIDER RELIABILITY =====================

    def save_provider_reliability(self, name: str, total_calls: int, total_failures: int, recent_results: list):
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
            row = conn.execute("SELECT * FROM provider_reliability WHERE name = ?", (name,)).fetchone()
            if row:
                result = dict(row)
                result["recent_results"] = orjson.loads(result["recent_results"])
                return result
        return None

    # ===================== RATE LIMITERS =====================

    def save_rate_limiter(self, name: str, tokens: float):
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
            return row["tokens"] if row else None

    # ===================== LEARNING LOOP =====================

    def save_learning_state(self, state: dict[str, Any]):
        """Learning loop durumunu kaydet."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            for key, value in state.items():
                value = orjson.dumps(value, default=str).decode() if isinstance(value, (dict, list)) else str(value)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO learning_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                """,
                    (key, value, now),
                )
            conn.commit()

    def load_learning_state(self) -> dict[str, Any]:
        """Learning loop durumunu yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM learning_state").fetchall()
            state = {}
            for row in rows:
                try:
                    state[row["key"]] = orjson.loads(row["value"])
                except Exception:
                    state[row["key"]] = row["value"]
            return state

    def save_prediction(
        self,
        ticker: str,
        predicted_direction: str,
        predicted_return: float,
        confidence: float,
        regime: str,
        features: dict,
    ):
        """Tahmin kaydet."""
        now = datetime.now(UTC).isoformat()
        features_json = orjson.dumps(features, default=str).decode()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_predictions
                (ticker, predicted_direction, predicted_return, confidence,
                 regime, features, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (ticker, predicted_direction, predicted_return, confidence, regime, features_json, now),
            )
            conn.commit()

    def update_prediction_outcome(self, ticker: str, outcome: dict):
        """Tahmin sonucunu güncelle."""
        outcome_json = orjson.dumps(outcome, default=str).decode()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE learning_predictions SET outcome = ?
                WHERE ticker = ? AND outcome IS NULL
                AND id = (SELECT id FROM learning_predictions
                          WHERE ticker = ? AND outcome IS NULL
                          ORDER BY created_at DESC LIMIT 1)
            """,
                (outcome_json, ticker, ticker),
            )
            conn.commit()

    def load_recent_predictions(self, limit: int = 100) -> list[dict]:
        """Son tahminleri yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_predictions
                ORDER BY created_at DESC LIMIT ?
            """,
                (limit,),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("features"):
                    d["features"] = orjson.loads(d["features"])
                if d.get("outcome"):
                    d["outcome"] = orjson.loads(d["outcome"])
                results.append(d)
            return results

    def cleanup_old_predictions(self, keep_days: int = 30):
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

    def save_fusion_weights(self, weights: dict[str, float]):
        """Signal fusion ağırlıklarını kaydet."""
        now = datetime.now(UTC).isoformat()
        weights_json = orjson.dumps(weights).decode()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fusion_weights (key, weights, updated_at)
                VALUES ('adaptive', ?, ?)
            """,
                (weights_json, now),
            )
            conn.commit()

    def load_fusion_weights(self) -> dict[str, float] | None:
        """Signal fusion ağırlıklarını yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            row = conn.execute("SELECT weights FROM fusion_weights WHERE key = 'adaptive'").fetchone()
            if row:
                return orjson.loads(row["weights"])
        return None

    # ===================== CORRELATION TRACKER =====================

    def save_correlation_history(self, var1: str, var2: str, values: list[float]):
        """Korelasyon geçmişini kaydet."""
        now = datetime.now(UTC).isoformat()
        values_json = orjson.dumps(values).decode()
        f"{min(var1, var2)}:{max(var1, var2)}"
        self._buffered_write(
            """
            INSERT OR REPLACE INTO correlation_history
            (var1, var2, corr_values, updated_at)
            VALUES (?, ?, ?, ?)
        """,
            (var1, var2, values_json, now),
        )

    def load_correlation_history(self, var1: str, var2: str) -> list[float] | None:
        """Korelasyon geçmişini yükle."""
        self._flush_buffer()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT corr_values FROM correlation_history
                WHERE var1 = ? AND var2 = ?
            """,
                (var1, var2),
            ).fetchone()
            if row:
                return orjson.loads(row["corr_values"])
        return None

    # ===================== CHAMPION CHALLENGER =====================

    def save_champion_entry(self, data: dict):
        """Champion challenger kaydı ekle."""
        now = datetime.now(UTC).isoformat()
        data_json = orjson.dumps(data, default=str).decode()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO champion_history (data, created_at)
                VALUES (?, ?)
            """,
                (data_json, now),
            )
            conn.commit()

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
            "buffer_size": len(self._write_buffer),
            "table_counts": stats,
        }

    def flush(self):
        """Manuel flush."""
        self._flush_buffer()


# Singleton
state_store = CentralStateStore()


# =====================================================
# GRACEFUL SHUTDOWN: Signal handler + atexit
# Elektrik kesintisi veya SIGTERM/SIGINT'te buffer'ı flush et
# =====================================================


def _flush_on_exit():
    try:
        state_store.flush()
    except Exception:
        logger.warning("Caught Exception in _flush_on_exit", exc_info=True)


def _flush_on_signal(signum, frame):
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
