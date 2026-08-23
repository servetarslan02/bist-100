"""
ALPHA BIST — Real-Time WebSocket Streaming Router v2.0
Milisaniyelik Fiyat, KAP, Olay ve Portföy Canlı Yayını
"""

import asyncio
import json
from typing import Dict, Set, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        # Kanal bazlı aktif WebSocket bağlantıları: "live", "radar", "events"
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "live": set(),
            "radar": set(),
            "events": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        logger.debug(f"WS client connected to channel: {channel} (Total: {len(self.active_connections[channel])})")

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections and websocket in self.active_connections[channel]:
            self.active_connections[channel].remove(websocket)
            logger.debug(f"WS client disconnected from {channel}")

    async def broadcast(self, channel: str, message: Dict[str, Any]):
        if channel not in self.active_connections or not self.active_connections[channel]:
            return
        
        payload = json.dumps(message, default=str)
        dead_connections = set()
        
        for connection in self.active_connections[channel]:
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)
                
        for dead in dead_connections:
            self.disconnect(dead, channel)

manager = ConnectionManager()

@router.websocket("/live")
async def websocket_live(websocket: WebSocket):
    await manager.connect(websocket, "live")
    try:
        # Bağlantı açıldığında ilk hoş geldin ve durum paketi
        await websocket.send_text(json.dumps({
            "type": "CONNECTION_ESTABLISHED",
            "channel": "live",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "connected",
        }))
        while True:
            # Heartbeat ping / pong dinle
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")
    except Exception as e:
        manager.disconnect(websocket, "live")

@router.websocket("/radar")
async def websocket_radar(websocket: WebSocket):
    await manager.connect(websocket, "radar")
    try:
        await websocket.send_text(json.dumps({
            "type": "CONNECTION_ESTABLISHED",
            "channel": "radar",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
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
    await manager.connect(websocket, "events")
    try:
        await websocket.send_text(json.dumps({
            "type": "CONNECTION_ESTABLISHED",
            "channel": "events",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "events")
    except Exception as e:
        manager.disconnect(websocket, "events")
