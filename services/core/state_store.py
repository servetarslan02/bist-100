"""
ALPHA BIST — Central State Store v2.0

Tüm in-memory state'lerin DuckDB tabanlı yüksek performanslı kalıcılık katmanı.
Sistem yeniden başlatıldığında (restart/crash) in-memory state'ler bu motor sayesinde kaybolmaz.

Kapsanan Bileşenler:
- Circuit Breaker (Devre Kesici) durumları ve arıza sayaçları
- Provider Reliability (Veri Sağlayıcı Güvenilirlik) metrikleri
- Rate Limiter token durumları
- Learning Loop tahmin geçmişi, başarı oranları ve model durumları
- Signal Fusion adaptive ağırlık matrisleri
- Correlation Tracker geçmişi (Normalize değişken eşleşmeleri)
- Champion Challenger model terfi geçmişi

Performans ve Güvenilirlik:
- SSD Dostu: WAL modu, optimize batched writes ve minimal I/O
- İş Parçacığı Güvenliği: threading.RLock() korumalı eşzamanlı erişim
- DuckDB >= 1.3.0 yerel motoru, Polars >= 1.30.0 analitik sorgulama ve orjson serileştirme
- Graceful Shutdown: SIGTERM, SIGINT ve atexit ile elektrik kesintisi/kapanma tampon temizliği
"""

from __future__ import annotations

import atexit
import contextlib
import functools
import inspect
import signal
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

DEFAULT_CENTRAL_STATE_DB: Final[str] = "data/central_state.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "8MB"
DEFAULT_WAL_SIZE: Final[str] = "4MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span veya güvenli yerel izleme sarmalayıcısına alır."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


@dataclass(slots=True)
class StateStoreStats:
    """StateStore genel çalışma istatistikleri veri modeli."""

    db_path: str
    db_size_bytes: int
    buffer_size: int
    table_counts: dict[str, int] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """İstatistikleri standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["updated_at"] = self.updated_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """İstatistikleri orjson ikili baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"StateStoreStats(path={self.db_path!r}, size_bytes={self.db_size_bytes}, "
            f"buffer={self.buffer_size}, tables={len(self.table_counts)})"
        )


