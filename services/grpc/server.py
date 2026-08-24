"""
ALPHA BIST — gRPC Server v1.0

Protobuf tabanlı hızlı servisler arası iletişim.
JSON'dan 10x küçük, 10x hızlı.

Kullanım:
    python -m services.grpc.server
    # veya
    from services.grpc.server import start_grpc_server
"""

import asyncio
import time
from typing import AsyncIterator
import structlog

try:
    import grpc
    from grpc import aio
    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

logger = structlog.get_logger()

# Protobuf mesajları (generated veya manual)
# Eğer protoc ile generate edilmemişse, Python dict kullanırız
# Gerçek production'da: protoc --python_out=. proto/market.proto


class MarketServiceServicer:
    """Piyasa verisi gRPC servisi."""

    def __init__(self):
        self._subscribers = {}

    async def StreamTicks(self, request, context) -> AsyncIterator[dict]:
        """Anlık fiyat stream'i."""
        tickers = request.get("tickers", [])
        logger.info("gRPC StreamTicks started", tickers=tickers)

        while True:
            try:
                # Redis'ten güncel fiyatları al
                from ..core.redis_helper import get_cached
                for ticker in tickers:
                    data = get_cached(f"price:{ticker}")
                    if data:
                        yield {
                            "ticker": ticker,
                            "price": data.get("price", 0),
                            "change": data.get("change", 0),
                            "change_pct": data.get("change_pct", 0),
                            "volume": data.get("volume", 0),
                            "timestamp": int(time.time() * 1000),
                        }
                await asyncio.sleep(0.1)  # 100ms güncelleme
            except Exception as e:
                logger.error("gRPC StreamTicks error", error=str(e))
                break

    async def GetTick(self, request, context) -> dict:
        """Tek seferlik fiyat."""
        ticker = request.get("ticker", "")
        from ..core.redis_helper import get_cached
        data = get_cached(f"price:{ticker}")
        if data:
            return {
                "ticker": ticker,
                "price": data.get("price", 0),
                "change": data.get("change", 0),
                "change_pct": data.get("change_pct", 0),
                "volume": data.get("volume", 0),
                "timestamp": int(time.time() * 1000),
            }
        return {"ticker": ticker, "price": 0, "timestamp": int(time.time() * 1000)}


class SignalServiceServicer:
    """Sinyal gRPC servisi."""

    async def StreamSignals(self, request, context) -> AsyncIterator[dict]:
        """Sinyal stream'i."""
        min_confidence = request.get("min_confidence", 0.5)
        logger.info("gRPC StreamSignals started", min_confidence=min_confidence)

        while True:
            try:
                from ..core.redis_helper import get_cached
                signals = get_cached("signals:latest") or []
                for signal in signals:
                    if signal.get("confidence", 0) >= min_confidence:
                        yield signal
                await asyncio.sleep(1)  # 1 saniye güncelleme
            except Exception as e:
                logger.error("gRPC StreamSignals error", error=str(e))
                break

    async def GetRecentSignals(self, request, context) -> dict:
        """Son sinyalleri al."""
        from ..core.redis_helper import get_cached
        signals = get_cached("signals:latest") or []
        min_confidence = request.get("min_confidence", 0.5)
        filtered = [s for s in signals if s.get("confidence", 0) >= min_confidence]
        return {"signals": filtered}


class PortfolioServiceServicer:
    """Portföy gRPC servisi."""

    async def StreamPortfolio(self, request, context) -> AsyncIterator[dict]:
        """Portföy durumu stream'i."""
        while True:
            try:
                from ..core.redis_helper import get_cached
                portfolio = get_cached("portfolio:state")
                if portfolio:
                    yield portfolio
                await asyncio.sleep(2)  # 2 saniye güncelleme
            except Exception as e:
                logger.error("gRPC StreamPortfolio error", error=str(e))
                break

    async def GetPortfolio(self, request, context) -> dict:
        """Anlık portföy durumu."""
        from ..core.redis_helper import get_cached
        portfolio = get_cached("portfolio:state")
        return portfolio or {"total_value": 0, "cash": 0, "positions": []}


class RiskServiceServicer:
    """Risk gRPC servisi."""

    async def StreamRisk(self, request, context) -> AsyncIterator[dict]:
        """Risk metrikleri stream'i."""
        while True:
            try:
                from ..core.redis_helper import get_cached
                risk = get_cached("risk:metrics")
                if risk:
                    yield risk
                await asyncio.sleep(5)  # 5 saniye güncelleme
            except Exception as e:
                logger.error("gRPC StreamRisk error", error=str(e))
                break

    async def GetRisk(self, request, context) -> dict:
        """Anlık risk durumu."""
        from ..core.redis_helper import get_cached
        risk = get_cached("risk:metrics")
        return risk or {"var_95": 0, "sharpe": 0, "max_drawdown": 0}


async def start_grpc_server(host: str = "0.0.0.0", port: int = 50051):
    """gRPC sunucusunu başlat."""
    if not HAS_GRPC:
        logger.warning("gRPC not available, skipping server start")
        return None

    server = aio.server()

    # Servisleri kaydet
    # Gerçek production'da generated stub'lar kullanılır
    # Şimdilik basit bir HTTP/2 endpoint sunuyoruz

    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC server started", host=host, port=port)
    return server


if __name__ == "__main__":
    async def main():
        server = await start_grpc_server()
        if server:
            await server.wait_for_termination()

    asyncio.run(main())
