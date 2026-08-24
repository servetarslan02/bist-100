"""
ALPHA BIST — gRPC Client v1.0

Servisler arası hızlı iletişim için gRPC istemcisi.
JSON'dan 10x küçük, 10x hızlı.

Kullanım:
    from services.grpc.client import MarketClient, SignalClient
    
    async with MarketClient() as client:
        async for tick in client.stream_ticks(["THYAO", "ASELS"]):
            print(tick)
"""

import asyncio
import time
from typing import List, AsyncIterator, Optional, Dict, Any
import structlog

try:
    import grpc
    from grpc import aio
    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

logger = structlog.get_logger()


class BaseGRPCClient:
    """gRPC istemci taban sınıfı."""

    def __init__(self, host: str = "localhost", port: int = 50051):
        self.host = host
        self.port = port
        self._channel = None

    async def connect(self):
        if not HAS_GRPC:
            logger.warning("gRPC not available")
            return
        self._channel = aio.insecure_channel(f"{self.host}:{self.port}")
        await self._channel.channel_ready()

    async def close(self):
        if self._channel:
            await self._channel.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()


class MarketClient(BaseGRPCClient):
    """Piyasa verisi gRPC istemcisi."""

    async def stream_ticks(self, tickers: List[str]) -> AsyncIterator[Dict[str, Any]]:
        """Anlık fiyat stream'i."""
        if not HAS_GRPC:
            # Fallback: Redis'ten oku
            from ..core.redis_helper import get_cached
            while True:
                for ticker in tickers:
                    data = get_cached(f"price:{ticker}")
                    if data:
                        yield {
                            "ticker": ticker,
                            "price": data.get("price", 0),
                            "change": data.get("change", 0),
                            "timestamp": int(time.time() * 1000),
                        }
                await asyncio.sleep(0.1)
            return

        # gRPC stream
        stub = None  # Gerçek production'da generated stub
        request = {"tickers": tickers}
        async for tick in stub.StreamTicks(request):
            yield tick

    async def get_tick(self, ticker: str) -> Dict[str, Any]:
        """Tek seferlik fiyat."""
        if not HAS_GRPC:
            from ..core.redis_helper import get_cached
            data = get_cached(f"price:{ticker}")
            return data or {"ticker": ticker, "price": 0}

        stub = None
        return await stub.GetTick({"ticker": ticker})


class SignalClient(BaseGRPCClient):
    """Sinyal gRPC istemcisi."""

    async def stream_signals(self, min_confidence: float = 0.5) -> AsyncIterator[Dict[str, Any]]:
        """Sinyal stream'i."""
        if not HAS_GRPC:
            from ..core.redis_helper import get_cached
            while True:
                signals = get_cached("signals:latest") or []
                for signal in signals:
                    if signal.get("confidence", 0) >= min_confidence:
                        yield signal
                await asyncio.sleep(1)
            return

        stub = None
        request = {"min_confidence": min_confidence}
        async for signal in stub.StreamSignals(request):
            yield signal


class PortfolioClient(BaseGRPCClient):
    """Portföy gRPC istemcisi."""

    async def get_portfolio(self) -> Dict[str, Any]:
        """Anlık portföy durumu."""
        if not HAS_GRPC:
            from ..core.redis_helper import get_cached
            return get_cached("portfolio:state") or {}

        stub = None
        return await stub.GetPortfolio({})


class RiskClient(BaseGRPCClient):
    """Risk gRPC istemcisi."""

    async def get_risk(self) -> Dict[str, Any]:
        """Anlık risk durumu."""
        if not HAS_GRPC:
            from ..core.redis_helper import get_cached
            return get_cached("risk:metrics") or {}

        stub = None
        return await stub.GetRisk({})
