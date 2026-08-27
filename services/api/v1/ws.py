"""
ALPHA BIST — Real-Time WebSocket Streaming Router v2.0
Milisaniyelik Fiyat, KAP, Olay ve Portföy Canlı Yayını

Desteklenen formatlar:
- JSON (varsayılan, text frame)
- Protobuf (binary frame, 10x daha küçük)
"""

from datetime import UTC, datetime
from typing import Any

import orjson
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = structlog.get_logger()

router = APIRouter()

# Binary WebSocket desteği (Protobuf native)
try:
    from ..binary_ws import ProtobufMessage

    HAS_BINARY_WS = True
except ImportError:
    HAS_BINARY_WS = False

# Protobuf desteği
try:
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False


class ConnectionManager:
    def __init__(self):
        # Kanal bazlı aktif WebSocket bağlantıları: "live", "radar", "events"
        self.active_connections: dict[str, set[WebSocket]] = {
            "live": set(),
            "radar": set(),
            "events": set(),
        }
        # Bağlantı format tercihi: websocket -> "json" | "protobuf"
        self._client_format: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, channel: str, fmt: str = "json"):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        self._client_format[websocket] = fmt
        logger.debug(
            f"WS client connected to channel: {channel} format: {fmt} (Total: {len(self.active_connections[channel])})"
        )

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections and websocket in self.active_connections[channel]:
            self.active_connections[channel].remove(websocket)
            self._client_format.pop(websocket, None)
            logger.debug(f"WS client disconnected from {channel}")

    async def broadcast(self, channel: str, message: dict[str, Any]):
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
                    payload = orjson.dumps(message, default=str).decode()
                    await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)

        for dead in dead_connections:
            self.disconnect(dead, channel)

    def _to_protobuf_bytes(self, message: dict[str, Any]) -> bytes:
        """Dict'i Protobuf binary'ye çevir.

        StreamMessage wrapper kullanarak gerçek Protobuf serialization.
        Protobuf yoksa orjson fallback.
        """
        if not HAS_PROTOBUF or not HAS_BINARY_WS:
            return orjson.dumps(message, default=str)

        msg_type = message.get("type", "")

        try:
            if msg_type == "tick":
                return ProtobufMessage.encode_tick(
                    ticker=message.get("ticker", ""),
                    price=float(message.get("price", 0)),
                    change=float(message.get("change", 0)),
                    change_pct=float(message.get("change_pct", 0)),
                    volume=int(message.get("volume", 0)),
                    bid=float(message.get("bid", 0)),
                    ask=float(message.get("ask", 0)),
                )
            elif msg_type == "ohlcv":
                return ProtobufMessage.encode_ohlcv(
                    ticker=message.get("ticker", ""),
                    open_p=float(message.get("open", 0)),
                    high=float(message.get("high", 0)),
                    low=float(message.get("low", 0)),
                    close=float(message.get("close", 0)),
                    volume=int(message.get("volume", 0)),
                    timeframe=message.get("timeframe", "1m"),
                )
            elif msg_type == "signal":
                return ProtobufMessage.encode_signal(
                    ticker=message.get("ticker", ""),
                    direction=message.get("direction", "HOLD"),
                    confidence=float(message.get("confidence", 0)),
                    target_price=float(message.get("target_price", 0)),
                    stop_loss=float(message.get("stop_loss", 0)),
                    reason=message.get("reason", ""),
                )
            elif msg_type == "portfolio_update":
                return ProtobufMessage.encode_portfolio(
                    total_value=float(message.get("equity", 0)),
                    cash=float(message.get("cash", 0)),
                    daily_pnl=float(message.get("pnl", 0)),
                    daily_pnl_pct=float(message.get("pnl_pct", 0)),
                    positions=message.get("positions", []),
                )
            elif msg_type == "risk_alert":
                return ProtobufMessage.encode_alert(
                    alert_type=message.get("alert_type", "RISK"),
                    ticker=message.get("ticker", ""),
                    message_text=message.get("message", ""),
                    severity=message.get("severity", "WARNING"),
                )
            elif msg_type == "system_status":
                return ProtobufMessage.encode_heartbeat()
            else:
                # Bilinmeyen tip → orjson fallback
                return orjson.dumps(message, default=str)
        except Exception as e:
            logger.warning("Protobuf encode failed, using orjson", error=str(e))
            return orjson.dumps(message, default=str)


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
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "connected",
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(orjson.dumps(welcome).decode())
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")
    except Exception:
        manager.disconnect(websocket, "live")


@router.websocket("/radar")
async def websocket_radar(websocket: WebSocket):
    fmt = _get_ws_format(websocket)
    await manager.connect(websocket, "radar", fmt)
    try:
        welcome = {
            "type": "CONNECTION_ESTABLISHED",
            "channel": "radar",
            "timestamp": datetime.now(UTC).isoformat(),
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(orjson.dumps(welcome).decode())
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "radar")
    except Exception:
        manager.disconnect(websocket, "radar")


@router.websocket("/events")
async def websocket_events(websocket: WebSocket):
    fmt = _get_ws_format(websocket)
    await manager.connect(websocket, "events", fmt)
    try:
        welcome = {
            "type": "CONNECTION_ESTABLISHED",
            "channel": "events",
            "timestamp": datetime.now(UTC).isoformat(),
            "format": fmt,
        }
        if fmt == "protobuf":
            await websocket.send_bytes(manager._to_protobuf_bytes(welcome))
        else:
            await websocket.send_text(orjson.dumps(welcome).decode())
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "events")
    except Exception:
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
    protocol = "protobuf" if HAS_PROTOBUF else "orjson-fallback"
    logger.info("Binary WS client connected", protocol=protocol)

    try:
        # Heartbeat gönder (Protobuf StreamMessage)
        heartbeat = ProtobufMessage.encode_heartbeat()
        await websocket.send_bytes(heartbeat)

        while True:
            data = await websocket.receive_bytes()
            if data:
                decoded = ProtobufMessage.decode(data)
                msg_type = decoded.get("type", "unknown")

                if msg_type == "heartbeat" or msg_type == "ping":
                    await websocket.send_bytes(ProtobufMessage.encode_heartbeat())
                else:
                    logger.debug("Binary WS message", type=msg_type)
    except WebSocketDisconnect:
        logger.debug("Binary WS client disconnected")
    except Exception as e:
        logger.debug("Binary WS error", error=str(e))
