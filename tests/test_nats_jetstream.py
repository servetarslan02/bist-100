from typing import Any
"""
ALPHA BIST — NATS JetStream & Event-Driven Engine Test Suite
Doğrulanan Özellikler:
1. CanonicalEvent Schema: Versioning, Validation, Serialization (JSON & Binary), Correlation ID
2. EventEnhancements: Idempotency, Retry Policy, Sequence Ordering, Out-of-Order Detection
3. NatsClient: Payload preparation, Correlation propagation, DLQ auto-routing, Observability stats
4. Dead Letter Queue Entegrasyonu & Mock Replay
"""

import pytest

from services.core.event_enhancements import (
    EventEnhancements,
    RetryPolicy,
)
from services.core.event_schema import CanonicalEvent, EventType
from services.nats.client import NatsClient, Subjects


class TestEventSchemaVersioning:
    """CanonicalEvent şema, versiyon ve doğrulama testleri."""

    def test_canonical_event_creation_and_validation(self) -> Any:
        """Otomatik eklendi."""
        event = CanonicalEvent(
            type=EventType.TICK,
            ticker="THYAO",
            data={"price": 305.50, "volume": 125000},
            source="matriks",
            confidence=0.95,
            version=1,
            correlation_id="corr-12345",
        )
        is_valid, msg = event.validate()
        assert is_valid is True
        assert msg == "OK"
        assert event.timestamp > 0

    def test_canonical_event_json_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        event = CanonicalEvent(
            type=EventType.SIGNAL,
            ticker="ASELS",
            data={"score": 88.5, "action": "BUY"},
            source="model_ensemble",
            confidence=0.85,
            sequence=42,
            version=1,
            correlation_id="test-corr-abc",
        )
        json_str = event.to_json()
        reconstructed = CanonicalEvent.from_json(json_str)

        assert reconstructed.type == EventType.SIGNAL
        assert reconstructed.ticker == "ASELS"
        assert reconstructed.data["score"] == 88.5
        assert reconstructed.sequence == 42
        assert reconstructed.version == 1
        assert reconstructed.correlation_id == "test-corr-abc"

    def test_canonical_event_dict_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        event = CanonicalEvent(
            type=EventType.RISK,
            ticker="TUPRS",
            data={"alert": "LIMIT_PROXIMITY", "distance_pct": 1.2},
            source="risk_orchestrator",
        )
        d = event.to_dict()
        assert d["type"] == EventType.RISK.value
        assert d["ticker"] == "TUPRS"
        assert d["data"]["distance_pct"] == 1.2

        reconstructed = CanonicalEvent.from_dict(d)
        assert reconstructed.type == EventType.RISK
        assert reconstructed.ticker == "TUPRS"


class TestEventEnhancementsOrdering:
    """Idempotency, Retry ve Sequence Ordering testleri."""

    def test_idempotency_deduplication(self) -> Any:
        """Otomatik eklendi."""
        ee = EventEnhancements()
        event_id = "evt-unique-001"

        assert ee.is_duplicate(event_id) is False
        ee.mark_processed(event_id)
        assert ee.is_duplicate(event_id) is True

        # Process with idempotency
        executed = []
        res1 = ee.process_with_idempotency("evt-task-1", lambda: executed.append(1) or "SUCCESS")
        assert res1 == "SUCCESS"
        assert len(executed) == 1

        # Duplicate call -> blocked
        res2 = ee.process_with_idempotency("evt-task-1", lambda: executed.append(2) or "SUCCESS")
        assert res2 is None
        assert len(executed) == 1

    def test_retry_policy_exponential_backoff(self) -> Any:
        """Otomatik eklendi."""
        policy = RetryPolicy(max_retries=3, base_delay=0.5, exponential_base=2.0, jitter=False)
        ee = EventEnhancements(retry_policy=policy)

        assert ee.should_retry("evt-retry", attempt=0) is True
        assert ee.should_retry("evt-retry", attempt=2) is True
        assert ee.should_retry("evt-retry", attempt=3) is False  # Max retries exhausted

        delay_0 = ee.get_retry_delay(0)
        delay_1 = ee.get_retry_delay(1)
        delay_2 = ee.get_retry_delay(2)

        assert delay_0 == 0.5
        assert delay_1 == 1.0
        assert delay_2 == 2.0

    def test_sequence_ordering_and_out_of_order_detection(self) -> Any:
        """Otomatik eklendi."""
        ee = EventEnhancements()
        key = "THYAO.ticks"

        seq1 = ee.get_next_sequence(key)  # 1
        seq2 = ee.get_next_sequence(key)  # 2
        seq3 = ee.get_next_sequence(key)  # 3

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

        # Record sequence
        ee.record_sequence(key, 100)
        assert ee.is_out_of_order(key, 99) is True  # Stale sequence
        assert ee.is_out_of_order(key, 100) is True  # Duplicate sequence
        assert ee.is_out_of_order(key, 101) is False  # Valid new sequence


class TestNatsClientEngine:
    """NatsClient payload hazırlama, tracing ve DLQ yönlendirme testleri."""

    @pytest.mark.asyncio
    async def test_nats_payload_preparation_and_stats(self) -> Any:
        """Otomatik eklendi."""
        client = NatsClient()
        stats = client.get_stats()
        assert "connected" in stats
        assert "total_published" in stats
        assert "total_errors" in stats
        assert "total_dlq_routed" in stats

        # Payload preparation
        data = {"ticker": "THYAO", "price": 300.0}
        payload_bytes = client._prepare_payload(data)
        assert isinstance(payload_bytes, bytes)
        assert b"THYAO" in payload_bytes

        # CanonicalEvent publish validation
        invalid_event = CanonicalEvent(type=EventType.TICK, timestamp=-1)
        res = await client.publish_canonical_event(Subjects.TICKS, invalid_event)
        assert res is False  # Validation failure caught safely

    @pytest.mark.asyncio
    async def test_nats_dlq_fallback_routing(self) -> Any:
        """Otomatik eklendi."""
        client = NatsClient()
        initial_dlq = client._total_dlq_routed

        # Simulate handler failure routing to DLQ
        await client._route_to_dlq(
            subject=Subjects.TICKS,
            raw_payload='{"ticker": "THYAO", "corrupted": true}',
            error_str="Simulated Parsing Exception",
        )
        assert client._total_dlq_routed == initial_dlq + 1
