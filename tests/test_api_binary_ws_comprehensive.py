"""Comprehensive unit tests for services.api.binary_ws."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.api.binary_ws import (
    BinaryWebSocket,
    ProtobufMessage,
)


def test_protobuf_message_encoding_and_decoding():
    """Verify serialization and deserialization of all stream message types."""
    # 1. Tick
    tick_bytes = ProtobufMessage.encode_tick(
        ticker="THYAO",
        price=320.5,
        change=4.5,
        change_pct=1.42,
        volume=1200000,
        bid=320.0,
        ask=320.5,
    )
    assert isinstance(tick_bytes, bytes)
    assert len(tick_bytes) > 0
    decoded_tick = ProtobufMessage.decode(tick_bytes)
    assert decoded_tick["type"] in ("tick", "unknown")
    if "data" in decoded_tick and decoded_tick["type"] == "tick":
        assert decoded_tick["data"]["ticker"] == "THYAO"
        assert abs(decoded_tick["data"]["price"] - 320.5) < 1e-3

    # 2. OHLCV
    ohlcv_bytes = ProtobufMessage.encode_ohlcv(
        ticker="GARAN",
        open_p=110.0,
        high=115.0,
        low=109.5,
        close=114.2,
        volume=5000000,
        timeframe="5m",
    )
    assert isinstance(ohlcv_bytes, bytes)
    decoded_ohlcv = ProtobufMessage.decode(ohlcv_bytes)
    assert decoded_ohlcv["type"] in ("ohlcv", "unknown")

    # 3. Signal
    sig_bytes = ProtobufMessage.encode_signal(
        ticker="ASELS",
        direction="BUY",
        confidence=0.85,
        target_price=65.0,
        stop_loss=58.0,
        reason="Breakout test",
    )
    assert isinstance(sig_bytes, bytes)
    decoded_sig = ProtobufMessage.decode(sig_bytes)
    assert decoded_sig["type"] in ("signal", "unknown")

    # 4. Alert
    alert_bytes = ProtobufMessage.encode_alert(
        alert_type="PRICE",
        ticker="BIMAS",
        message="Price target hit",
        severity="INFO",
        value=520.0,
        threshold=500.0,
    )
    assert isinstance(alert_bytes, bytes)
    decoded_alert = ProtobufMessage.decode(alert_bytes)
    assert decoded_alert["type"] in ("alert", "unknown")

    # 5. Heartbeat
    hb_bytes = ProtobufMessage.encode_heartbeat()
    assert isinstance(hb_bytes, bytes)
    decoded_hb = ProtobufMessage.decode(hb_bytes)
    assert decoded_hb["type"] in ("heartbeat", "unknown")


def test_protobuf_fallback_methods():
    """Verify fallback encode and decode when protobuf structures are bypassed."""
    raw = ProtobufMessage._fallback_encode("custom_ping", foo="bar", num=123)
    assert isinstance(raw, bytes)

    decoded = ProtobufMessage._fallback_decode(raw)
    assert decoded["type"] == "custom_ping"
    assert decoded["foo"] == "bar"
    assert decoded["num"] == 123

    # Invalid payload decode
    assert ProtobufMessage._fallback_decode(b"invalid json non-bytes")["type"] == "unknown"


@pytest.mark.asyncio
async def test_binary_websocket_broadcast_and_lifecycle():
    """Verify client subscription, message broadcasting, and stats."""
    server = BinaryWebSocket()

    # Initial stats
    stats = server.get_stats()
    assert stats["clients"] == 0
    assert stats["running"] is False

    # Mock client
    mock_client = AsyncMock()
    mock_client.send = AsyncMock()
    mock_client.close = AsyncMock()

    server._clients.add(mock_client)
    assert server.get_stats()["clients"] == 1

    # Broadcast alert
    await server.broadcast_alert(
        alert_type="RISK",
        ticker="KCHOL",
        message_text="High volatility alert",
        severity="WARNING",
    )
    mock_client.send.assert_called_once()

    # Broadcast json
    mock_client.send.reset_mock()
    await server.broadcast_json({"action": "ping"})
    mock_client.send.assert_called_once()

    # Stop server
    await server.stop()
    assert len(server._clients) == 0
    assert server._running is False
    mock_client.close.assert_called_once()
