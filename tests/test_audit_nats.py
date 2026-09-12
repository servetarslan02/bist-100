"""
ALPHA BIST — NATS Service Audit Test Suite
===========================================
Tests for services/nats hardening:
- Exports and module interface
- Subjects constants and representations
- NatsClient initialization, state, and string representations
- Payload preparation, serialization, and gzip compression for payloads > 4KB
- OpenTelemetry decorator integration
- Safe degradation and graceful failure when broker is offline
- Dead Letter Queue (DLQ) routing and metric tracking
"""

import gzip
from unittest.mock import AsyncMock, patch

import pytest

import services.nats as nats_mod
from services.nats import (
    NatsClient,
    Subjects,
    otel_trace,
)


def test_nats_exports():
    """Verify public module interface and __all__ list."""
    expected = [
        "HAS_NATS",
        "NatsClient",
        "Subjects",
        "nats_client",
        "otel_trace",
    ]
    for symbol in expected:
        assert hasattr(nats_mod, symbol)
    assert sorted(nats_mod.__all__) == sorted(expected)


def test_subjects_constants_and_repr():
    """Verify Subject definitions and representation."""
    assert Subjects.TICKS == "alpha.market.ticks"
    assert Subjects.OHLCV == "alpha.market.ohlcv"
    assert Subjects.SIGNALS == "alpha.signals.new"
    assert Subjects.PORTFOLIO == "alpha.portfolio.update"
    assert Subjects.RISK == "alpha.risk.alerts"
    assert Subjects.DLQ == "alpha.dlq.events"

    assert Subjects.STREAM_TICKS == "ALPHA_TICKS"
    assert Subjects.STREAM_SIGNALS == "ALPHA_SIGNALS"

    subj_instance = Subjects()
    repr_str = repr(subj_instance)
    assert "Subjects" in repr_str
    assert "TICKS" in repr_str
    assert "DLQ" in repr_str


def test_nats_client_initialization_and_repr():
    """Verify NatsClient initialization, default metrics, and __repr__."""
    client = NatsClient()
    assert not client.is_connected
    assert client.get_stats()["connected"] is False
    assert client.get_stats()["total_published"] == 0
    assert client.get_stats()["total_received"] == 0
    assert client.get_stats()["total_errors"] == 0
    assert client.get_stats()["total_dlq_routed"] == 0

    repr_str = repr(client)
    assert "NatsClient" in repr_str
    assert "connected=False" in repr_str
    assert "published=0" in repr_str
    assert "errors=0" in repr_str


def test_prepare_payload_small_and_large():
    """Verify orjson payload serialization and conditional gzip compression."""
    client = NatsClient()

    # Small payload (<4KB)
    small_data = {"ticker": "THYAO", "price": 285.50, "volume": 1000}
    payload = client._prepare_payload(small_data)
    assert isinstance(payload, bytes)
    assert not payload.startswith(b"GZ:")
    assert b"THYAO" in payload

    # Large payload (>4KB) -> Should be compressed with GZ: prefix
    large_list = [{"idx": i, "data": "x" * 100} for i in range(100)]
    large_data = {"items": large_list}
    compressed_payload = client._prepare_payload(large_data)
    assert compressed_payload.startswith(b"GZ:")

    # Verify decompress
    decompressed = gzip.decompress(compressed_payload[3:])
    assert b"items" in decompressed


def test_otel_trace_decorator():
    """Verify OTel tracing wrapper executes without error."""
    class SampleService:
        @otel_trace("sample.operation")
        def compute(self, x: int, y: int) -> int:
            return x + y

    svc = SampleService()
    assert svc.compute(10, 20) == 30


@pytest.mark.asyncio
async def test_offline_operations_graceful_handling():
    """Verify publish and request fail gracefully when NATS server is unavailable."""
    client = NatsClient()

    # connect() is a coroutine — must use AsyncMock
    with patch.object(client, "connect", new=AsyncMock(return_value=False)):
        res = await client.publish("test.subject", {"hello": "world"})
        assert res is False

        durable_res = await client.publish_durable("test.subject", {"hello": "world"})
        assert durable_res is False

        req_res = await client.request("test.subject", {"hello": "world"}, timeout=0.1)
        assert req_res == {}


@pytest.mark.asyncio
async def test_dlq_routing_metric():
    """Verify _route_to_dlq increments total_dlq_routed and routes message."""
    client = NatsClient()
    initial_dlq = client._total_dlq_routed

    with patch("services.core.dead_letter_queue.dead_letter_queue.push", new_callable=AsyncMock) as mock_push:
        await client._route_to_dlq(subject="test.corrupted", raw_payload="bad_json", error_str="JSONDecodeError")
        assert client._total_dlq_routed == initial_dlq + 1
        mock_push.assert_awaited_once()
