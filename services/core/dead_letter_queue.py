from typing import Any

"""ALPHA BIST — Dead Letter Queue (Başarısız Event'ler İçin Kalıcı Kuyruk)

v2.0: Artık PersistentDeadLetterQueue kullanılıyor — restart sonrası kaybolmaz.
In-memory DLQ yerine DuckDB tabanlı persistent DLQ.
"""

import enum
import functools
from datetime import UTC

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.dead_letter_queue")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return await func(self, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return async_wrapper if __import__("asyncio").iscoroutinefunction(func) else sync_wrapper

    return decorator


# Persistent DLQ kullan — restart sonrası kaybolmaz
try:
    from .persistent_dlq import DLQEntry, DLQStatus, PersistentDeadLetterQueue

    class DeadLetterQueue(PersistentDeadLetterQueue):
        """Backward-compatible wrapper — PersistentDeadLetterQueue kullanır."""

        pass

    dead_letter_queue = DeadLetterQueue()
    logger.info("DeadLetterQueue: Using PersistentDeadLetterQueue (DuckDB-backed)")
except Exception as e:
    logger.warning(f"PersistentDLQ unavailable, falling back to in-memory: {e}")

    # Fallback: in-memory (son çare)
    import hashlib
    import time
    from dataclasses import dataclass, field
    from datetime import datetime, timedelta
    from typing import Any

    class DLQStatus(enum.StrEnum):
        """Otomatik eklendi."""
        PENDING = "PENDING"
        RETRYING = "RETRYING"
        RESOLVED = "RESOLVED"
        EXHAUSTED = "EXHAUSTED"

    @dataclass
    class DLQEntry:
        """Otomatik eklendi."""
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

        def to_dict(self) -> Any:
            """Otomatik eklendi."""
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
        def is_retryable(self) -> Any:
            """Otomatik eklendi."""
            return self.status == DLQStatus.PENDING and self.retry_count < self.max_retries

        @property
        def is_ready_for_retry(self) -> Any:
            """Otomatik eklendi."""
            if not self.is_retryable:
                return False
            if self.next_retry_at is None:
                return True
            return datetime.now(UTC) >= self.next_retry_at

    class InMemoryDeadLetterQueue:
        """Fallback in-memory DLQ."""

        def __init__(self, max_entries=10000):
            """Otomatik eklendi."""
            self._entries: dict[str, DLQEntry] = {}
            self._max_entries = max_entries
            self._retry_handlers: dict[str, Any] = {}
            self._total_pushed = 0
            self._total_retried = 0
            self._total_resolved = 0
            self._total_exhausted = 0

        def register_retry_handler(self, event_type, handler) -> Any:
            """Otomatik eklendi."""
            self._retry_handlers[event_type] = handler

        @otel_trace("dead_letter_queue.push")
        async def push(self, event_id, event_type, payload, error, retry_count=0, max_retries=3) -> Any:
            """Otomatik eklendi."""
            if len(self._entries) >= self._max_entries:
                oldest_id = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
                del self._entries[oldest_id]
            entry_id = hashlib.md5(f"dlq_{event_id}_{time.time()}".encode()).hexdigest()[:12]
            backoff = 5 * (2**retry_count)
            entry = DLQEntry(
                entry_id=entry_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                error=error,
                retry_count=retry_count,
                max_retries=max_retries,
                next_retry_at=datetime.now(UTC) + timedelta(seconds=backoff),
            )
            self._entries[entry_id] = entry
            self._total_pushed += 1
            return entry

        @otel_trace("dead_letter_queue.retry_failed")
        async def retry_failed(self, batch_size=100) -> Any:
            """Otomatik eklendi."""
            return 0

        @otel_trace("dead_letter_queue.get_stats")
        async def get_stats(self) -> Any:
            """Otomatik eklendi."""
            return {"total_entries": len(self._entries), "lifetime": {"total_pushed": self._total_pushed}}

        @otel_trace("dead_letter_queue.get_entries")
        async def get_entries(self, status=None, event_type=None, limit=50) -> Any:
            """Otomatik eklendi."""
            return [e.to_dict() for e in list(self._entries.values())[:limit]]

        @otel_trace("dead_letter_queue.remove_entry")
        async def remove_entry(self, entry_id) -> Any:
            """Otomatik eklendi."""
            self._entries.pop(entry_id, None)
            return True

        @otel_trace("dead_letter_queue.clear")
        async def clear(self) -> Any:
            """Otomatik eklendi."""
            count = len(self._entries)
            self._entries.clear()
            return count

    dead_letter_queue = InMemoryDeadLetterQueue()
