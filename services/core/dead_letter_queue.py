"""
ALPHA BIST — Dead Letter Queue (DLQ)

Başarısız event'ler için kalıcı kuyruk.
Event bus'ta handler crash ederse event kaybolmaz, DLQ'ya düşer.

Özellikler:
1. Başarısız event'leri sakla
2. Retry with exponential backoff
3. Max retry limiti
4. İstatistikler ve monitoring
5. Manuel retry desteği

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.1
- Temporal Error Handling Guide (2025)
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import structlog

logger = structlog.get_logger()


class DLQStatus(str, Enum):
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"  # Max retry aşıldı


@dataclass
class DLQEntry:
    """DLQ kaydı."""
    entry_id: str
    event_id: str
    event_type: str
    payload: str  # JSON serialized event
    error: str
    retry_count: int = 0
    max_retries: int = 3
    status: DLQStatus = DLQStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_retry_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
        }

    @property
    def is_retryable(self) -> bool:
        """Tekrar denenebilir mi?"""
        return (
            self.status == DLQStatus.PENDING and
            self.retry_count < self.max_retries
        )

    @property
    def is_ready_for_retry(self) -> bool:
        """Retry zamanı geldi mi?"""
        if not self.is_retryable:
            return False
        if self.next_retry_at is None:
            return True
        return datetime.now(timezone.utc) >= self.next_retry_at


class DeadLetterQueue:
    """
    Dead Letter Queue — başarısız event'ler için kalıcı kuyruk.

    Kullanım:
        dlq = DeadLetterQueue()
        await dlq.push(event, error="Connection timeout", retry_count=0)
        retried = await dlq.retry_failed()
        stats = await dlq.get_stats()
    """

    def __init__(self, max_entries: int = 10000):
        self._entries: Dict[str, DLQEntry] = {}
        self._max_entries = max_entries
        self._retry_handlers: Dict[str, Callable] = {}  # event_type → handler
        self._total_pushed: int = 0
        self._total_retried: int = 0
        self._total_resolved: int = 0
        self._total_exhausted: int = 0

    def register_retry_handler(self, event_type: str, handler: Callable):
        """Event type için retry handler kaydet."""
        self._retry_handlers[event_type] = handler

    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: str,
        error: str,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> DLQEntry:
        """
        Başarısız event'i DLQ'ya kaydet.

        Args:
            event_id: Event ID
            event_type: Event tipi
            payload: JSON serialized event
            error: Hata mesajı
            retry_count: Mevcut retry sayısı
            max_retries: Maksimum retry

        Returns:
            DLQEntry
        """
        # Max entries kontrolü
        if len(self._entries) >= self._max_entries:
            self._evict_oldest()

        import hashlib
        entry_id = hashlib.md5(
            f"dlq_{event_id}_{time.time()}".encode()
        ).hexdigest()[:12]

        # Exponential backoff: 5s, 10s, 20s, 40s...
        backoff_seconds = 5 * (2 ** retry_count)
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

        entry = DLQEntry(
            entry_id=entry_id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
            status=DLQStatus.PENDING,
            next_retry_at=next_retry,
        )

        self._entries[entry_id] = entry
        self._total_pushed += 1

        logger.warning("Event pushed to DLQ",
                       entry_id=entry_id,
                       event_type=event_type,
                       retry_count=retry_count,
                       next_retry=next_retry.isoformat())

        return entry

    async def retry_failed(self, batch_size: int = 100) -> int:
        """
        DLQ'daki retry edilebilir event'leri tekrar dene.

        Returns:
            Başarıyla retry edilen sayısı
        """
        retried = 0
        # Include entries that are ready OR have no handler (immediate exhaustion)
        ready_entries = [
            e for e in self._entries.values()
            if e.is_ready_for_retry or (
                e.status == DLQStatus.PENDING and
                e.retry_count < e.max_retries and
                e.event_type not in self._retry_handlers
            )
        ][:batch_size]

        for entry in ready_entries:
            try:
                handler = self._retry_handlers.get(entry.event_type)
                if handler:
                    entry.status = DLQStatus.RETRYING
                    entry.last_retry_at = datetime.now(timezone.utc)
                    entry.retry_count += 1

                    # Deserialize and retry
                    if asyncio.iscoroutinefunction(handler):
                        await handler(entry.payload)
                    else:
                        handler(entry.payload)

                    # Success
                    entry.status = DLQStatus.RESOLVED
                    entry.resolved_at = datetime.now(timezone.utc)
                    self._total_resolved += 1
                    retried += 1

                    logger.info("DLQ entry resolved",
                               entry_id=entry.entry_id,
                               event_type=entry.event_type,
                               retry_count=entry.retry_count)
                else:
                    # No handler registered
                    entry.status = DLQStatus.EXHAUSTED
                    self._total_exhausted += 1
                    logger.warning("DLQ no handler for event type",
                                  event_type=entry.event_type)

            except Exception as e:
                # Retry failed again
                entry.error = str(e)
                entry.status = DLQStatus.PENDING

                if entry.retry_count >= entry.max_retries:
                    entry.status = DLQStatus.EXHAUSTED
                    self._total_exhausted += 1
                    logger.error("DLQ entry exhausted",
                                entry_id=entry.entry_id,
                                retries=entry.retry_count)
                else:
                    # Schedule next retry
                    backoff = 5 * (2 ** entry.retry_count)
                    entry.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

        # Cleanup resolved entries
        self._cleanup_resolved()

        return retried

    async def get_stats(self) -> Dict[str, Any]:
        """DLQ istatistikleri."""
        by_status = {}
        by_type = {}

        for entry in self._entries.values():
            by_status[entry.status.value] = by_status.get(entry.status.value, 0) + 1
            by_type[entry.event_type] = by_type.get(entry.event_type, 0) + 1

        return {
            "total_entries": len(self._entries),
            "by_status": by_status,
            "by_event_type": by_type,
            "lifetime": {
                "total_pushed": self._total_pushed,
                "total_retried": self._total_retried,
                "total_resolved": self._total_resolved,
                "total_exhausted": self._total_exhausted,
            },
        }

    async def get_entries(
        self,
        status: Optional[DLQStatus] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """DLQ kayıtlarını listele."""
        entries = list(self._entries.values())

        if status:
            entries = [e for e in entries if e.status == status]
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]

        entries.sort(key=lambda e: e.created_at, reverse=True)
        return [e.to_dict() for e in entries[:limit]]

    async def remove_entry(self, entry_id: str) -> bool:
        """DLQ kaydını sil."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    async def clear(self) -> int:
        """Tüm DLQ'yı temizle."""
        count = len(self._entries)
        self._entries.clear()
        return count

    def _evict_oldest(self):
        """En eski kaydı çıkar (FIFO)."""
        if not self._entries:
            return
        oldest_id = min(
            self._entries.keys(),
            key=lambda k: self._entries[k].created_at
        )
        del self._entries[oldest_id]

    def _cleanup_resolved(self):
        """Çözülmüş kayıtları temizle (son 1 saat tut)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        to_remove = [
            eid for eid, entry in self._entries.items()
            if entry.status == DLQStatus.RESOLVED and
               entry.resolved_at and entry.resolved_at < cutoff
        ]
        for eid in to_remove:
            del self._entries[eid]


# Singleton
dead_letter_queue = DeadLetterQueue()
