"""ALPHA BIST — Dead Letter Queue (DLQ) Kalıcı Olay ve Hata Yönetim Motoru.

Bu modül, mikroservisler, asenkron olay hatları (EventBus, NATS) ve arka plan
görevleri sırasında başarısız olan tüm olayların (events) güvenli şekilde muhafaza
edilmesini ve üstel geri çekilme (exponential backoff) ile yeniden işlenmesini sağlar:

1. Kalıcı Saklama (Persistence):
   - Birincil motor olarak `PersistentDeadLetterQueue` (DuckDB WAL destekli) kullanılır.
   - Sistem veya süreç yeniden başladığında (restart) başarısız olaylar asla kaybolmaz.
2. Esnek ve Kurumsal Geri Çekilme (Exponential Backoff):
   - Her başarısız denemede bekleme süresi katlanarak artar (`5 * 2^retry_count`).
3. Thread & Coroutine Eşzamanlılık Güvenliği:
   - Çoklu iş parçacığı ve asyncio ortamında reentrant kilit (`threading.RLock`) ile
     veri bütünlüğü korunur.
4. Sıfır Kopyalı Polars Analitiği:
   - Kuyruktaki olaylar analitik inceleme ve monitoring için Polars DataFrame olarak sunulur.
5. Fail-Closed ve Dayanıklılık Garantisi:
   - DuckDB veritabanına erişilemediği olağanüstü durumlarda, olay kaybını önlemek
     amacıyla tam fonksiyonel ve thread-safe `InMemoryDeadLetterQueue` devreye girer.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import polars as pl
import structlog

from services.core.otel import otel_trace
from services.core.persistent_dlq import (
    DLQEntry as PersistentDLQEntry,
)
from services.core.persistent_dlq import (
    DLQStatus as PersistentDLQStatus,
)
from services.core.persistent_dlq import (
    PersistentDeadLetterQueue,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class DLQStatus(StrEnum):
    """Dead Letter Queue kayıt durum kodları."""

    PENDING = "PENDING"  # Yeniden denenmeyi bekliyor
    RETRYING = "RETRYING"  # Şu anda işleniyor
    RESOLVED = "RESOLVED"  # Başarıyla tamamlandı/çözüldü
    EXHAUSTED = "EXHAUSTED"  # Maksimum deneme sayısına ulaştı ve tükendi


@dataclass(slots=True)
class DLQEntry:
    """Kalıcı DLQ olay kaydı veri modeli.

    Attributes:
        entry_id: Kuyruk kayıt kimliği (MD5 özeti).
        event_id: Orijinal olayın benzersiz kimliği.
        event_type: Olayın türü veya kanalı (örn. "ORDER_EXECUTION").
        payload: Olayın serileştirilmiş JSON içeriği.
        error: Oluşan hatanın açıklama veya izleme metni.
        retry_count: Şu ana kadar yapılan yeniden deneme sayısı.
        max_retries: İzin verilen azami yeniden deneme adedi.
        status: Kaydın güncel işlem durumu.
        created_at: Kuyruğa ilk eklenme UTC zaman damgası.
        last_retry_at: Son deneme UTC zaman damgası.
        next_retry_at: Bir sonraki planlanan deneme UTC zaman damgası.
        resolved_at: Çözülme/başarı UTC zaman damgası.
    """

    entry_id: str
    event_id: str
    event_type: str
    payload: str
    error: str
    retry_count: int = 0
    max_retries: int = 3
    status: DLQStatus = DLQStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_retry_at: datetime | None = None
    next_retry_at: datetime | None = None
    resolved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Kayıt alanlarını JSON uyumlu sözlüğe dönüştürür."""
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
        """Kaydın tekrar denenmeye uygun olup olmadığını doğrular."""
        return self.status == DLQStatus.PENDING and self.retry_count < self.max_retries

    @property
    def is_ready_for_retry(self) -> bool:
        """Kaydın geri çekilme (backoff) süresinin dolup dolmadığını denetler."""
        if not self.is_retryable:
            return False
        if self.next_retry_at is None:
            return True
        return datetime.now(UTC) >= self.next_retry_at

    def __repr__(self) -> str:
        """Kayıt için açıklayıcı hata ayıklama temsili."""
        return (
            f"DLQEntry(id={self.entry_id!r}, event_type={self.event_type!r}, "
            f"status={self.status.value}, retries={self.retry_count}/{self.max_retries})"
        )


