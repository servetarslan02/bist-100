"""
ALPHA BIST — Persistent Dead Letter Queue v2.0
==============================================
DuckDB tabanlı kalıcı Dead Letter Queue (DLQ) Motoru:
- Sistem yeniden başlatıldığında veya çöktüğünde olay verisi kaybolmaz.
- DuckDB WAL optimizasyonu ve atomik işlem güvencesi.
- Üstel geri çekilme (exponential backoff) ile otomatik yeniden deneme (retry).
- Maksimum deneme sınırı ve kapasite aşımında güvenli tahliye (eviction).
- Polars analitik defter aktarımı (GEMINI.md Kural 2).
- Thread-safe eşzamanlı kilit mimarisi (threading.RLock).
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.dlq")
meter = metrics.get_meter("alpha-bist.dlq")

dlq_push_counter = meter.create_counter("alpha.dlq.pushes", description="DLQ'ya aktarılan toplam başarısız olay sayısı")
dlq_resolve_counter = meter.create_counter("alpha.dlq.resolved", description="DLQ'dan başarıyla çözülen toplam olay sayısı")

# Sabitler
DEFAULT_DLQ_DB_PATH: Final[str] = "data/dlq.db"
DEFAULT_MAX_ENTRIES: Final[int] = 50_000
DEFAULT_BATCH_SIZE: Final[int] = 100
DEFAULT_BASE_BACKOFF_SECONDS: Final[int] = 5


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


class DLQStatus(StrEnum):
    """Dead Letter Queue durum kodları."""

    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"


@dataclass(slots=True)
class DLQEntry:
    """Kalıcı DLQ olay kaydı veri modeli."""

    entry_id: str
    event_id: str
    event_type: str
    payload: str
    error: str
    retry_count: int = 0
    max_retries: int = 3
    status: DLQStatus = DLQStatus.PENDING
    created_at: datetime | None = None
    last_retry_at: datetime | None = None
    next_retry_at: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        """Kayıt oluşturma zaman damgasını varsayılan olarak UTC şimdiye ayarlar."""
        if self.created_at is None:
            self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Kayıt alanlarını serileştirilebilir Python sözlüğüne dönüştürür."""
        return {
            "entry_id": self.entry_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def to_orjson_bytes(self) -> bytes:
        """Kayıt alanlarını orjson ikili serileştirme ile paketler."""
        return orjson.dumps(self.to_dict(), default=str)

    @property
    def is_retryable(self) -> bool:
        """Kaydın yeniden denenmeye uygun olup olmadığını kontrol eder."""
        return self.status == DLQStatus.PENDING and self.retry_count < self.max_retries

    @property
    def is_ready_for_retry(self) -> bool:
        """Geri çekilme süresi dolmuş ve yeniden çalıştırılmaya hazır olup olmadığını denetler."""
        if not self.is_retryable:
            return False
        if self.next_retry_at is None:
            return True
        return datetime.now(UTC) >= self.next_retry_at

    def __repr__(self) -> str:
        return (
            f"<DLQEntry entry_id={self.entry_id} event_type={self.event_type} "
            f"status={self.status.value} retries={self.retry_count}/{self.max_retries}>"
        )


class PersistentDeadLetterQueue:
    """DuckDB tabanlı kalıcı Dead Letter Queue yöneticisi."""

    def __init__(self, db_path: str = DEFAULT_DLQ_DB_PATH, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        """Kalıcı DLQ bağlantısını ve dizin yapısını hazırlar."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._retry_handlers: dict[str, Callable[..., Any]] = {}
        self._bg_retrying = False
        self._bg_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._init_db()

        # Metrik sayaçları
        self._total_pushed: int = 0
        self._total_retried: int = 0
        self._total_resolved: int = 0
        self._total_exhausted: int = 0

        logger.info("PersistentDLQ başlatıldı", db_path=str(self.db_path), engine="DuckDB")

    def _init_db(self) -> None:
        """DuckDB DLQ şemasını ve indekslerini başlatır."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dlq_entries (
                    entry_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    event_type VARCHAR NOT NULL,
                    payload VARCHAR NOT NULL,
                    error VARCHAR NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    status VARCHAR DEFAULT 'PENDING',
                    created_at VARCHAR NOT NULL,
                    last_retry_at VARCHAR,
                    next_retry_at VARCHAR,
                    resolved_at VARCHAR
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_status ON dlq_entries(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_type ON dlq_entries(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_created ON dlq_entries(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq_entries(next_retry_at)")

    @contextmanager
    def _connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Güvenli DuckDB bağlantısı ve WAL yapılandırması sağlar."""
        with self._lock:
            conn = duckdb.connect(str(self.db_path))
            configure_duckdb_wal(conn)
            try:
                yield conn
            finally:
                conn.close()

    @staticmethod
    def _cursor_to_dicts(cursor: Any) -> list[dict[str, Any]]:
        """DuckDB cursor sonucunu dictionary listesine dönüştürür."""
        if not cursor or not cursor.description:
            return []
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

    @otel_trace("persistent_dlq.register_retry_handler")
    def register_retry_handler(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Belirli bir olay tipi için yeniden işleme işleyicisini kaydeder."""
        with self._lock:
            self._retry_handlers[event_type] = handler

    @otel_trace("persistent_dlq.push")
    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: str,
        error: str,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Başarısız olan olayı kalıcı DuckDB DLQ deposuna yazar."""
        now_dt = datetime.now(UTC)
        entry_id = f"dlq_{event_id}_{int(now_dt.timestamp() * 1000)}"
        now_str = now_dt.isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dlq_entries (
                    entry_id, event_id, event_type, payload, error,
                    retry_count, max_retries, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    entry_id,
                    event_id,
                    event_type,
                    payload,
                    error,
                    retry_count,
                    max_retries,
                    now_str,
                ),
            )

        with self._lock:
            self._total_pushed += 1

        dlq_push_counter.add(1, {"event_type": event_type})
        self._evict_oldest()
        logger.warning(
            "Event kalıcı DLQ'ya kaydedildi",
            entry_id=entry_id,
            event_id=event_id,
            event_type=event_type,
            error=error[:200],
        )
        return entry_id

    @otel_trace("persistent_dlq.retry_failed")
    async def retry_failed(self, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
        """DLQ'daki yeniden denenebilir olayları geri çekilme sırasına göre işler."""
        retried = 0
        now = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT entry_id, event_id, event_type, payload, error, retry_count, max_retries, status, created_at
                FROM dlq_entries
                WHERE status = 'PENDING'
                AND (next_retry_at IS NULL OR next_retry_at <= ?)
                AND retry_count < max_retries
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (now, batch_size),
            )
            rows = self._cursor_to_dicts(cur)

            for entry in rows:
                with self._lock:
                    handler = self._retry_handlers.get(entry["event_type"])

                if handler:
                    try:
                        conn.execute(
                            "UPDATE dlq_entries SET status = 'RETRYING' WHERE entry_id = ?",
                            (entry["entry_id"],),
                        )

                        if asyncio.iscoroutinefunction(handler):
                            await handler(entry["payload"])
                        else:
                            handler(entry["payload"])

                        # Başarılı çözüm
                        resolved_time = datetime.now(UTC).isoformat()
                        conn.execute(
                            """
                            UPDATE dlq_entries SET status = 'RESOLVED', resolved_at = ?
                            WHERE entry_id = ?
                            """,
                            (resolved_time, entry["entry_id"]),
                        )

                        with self._lock:
                            self._total_resolved += 1
                            self._total_retried += 1
                        retried += 1
                        dlq_resolve_counter.add(1, {"event_type": entry["event_type"]})

                    except Exception as e:
                        new_count = int(entry["retry_count"]) + 1
                        if new_count >= int(entry["max_retries"]):
                            conn.execute(
                                """
                                UPDATE dlq_entries SET status = 'EXHAUSTED',
                                retry_count = ?, error = ?
                                WHERE entry_id = ?
                                """,
                                (new_count, str(e), entry["entry_id"]),
                            )
                            with self._lock:
                                self._total_exhausted += 1
                        else:
                            backoff = DEFAULT_BASE_BACKOFF_SECONDS * (2**new_count)
                            next_retry = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()
                            conn.execute(
                                """
                                UPDATE dlq_entries SET status = 'PENDING',
                                retry_count = ?, error = ?, next_retry_at = ?
                                WHERE entry_id = ?
                                """,
                                (new_count, str(e), next_retry, entry["entry_id"]),
                            )
                else:
                    conn.execute(
                        "UPDATE dlq_entries SET status = 'EXHAUSTED' WHERE entry_id = ?",
                        (entry["entry_id"],),
                    )
                    with self._lock:
                        self._total_exhausted += 1

        self._cleanup_resolved()
        return retried

    @otel_trace("persistent_dlq.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """DLQ kuyruk istatistiklerini ve yaşam döngüsü sayaçlarını döner."""
        with self._connect() as conn:
            by_status: dict[str, int] = {}
            for row in conn.execute("SELECT status, COUNT(*) FROM dlq_entries GROUP BY status").fetchall():
                by_status[str(row[0])] = int(row[1])

            by_type: dict[str, int] = {}
            for row in conn.execute("SELECT event_type, COUNT(*) FROM dlq_entries GROUP BY event_type").fetchall():
                by_type[str(row[0])] = int(row[1])

            total_row = conn.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()
            total = int(total_row[0]) if total_row else 0

        with self._lock:
            return {
                "total_entries": total,
                "by_status": by_status,
                "by_event_type": by_type,
                "lifetime": {
                    "total_pushed": self._total_pushed,
                    "total_retried": self._total_retried,
                    "total_resolved": self._total_resolved,
                    "total_exhausted": self._total_exhausted,
                },
                "db_path": str(self.db_path),
                "persistent": True,
                "engine": "DuckDB",
            }

    @otel_trace("persistent_dlq.get_entries")
    async def get_entries(
        self,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Kalıcı DLQ kayıtlarını durum veya olay tipine göre listeler."""
        with self._connect() as conn:
            query = "SELECT * FROM dlq_entries WHERE 1=1"
            params: list[Any] = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cur = conn.execute(query, params)
            return self._cursor_to_dicts(cur)

    @otel_trace("persistent_dlq.get_entry")
    async def get_entry(self, entry_id: str) -> DLQEntry | None:
        """Belirtilen tekil entry_id'ye ait DLQ kaydını DLQEntry nesnesi olarak çeker.

        Args:
            entry_id: Sorgulanacak kayıt kimliği.

        Returns:
            Bulunursa DLQEntry nesnesi, yoksa None.
        """
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM dlq_entries WHERE entry_id = ? LIMIT 1", (entry_id,))
            rows = self._cursor_to_dicts(cur)
            if not rows:
                return None
            r = rows[0]
            return DLQEntry(
                entry_id=str(r["entry_id"]),
                event_id=str(r["event_id"]),
                event_type=str(r["event_type"]),
                payload=str(r.get("payload", "")),
                error=str(r.get("error", "")),
                retry_count=int(r.get("retry_count", 0)),
                max_retries=int(r.get("max_retries", 3)),
                status=DLQStatus(r.get("status", "PENDING")),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                last_retry_at=datetime.fromisoformat(r["last_retry_at"]) if r.get("last_retry_at") else None,
                next_retry_at=datetime.fromisoformat(r["next_retry_at"]) if r.get("next_retry_at") else None,
                resolved_at=datetime.fromisoformat(r["resolved_at"]) if r.get("resolved_at") else None,
            )

    @otel_trace("persistent_dlq.clear")
    async def clear(self) -> int:
        """Tüm DLQ tablosunu temizler ve silinen kayıt adedini döner."""
        with self._connect() as conn:
            count_row = conn.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()
            count = int(count_row[0]) if count_row else 0
            conn.execute("DELETE FROM dlq_entries")
        return count

    def _cleanup_resolved(self) -> None:
        """Çözülmüş kayıtları temizler (son 24 saat muhafaza edilir)."""
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM dlq_entries
                WHERE status = 'RESOLVED' AND resolved_at < ?
                """,
                (cutoff,),
            )

    def _evict_oldest(self) -> None:
        """Maksimum kayıt kapasitesi aşıldığında en eski çözülmüş veya tükenmiş kayıtları siler."""
        with self._connect() as conn:
            count_row = conn.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()
            count = int(count_row[0]) if count_row else 0
            if count > self._max_entries:
                excess = count - self._max_entries
                conn.execute(
                    """
                    DELETE FROM dlq_entries WHERE entry_id IN (
                        SELECT entry_id FROM dlq_entries
                        WHERE status IN ('RESOLVED', 'EXHAUSTED')
                        ORDER BY created_at ASC LIMIT ?
                    )
                    """,
                    (excess,),
                )

    @otel_trace("persistent_dlq.replay_single")
    async def replay_single(self, entry_id: str) -> bool:
        """Belirtilen tekil DLQ olayını derhal yeniden işler (self-healing).

        Args:
            entry_id: Yeniden işletilecek tekil kayıt kimliği.

        Returns:
            İşlem başarılıysa True, kayıt veya işleyici bulunamazsa ya da hata alırsa False.
        """
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM dlq_entries WHERE entry_id = ?", (entry_id,))
            rows = self._cursor_to_dicts(cur)
            if not rows:
                return False
            entry = rows[0]

            with self._lock:
                handler = self._retry_handlers.get(entry["event_type"])

            if not handler:
                return False

            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(entry["payload"])
                else:
                    handler(entry["payload"])

                conn.execute(
                    "UPDATE dlq_entries SET status = 'RESOLVED', resolved_at = ? WHERE entry_id = ?",
                    (datetime.now(UTC).isoformat(), entry_id),
                )
                with self._lock:
                    self._total_resolved += 1
                    self._total_retried += 1
                logger.info("dlq_kaydi_self_healing_ile_cozuldu", entry_id=entry_id)
                return True
            except Exception as exc:
                conn.execute(
                    "UPDATE dlq_entries SET retry_count = retry_count + 1, error = ? WHERE entry_id = ?",
                    (str(exc)[:200], entry_id),
                )
                logger.error("dlq_tekil_replay_hatasi", entry_id=entry_id, hata=str(exc))
                return False

    @otel_trace("persistent_dlq.reset_exhausted_entries")
    def reset_exhausted_entries(self, event_type: str | None = None) -> int:
        """Tükenmiş (EXHAUSTED) kayıtları sıfırlayarak yeniden denenebilir (PENDING) yapar.

        Self-healing mekanizması olarak kullanılır.

        Args:
            event_type: İsteğe bağlı filtrelenecek olay türü.

        Returns:
            Sıfırlanan ve yeniden canlandırılan kayıt adedi.
        """
        query = "UPDATE dlq_entries SET status = 'PENDING', retry_count = 0, next_retry_at = NULL WHERE status = 'EXHAUSTED'"
        params: list[Any] = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        with self._connect() as conn:
            conn.execute(query, params)
            cur = conn.execute("SELECT COUNT(*) FROM dlq_entries WHERE status = 'PENDING'")
            row = cur.fetchone()
            count = int(row[0]) if row else 0

        logger.info("dlq_tukenmis_kayitlar_sifirlandi", pending_toplam=count, event_type=event_type)
        return count

    @otel_trace("persistent_dlq.start_background_retry_worker")
    def start_background_retry_worker(self, interval_seconds: int = 15) -> None:
        """Arka planda periyodik olarak DLQ yeniden deneme döngüsünü çalıştırır."""
        with self._lock:
            if self._bg_retrying:
                return
            self._bg_retrying = True

            def _retry_worker() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    while self._bg_retrying:
                        try:
                            loop.run_until_complete(self.retry_failed())
                        except Exception as exc:
                            logger.warning("arkaplan_dlq_retry_hatasi", hata=str(exc))
                        time.sleep(interval_seconds)
                finally:
                    loop.close()

            self._bg_thread = threading.Thread(
                target=_retry_worker,
                daemon=True,
                name="DLQRetryWorkerThread",
            )
            self._bg_thread.start()
            logger.info("arkaplan_dlq_retry_worker_baslatildi", aralik_sn=interval_seconds)

    @otel_trace("persistent_dlq.stop_background_retry_worker")
    def stop_background_retry_worker(self) -> None:
        """Arka plan DLQ yeniden deneme iş parçacığını durdurur."""
        with self._lock:
            self._bg_retrying = False
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=2.0)
            self._bg_thread = None
            logger.info("arkaplan_dlq_retry_worker_durduruldu")

    async def to_orjson_bytes(self) -> bytes:
        """DLQ istatistiklerini C seviyesinde orjson bayt dizisine serileştirir."""
        stats = await self.get_stats()
        return orjson.dumps(stats, option=orjson.OPT_SORT_KEYS, default=str)

    def export_dlq_to_polars(self, status: str | None = None, limit: int = 1000) -> pl.DataFrame:
        """Kalıcı DLQ kayıtlarını Polars DataFrame olarak dışa aktarır."""
        with self._connect() as conn:
            query = "SELECT entry_id, event_id, event_type, status, retry_count, max_retries, created_at, last_retry_at, next_retry_at, resolved_at, error FROM dlq_entries WHERE 1=1"
            params: list[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cur = conn.execute(query, params)
            rows = self._cursor_to_dicts(cur)

        schema = {
            "entry_id": pl.String,
            "event_id": pl.String,
            "event_type": pl.String,
            "status": pl.String,
            "retry_count": pl.Int64,
            "max_retries": pl.Int64,
            "created_at": pl.String,
            "last_retry_at": pl.String,
            "next_retry_at": pl.String,
            "resolved_at": pl.String,
            "error": pl.String,
        }
        if not rows:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(rows, schema=schema)

    def export_dlq_stats_to_polars(self) -> pl.DataFrame:
        """Kalıcı DLQ sayaçlarını Polars DataFrame olarak dışa aktarır."""
        with self._connect() as conn:
            total_row = conn.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()
            total = int(total_row[0]) if total_row else 0

        with self._lock:
            records = [
                {"metric_name": "total_entries", "metric_value": float(total)},
                {"metric_name": "total_pushed", "metric_value": float(self._total_pushed)},
                {"metric_name": "total_retried", "metric_value": float(self._total_retried)},
                {"metric_name": "total_resolved", "metric_value": float(self._total_resolved)},
                {"metric_name": "total_exhausted", "metric_value": float(self._total_exhausted)},
            ]

        schema = {
            "metric_name": pl.String,
            "metric_value": pl.Float64,
        }
        return pl.DataFrame(records, schema=schema)

    def __repr__(self) -> str:
        with self._lock:
            return f"<PersistentDeadLetterQueue db_path='{self.db_path}' max_entries={self._max_entries} engine=DuckDB>"


# Singleton
persistent_dlq: Final[PersistentDeadLetterQueue] = PersistentDeadLetterQueue()


def export_dlq_to_polars(status: str | None = None, limit: int = 1000) -> pl.DataFrame:
    """Kalıcı DLQ kayıtlarını Polars DataFrame olarak dışa aktarır."""
    return persistent_dlq.export_dlq_to_polars(status=status, limit=limit)


def export_dlq_stats_to_polars() -> pl.DataFrame:
    """Kalıcı DLQ istatistiklerini Polars DataFrame olarak dışa aktarır."""
    return persistent_dlq.export_dlq_stats_to_polars()


def replay_single_dlq_entry(entry_id: str) -> Any:
    """Singleton üzerinden tekil DLQ olayını yeniden oynatır."""
    return persistent_dlq.replay_single(entry_id=entry_id)


def reset_exhausted_dlq_entries(event_type: str | None = None) -> int:
    """Singleton üzerinden tükenmiş DLQ kayıtlarını sıfırlar."""
    return persistent_dlq.reset_exhausted_entries(event_type=event_type)


def get_dlq_entry(entry_id: str) -> Any:
    """Singleton üzerinden tekil DLQ kaydını asenkron çeker."""
    return persistent_dlq.get_entry(entry_id=entry_id)


def clear_dlq_duckdb(db_path: str = DEFAULT_DLQ_DB_PATH) -> None:
    """Belirtilen DuckDB veritabanındaki DLQ tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path = Path(db_path)
    if not path.exists():
        return
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("DELETE FROM dlq_entries")
        conn.commit()
        logger.info("dlq_duckdb_temizlendi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_BASE_BACKOFF_SECONDS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DLQ_DB_PATH",
    "DEFAULT_MAX_ENTRIES",
    "DLQEntry",
    "DLQStatus",
    "PersistentDeadLetterQueue",
    "clear_dlq_duckdb",
    "configure_duckdb_wal",
    "export_dlq_stats_to_polars",
    "export_dlq_to_polars",
    "get_dlq_entry",
    "otel_trace",
    "persistent_dlq",
    "replay_single_dlq_entry",
    "reset_exhausted_dlq_entries",
]
