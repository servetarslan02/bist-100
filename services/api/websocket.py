"""
ALPHA BIST — WebSocket Real-time Server v1.0

Gerçek zamanlı güncelleme:
- /ws/market — anlık fiyatlar
- /ws/opportunities — yeni fırsatlar
- /ws/portfolio — P&L güncelleme
- /ws/risk — risk alertleri
- /ws/system — servis durumu

Kullanım:
  ws_server = WebSocketServer()
  await ws_server.start(port=8765)
"""

import asyncio
import json
from typing import Dict, List, Set, Any, Callable
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class WebSocketConnection:
    """Tek bir WebSocket bağlantısı."""

    def __init__(self, ws, channel: str, client_id: str):
        self.ws = ws
        self.channel = channel
        self.client_id = client_id
        self.connected_at = datetime.now(timezone.utc)
        self.messages_sent = 0

    async def send(self, data: Dict[str, Any]):
        """Veri gönder."""
        try:
            message = json.dumps(data, default=str)
            await self.ws.send(message)
            self.messages_sent += 1
        except Exception as e:
            logger.warning("WebSocket send failed", client=self.client_id, error=str(e))

    async def close(self):
        """Bağlantıyı kapat."""
        try:
            await self.ws.close()
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="websocket.py:48")
            pass


class WebSocketServer:
    """WebSocket sunucusu — gerçek zamanlı veri dağıtımı."""

    CHANNELS = ["market", "opportunities", "portfolio", "risk", "system"]

    def __init__(self):
        self._connections: Dict[str, List[WebSocketConnection]] = {
            ch: [] for ch in self.CHANNELS
        }
        self._running = False
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """WebSocket sunucusunu başlat."""
        try:
            import websockets
            self._running = True
            logger.info("WebSocket server starting", host=host, port=port)

            async def handler(ws, path):
                await self._handle_connection(ws, path)

            server = await websockets.serve(handler, host, port)
            logger.info("WebSocket server started", port=port)

            # Background task: message broadcaster
            asyncio.create_task(self._broadcast_loop())

            await server.wait_closed()
        except ImportError:
            logger.warning("websockets not installed, WebSocket server disabled")
        except Exception as e:
            logger.error("WebSocket server error", error=str(e))

    async def _handle_connection(self, ws, path: str):
        """Yeni WebSocket bağlantısını işle."""
        client_id = str(uuid.uuid4())[:8]

        # Path'ten channel'ı belirle
        channel = path.strip("/") or "system"
        if channel not in self.CHANNELS:
            channel = "system"

        conn = WebSocketConnection(ws, channel, client_id)
        self._connections[channel].append(conn)

        logger.info("WebSocket client connected", client=client_id, channel=channel)

        try:
            # Hoşgeldin mesajı
            await conn.send({
                "type": "connected",
                "channel": channel,
                "client_id": client_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Bağlantıyı açık tut
            async for message in ws:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(conn, data)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug("WebSocket disconnected", client=client_id, error=str(e))
        finally:
            if conn in self._connections[channel]:
                self._connections[channel].remove(conn)

    async def _handle_client_message(self, conn: WebSocketConnection, data: Dict):
        """İstemciden gelen mesajı işle."""
        msg_type = data.get("type", "")

        if msg_type == "ping":
            await conn.send({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})

        elif msg_type == "subscribe":
            new_channel = data.get("channel", "")
            if new_channel in self.CHANNELS:
                # Eski kanaldan çıkar
                if conn in self._connections[conn.channel]:
                    self._connections[conn.channel].remove(conn)
                # Yeni kanala ekle
                conn.channel = new_channel
                self._connections[new_channel].append(conn)
                await conn.send({"type": "subscribed", "channel": new_channel})

    async def broadcast(self, channel: str, data: Dict[str, Any]):
        """Belirli kanala veri gönder."""
        await self._message_queue.put((channel, data))

    async def _broadcast_loop(self):
        """Mesaj kuyruğunu işleyip ilgili bağlantılara gönder."""
        while self._running:
            try:
                channel, data = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )

                connections = self._connections.get(channel, [])
                dead = []

                for conn in connections:
                    try:
                        await conn.send(data)
                    except Exception as e:
                        dead.append(conn)

                # Ölü bağlantıları temizle
                for conn in dead:
                    if conn in self._connections[channel]:
                        self._connections[channel].remove(conn)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Broadcast loop error", error=str(e))

    async def broadcast_market(self, ticker: str, price: float, change_pct: float, volume: int):
        """Piyasa verisi yayınla."""
        await self.broadcast("market", {
            "type": "tick",
            "ticker": ticker,
            "price": price,
            "change_pct": change_pct,
            "volume": volume,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_opportunity(self, ticker: str, score: float, signal: str, direction: str):
        """Fırsat yayını."""
        await self.broadcast("opportunities", {
            "type": "opportunity",
            "ticker": ticker,
            "score": score,
            "signal": signal,
            "direction": direction,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_portfolio(self, equity: float, pnl: float, pnl_pct: float):
        """Portföy yayını."""
        await self.broadcast("portfolio", {
            "type": "portfolio_update",
            "equity": equity,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_risk(self, alert_type: str, message: str, severity: str):
        """Risk alerti yayını."""
        await self.broadcast("risk", {
            "type": "risk_alert",
            "alert_type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_system(self, component: str, status: str, details: str = ""):
        """Sistem durumu yayını."""
        await self.broadcast("system", {
            "type": "system_status",
            "component": component,
            "status": status,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_stats(self) -> Dict[str, Any]:
        """Bağlantı istatistikleri."""
        return {
            "total_connections": sum(len(conns) for conns in self._connections.values()),
            "by_channel": {ch: len(conns) for ch, conns in self._connections.items()},
            "queue_size": self._message_queue.qsize(),
        }

    async def stop(self):
        """Sunucuyu durdur."""
        self._running = False
        for channel, conns in self._connections.items():
            for conn in conns:
                await conn.close()
            conns.clear()


# Singleton
ws_server = WebSocketServer()
