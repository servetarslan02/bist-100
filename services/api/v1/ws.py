"""
ALPHA BIST — Real-Time WebSocket Streaming Router v2.0
Milisaniyelik Fiyat, KAP, Olay ve Portföy Canlı Yayını

Desteklenen formatlar:
- JSON (varsayılan, text frame)
- Protobuf (binary frame, 10x daha küçük)
"""

import asyncio
import json
from typing import Dict, Set, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

router = APIRouter()

# Binary WebSocket desteği
try:
    from ..binary_ws import BinaryMessage
    HAS_BINARY_WS = True
except ImportError:
    HAS_BINARY_WS = False

# Protobuf desteği (opsiyonel)
try:
    from google.protobuf import json_format
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False


class ConnectionManager:
    def __init__(self):
        # Kanal bazlı aktif WebSocket bağlantıları: "live", "radar", "events"
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "live": set(),
            "radar": set(),
            "events": set(),
        }
        # Bağlantı format tercihi: websocket -> "json" | "protobuf"
        self._client_format: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, channel: str, fmt: str = "json"):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        self._client_format[websocket] = fmt
        logger.debug(f"WS client connected to channel: {channel} format: {fmt} (Total: {len(self.active_connections[channel])})")

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections and websocket in self.active_connections[channel]:
            self.active_connections[channel].remove(websocket)
            self._client_format.pop(websocket, None)
            logger.debug(f"WS client disconnected from {channel}")

    async def broadcast(self, channel: str, message: Dict[str, Any]):
        if channel not in self.active_connections or not self.active_connections[channel]:
            return
        
        dead_connections = set()
        
        for connection in self.active_connections[channel]:
            try:
                fmt = self._client_format.get(connection, "json")
                if fmt == "protobuf" and HAS_PROTOBUF:
                    # Protobuf binary frame (10x daha küçük)
                    payload = self._to_protobuf_bytes(message)
                    await connection.send_bytes(payload)
                else:
                    # JSON text frame (varsayılan)
                    payload = json.dumps(message, default=str)
                    await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)
                
        for dead in dead_connections:
            self.disconnect(dead, channel)

    def _to_protobuf_bytes(self, message: Dict[str, Any]) -> bytes:
        """Dict'i Protobuf binary'ye çevir (StreamMessage wrapper)."""
        try:
            # Basit Protobuf encoding: msgpack-like binary format
            # Gerçek production'da proto/market.proto'daki StreamMessage kullanılır
            import msgpack
            return msgpack.packb(message, default=str)
        except ImportError:
            # Fallback: JSON bytes
            return json.dumps(message, default=str).encode("utf-8")

manager = ConnectionManager()


def _get_ws_format(websocket: WebSocket) -> str:
    """Query parametre'den format tercihi al: ?format=protobuf | json"""
    fmt = websocket.query_params.get("format", "json")
    return "protobuf" if fmt == "protobuf" and HAS_PROTOBUF else "json"


@router.websocket("/live")
async def websocket_live(websocket: WebSocket):
    fmt = _get_ws_format(websocket)
    await manager.connect(websocket, "live", fmt)
    try:
        welcome = {
            "type": "CONNECTION_ESTABLISHED",
            "channel": "live",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "connected",
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(json.dumps(welcome))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")
    except Exception as e:
        manager.disconnect(websocket, "live")

@router.websocket("/radar")
async def websocket_radar(websocket: WebSocket):
    fmt = _get_ws_format(websocket)
    await manager.connect(websocket, "radar", fmt)
    try:
        welcome = {
            "type": "CONNECTION_ESTABLISHED",
            "channel": "radar",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(json.dumps(welcome))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "radar")
    except Exception as e:
        manager.disconnect(websocket, "radar")

@router.websocket("/events")
async def websocket_events(websocket: WebSocket):
    fmt = _get_ws_format(websocket)
    await manager.connect(websocket, "events", fmt)
    try:
        welcome = {
            "type": "CONNECTION_ESTABLISHED",
            "channel": "events",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(json.dumps(welcome))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "events")
    except Exception as e:
        manager.disconnect(websocket, "events")


@router.websocket("/binary")
async def websocket_binary(websocket: WebSocket):
    """Binary WebSocket — custom binary protocol.

    En küçük paket boyutu. Özel binary encoding.
    Desteklenen mesaj tipleri: tick, ohlcv, signal, heartbeat

    Kullanım:
        const ws = new WebSocket('ws://localhost:8000/ws/binary');
        ws.binaryType = 'arraybuffer';
    """
    if not HAS_BINARY_WS:
        await websocket.close(code=1013, reason="Binary WS not available")
        return

    await websocket.accept()
    logger.debug("Binary WS client connected")

    try:
        # Heartbeat gönder
        heartbeat = BinaryMessage.encode_heartbeat()
        await websocket.send_bytes(heartbeat)

        while True:
            data = await websocket.receive_bytes()
            if data:
                decoded = BinaryMessage.decode(data)
                msg_type = decoded.get("type", "unknown")

                if msg_type == "heartbeat":
                    await websocket.send_bytes(BinaryMessage.encode_heartbeat())
                elif msg_type == "ping":
                    await websocket.send_bytes(BinaryMessage.encode_heartbeat())
                else:
                    logger.debug("Binary WS message", type=msg_type)
    except WebSocketDisconnect:
        logger.debug("Binary WS client disconnected")
    except Exception as e:
        logger.debug("Binary WS error", error=str(e))
