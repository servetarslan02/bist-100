"""
ALPHA BIST — Downtime Tracker v2.0 (DuckDB + Polars)

Sistem downtime süresini ve planlı/beklenmeyen kesintileri takip eder.
Kişisel PC senaryosu ve algoritmik alım-satım sürekliliği için kritik altyapıdır:

- Kapanış zamanını kaydeder (graceful shutdown).
- Açılışta ne kadar süre kapalı kalındığını hesaplar.
- Catch-up modunu (veri backfill, model refresh, tam rekalibrasyon) tetikler.
- Downtime istatistiklerini ve tarihsel kayıtları DuckDB hyper-lite mimarisinde saklar.
- Kesinti geçmişini Polars DataFrame olarak dışa aktarabilir.
- Eşzamanlı (thread-safe) işlem güvenliği sağlar.
"""

from __future__ import annotations

import functools
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Final, Generator

import duckdb
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.downtime_tracker")

DEFAULT_DOWNTIME_DB_PATH: Final[str] = "data/downtime.db"

DEFAULT_CATCHUP_THRESHOLDS: Final[dict[str, timedelta]] = {
    "data_backfill": timedelta(minutes=30),  # 30 dk+ → veri backfill
    "model_refresh": timedelta(hours=6),  # 6 saat+ → model yenile
    "full_recalibration": timedelta(hours=24),  # 24 saat+ → tam kalibrasyon
}


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metot çağrılarını OpenTelemetry span'i ile sarmalayan dekoratör.

    Args:
        span_name: İzleme span'i için benzersiz adlandırma.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Metodu OpenTelemetry span bağlamında çalıştırır."""

        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Span oluşturup hedef fonksiyonu icra eder."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class DowntimeTracker:
    """Sistem downtime takipçisi — DuckDB ve Polars tabanlı.

    Özellikler:
    - Graceful shutdown kaydı ve zaman damgası tespiti.
    - Startup'ta sistemin ne kadar süre kapalı kaldığını milisaniye hassasiyetinde hesaplama.
    - Downtime süresine göre catch-up gereksinimlerini belirleme.
    - Geçmiş kesintileri DuckDB üzerinde saklama ve Polars ile analiz etme.
    - Windows dosya kilidi ve 0-byte bozulma korumaları.
    - İş parçacığı güvenli (thread-safe) kilit yönetimi.
    """

    CATCHUP_THRESHOLDS: Final[dict[str, timedelta]] = DEFAULT_CATCHUP_THRESHOLDS

    def __init__(self, db_path: str = DEFAULT_DOWNTIME_DB_PATH) -> None:
        """DowntimeTracker örneğini başlatır ve veritabanı şemasını kurar.

        Args:
            db_path: DuckDB veritabanı dosyasının disk konumu.
        """
        self._db_path: Path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._startup_time: float | None = None
        self._downtime_seconds: float = 0.0
        self._lock: threading.RLock = threading.RLock()
        self._init_db()

    def __repr__(self) -> str:
        """DowntimeTracker nesnesinin okunabilir temsilini döner."""
        return (
            f"DowntimeTracker(db_path={str(self._db_path)!r}, "
            f"downtime_seconds={self._downtime_seconds:.1f}, "
            f"catchup_level={self.get_catchup_level()!r})"
        )

    def _init_db(self) -> None:
        """DuckDB tablolarını ve dizinlerini oluşturur."""
        with self._lock, self._connect() as conn:
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
    def _connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """DuckDB bağlantısı açan ve kaynakları güvenle serbest bırakan bağlam yöneticisi.

        Yields:
            Aktif DuckDB bağlantı nesnesi.

        Raises:
            duckdb.Error: Veritabanı bağlantı hatası durumunda.
        """
        # Windows 0-byte dosya çökme önlemi
        if self._db_path.exists() and self._db_path.is_file() and self._db_path.stat().st_size == 0:
            try:
                self._db_path.unlink()
                logger.warning("Bozuk sıfır baytlık DuckDB dosyası temizlendi", path=str(self._db_path))
            except OSError as unlink_err:
                logger.debug("Sıfır baytlık dosya silinirken hata oluştu", error=str(unlink_err))

        conn = duckdb.connect(str(self._db_path))
        try:
            from services.core.duckdb_store import configure_duckdb_wal

            configure_duckdb_wal(conn)
        except Exception as wal_err:
            logger.debug("DuckDB WAL yapılandırması atlandı", error=str(wal_err))

        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception as close_err:
                logger.debug("DuckDB bağlantısı kapatılırken hata", error=str(close_err))

    @otel_trace("downtime_tracker.record_shutdown")
    def record_shutdown(self) -> None:
        """Kapanış zamanını kaydeder (graceful shutdown sürecinde çağrılır).

        Sistem kapanırken çağrılır, kapanış anını zaman damgası olarak
        hem olay tablosuna hem de hızlı erişim konfigürasyonuna yazar.
        """
        with self._lock:
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

            # Hızlı erişim konfigürasyonunu güncelle
            self._set_config("last_shutdown_at", now_iso)
            self._set_config("last_shutdown_timestamp", str(now))

            logger.info("Kapanış zamanı başarıyla kaydedildi", shutdown_time=now_iso)

    @otel_trace("downtime_tracker.record_startup")
    def record_startup(self) -> None:
        """Başlangıç zamanını kaydeder ve downtime süresini hesaplar.

        Sistem açılışında çağrılır. En son kaydedilen shutdown kaydını bulup
        aradaki kesinti süresini ve catch-up seviyesini hesaplar ve günceller.
        """
        with self._lock:
            self._startup_time = time.time()
            self._downtime_seconds = max(0.0, self._calculate_downtime())

            now_iso = datetime.now(UTC).isoformat()
            catchup_level = self.get_catchup_level()

            with self._connect() as conn:
                # Kapanmış fakat açılış damgası işlenmemiş son kaydı bul
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
                    # Shutdown kaydı yoksa (ilk çalıştırma veya ani kilitlenme/crash)
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

            # Konfigürasyonu güncelle
            self._set_config("last_startup_at", now_iso)
            self._set_config("last_startup_timestamp", str(self._startup_time))
            self._set_config("last_downtime_seconds", str(self._downtime_seconds))

            if self._downtime_seconds > 60:
                logger.warning(
                    "Sistem kesinti sonrası yeniden başlatıldı",
                    downtime_minutes=round(self._downtime_seconds / 60, 1),
                    downtime_hours=round(self._downtime_seconds / 3600, 2),
                    catchup_level=catchup_level,
                )
            else:
                logger.info("Sistem açılışı tamamlandı", downtime_seconds=round(self._downtime_seconds, 1))

    def _calculate_downtime(self) -> float:
        """Son kapanıştan bu yana geçen kesinti süresini saniye cinsinden hesaplar.

        Returns:
            Geçen süre (saniye).
        """
        # 1. Konfigürasyondan son shutdown zaman damgasını al
        shutdown_ts = self._get_config("last_shutdown_timestamp")
        if shutdown_ts:
            try:
                val = float(shutdown_ts)
                if val > 0:
                    return time.time() - val
            except (ValueError, TypeError) as conv_err:
                logger.warning("Son shutdown zaman damgası ayrıştırılamadı", error=str(conv_err))

        # 2. Veritabanındaki son shutdown olayını kontrol et
        with self._connect() as conn:
            row = conn.execute("""
                SELECT shutdown_timestamp FROM shutdown_events
                ORDER BY shutdown_timestamp DESC LIMIT 1
            """).fetchone()

            if row:
                ts_val = row[0] if isinstance(row, (tuple, list)) else row["shutdown_timestamp"]
                try:
                    return time.time() - float(ts_val)
                except (ValueError, TypeError):
                    pass

        # 3. Dosya değiştirilme zaman damgasını (mtime) son çare olarak kullan
        try:
            if self._db_path.exists():
                mtime = self._db_path.stat().st_mtime
                return time.time() - mtime
        except OSError:
            pass

        return 0.0

    def _set_config(self, key: str, value: str) -> None:
        """Konfigürasyon anahtarını atomik olarak ayarlar ve kaydeder.

        Args:
            key: Konfigürasyon anahtarı.
            value: Kaydedilecek metin değeri.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO downtime_config (key, value, updated_at)
                VALUES (?, ?, ?)
            """,
                (key, value, datetime.now(UTC).isoformat()),
            )
            conn.commit()

    def _get_config(self, key: str) -> str | None:
        """Konfigürasyon anahtarının değerini okur.

        Args:
            key: Okunacak konfigürasyon anahtarı.

        Returns:
            Anahtarın değeri veya bulunamazsa None.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM downtime_config WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            return str(row[0]) if isinstance(row, (tuple, list)) else str(row["value"])

    def get_downtime(self) -> timedelta:
        """Hesaplanan kesinti süresini timedelta nesnesi olarak döner.

        Returns:
            Kesinti süresi.
        """
        return timedelta(seconds=self._downtime_seconds)

    def get_downtime_seconds(self) -> float:
        """Hesaplanan kesinti süresini saniye cinsinden döner.

        Returns:
            Kesinti saniyesi.
        """
        return self._downtime_seconds

    def needs_catchup(self) -> dict[str, bool]:
        """Sistemin kesinti süresine göre hangi catch-up adımlarını gerektirdiğini belirler.

        Returns:
            Her catch-up adımı için gereklilik durumunu belirten sözlük.
        """
        downtime = timedelta(seconds=self._downtime_seconds)
        return {key: downtime >= threshold for key, threshold in self.CATCHUP_THRESHOLDS.items()}

    def get_catchup_level(self) -> str:
        """Kesinti süresine göre gereken en yüksek catch-up seviyesini döner.

        Returns:
            'full_recalibration', 'model_refresh', 'data_backfill' veya 'none'.
        """
        downtime = timedelta(seconds=self._downtime_seconds)

        if downtime >= self.CATCHUP_THRESHOLDS["full_recalibration"]:
            return "full_recalibration"
        if downtime >= self.CATCHUP_THRESHOLDS["model_refresh"]:
            return "model_refresh"
        if downtime >= self.CATCHUP_THRESHOLDS["data_backfill"]:
            return "data_backfill"
        return "none"

    @otel_trace("downtime_tracker.get_status")
    def get_status(self) -> dict[str, Any]:
        """Downtime takipçisinin anlık durum özetini döner.

        Returns:
            Durum metrikleri, eşikler ve son kesinti detayları.
        """
        with self._lock:
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
        """Geçmiş kesinti kayıtlarını sözlük listesi olarak döner.

        Args:
            limit: Döndürülecek maksimum kayıt adedi.

        Returns:
            Kesinti kayıtlarının listesi.
        """
        with self._lock, self._connect() as conn:
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

    def export_history_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """Geçmiş kesinti kayıtlarını Polars DataFrame formatında dışa aktarır.

        Args:
            limit: Analiz edilecek maksimum kayıt adedi.

        Returns:
            Kayıtları içeren Polars DataFrame.
        """
        with self._lock, self._connect() as conn:
            try:
                # Arrow zero-copy dönüşümü ile Polars DataFrame oluştur
                arrow_table = conn.execute(
                    """
                    SELECT id, shutdown_at, shutdown_timestamp, startup_at,
                           startup_timestamp, downtime_seconds, catchup_level
                    FROM shutdown_events
                    ORDER BY shutdown_timestamp DESC
                    LIMIT ?
                """,
                    (limit,),
                ).fetch_arrow_table()
                return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as arrow_err:
                logger.debug("Arrow sıfır-kopyalama başarısız, cursor yedeğine geçiliyor", error=str(arrow_err))
                records = self.get_history(limit=limit)
                if not records:
                    return pl.DataFrame(
                        schema={
                            "id": pl.Int64,
                            "shutdown_at": pl.Utf8,
                            "shutdown_timestamp": pl.Float64,
                            "startup_at": pl.Utf8,
                            "startup_timestamp": pl.Float64,
                            "downtime_seconds": pl.Float64,
                            "catchup_level": pl.Utf8,
                        }
                    )
                return pl.DataFrame(records)


# Global tekil (singleton) örnek
downtime_tracker: Final[DowntimeTracker] = DowntimeTracker()


def record_shutdown() -> None:
    """Kapanış zamanını aktif singleton tracker üzerinden kaydeder."""
    downtime_tracker.record_shutdown()


def record_startup() -> None:
    """Başlangıç zamanını ve kesinti süresini aktif singleton tracker üzerinden kaydeder."""
    downtime_tracker.record_startup()


def get_downtime_status() -> dict[str, Any]:
    """Downtime takipçisinin anlık durum özetini döner."""
    return downtime_tracker.get_status()


def export_downtime_to_polars(limit: int = 1000) -> pl.DataFrame:
    """Geçmiş kesinti kayıtlarını Polars DataFrame olarak dışa aktarır."""
    return downtime_tracker.export_history_to_polars(limit=limit)


__all__ = [
    "DEFAULT_CATCHUP_THRESHOLDS",
    "DEFAULT_DOWNTIME_DB_PATH",
    "DowntimeTracker",
    "downtime_tracker",
    "export_downtime_to_polars",
    "get_downtime_status",
    "otel_trace",
    "record_shutdown",
    "record_startup",
]
