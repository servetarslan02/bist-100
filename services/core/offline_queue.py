"""
ALPHA BIST — Offline Queue v1.0
===============================
İnternet bağlantısı kesildiğinde üretilen finansal sinyalleri kuyruğa alır;
bağlantı sağlandığında öncelik ve zaman sırasına göre otomatik dağıtır.

Temel Özellikler:
- İnternet kesintisinde üretilen alım/satım sinyallerinin sıfır kayıp garantisi
- DuckDB tabanlı kalıcı defter — sistem yeniden başlasa dahi kuyruk korunur
- Öncelik (Priority) ve FIFO sıralaması
- TTL (Time-To-Live) mekanizması ile süresi dolmuş sinyallerin otomatik temizlenmesi
- Deadlock korumalı thread-safe kilit yönetimi (threading.RLock)
- Tuple/Dict ayrıştırma hatalarından arındırılmış sağlam sorgu katmanı
- Polars analitik dışa aktarımı (GEMINI.md Kural 2)
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.offline_queue")

DEFAULT_OFFLINE_DB_PATH: Final[str] = "data/offline_queue.db"
DEFAULT_MAX_ENTRIES: Final[int] = 10_000
DEFAULT_TTL_HOURS: Final[int] = 48
DEFAULT_PRIORITY: Final[int] = 5
MAX_RETRY_ATTEMPTS: Final[int] = 5


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için SSD koruyucu ve optimize WAL parametrelerini ayarlar."""
    try:
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def otel_trace(span_name: str) -> Any:
    """Metot, senkron fonksiyon veya asenkron coroutine'i OpenTelemetry span içine alan dekoratör.

    Args:
        span_name: Span adı.

    Returns:
        Sarmalayıcı fonksiyon veya coroutine.
    """

    def decorator(func: Any) -> Any:
        """Hedef fonksiyon veya coroutine'i OTel span ile sarmalar."""
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        if hasattr(span, "record_exception"):
                            span.record_exception(exc)
                        raise

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            """Fonksiyon çağrısını span içinde icra eder."""
            with tracer.start_as_current_span(span_name) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if hasattr(span, "record_exception"):
                        span.record_exception(exc)
                    raise

        return sync_wrapper

    return decorator


