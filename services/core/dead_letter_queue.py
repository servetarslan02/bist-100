"""ALPHA BIST — Dead Letter Queue (Başarısız Event'ler İçin Kalıcı Kuyruk)

v2.0: Artık PersistentDeadLetterQueue kullanılıyor — restart sonrası kaybolmaz.
In-memory DLQ yerine SQLite tabanlı persistent DLQ.
"""

import structlog

logger = structlog.get_logger()

# Persistent DLQ kullan — restart sonrası kaybolmaz
try:
    from .persistent_dlq import PersistentDeadLetterQueue, DLQStatus

    class DeadLetterQueue(PersistentDeadLetterQueue):
        """Backward-compatible wrapper — PersistentDeadLetterQueue kullanır."""
        pass

    dead_letter_queue = DeadLetterQueue()
    logger.info("DeadLetterQueue: Using PersistentDeadLetterQueue (SQLite-backed)")
except Exception as e:
    logger.warning(f"PersistentDLQ unavailable, falling back to in-memory: {e}")

    # Fallback: in-memory (son çare)
    import hashlib
    import time
    from typing import Dict, List, Optional, Any, Callable
    from dataclasses import dataclass, field
    from datetime import datetime, timezone, timedelta
    from enum import Enum

    class DLQStatus(str, Enum):
        PENDING = "PENDING"
        RETRYING = "RETRYING"
        RESOLVED = "RESOLVED"
        EXHAUSTED = "EXHAUSTED"

    @dataclass
    class DLQEntry:
        entry_id: str
        event_id: str
        event_type: str
        payload: str
        error: str
        retry_count: int = 0
        max_retries: int = 3
        status: DLQStatus = DLQStatus.PENDING
        created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
        last_retry_at: Optional[datetime] = None
        next_retry_at: Optional[datetime] = None
        resolved_at: Optional[datetime] = None

        def to_dict(self):
            return {
                "entry_id": self.entry_id,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "error": self.error,
                "retry_count": self.retry_count,
                "max_retries": self.max_retries,
                "status": self.status.value,
                "created_at": self.created_at.isoformat(),
            }

        @property
        def is_retryable(self):
            return self.status == DLQStatus.PENDING and self.retry_count < self.max_retries

        @property
        def is_ready_for_retry(self):
            if not self.is_retryable:
                return False
            if self.next_retry_at is None:
                return True
            return datetime.now(timezone.utc) >= self.next_retry_at

    class InMemoryDeadLetterQueue:
        """Fallback in-memory DLQ."""
        def __init__(self, max_entries=10000):
            self._entries: Dict[str, DLQEntry] = {}
            self._max_entries = max_entries
            self._retry_handlers: Dict[str, Any] = {}
            self._total_pushed = 0
            self._total_retried = 0
            self._total_resolved = 0
            self._total_exhausted = 0

        def register_retry_handler(self, event_type, handler):
            self._retry_handlers[event_type] = handler

        async def push(self, event_id, event_type, payload, error, retry_count=0, max_retries=3):
            if len(self._entries) >= self._max_entries:
                oldest_id = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
                del self._entries[oldest_id]
            entry_id = hashlib.md5(f"dlq_{event_id}_{time.time()}".encode()).hexdigest()[:12]
            backoff = 5 * (2 ** retry_count)
            entry = DLQEntry(
                entry_id=entry_id, event_id=event_id, event_type=event_type,
                payload=payload, error=error, retry_count=retry_count,
                max_retries=max_retries,
                next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=backoff),
            )
            self._entries[entry_id] = entry
            self._total_pushed += 1
            return entry

        async def retry_failed(self, batch_size=100):
            return 0

        async def get_stats(self):
            return {"total_entries": len(self._entries), "lifetime": {"total_pushed": self._total_pushed}}

        async def get_entries(self, status=None, event_type=None, limit=50):
            return [e.to_dict() for e in list(self._entries.values())[:limit]]

        async def remove_entry(self, entry_id):
            self._entries.pop(entry_id, None)
            return True

        async def clear(self):
            count = len(self._entries)
            self._entries.clear()
            return count

    dead_letter_queue = InMemoryDeadLetterQueue()