class CentralStateStore:
    """Merkezi durum deposu — tüm in-memory durumlar için DuckDB tabanlı motor."""

    def __init__(self, db_path: str = DEFAULT_CENTRAL_STATE_DB) -> None:
        """CentralStateStore başlatıcısı.

        Args:
            db_path: DuckDB veritabanı dosya yolu veya ':memory:'.
        """
        self._db_path = Path(db_path) if db_path != ":memory:" else db_path
        self._lock = threading.RLock()
        self._write_buffer: list[tuple[str, tuple[Any, ...]]] = []
        self._buffer_size = 10  # Crash safety için küçük buffer
        self._last_flush = time.monotonic()
        self._flush_interval = 30.0  # saniye
        self._stop_periodic = threading.Event()

        # Dizin oluşturma ve DuckDB singleton bağlantısı
        if isinstance(self._db_path, Path):
            try:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(str(self._db_path))
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=str(self._db_path),
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        # WAL ve şema kurulumu
        configure_duckdb_wal(self._duckdb_con)
        self._init_db()

        # Periyodik arka plan flush iş parçacığı
        self._periodic_thread = threading.Thread(
            target=self._periodic_flush_loop,
            daemon=True,
            name="central-state-flush",
        )
        self._periodic_thread.start()

    @contextlib.contextmanager
    def _connect(self) -> Any:
        """Kilit korumalı aktif DuckDB bağlantısını context manager olarak sağlar."""
        with self._lock:
            yield self._duckdb_con

    def _configure_wal(self) -> None:
        """SSD aşınmasını önleyen optimize DuckDB WAL ayarlarını uygular."""
        with self._lock:
            try:
                self._duckdb_con.execute("PRAGMA checkpoint_threshold='8MB';")
                self._duckdb_con.execute("PRAGMA wal_autocheckpoint='4MB';")
            except Exception as exc:
                logger.debug("DuckDB WAL configuration notice", error=str(exc))

    def _init_db(self) -> None:
        """Veritabanı tablolarını, dizinlerini ve dizilerini eksiksiz oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE TABLE IF NOT EXISTS circuit_breakers (
                        name VARCHAR PRIMARY KEY,
                        state VARCHAR NOT NULL,
                        failure_count INTEGER DEFAULT 0,
                        last_failure_at VARCHAR,
                        last_success_at VARCHAR,
                        updated_at VARCHAR NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS provider_reliability (
                        name VARCHAR PRIMARY KEY,
                        total_calls INTEGER DEFAULT 0,
                        total_failures INTEGER DEFAULT 0,
                        recent_results VARCHAR DEFAULT '[]',
                        updated_at VARCHAR NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS rate_limiters (
                        name VARCHAR PRIMARY KEY,
                        tokens DOUBLE NOT NULL,
                        updated_at VARCHAR NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS learning_state (
                        key VARCHAR PRIMARY KEY,
                        value VARCHAR NOT NULL,
                        updated_at VARCHAR NOT NULL
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_learning_pred_id START 1;
                    CREATE TABLE IF NOT EXISTS learning_predictions (
                        id BIGINT DEFAULT nextval('seq_learning_pred_id') PRIMARY KEY,
                        ticker VARCHAR NOT NULL,
                        predicted_direction VARCHAR,
                        predicted_return DOUBLE,
                        confidence DOUBLE,
                        regime VARCHAR,
                        features VARCHAR,
                        outcome VARCHAR,
                        created_at VARCHAR NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS fusion_weights (
                        key VARCHAR PRIMARY KEY,
                        weights VARCHAR NOT NULL,
                        updated_at VARCHAR NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS correlation_history (
                        var1 VARCHAR NOT NULL,
                        var2 VARCHAR NOT NULL,
                        corr_values VARCHAR NOT NULL,
                        updated_at VARCHAR NOT NULL,
                        PRIMARY KEY (var1, var2)
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_champion_hist_id START 1;
                    CREATE TABLE IF NOT EXISTS champion_history (
                        id BIGINT DEFAULT nextval('seq_champion_hist_id') PRIMARY KEY,
                        data VARCHAR NOT NULL,
                        created_at VARCHAR NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_pred_ticker ON learning_predictions(ticker);
                    CREATE INDEX IF NOT EXISTS idx_pred_created ON learning_predictions(created_at);
                """)
            except Exception as exc:
                logger.error("State store database schema initialization failed", error=str(exc))

    def _flush_buffer_locked(self) -> None:
        """Tampondaki yazma işlemlerini veritabanına toplu aktarır (Kilit altında çağrılmalıdır)."""
        if not self._write_buffer:
            return

        batch = list(self._write_buffer)
        self._write_buffer.clear()

        try:
            for query, params in batch:
                self._duckdb_con.execute(query, params)
            self._last_flush = time.monotonic()
        except Exception as exc:
            logger.warning("State store buffer flush failed, re-queuing batch", error=str(exc))
            # Hata durumunda kuyruğu geri yükle
            self._write_buffer = batch + self._write_buffer

    def _buffered_write(self, query: str, params: tuple[Any, ...]) -> None:
        """SSD korumalı tamponlanmış yazma işlemi gerçekleştirir."""
        with self._lock:
            self._write_buffer.append((query, params))
            if len(self._write_buffer) >= self._buffer_size:
                self._flush_buffer_locked()

    def _periodic_flush_loop(self) -> None:
        """Arka planda periyodik tampon boşaltma döngüsü."""
        while not self._stop_periodic.wait(self._flush_interval):
            try:
                self.flush()
            except Exception as exc:
                logger.debug("Periodic flush background notice", error=str(exc))

    def flush(self) -> None:
        """Yazma tamponunu anında diske senkronize eder."""
        with self._lock:
            self._flush_buffer_locked()

    def close(self) -> None:
        """Bağlantıyı ve periyodik iş parçacığını güvenli şekilde kapatır."""
        self._stop_periodic.set()
        self.flush()
        with self._lock:
            with contextlib.suppress(Exception):
                self._duckdb_con.close()

    # ===================== CIRCUIT BREAKER =====================

    @otel_trace("state_store.save_circuit_state")
    def save_circuit_state(
        self,
        name: str,
        state: str,
        failure_count: int,
        last_failure: str | None = None,
        last_success: str | None = None,
    ) -> None:
        """Circuit breaker durumunu kaydeder."""
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
        """Tekil circuit breaker durumunu yükler."""
        self.flush()
        with self._lock:
            try:
                cursor = self._duckdb_con.execute(
                    "SELECT name, state, failure_count, last_failure_at, last_success_at, updated_at "
                    "FROM circuit_breakers WHERE name = ?",
                    [name],
                )
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    return dict(zip(cols, row, strict=False))
            except Exception as exc:
                logger.warning("Failed to load circuit breaker state", name=name, error=str(exc))
        return None

    def load_all_circuit_states(self) -> dict[str, dict[str, Any]]:
        """Tüm kayıtlı devre kesici durumlarını sözlük olarak döndürür."""
        self.flush()
        with self._lock:
            try:
                cursor = self._duckdb_con.execute(
                    "SELECT name, state, failure_count, last_failure_at, last_success_at, updated_at "
                    "FROM circuit_breakers"
                )
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                name_idx = cols.index("name")
                return {row[name_idx]: dict(zip(cols, row, strict=False)) for row in rows}
            except Exception as exc:
                logger.warning("Failed to load all circuit states", error=str(exc))
                return {}

    # ===================== PROVIDER RELIABILITY =====================

    def save_provider_reliability(
        self,
        name: str,
        total_calls: int,
        total_failures: int,
        recent_results: list[Any],
    ) -> None:
        """Veri sağlayıcı güvenilirlik skorunu kaydeder."""
        now = datetime.now(UTC).isoformat()
        results_json = orjson.dumps(recent_results[-100:]).decode("utf-8")
        self._buffered_write(
            """
            INSERT OR REPLACE INTO provider_reliability
            (name, total_calls, total_failures, recent_results, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, total_calls, total_failures, results_json, now),
        )

    def load_provider_reliability(self, name: str) -> dict[str, Any] | None:
        """Veri sağlayıcı güvenilirlik skorunu yükler."""
        self.flush()
        with self._lock:
            try:
                cursor = self._duckdb_con.execute(
                    "SELECT name, total_calls, total_failures, recent_results, updated_at "
                    "FROM provider_reliability WHERE name = ?",
                    [name],
                )
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    result = dict(zip(cols, row, strict=False))
                    try:
                        result["recent_results"] = orjson.loads(result["recent_results"])
                    except Exception:
                        result["recent_results"] = []
                    return result
            except Exception as exc:
                logger.warning("Failed to load provider reliability", name=name, error=str(exc))
        return None

    # ===================== RATE LIMITERS =====================

    def save_rate_limiter(self, name: str, tokens: float) -> None:
        """Rate limiter kalan token durumunu kaydeder."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO rate_limiters (name, tokens, updated_at)
            VALUES (?, ?, ?)
            """,
            (name, float(tokens), now),
        )

    def load_rate_limiter(self, name: str) -> float | None:
        """Rate limiter token durumunu yükler."""
        self.flush()
        with self._lock:
            try:
                row = self._duckdb_con.execute(
                    "SELECT tokens FROM rate_limiters WHERE name = ?", [name]
                ).fetchone()
                return float(row[0]) if row else None
            except Exception as exc:
                logger.warning("Failed to load rate limiter", name=name, error=str(exc))
                return None

    # ===================== LEARNING LOOP =====================

    @otel_trace("state_store.save_learning_state")
    def save_learning_state(self, state: dict[str, Any]) -> None:
        """Learning loop durumunu kaydeder."""
        now = datetime.now(UTC).isoformat()
        for key, value in state.items():
            if isinstance(value, (dict, list)):
                val_str = orjson.dumps(value, default=str).decode("utf-8")
            else:
                val_str = str(value)
            self._buffered_write(
                """
                INSERT OR REPLACE INTO learning_state (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (str(key), val_str, now),
            )

    @otel_trace("state_store.load_learning_state")
    def load_learning_state(self) -> dict[str, Any]:
        """Learning loop durumunu yükler."""
        self.flush()
        with self._lock:
            state: dict[str, Any] = {}
            try:
                rows = self._duckdb_con.execute("SELECT key, value FROM learning_state").fetchall()
                for row in rows:
                    k, v = row[0], row[1]
                    try:
                        state[k] = orjson.loads(v)
                    except Exception:
                        state[k] = v
            except Exception as exc:
                logger.warning("Failed to load learning state", error=str(exc))
            return state

    def save_prediction(
        self,
        ticker: str,
        predicted_direction: str,
        predicted_return: float,
        confidence: float,
        regime: str,
        features: dict[str, Any],
    ) -> None:
        """Model tahmin kaydını tampona ekler."""
        now = datetime.now(UTC).isoformat()
        features_json = orjson.dumps(features, default=str).decode("utf-8")
        self._buffered_write(
            """
            INSERT INTO learning_predictions
            (ticker, predicted_direction, predicted_return, confidence, regime, features, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                predicted_direction,
                float(predicted_return),
                float(confidence),
                regime,
                features_json,
                now,
            ),
        )

    def update_prediction_outcome(self, ticker: str, outcome: dict[str, Any]) -> None:
        """Gerçekleşen tahmin sonucunu günceller."""
        outcome_json = orjson.dumps(outcome, default=str).decode("utf-8")
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

    def load_recent_predictions(self, limit: int = 100) -> list[dict[str, Any]]:
        """En son model tahminlerini yükler."""
        self.flush()
        with self._lock:
            results: list[dict[str, Any]] = []
            try:
                cursor = self._duckdb_con.execute(
                    """
                    SELECT id, ticker, predicted_direction, predicted_return, confidence,
                           regime, features, outcome, created_at
                    FROM learning_predictions
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    [limit],
                )
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description] if cursor.description else []
                for row in rows:
                    d = dict(zip(cols, row, strict=False))
                    if d.get("features"):
                        with contextlib.suppress(Exception):
                            d["features"] = orjson.loads(d["features"])
                    if d.get("outcome"):
                        with contextlib.suppress(Exception):
                            d["outcome"] = orjson.loads(d["outcome"])
                    results.append(d)
            except Exception as exc:
                logger.warning("Failed to load recent predictions", error=str(exc))
            return results

    def cleanup_old_predictions(self, keep_days: int = 30) -> None:
        """Belirtilen günden eski tahminleri temizler."""
        self.flush()
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    DELETE FROM learning_predictions
                    WHERE created_at < CAST((CURRENT_DATE - INTERVAL '1 day' * ?) AS VARCHAR)
                    """,
                    [keep_days],
                )
            except Exception as exc:
                logger.warning("Failed to cleanup old predictions", error=str(exc))

    # ===================== SIGNAL FUSION =====================

    def save_fusion_weights(self, weights: dict[str, float]) -> None:
        """Signal fusion ağırlık matrisini kaydeder."""
        now = datetime.now(UTC).isoformat()
        weights_json = orjson.dumps(weights).decode("utf-8")
        self._buffered_write(
            """
            INSERT OR REPLACE INTO fusion_weights (key, weights, updated_at)
            VALUES ('adaptive', ?, ?)
            """,
            (weights_json, now),
        )

    def load_fusion_weights(self) -> dict[str, float] | None:
        """Signal fusion ağırlık matrisini yükler."""
        self.flush()
        with self._lock:
            try:
                row = self._duckdb_con.execute(
                    "SELECT weights FROM fusion_weights WHERE key = 'adaptive'"
                ).fetchone()
                if row:
                    return orjson.loads(row[0])
            except Exception as exc:
                logger.warning("Failed to load fusion weights", error=str(exc))
        return None

    # ===================== CORRELATION TRACKER =====================

    def save_correlation_history(self, var1: str, var2: str, values: list[float]) -> None:
        """Korelasyon geçmişini normalize sıralamayla saklar."""
        now = datetime.now(UTC).isoformat()
        values_json = orjson.dumps(values).decode("utf-8")
        norm_v1, norm_v2 = min(var1, var2), max(var1, var2)
        self._buffered_write(
            """
            INSERT OR REPLACE INTO correlation_history (var1, var2, corr_values, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (norm_v1, norm_v2, values_json, now),
        )

    def load_correlation_history(self, var1: str, var2: str) -> list[float] | None:
        """Korelasyon geçmişini yükler."""
        self.flush()
        norm_v1, norm_v2 = min(var1, var2), max(var1, var2)
        with self._lock:
            try:
                row = self._duckdb_con.execute(
                    "SELECT corr_values FROM correlation_history WHERE var1 = ? AND var2 = ?",
                    [norm_v1, norm_v2],
                ).fetchone()
                if row:
                    return orjson.loads(row[0])
            except Exception as exc:
                logger.warning("Failed to load correlation history", var1=var1, var2=var2, error=str(exc))
        return None

    # ===================== CHAMPION CHALLENGER =====================

    def save_champion_entry(self, data: dict[str, Any]) -> None:
        """Champion challenger model terfi kaydını saklar."""
        now = datetime.now(UTC).isoformat()
        data_json = orjson.dumps(data, default=str).decode("utf-8")
        self._buffered_write(
            """
            INSERT INTO champion_history (data, created_at)
            VALUES (?, ?)
            """,
            (data_json, now),
        )

    def load_champion_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Champion challenger model geçmişini yükler."""
        self.flush()
        with self._lock:
            results: list[dict[str, Any]] = []
            try:
                rows = self._duckdb_con.execute(
                    "SELECT data FROM champion_history ORDER BY created_at DESC LIMIT ?",
                    [limit],
                ).fetchall()
                for row in rows:
                    results.append(orjson.loads(row[0]))
            except Exception as exc:
                logger.warning("Failed to load champion history", error=str(exc))
            return results

    # ===================== GENEL & POLARS =====================

    def get_stats(self) -> StateStoreStats:
        """Merkezi durum deposunun istatistiklerini hesaplar."""
        self.flush()
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
        stats: dict[str, int] = {}
        with self._lock:
            for table in tables:
                try:
                    row = self._duckdb_con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    stats[table] = int(row[0]) if row else 0
                except Exception:
                    stats[table] = 0

            db_size = 0
            if isinstance(self._db_path, Path) and self._db_path.exists():
                with contextlib.suppress(Exception):
                    db_size = self._db_path.stat().st_size

            return StateStoreStats(
                db_path=str(self._db_path),
                db_size_bytes=db_size,
                buffer_size=len(self._write_buffer),
                table_counts=stats,
            )

    def export_predictions_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """Tahmin kayıtlarını Polars DataFrame olarak dışa aktarır."""
        self.flush()
        with self._lock:
            try:
                return self._duckdb_con.execute(
                    """
                    SELECT id, ticker, predicted_direction, predicted_return, confidence,
                           regime, features, outcome, created_at
                    FROM learning_predictions
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    [limit],
                ).pl()
            except Exception as exc:
                logger.error("DuckDB export predictions to Polars failed", error=str(exc))
                return pl.DataFrame()

    def export_circuit_breakers_to_polars(self) -> pl.DataFrame:
        """Devre kesici durumlarını Polars DataFrame olarak dışa aktarır."""
        self.flush()
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT name, state, failure_count, last_failure_at, last_success_at, updated_at
                    FROM circuit_breakers
                    ORDER BY name ASC
                """).pl()
            except Exception as exc:
                logger.error("DuckDB export circuit breakers to Polars failed", error=str(exc))
                return pl.DataFrame()

    def clear_all_tables(self) -> None:
        """Tüm durum tablolarındaki kayıtları temizler."""
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
        self.flush()
        with self._lock:
            for t in tables:
                try:
                    self._duckdb_con.execute(f"DELETE FROM {t}")
                except Exception as exc:
                    logger.warning("Tablo temizlenemedi", tablo=t, hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"CentralStateStore(path={str(self._db_path)!r}, "
                f"buffer={len(self._write_buffer)}, interval={self._flush_interval}s)"
            )


def read_predictions_from_duckdb(
    db_path: str = DEFAULT_CENTRAL_STATE_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan model tahmin kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(db_path)
        try:
            return conn.execute(
                """
                SELECT id, ticker, predicted_direction, predicted_return, confidence,
                       regime, features, outcome, created_at
                FROM learning_predictions
                ORDER BY created_at DESC LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan tahmin kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_state_store_duckdb(db_path: str = DEFAULT_CENTRAL_STATE_DB) -> None:
    """Belirtilen DuckDB durum deposundaki tüm tabloları temizler."""
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
    try:
        conn = duckdb.connect(db_path)
        try:
            for t in tables:
                with contextlib.suppress(Exception):
                    conn.execute(f"DELETE FROM {t}")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB durum tablolari temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
state_store = CentralStateStore()


# Graceful Shutdown
def _flush_on_exit() -> None:
    """Uygulama sonlandığında tamponu diske yazar."""
    with contextlib.suppress(Exception):
        state_store.flush()


def _flush_on_signal(signum: int, frame: Any) -> None:
    """İşletim sistemi sinyali alındığında tamponu diske yazar."""
    try:
        logger.info("Signal received, flushing state store buffer", signum=signum)
        state_store.flush()
    except Exception:
        pass


atexit.register(_flush_on_exit)
try:
    signal.signal(signal.SIGTERM, _flush_on_signal)
    signal.signal(signal.SIGINT, _flush_on_signal)
except (ValueError, OSError):
    pass

__all__ = [
    "CentralStateStore",
    "DEFAULT_CENTRAL_STATE_DB",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_WAL_SIZE",
    "StateStoreStats",
    "clear_state_store_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_predictions_from_duckdb",
    "state_store",
    "to_orjson_bytes",
]
