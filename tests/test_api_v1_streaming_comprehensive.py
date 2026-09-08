"""
Tests for services/api/v1/sse.py and services/api/v1/ws.py
Covers:
- SSE: /ticks (validation, generator output, keep-alive)
- SSE: /signals, /portfolio, /alerts, /regime, /radar
- WS: ConnectionManager connect, disconnect, broadcast
- WS: /live, /radar, /events text channels & ping-pong
- WS: /binary Protobuf message handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.sse import router as sse_router
from services.api.v1.ws import ConnectionManager
from services.api.v1.ws import router as ws_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(sse_router, prefix="/api/v1/sse")
    app.include_router(ws_router, prefix="/api/v1/ws")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# SSE Tests
# =====================================================


def test_sse_ticks_validation(client: TestClient) -> None:
    # No tickers -> 400
    resp = client.get("/api/v1/sse/ticks")
    assert resp.status_code == 400


def test_sse_ticks_stream(client: TestClient) -> None:
    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.return_value = {"price": 295.5, "change": 1.5}
        # Request stream, read first chunk
        with client.stream("GET", "/api/v1/sse/ticks?tickers=THYAO&interval=0.1") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 3:
                    break
            assert any("connected" in l or "retry" in l or "tick" in l for l in lines)


def test_sse_endpoints(client: TestClient) -> None:
    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.return_value = [{"signal": "BUY", "ticker": "GARAN"}]

        for endpoint in ["signals", "portfolio", "alerts", "regime", "radar"]:
            with client.stream("GET", f"/api/v1/sse/{endpoint}?interval=0.1") as response:
                assert response.status_code == 200
                lines = []
                for line in response.iter_lines():
                    if line:
                        lines.append(line)
                    if len(lines) >= 2:
                        break
                assert len(lines) > 0


# =====================================================
# WebSocket Tests
# =====================================================


def test_ws_connection_manager() -> None:
    mgr = ConnectionManager()
    mock_ws = MagicMock()

    # Test connect
    import asyncio

    asyncio.run(mgr.connect(mock_ws, "live", "json"))
    assert mock_ws in mgr.active_connections["live"]

    # Test broadcast
    asyncio.run(mgr.broadcast("live", {"type": "tick", "ticker": "THYAO", "price": 300.0}))
    mock_ws.send_text.assert_called_once()

    # Test disconnect
    mgr.disconnect(mock_ws, "live")
    assert mock_ws not in mgr.active_connections["live"]


def test_ws_live_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/live") as websocket:
        welcome = websocket.receive_text()
        assert "CONNECTION_ESTABLISHED" in welcome

        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"


def test_ws_radar_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/radar") as websocket:
        welcome = websocket.receive_text()
        assert "CONNECTION_ESTABLISHED" in welcome

        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"


def test_ws_events_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        welcome = websocket.receive_text()
        assert "CONNECTION_ESTABLISHED" in welcome

        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"


def test_ws_binary_flow(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/binary") as websocket:
        # First packet is heartbeat in bytes
        heartbeat_bytes = websocket.receive_bytes()
        assert len(heartbeat_bytes) > 0

        # Send heartbeat bytes back
        websocket.send_bytes(heartbeat_bytes)
        resp_bytes = websocket.receive_bytes()
        assert len(resp_bytes) > 0
