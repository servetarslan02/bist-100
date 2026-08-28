"""ALPHA BIST — Event Bus Enhancements v1.0

Event bus geliştirmeleri:
- Idempotency (tekrarlanan mesaj koruması)
- Retry policy (exponential backoff)
- Correlation ID (izlenebilirlik)
- Message ordering (sıralı işleme)
- Timestamps (mesaj zaman damgası)

Kullanım:
    from services.core.event_enhancements import event_enhancements

    # Idempotency kontrolü
    is_dup = event_enhancements.is_duplicate(event_id)

    # Retry policy
    should_retry = event_enhancements.should_retry(event_id, attempt)

    # Correlation ID üret
    corr_id = event_enhancements.generate_correlation_id()
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class EventMetadata:
    """Event metadata."""

    event_id: str
    correlation_id: str
    timestamp: str
    attempt: int
    max_retries: int
    retry_after: float | None = None


@dataclass
class RetryPolicy:
    """Retry policy."""

    max_retries: int = 3
    base_delay: float = 1.0  # saniye
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


class EventEnhancements:
    """Event bus geliştirmeleri.

    Özellikler:
    - Idempotency: Aynı event_id tekrar gelirse reddet
    - Retry policy: Exponential backoff ile retry
    - Correlation ID: Tüm ilgili event'leri bağla
    - Message ordering: Per-key sıralı işleme
    - Timestamps: Her event için zaman damgası
    """

    def __init__(
        self,
        idempotency_window_hours: float = 24.0,
        retry_policy: RetryPolicy | None = None,
    ):
        self.idempotency_window_hours = idempotency_window_hours
        self.retry_policy = retry_policy or RetryPolicy()
        self._processed_events: dict[str, float] = {}  # event_id → timestamp
        self._retry_counts: dict[str, int] = {}  # event_id → attempt count
        self._retry_after: dict[str, float] = {}  # event_id → next retry time
        self._correlation_map: dict[str, list[str]] = {}  # correlation_id → [event_ids]
        self._sequence_numbers: dict[str, int] = defaultdict(int)  # key → seq

    # =====================================================
    # IDEMPOTENCY
    # =====================================================

    def is_duplicate(self, event_id: str) -> bool:
        """Event daha önce işlendi mi?

        Args:
            event_id: Event ID

        Returns:
            Duplicate mu?
        """
        self._cleanup_old_events()

        if event_id in self._processed_events:
            logger.debug("idempotency_duplicate_detected", event_id=event_id)
            return True

        return False

    def mark_processed(self, event_id: str) -> None:
        """Event'i işlenmiş olarak işaretle.

        Args:
            event_id: Event ID
        """
        self._processed_events[event_id] = time.time()

    def process_with_idempotency(
        self,
        event_id: str,
        handler: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any | None:
        """Idempotent event işleme.

        Args:
            event_id: Event ID
            handler: İşleyici fonksiyon
            *args, **kwargs: Handler argümanları

        Returns:
            Handler sonucu veya None (duplicate ise)
        """
        if self.is_duplicate(event_id):
            return None

        result = handler(*args, **kwargs)
        self.mark_processed(event_id)
        return result

    # =====================================================
    # RETRY POLICY
    # =====================================================

    def should_retry(self, event_id: str, attempt: int) -> bool:
        """Retry yapılmalı mı?

        Args:
            event_id: Event ID
            attempt: Mevcut deneme sayısı

        Returns:
            Retry yapılmalı mı?
        """
        if attempt >= self.retry_policy.max_retries:
            logger.warning("retry_exhausted", event_id=event_id, attempt=attempt)
            return False

        # Retry after kontrolü
        retry_after = self._retry_after.get(event_id, 0)
        if time.time() < retry_after:
            return False

        return True

    def get_retry_delay(self, attempt: int) -> float:
        """Retry gecikmesi hesapla (exponential backoff + jitter).

        Args:
            attempt: Deneme sayısı

        Returns:
            Gecikme süresi (saniye)
        """
        delay = min(
            self.retry_policy.base_delay * (self.retry_policy.exponential_base ** attempt),
            self.retry_policy.max_delay,
        )

        if self.retry_policy.jitter:
            import random
            delay *= 0.5 + random.random()

        return delay

    def schedule_retry(self, event_id: str, attempt: int) -> float:
        """Retry zamanla.

        Args:
            event_id: Event ID
            attempt: Deneme sayısı

        Returns:
            Retry zamanı (timestamp)
        """
        delay = self.get_retry_delay(attempt)
        retry_time = time.time() + delay

        self._retry_after[event_id] = retry_time
        self._retry_counts[event_id] = attempt + 1

        logger.debug(
            "retry_scheduled",
            event_id=event_id,
            attempt=attempt,
            delay=round(delay, 2),
            retry_at=round(retry_time, 2),
        )

        return retry_time

    def reset_retry(self, event_id: str) -> None:
        """Retry sayacını sıfırla.

        Args:
            event_id: Event ID
        """
        self._retry_counts.pop(event_id, None)
        self._retry_after.pop(event_id, None)

    # =====================================================
    # CORRELATION ID
    # =====================================================

    def generate_correlation_id(self) -> str:
        """Yeni correlation ID üret.

        Returns:
            UUID formatında correlation ID
        """
        return str(uuid.uuid4())

    def link_event(self, correlation_id: str, event_id: str) -> None:
        """Event'i correlation ID'ye bağla.

        Args:
            correlation_id: Correlation ID
            event_id: Event ID
        """
        if correlation_id not in self._correlation_map:
            self._correlation_map[correlation_id] = []

        self._correlation_map[correlation_id].append(event_id)

    def get_linked_events(self, correlation_id: str) -> list[str]:
        """Correlation ID'ye bağlı event'leri döndür.

        Args:
            correlation_id: Correlation ID

        Returns:
            Event ID listesi
        """
        return self._correlation_map.get(correlation_id, [])

    # =====================================================
    # MESSAGE ORDERING
    # =====================================================

    def get_next_sequence(self, key: str) -> int:
        """Sıradaki sequence number'ı döndür.

        Args:
            key: Sıralama anahtarı (ör: ticker, topic)

        Returns:
            Sequence number
        """
        self._sequence_numbers[key] += 1
        return self._sequence_numbers[key]

    def create_metadata(
        self,
        event_id: str,
        correlation_id: str | None = None,
    ) -> EventMetadata:
        """Event metadata oluştur.

        Args:
            event_id: Event ID
            correlation_id: Correlation ID (opsiyonel)

        Returns:
            EventMetadata
        """
        return EventMetadata(
            event_id=event_id,
            correlation_id=correlation_id or self.generate_correlation_id(),
            timestamp=datetime.now(UTC).isoformat(),
            attempt=self._retry_counts.get(event_id, 0),
            max_retries=self.retry_policy.max_retries,
            retry_after=self._retry_after.get(event_id),
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    def _cleanup_old_events(self) -> None:
        """Eski event kayıtlarını temizle."""
        cutoff = time.time() - (self.idempotency_window_hours * 3600)
        old_events = [eid for eid, ts in self._processed_events.items() if ts < cutoff]

        for eid in old_events:
            del self._processed_events[eid]

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        return {
            "processed_events": len(self._processed_events),
            "pending_retries": len(self._retry_after),
            "correlation_groups": len(self._correlation_map),
            "sequence_keys": len(self._sequence_numbers),
        }


# Singleton
event_enhancements = EventEnhancements()
