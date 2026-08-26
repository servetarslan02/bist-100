"""
ALPHA BIST — Downtime Tracker v2.0 (SQLite)

Sistem downtime süresini takip eder.
Kişisel PC senaryosu için kritik:

- Kapanış zamanını kaydeder (graceful shutdown)
- Açılışta ne kadar kapalı kaldığını hesaplar
- Catch-up modunu tetikler
- Downtime istatistiklerini tutar
- SQLite tabanlı — restart sonrası kaybolmaz

Kullanım:
    from services.core.downtime_tracker import downtime_tracker

    # Shutdown'ta
    downtime_tracker.record_shutdown()

    # Startup'ta
    downtime = downtime_tracker.get_downtime()
    if downtime > timedelta(hours=1):
        await backfill_manager.backfill_all(...)
"""

import duckdb
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import structlog

logger = structlog.get_logger()


class DowntimeTracker:
    """Sistem downtime takipçisi — SQLite tabanlı.

    Özellikler:
    - Graceful shutdown kaydı
    - Startup'ta downtime hesaplama
    - Downtime istatistikleri
    - Catch-up tetikleme eşiği
    - Geçmiş downtime kayıtları
    """

    # Catch-up eşikleri
    CATCHUP_THRESHOLDS = {
        "data_backfill": timedelta(minutes=30),    # 30 dk+ → veri backfill
        "model_refresh": timedelta(hours=6),        # 6 saat+ → model yenile
        "full_recalibration": timedelta(hours=24),  # 24 saat+ → tam kalibrasyon
    }

    def __init__(self, db_path: str = "data/downtime.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._startup_time: Optional[float] = None
        self._downtime_seconds: float = 0.0
        self._init_db()

    def _init_db(self):
        """SQLite tablolarını oluştur."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shutdown_events (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    def _connect(self):
        conn = duckdb.connect(str(self._db_path))
        try:
            yield conn
        finally:
            conn.close()

    def record_shutdown(self):
        """Kapanış zamanını kaydet (graceful shutdown'ta çağrılır)."""
        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO shutdown_events (shutdown_at, shutdown_timestamp)
                VALUES (?, ?)
            """, (now_iso, now))
            conn.commit()

        # Config'e de kaydet (hızlı erişim için)
        self._set_config("last_shutdown_at", now_iso)
        self._set_config("last_shutdown_timestamp", str(now))

        logger.info("Shutdown time recorded", time=now_iso)

    def record_startup(self):
        """Başlangıç zamanını kaydet ve downtime hesapla."""
        self._startup_time = time.time()
        self._downtime_seconds = self._calculate_downtime()

        now_iso = datetime.now(timezone.utc).isoformat()
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
                conn.execute("""
                    UPDATE shutdown_events
                    SET startup_at = ?, startup_timestamp = ?,
                        downtime_seconds = ?, catchup_level = ?
                    WHERE id = ?
                """, (now_iso, self._startup_time,
                      self._downtime_seconds, catchup_level, row["id"]))
            else:
                # Shutdown kaydı yok — ilk çalıştırma veya crash
                conn.execute("""
                    INSERT INTO shutdown_events
                    (shutdown_at, shutdown_timestamp, startup_at, startup_timestamp,
                     downtime_seconds, catchup_level)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (now_iso, self._startup_time - self._downtime_seconds,
                      now_iso, self._startup_time,
                      self._downtime_seconds, catchup_level))

            conn.commit()

        # Config güncelle
        self._set_config("last_startup_at", now_iso)
        self._set_config("last_startup_timestamp", str(self._startup_time))
        self._set_config("last_downtime_seconds", str(self._downtime_seconds))

        if self._downtime_seconds > 60:
            logger.warning("System was down",
                          downtime_minutes=round(self._downtime_seconds / 60, 1),
                          downtime_hours=round(self._downtime_seconds / 3600, 2),
                          catchup_level=catchup_level)
        else:
            logger.info("System startup",
                       downtime_seconds=round(self._downtime_seconds, 1))

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
                return time.time() - row["shutdown_timestamp"]

        # 3. Dosya modification time'ını kullan (son çare)
        try:
            mtime = self._db_path.stat().st_mtime
            return time.time() - mtime
        except Exception:
            return 0.0

    def _set_config(self, key: str, value: str):
        """Config anahtarını ayarla."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO downtime_config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def _get_config(self, key: str) -> Optional[str]:
        """Config anahtarını oku."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM downtime_config WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def get_downtime(self) -> timedelta:
        """Downtime süresini döndür."""
        return timedelta(seconds=self._downtime_seconds)

    def get_downtime_seconds(self) -> float:
        """Downtime süresini saniye olarak döndür."""
        return self._downtime_seconds

    def needs_catchup(self) -> Dict[str, bool]:
        """Hangi catch-up'lar gerekli?"""
        downtime = timedelta(seconds=self._downtime_seconds)
        return {
            key: downtime >= threshold
            for key, threshold in self.CATCHUP_THRESHOLDS.items()
        }

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

    def get_status(self) -> Dict[str, Any]:
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

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Downtime geçmişini döndür."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM shutdown_events
                ORDER BY shutdown_timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]


# Singleton
downtime_tracker = DowntimeTracker()