class InMemoryDeadLetterQueue:
    """Yedek (Fallback) Bellek İçi Dead Letter Queue Motoru.

    DuckDB bağlantısının kurulamadığı olağanüstü durumlarda veri kaybını
    önlemek üzere devreye giren tam teşekküllü, thread-safe bellek kuyruğu.
    """

    def __init__(self, max_entries: int = 10000) -> None:
        """InMemoryDeadLetterQueue örneğini başlatır.

        Args:
            max_entries: Saklanabilecek maksimum kayıt sayısı.
        """
        self._entries: dict[str, DLQEntry] = {}
        self._max_entries = max_entries
        self._retry_handlers: dict[str, Callable[..., Any]] = {}
        self._lock = threading.RLock()
        self._total_pushed: int = 0
        self._total_retried: int = 0
        self._total_resolved: int = 0
        self._total_exhausted: int = 0

    def register_retry_handler(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Belirli bir olay tipi için yeniden deneme işleyicisi kaydeder."""
        with self._lock:
            self._retry_handlers[event_type] = handler

    @otel_trace("dead_letter_queue.in_memory.push")
    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: str,
        error: str,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Başarısız bir olayı bellek içi kuyruğa ekler ve entry_id döner."""
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest_id = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
                del self._entries[oldest_id]

            entry_id = hashlib.md5(f"dlq_{event_id}_{time.time()}".encode()).hexdigest()[:12]
            backoff_seconds = 5 * (2**retry_count)
            now = datetime.now(UTC)

            entry = DLQEntry(
                entry_id=entry_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                error=error,
                retry_count=retry_count,
                max_retries=max_retries,
                status=DLQStatus.PENDING,
                created_at=now,
                next_retry_at=now + timedelta(seconds=backoff_seconds),
            )
            self._entries[entry_id] = entry
            self._total_pushed += 1
            logger.info("dlq_in_memory_olay_eklendi", entry_id=entry_id, event_type=event_type)
            return entry_id

    @otel_trace("dead_letter_queue.in_memory.retry_failed")
    async def retry_failed(self, batch_size: int = 100) -> int:
        """Zamanı gelen başarısız olayları kayıtlı işleyicilerle yeniden çalıştırır."""
        with self._lock:
            candidates = [
                entry
                for entry in self._entries.values()
                if entry.is_ready_for_retry
            ][:batch_size]

        resolved_count = 0
        for entry in candidates:
            with self._lock:
                handler = self._retry_handlers.get(entry.event_type)
                entry.status = DLQStatus.RETRYING
                entry.last_retry_at = datetime.now(UTC)
                entry.retry_count += 1
                self._total_retried += 1

            if handler is None:
                with self._lock:
                    entry.status = DLQStatus.PENDING
                continue

            try:
                if asyncio.iscoroutinefunction(handler):
                    success = await handler(entry.payload)
                else:
                    success = handler(entry.payload)

                with self._lock:
                    if success:
                        entry.status = DLQStatus.RESOLVED
                        entry.resolved_at = datetime.now(UTC)
                        self._total_resolved += 1
                        resolved_count += 1
                    elif entry.retry_count >= entry.max_retries:
                        entry.status = DLQStatus.EXHAUSTED
                        self._total_exhausted += 1
                    else:
                        backoff = 5 * (2**entry.retry_count)
                        entry.status = DLQStatus.PENDING
                        entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)
            except Exception as exc:
                logger.error("dlq_retry_isleyici_hatasi", entry_id=entry.entry_id, error=str(exc))
                with self._lock:
                    if entry.retry_count >= entry.max_retries:
                        entry.status = DLQStatus.EXHAUSTED
                        self._total_exhausted += 1
                    else:
                        backoff = 5 * (2**entry.retry_count)
                        entry.status = DLQStatus.PENDING
                        entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)

        return resolved_count

    @otel_trace("dead_letter_queue.in_memory.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """Kuyruk durum istatistiklerini döndürür."""
        with self._lock:
            pending = sum(1 for e in self._entries.values() if e.status == DLQStatus.PENDING)
            resolved = sum(1 for e in self._entries.values() if e.status == DLQStatus.RESOLVED)
            exhausted = sum(1 for e in self._entries.values() if e.status == DLQStatus.EXHAUSTED)
            return {
                "engine": "InMemory",
                "total_entries": len(self._entries),
                "by_status": {
                    "PENDING": pending,
                    "RESOLVED": resolved,
                    "EXHAUSTED": exhausted,
                },
                "pending": pending,
                "resolved": resolved,
                "exhausted": exhausted,
                "lifetime": {
                    "total_pushed": self._total_pushed,
                    "total_retried": self._total_retried,
                    "total_resolved": self._total_resolved,
                    "total_exhausted": self._total_exhausted,
                },
                "persistent": False,
            }

    @otel_trace("dead_letter_queue.in_memory.get_entries")
    async def get_entries(
        self,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Kuyruktaki kayıtları filtreleyerek getirir."""
        with self._lock:
            results = []
            for entry in self._entries.values():
                if status and entry.status.value != status:
                    continue
                if event_type and entry.event_type != event_type:
                    continue
                results.append(entry.to_dict())
                if len(results) >= limit:
                    break
            return results

    @otel_trace("dead_letter_queue.in_memory.remove_entry")
    async def remove_entry(self, entry_id: str) -> bool:
        """Belirtilen kaydı bellekten kaldırır."""
        with self._lock:
            return self._entries.pop(entry_id, None) is not None

    @otel_trace("dead_letter_queue.in_memory.clear")
    async def clear(self) -> int:
        """Tüm kayıtları siler."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def export_to_polars(self, limit: int = 100) -> pl.DataFrame:
        """Bellek içi kayıtları Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            rows = [e.to_dict() for e in self._entries.values()][:limit]
            if not rows:
                return pl.DataFrame()
            return pl.DataFrame(rows)

    def __repr__(self) -> str:
        """Nesne durum temsili."""
        with self._lock:
            return f"InMemoryDeadLetterQueue(entries={len(self._entries)}, max={self._max_entries})"


class DeadLetterQueue(PersistentDeadLetterQueue):
    """Kurumsal ve Kalıcı Dead Letter Queue Motoru.

    `PersistentDeadLetterQueue` sınıfını miras alarak DuckDB WAL garantisiyle
    tüm hata ve olay kuyruğu operasyonlarını yürütür; sistem çöküşlerinde
    veri kaybı yaşanmasını önler.
    """

    def __init__(
        self,
        db_path: str = "data/dlq.db",
        max_entries: int = 50000,
    ) -> None:
        """DeadLetterQueue örneğini başlatır."""
        super().__init__(db_path=db_path, max_entries=max_entries)

    async def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döner; doğrudan pending/resolved alanları ile zenginleştirir."""
        stats = await super().get_stats()
        by_status = stats.get("by_status", {})
        stats["pending"] = by_status.get("PENDING", 0)
        stats["resolved"] = by_status.get("RESOLVED", 0)
        stats["exhausted"] = by_status.get("EXHAUSTED", 0)
        return stats

    def export_to_polars(self, limit: int = 100) -> pl.DataFrame:
        """Kalıcı DuckDB DLQ kayıtlarını sıfır kopyalı Polars DataFrame olarak dışa aktarır."""
        with self._connect() as conn:
            try:
                arrow_table = conn.execute(
                    """
                    SELECT entry_id, event_id, event_type, error, retry_count,
                           max_retries, status, created_at, last_retry_at, next_retry_at, resolved_at
                    FROM dlq_entries
                    ORDER BY created_at DESC
                    LIMIT ?;
                    """,
                    [limit],
                ).arrow()
                return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("dlq_polars_aktarim_hatasi", error=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """Kalıcı kuyruk durum temsili."""
        return f"DeadLetterQueue(db_path={self.db_path!r}, max_entries={self._max_entries})"


# Singleton Kuyruk Nesnesini Hazırla
def _create_dlq_instance() -> PersistentDeadLetterQueue | InMemoryDeadLetterQueue:
    """Kalıcı DuckDB motorunu başlatır; disk arızası halinde güvenli InMemory fallback'e geçer."""
    try:
        instance = DeadLetterQueue()
        logger.info("dead_letter_queue_persistent_aktif", db_path=instance.db_path)
        return instance
    except Exception as exc:
        logger.warning(
            "dead_letter_queue_persistent_baslatilamadi_in_memory_devrede",
            error=str(exc),
        )
        return InMemoryDeadLetterQueue()


# Global Singleton
dead_letter_queue: Final[PersistentDeadLetterQueue | InMemoryDeadLetterQueue] = _create_dlq_instance()

__all__: Final[list[str]] = [
    "DLQEntry",
    "DLQStatus",
    "DeadLetterQueue",
    "InMemoryDeadLetterQueue",
    "PersistentDLQEntry",
    "PersistentDLQStatus",
    "dead_letter_queue",
]