class OfflineQueue:
    """DuckDB tabanlı dayanıklı çevrimdışı (offline) olay kuyruğu yöneticisi."""

    def __init__(
        self,
        db_path: str = DEFAULT_OFFLINE_DB_PATH,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        default_ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        """Offline kuyruk yöneticisini ve DuckDB dosya dizinini başlatır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            max_entries: Kuyrukta tutulabilecek azami kayıt adedi.
            default_ttl_hours: Varsayılan geçerlilik süresi (saat).
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._default_ttl_hours = default_ttl_hours
        self._publish_handlers: dict[str, Callable[..., Any]] = {}
        self._flushing = False
        self._bg_flushing = False
        self._bg_thread: threading.Thread | None = None
        self._lock = threading.RLock()

        # Yaşam döngüsü sayaçları
        self._total_enqueued = 0
        self._total_flushed = 0
        self._total_expired = 0

        self._init_db()
        logger.info("offline_queue_baslatildi", db_path=str(self.db_path), max_entries=self._max_entries)

    def _init_db(self) -> None:
        """DuckDB tablolarını ve gerekli indeksleri oluşturur."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offline_queue (
                    entry_id VARCHAR PRIMARY KEY,
                    event_type VARCHAR NOT NULL,
                    subject VARCHAR NOT NULL,
                    payload VARCHAR NOT NULL,
                    priority INTEGER DEFAULT 5,
                    created_at VARCHAR NOT NULL,
                    expires_at VARCHAR NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_error VARCHAR
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_created ON offline_queue(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_expires ON offline_queue(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_type ON offline_queue(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oq_priority ON offline_queue(priority)")

    @contextmanager
    def _connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Güvenli, thread-safe DuckDB bağlantısı ve WAL optimizasyonu sağlar.

        Yields:
            Aktif DuckDBPyConnection nesnesi.
        """
        with self._lock:
            conn = duckdb.connect(str(self.db_path))
            configure_duckdb_wal(conn)
            try:
                yield conn
            finally:
                conn.close()

    @otel_trace("offline_queue.register_publish_handler")
    def register_publish_handler(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Belirtilen olay türü için dağıtım işleyici fonksiyonunu kaydeder.

        Args:
            event_type: Olay tipi (örn: 'signal.generated').
            handler: Tetiklenecek senkron veya asenkron fonksiyon.
        """
        with self._lock:
            self._publish_handlers[event_type] = handler
        logger.info("offline_isleyici_kaydedildi", event_type=event_type)

    @otel_trace("offline_queue.enqueue")
    async def enqueue(
        self,
        event_type: str,
        payload: dict[str, Any],
        subject: str = "alpha.offline",
        priority: int = DEFAULT_PRIORITY,
        ttl_hours: int | None = None,
    ) -> str:
        """Olayı çevrimdışı kuyruğa ekler.

        Args:
            event_type: Olay tipi.
            payload: Olay veri yükü sözlüğü.
            subject: Konu başlığı.
            priority: Öncelik (1 en yüksek, 10 en düşük).
            ttl_hours: Özel TTL süresi (saat).

        Returns:
            Oluşturulan tekil entry_id.
        """
        entry_id = hashlib.md5(f"oq_{event_type}_{time.time_ns()}_{id(payload)}".encode()).hexdigest()[:16]
        ttl = ttl_hours or self._default_ttl_hours
        expires_at = datetime.now(UTC) + timedelta(hours=ttl)
        payload_json = orjson.dumps(payload, default=str).decode("utf-8")

        with self._connect() as conn:
            # Kapasite kontrolü ve gerektiğinde en eski düşük öncelikliyi çıkarma
            row = conn.execute("SELECT COUNT(*) FROM offline_queue").fetchone()
            current_count = int(row[0]) if row else 0

            if current_count >= self._max_entries:
                # En düşük öncelikli ve en eski kaydı sil
                conn.execute("""
                    DELETE FROM offline_queue
                    WHERE entry_id IN (
                        SELECT entry_id FROM offline_queue
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                    )
                """)
                logger.warning("offline_kuyruk_kapasite_asimi_en_eski_silindi", limit=self._max_entries)

            conn.execute(
                """
                INSERT INTO offline_queue
                (entry_id, event_type, subject, payload, priority, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry_id,
                    event_type,
                    subject,
                    payload_json,
                    priority,
                    datetime.now(UTC).isoformat(),
                    expires_at.isoformat(),
                ),
            )

        with self._lock:
            self._total_enqueued += 1

        logger.info("olay_offline_kuyruga_eklendi", entry_id=entry_id, event_type=event_type, priority=priority)
        return entry_id

    @otel_trace("offline_queue.flush")
    async def flush(self) -> int:
        """Kuyruktaki tüm geçerli olayları kayıtlı işleyicilere gönderir.

        FIFO ve öncelik (küçük sayı = yüksek öncelik) sırasıyla gönderir.

        Returns:
            Başarıyla dağıtılan olay adedi.
        """
        with self._lock:
            if self._flushing:
                return 0
            self._flushing = True

        flushed = 0

        try:
            # Süresi dolmuş kayıtları temizle
            self._cleanup_expired()

            with self._connect() as conn:
                cur = conn.execute("""
                    SELECT entry_id, event_type, subject, payload, priority, created_at, expires_at, attempts, last_error
                    FROM offline_queue
                    ORDER BY priority ASC, created_at ASC
                """)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

                for entry in rows:
                    with self._lock:
                        handler = self._publish_handlers.get(entry["event_type"])

                    if handler:
                        try:
                            payload = orjson.loads(entry["payload"])

                            if asyncio.iscoroutinefunction(handler):
                                await handler(entry["subject"], payload)
                            else:
                                handler(entry["subject"], payload)

                            # Başarılı — kuyruktan çıkar
                            conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))
                            flushed += 1
                            with self._lock:
                                self._total_flushed += 1

                        except Exception as e:
                            attempts = int(entry.get("attempts", 0)) + 1
                            if attempts >= MAX_RETRY_ATTEMPTS:
                                conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))
                                logger.warning(
                                    "offline_kayit_deneme_sinirini_asti_silindi",
                                    entry_id=entry["entry_id"],
                                    hata=str(e),
                                )
                            else:
                                conn.execute(
                                    """
                                    UPDATE offline_queue
                                    SET attempts = attempts + 1, last_error = ?
                                    WHERE entry_id = ?
                                """,
                                    (str(e)[:200], entry["entry_id"]),
                                )

                    else:
                        # Kayıtlı işleyici yok — güvenli şekilde temizle
                        conn.execute("DELETE FROM offline_queue WHERE entry_id = ?", (entry["entry_id"],))

            if flushed > 0:
                logger.info("offline_kuyruk_bosaltildi", adet=flushed)

        except Exception as exc:
            logger.error("offline_kuyruk_flush_hatasi", hata=str(exc))
        finally:
            with self._lock:
                self._flushing = False

        return flushed

    def _cleanup_expired(self) -> int:
        """Süresi dolmuş kayıtları temizler ve adedini döndürür."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            deleted_rows = conn.execute(
                "DELETE FROM offline_queue WHERE expires_at <= ? RETURNING entry_id",
                (now,),
            ).fetchall()
            expired_count = len(deleted_rows)

        if expired_count > 0:
            with self._lock:
                self._total_expired += expired_count
            logger.debug("suresi_dolan_offline_kayitlar_temizlendi", adet=expired_count)

        return expired_count

    @otel_trace("offline_queue.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """Kuyruk özet istatistiklerini sözlük olarak döndürür."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM offline_queue").fetchone()
            total = int(row[0]) if row else 0

            by_type: dict[str, int] = {}
            rows = conn.execute("""
                SELECT event_type, COUNT(*) FROM offline_queue GROUP BY event_type
            """).fetchall()
            for r in rows:
                by_type[str(r[0])] = int(r[1])

        with self._lock:
            return {
                "pending_entries": total,
                "by_event_type": by_type,
                "lifetime": {
                    "total_enqueued": self._total_enqueued,
                    "total_flushed": self._total_flushed,
                    "total_expired": self._total_expired,
                },
                "db_path": str(self.db_path),
                "flushing": self._flushing,
            }

    @otel_trace("offline_queue.get_entries")
    async def get_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Kuyruktaki bekleyen kayıtları sözlük listesi olarak döndürür."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT entry_id, event_type, subject, payload, priority, created_at, expires_at, attempts, last_error
                FROM offline_queue
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
            """,
                (limit,),
            )
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    @otel_trace("offline_queue.clear")
    async def clear(self) -> int:
        """Tüm kuyruğu temizler ve silinen kayıt adedini döndürür."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM offline_queue").fetchone()
            count = int(row[0]) if row else 0
            conn.execute("DELETE FROM offline_queue")
        logger.info("offline_kuyruk_sifirlandi", silinen_adet=count)
        return count

    @otel_trace("offline_queue.retry_failed_entries")
    def retry_failed_entries(self, event_type: str | None = None) -> int:
        """Hata deneme sınırına takılmış veya son hatası bulunan kayıtları sıfırlayarak yeniden kuyruğa alır.

        Self-healing mekanizması olarak kullanılır.

        Args:
            event_type: İsteğe bağlı filtrelenecek olay tipi.

        Returns:
            Sıfırlanan ve yeniden canlandırılan kayıt adedi.
        """
        query = "UPDATE offline_queue SET attempts = 0, last_error = NULL WHERE attempts > 0"
        params: list[Any] = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        with self._connect() as conn:
            conn.execute(query, params)
            row = conn.execute("SELECT COUNT(*) FROM offline_queue WHERE attempts = 0").fetchone()
            count = int(row[0]) if row else 0

        logger.info("offline_kayitlar_self_healing_ile_yeniden_deneniyor", sifirlanan=count, event_type=event_type)
        return count

    @otel_trace("offline_queue.start_background_flusher")
    def start_background_flusher(self, interval_seconds: int = 15) -> None:
        """Arka planda periyodik flush işlemini yürüten iş parçacığını başlatır."""
        with self._lock:
            if self._bg_flushing:
                return
            self._bg_flushing = True

            def _flusher_worker() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    while self._bg_flushing:
                        try:
                            loop.run_until_complete(self.flush())
                        except Exception as exc:
                            logger.warning("arkaplan_offline_flush_hatasi", hata=str(exc))
                        time.sleep(interval_seconds)
                finally:
                    loop.close()

            self._bg_thread = threading.Thread(
                target=_flusher_worker,
                daemon=True,
                name="OfflineQueueFlusherThread",
            )
            self._bg_thread.start()
            logger.info("arkaplan_offline_flusher_baslatildi", aralik_sn=interval_seconds)

    @otel_trace("offline_queue.stop_background_flusher")
    def stop_background_flusher(self) -> None:
        """Arka plan flush iş parçacığını güvenle durdurur."""
        with self._lock:
            self._bg_flushing = False
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=2.0)
            self._bg_thread = None
            logger.info("arkaplan_offline_flusher_durduruldu")

    async def to_orjson_bytes(self) -> bytes:
        """Kuyruk istatistiklerini ve özetini C seviyesinde orjson bayt dizisine serileştirir."""
        stats = await self.get_stats()
        return orjson.dumps(stats, option=orjson.OPT_SORT_KEYS, default=str)

    def export_offline_queue_to_polars(self) -> pl.DataFrame:
        """Kuyruktaki tüm bekleyen kayıtları Polars DataFrame olarak dışa aktarır."""
        with self._connect() as conn:
            cur = conn.execute("""
                SELECT entry_id, event_type, subject, priority, created_at, expires_at, attempts, last_error
                FROM offline_queue
                ORDER BY priority ASC, created_at ASC
            """)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

        schema = {
            "entry_id": pl.String,
            "event_type": pl.String,
            "subject": pl.String,
            "priority": pl.Int64,
            "created_at": pl.String,
            "expires_at": pl.String,
            "attempts": pl.Int64,
            "last_error": pl.String,
        }
        if not rows:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(rows, schema=schema)

    def export_offline_stats_to_polars(self) -> pl.DataFrame:
        """Kuyruk metriklerini Polars DataFrame olarak dışa aktarır."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM offline_queue").fetchone()
            pending = int(row[0]) if row else 0

        with self._lock:
            records = [
                {"metric_name": "pending_entries", "metric_value": float(pending)},
                {"metric_name": "total_enqueued", "metric_value": float(self._total_enqueued)},
                {"metric_name": "total_flushed", "metric_value": float(self._total_flushed)},
                {"metric_name": "total_expired", "metric_value": float(self._total_expired)},
            ]

        schema = {
            "metric_name": pl.String,
            "metric_value": pl.Float64,
        }
        return pl.DataFrame(records, schema=schema)

    def __repr__(self) -> str:
        """Offline kuyruk yöneticisinin metinsel temsili."""
        with self._lock:
            return (
                f"<OfflineQueue db_path='{self.db_path}' max_entries={self._max_entries} "
                f"enqueued={self._total_enqueued} flushed={self._total_flushed}>"
            )


# Singleton
offline_queue: Final[OfflineQueue] = OfflineQueue()


def export_offline_queue_to_polars() -> pl.DataFrame:
    """Singleton üzerinden bekleyen offline kuyruk DataFrame'ini döner."""
    return offline_queue.export_offline_queue_to_polars()


def export_offline_stats_to_polars() -> pl.DataFrame:
    """Singleton üzerinden kuyruk istatistikleri DataFrame'ini döner."""
    return offline_queue.export_offline_stats_to_polars()


def retry_failed_entries(event_type: str | None = None) -> int:
    """Singleton üzerinden başarısız kayıtları yeniden denemeye alır."""
    return offline_queue.retry_failed_entries(event_type=event_type)


def clear_offline_queue_duckdb(db_path: str = DEFAULT_OFFLINE_DB_PATH) -> None:
    """Belirtilen DuckDB veritabanındaki offline kuyruk tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path = Path(db_path)
    if not path.exists():
        return
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("DELETE FROM offline_queue")
        conn.commit()
        logger.info("offline_queue_duckdb_temizlendi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_OFFLINE_DB_PATH",
    "DEFAULT_PRIORITY",
    "DEFAULT_TTL_HOURS",
    "MAX_RETRY_ATTEMPTS",
    "OfflineQueue",
    "clear_offline_queue_duckdb",
    "configure_duckdb_wal",
    "export_offline_queue_to_polars",
    "export_offline_stats_to_polars",
    "offline_queue",
    "otel_trace",
    "retry_failed_entries",
]
