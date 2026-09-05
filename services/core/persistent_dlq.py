"""ALPHA BIST — Persistent Dead Letter Queue v2.0

DuckDB tabanlı kalıcı Dead Letter Queue — sistem yeniden başlatıldığında veri kaybolmaz.
In-memory DLQ'nun kurumsal ve dayanıklı sürümüdür.

Özellikler:
- DuckDB WAL modu (çökme güvenliği)
- Atomik toplu yazma
- Üstel geri çekilme (exponential backoff) ile yeniden deneme
- Maksimum deneme sınırı ve DLQ taşma koruması
- Çözülmüş eski kayıtların otomatik temizlenmesi
- OpenTelemetry metrik ve izleme entegrasyonu
"""

from __future__ import annotations

import asyncio
import functools
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import duckdb
import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.dlq")
meter = metrics.get_meter("alpha-bist.dlq")

dlq_push_counter = meter.create_counter("alpha.dlq.pushes", description="DLQ'ya aktarılan toplam başarısız olay sayısı")
dlq_resolve_counter = meter.create_counter("alpha.dlq.resolved", description="DLQ'dan başarıyla çözülen toplam olay sayısı")


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span bloğu içine alan yardımcı dekoratör."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class DLQStatus(StrEnum):
    """Dead Letter Queue durum kodları."""

    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"


@dataclass
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
    """DuckDB tabanlı kalıcı Dead Letter Queue yöneticisi.

    Sistem çökmesi veya yeniden başlatılması durumunda hatalı event'lerin
    kaybolmasını önler, güvenli kuyrukta muhafaza eder ve üstel geri çekilme ile yeniden dener.
    """

    def __init__(self, db_path: str = "data/dlq.db", max_entries: int = 50000) -> None:
        """Kalıcı DLQ bağlantısını ve dizin yapısını hazırlar."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._retry_handlers: dict[str, Callable] = {}
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
                    entry_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    last_retry_at TEXT,
                    next_retry_at TEXT,
                    resolved_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_status ON dlq_entries(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_type ON dlq_entries(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_created ON dlq_entries(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq_entries(next_retry_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dlq_stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                )
            """)

    @contextmanager
    def _connect(self) -> Any:
        """Güvenli DuckDB bağlantısı ve WAL yapılandırması sağlar."""
        conn = duckdb.connect(str(self.db_path))
        try:
            from services.core.debounce import configure_duckdb_wal

            configure_duckdb_wal(conn)
        except Exception:
            logger.debug("DuckDB WAL optimizasyonu uygulanamadı", exc_info=True)
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
    def register_retry_handler(self, event_type: str, handler: Callable) -> None:
        """Belirli bir olay tipi için yeniden işleme işleyicisini kaydeder."""
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
    async def retry_failed(self, batch_size: int = 100) -> int:
        """DLQ'daki yeniden denenebilir olayları geri çekilme sırasına göre işler."""
        retried = 0
        now = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM dlq_entries
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

                        self._total_resolved += 1
                        self._total_retried += 1
                        retried += 1
                        dlq_resolve_counter.add(1, {"event_type": entry["event_type"]})

                    except Exception as e:
                        new_count = entry["retry_count"] + 1
                        if new_count >= entry["max_retries"]:
                            conn.execute(
                                """
                                UPDATE dlq_entries SET status = 'EXHAUSTED',
                                retry_count = ?, error = ?
                                WHERE entry_id = ?
                                """,
                                (new_count, str(e), entry["entry_id"]),
                            )
                            self._total_exhausted += 1
                        else:
                            backoff = 5 * (2**new_count)
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

    def __repr__(self) -> str:
        return f"<PersistentDeadLetterQueue db_path={self.db_path} max_entries={self._max_entries} engine=DuckDB>"


# Singleton
persistent_dlq = PersistentDeadLetterQueue()
