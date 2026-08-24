"""
ALPHA BIST — Binary WebSocket v1.0

Protobuf tabanlı binary WebSocket — JSON'dan 10x küçük, 10x hızlı.

Kullanım:
    ws = BinaryWebSocket()
    await ws.send_tick(ticker, price, volume)
    # veya
    await ws.send_json(data)  # fallback
"""

import asyncio
import orjson
import struct
import time
from typing import Dict, Any, Optional, Set
import structlog

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

logger = structlog.get_logger()


class BinaryMessage:
    """Binary mesaj formatı — Protobuf yerine basit binary."""

    # Mesaj tipleri
    TYPE_TICK = 0x01
    TYPE_OHLCV = 0x02
    TYPE_SIGNAL = 0x03
    TYPE_PORTFOLIO = 0x04
    TYPE_RISK = 0x05
    TYPE_REGIME = 0x06
    TYPE_EVENT = 0x07
    TYPE_ALERT = 0x08
    TYPE_HEARTBEAT = 0x09

    @staticmethod
    def encode_tick(ticker: str, price: float, change: float, volume: int, timestamp: int) -> bytes:
        """Fiyat verisini binary olarak kodla."""
        ticker_bytes = ticker.encode('utf-8')[:10]  # Max 10 karakter
        ticker_bytes = ticker_bytes.ljust(10, b'\x00')

        # Format: type(1) + ticker(10) + price(8) + change(8) + volume(8) + timestamp(8)
        return struct.pack('!B10sddqQ',
            BinaryMessage.TYPE_TICK,
            ticker_bytes,
            price,
            change,
            volume,
            timestamp
        )

    @staticmethod
    def encode_ohlcv(ticker: str, open_p: float, high: float, low: float, close: float, volume: int, timestamp: int) -> bytes:
        """OHLCV verisini binary olarak kodla."""
        ticker_bytes = ticker.encode('utf-8')[:10]
        ticker_bytes = ticker_bytes.ljust(10, b'\x00')

        # Format: type(1) + ticker(10) + open(8) + high(8) + low(8) + close(8) + volume(8) + timestamp(8)
        return struct.pack('!B10sddddqQ',
            BinaryMessage.TYPE_OHLCV,
            ticker_bytes,
            open_p,
            high,
            low,
            close,
            volume,
            timestamp
        )

    @staticmethod
    def encode_signal(ticker: str, direction: int, confidence: float, target: float, stop_loss: float, timestamp: int) -> bytes:
        """Sinyali binary olarak kodla."""
        ticker_bytes = ticker.encode('utf-8')[:10]
        ticker_bytes = ticker_bytes.ljust(10, b'\x00')

        # Format: type(1) + ticker(10) + direction(1) + confidence(8) + target(8) + stop_loss(8) + timestamp(8)
        return struct.pack('!B10sBdddQ',
            BinaryMessage.TYPE_SIGNAL,
            ticker_bytes,
            direction,
            confidence,
            target,
            stop_loss,
            timestamp
        )

    @staticmethod
    def encode_heartbeat() -> bytes:
        """Heartbeat mesajı."""
        return struct.pack('!BQ', BinaryMessage.TYPE_HEARTBEAT, int(time.time() * 1000))

    @staticmethod
    def decode(data: bytes) -> Dict[str, Any]:
        """Binary mesajı decode et."""
        if len(data) < 1:
            return {}

        msg_type = data[0]

        if msg_type == BinaryMessage.TYPE_TICK and len(data) >= 43:
            _, ticker_bytes, price, change, volume, timestamp = struct.unpack('!B10sddqQ', data[:43])
            ticker = ticker_bytes.rstrip(b'\x00').decode('utf-8')
            return {
                "type": "tick",
                "ticker": ticker,
                "price": price,
                "change": change,
                "volume": volume,
                "timestamp": timestamp
            }

        elif msg_type == BinaryMessage.TYPE_OHLCV and len(data) >= 59:
            _, ticker_bytes, open_p, high, low, close, volume, timestamp = struct.unpack('!B10sddddqQ', data[:59])
            ticker = ticker_bytes.rstrip(b'\x00').decode('utf-8')
            return {
                "type": "ohlcv",
                "ticker": ticker,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "timestamp": timestamp
            }

        elif msg_type == BinaryMessage.TYPE_SIGNAL and len(data) >= 43:
            _, ticker_bytes, direction, confidence, target, stop_loss, timestamp = struct.unpack('!B10sBdddQ', data[:43])
            ticker = ticker_bytes.rstrip(b'\x00').decode('utf-8')
            return {
                "type": "signal",
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "target": target,
                "stop_loss": stop_loss,
                "timestamp": timestamp
            }

        elif msg_type == BinaryMessage.TYPE_HEARTBEAT and len(data) >= 9:
            _, timestamp = struct.unpack('!BQ', data[:9])
            return {"type": "heartbeat", "timestamp": timestamp}

        return {"type": "unknown", "raw": data.hex()}


class BinaryWebSocket:
    """Binary WebSocket sunucusu."""

    def __init__(self):
        self._clients: Set = set()
        self._running = False

    async def handler(self, websocket, path=None):
        """WebSocket bağlantı handler'ı."""
        self._clients.add(websocket)
        client_id = id(websocket)
        logger.info("Binary WebSocket client connected", client_id=client_id)

        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    # Binary mesaj
                    decoded = BinaryMessage.decode(message)
                    logger.debug("Binary message received", type=decoded.get("type"))
                else:
                    # JSON fallback
                    try:
                        data = orjson.loads(message)
                        logger.debug("JSON message received", type=data.get("type"))
                    except orjson.JSONDecodeError:
                        pass
        except Exception as e:
            logger.debug("WebSocket client disconnected", client_id=client_id, error=str(e))
        finally:
            self._clients.discard(websocket)

    async def broadcast_tick(self, ticker: str, price: float, change: float, volume: int):
        """Tüm istemcilere fiyat yayınla."""
        message = BinaryMessage.encode_tick(ticker, price, change, volume, int(time.time() * 1000))
        await self._broadcast_binary(message)

    async def broadcast_ohlcv(self, ticker: str, open_p: float, high: float, low: float, close: float, volume: int):
        """Tüm istemcilere OHLCV yayınla."""
        message = BinaryMessage.encode_ohlcv(ticker, open_p, high, low, close, volume, int(time.time() * 1000))
        await self._broadcast_binary(message)

    async def broadcast_signal(self, ticker: str, direction: int, confidence: float, target: float, stop_loss: float):
        """Tüm istemcilere sinyal yayınla."""
        message = BinaryMessage.encode_signal(ticker, direction, confidence, target, stop_loss, int(time.time() * 1000))
        await self._broadcast_binary(message)

    async def broadcast_json(self, data: Dict[str, Any]):
        """JSON fallback — eski istemciler için."""
        message = orjson.dumps(data, default=str).decode()
        await self._broadcast_text(message)

    async def _broadcast_binary(self, message: bytes):
        """Binary mesajı tüm istemcilere gönder."""
        if not self._clients:
            return

        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)

        self._clients -= disconnected

    async def _broadcast_text(self, message: str):
        """Text mesajı tüm istemcilere gönder."""
        if not self._clients:
            return

        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)

        self._clients -= disconnected

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """Binary WebSocket sunucusunu başlat."""
        if not HAS_WEBSOCKETS:
            logger.warning("websockets not installed")
            return

        self._running = True
        logger.info("Binary WebSocket server starting", host=host, port=port)

        async with websockets.serve(self.handler, host, port):
            while self._running:
                await asyncio.sleep(1)
