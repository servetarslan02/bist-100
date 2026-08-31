"""
ALPHA BIST — Downtime Tracker v2.0 (DuckDB)

Sistem downtime süresini takip eder.
Kişisel PC senaryosu için kritik:

- Kapanış zamanını kaydeder (graceful shutdown)
- Açılışta ne kadar kapalı kaldığını hesaplar
- Catch-up modunu tetikler
- Downtime istatistiklerini tutar
- DuckDB tabanlı — restart sonrası kaybolmaz

Kullanım:
    from services.core.downtime_tracker import downtime_tracker

    # Shutdown'ta
    downtime_tracker.record_shutdown()

    # Startup'ta
    downtime = downtime_tracker.get_downtime()
    if downtime > timedelta(hours=1):
        await backfill_manager.backfill_all(...)
"""

import functools
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.downtime_tracker")


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


class DowntimeTracker:
    """Sistem downtime takipçisi — DuckDB tabanlı.

    Özellikler:
    - Graceful shutdown kaydı
    - Startup'ta downtime hesaplama
    - Downtime istatistikleri
    - Catch-up tetikleme eşiği
    - Geçmiş downtime kayıtları
    """

    # Catch-up eşikleri
    CATCHUP_THRESHOLDS = {
        "data_backfill": timedelta(minutes=30),  # 30 dk+ → veri backfill
        "model_refresh": timedelta(hours=6),  # 6 saat+ → model yenile
        "full_recalibration": timedelta(hours=24),  # 24 saat+ → tam kalibrasyon
    }

    def __init__(self, db_path: str = "data/downtime.db"):
        """Otomatik eklendi."""
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._startup_time: float | None = None
        self._downtime_seconds: float = 0.0
        self._init_db()

    def _init_db(self) -> Any:
        """DuckDB tablolarını oluştur."""
        with self._connect() as conn:
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS shutdown_events_seq START 1
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shutdown_events (
                    id BIGINT PRIMARY KEY DEFAULT nextval('shutdown_events_seq'),
                    shutdown_at TEXT NOT NULL,
                    shutdown_timestamp REAL NOT NULL,
                    startup_at TEXT,
                    startup_timestamp REAL,
                    downtime_seconds REAL DEFAULT 0,
                    catchup_level TEXT DEFAULT 'none'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS downtime_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shutdown_at ON shutdown_events(shutdown_at)")
            conn.commit()

    @contextmanager
    def _connect(self) -> Any:
        """Otomatik eklendi."""
        conn = duckdb.connect(str(self._db_path))
        # SSD write reduction: DuckDB WAL ayarları
        try:
            from services.core.debounce import configure_duckdb_wal
            configure_duckdb_wal(conn)
        except Exception:
            logger.debug("Silent exception caught", exc_info=True)
        try:
            yield conn
        finally:
            conn.close()

    @otel_trace("downtime_tracker.record_shutdown")
    def record_shutdown(self) -> Any:
        """Kapanış zamanını kaydet (graceful shutdown'ta çağrılır)."""
        now = time.time()
        now_iso = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO shutdown_events (shutdown_at, shutdown_timestamp)
                VALUES (?, ?)
            """,
                (now_iso, now),
            )
            conn.commit()

        # Config'e de kaydet (hızlı erişim için)
        self._set_config("last_shutdown_at", now_iso)
        self._set_config("last_shutdown_timestamp", str(now))

        logger.info("Shutdown time recorded", time=now_iso)

    @otel_trace("downtime_tracker.record_startup")
    def record_startup(self) -> Any:
        """Başlangıç zamanını kaydet ve downtime hesapla."""
        self._startup_time = time.time()
        self._downtime_seconds = self._calculate_downtime()

        now_iso = datetime.now(UTC).isoformat()
        catchup_level = self.get_catchup_level()

        # Son shutdown kaydını güncelle
        with self._connect() as conn:
            # En son shutdown kaydını bul ve güncelle
            row = conn.execute("""
                SELECT id FROM shutdown_events
                WHERE startup_at IS NULL
                ORDER BY shutdown_timestamp DESC LIMIT 1
            """).fetchone()

            if row:
                row_id = row[0] if isinstance(row, (tuple, list)) else row["id"]
                conn.execute(
                    """
                    UPDATE shutdown_events
                    SET startup_at = ?, startup_timestamp = ?,
                        downtime_seconds = ?, catchup_level = ?
                    WHERE id = ?
                """,
                    (now_iso, self._startup_time, self._downtime_seconds, catchup_level, row_id),
                )
            else:
                # Shutdown kaydı yok — ilk çalıştırma veya crash
                conn.execute(
                    """
                    INSERT INTO shutdown_events
                    (shutdown_at, shutdown_timestamp, startup_at, startup_timestamp,
                     downtime_seconds, catchup_level)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        now_iso,
                        self._startup_time - self._downtime_seconds,
                        now_iso,
                        self._startup_time,
                        self._downtime_seconds,
                        catchup_level,
                    ),
                )

            conn.commit()

        # Config güncelle
        self._set_config("last_startup_at", now_iso)
        self._set_config("last_startup_timestamp", str(self._startup_time))
        self._set_config("last_downtime_seconds", str(self._downtime_seconds))

        if self._downtime_seconds > 60:
            logger.warning(
                "System was down",
                downtime_minutes=round(self._downtime_seconds / 60, 1),
                downtime_hours=round(self._downtime_seconds / 3600, 2),
                catchup_level=catchup_level,
            )
        else:
            logger.info("System startup", downtime_seconds=round(self._downtime_seconds, 1))

    def _calculate_downtime(self) -> float:
        """Downtime süresini hesapla."""
        # 1. Config'den son shutdown timestamp'ini al
        shutdown_ts = self._get_config("last_shutdown_timestamp")
        if shutdown_ts:
            try:
                return time.time() - float(shutdown_ts)
            except (ValueError, TypeError):
                logger.warning("Error in _calculate_downtime: (ValueError, TypeError)", exc_info=True)

        # 2. DB'den son shutdown'ı al
        with self._connect() as conn:
            row = conn.execute("""
                SELECT shutdown_timestamp FROM shutdown_events
                ORDER BY shutdown_timestamp DESC LIMIT 1
            """).fetchone()

            if row:
                ts_val = row[0] if isinstance(row, (tuple, list)) else row["shutdown_timestamp"]
                return time.time() - float(ts_val)

        # 3. Dosya modification time'ını kullan (son çare)
        try:
            mtime = self._db_path.stat().st_mtime
            return time.time() - mtime
        except Exception:
            return 0.0

    def _set_config(self, key: str, value: str) -> Any:
        """Config anahtarını ayarla."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO downtime_config (key, value, updated_at)
                VALUES (?, ?, ?)
            """,
                (key, value, datetime.now(UTC).isoformat()),
            )
            # SSD write reduction: commit deferred
            # conn.commit()

    def _get_config(self, key: str) -> str | None:
        """Config anahtarını oku."""
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM downtime_config WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            return row[0] if isinstance(row, (tuple, list)) else row["value"]

    def get_downtime(self) -> timedelta:
        """Downtime süresini döndür."""
        return timedelta(seconds=self._downtime_seconds)

    def get_downtime_seconds(self) -> float:
        """Downtime süresini saniye olarak döndür."""
        return self._downtime_seconds

    def needs_catchup(self) -> dict[str, bool]:
        """Hangi catch-up'lar gerekli?"""
        downtime = timedelta(seconds=self._downtime_seconds)
        return {key: downtime >= threshold for key, threshold in self.CATCHUP_THRESHOLDS.items()}

    def get_catchup_level(self) -> str:
        """Catch-up seviyesi."""
        downtime = timedelta(seconds=self._downtime_seconds)

        if downtime >= self.CATCHUP_THRESHOLDS["full_recalibration"]:
            return "full_recalibration"
        elif downtime >= self.CATCHUP_THRESHOLDS["model_refresh"]:
            return "model_refresh"
        elif downtime >= self.CATCHUP_THRESHOLDS["data_backfill"]:
            return "data_backfill"
        else:
            return "none"

    @otel_trace("downtime_tracker.get_status")
    def get_status(self) -> dict[str, Any]:
        """Durum bilgisi."""
        return {
            "downtime_seconds": round(self._downtime_seconds, 1),
            "downtime_minutes": round(self._downtime_seconds / 60, 1),
            "downtime_hours": round(self._downtime_seconds / 3600, 2),
            "catchup_level": self.get_catchup_level(),
            "needs_catchup": self.needs_catchup(),
            "last_shutdown": self._get_config("last_shutdown_at"),
            "last_startup": self._get_config("last_startup_at"),
            "db_path": str(self._db_path),
            "persistent": True,
        }

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Downtime geçmişini döndür."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM shutdown_events
                ORDER BY shutdown_timestamp DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, r, strict=False)) for r in rows]


# Singleton
downtime_tracker = DowntimeTracker()
