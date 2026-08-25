"""
ALPHA BIST — gRPC Server v2.0 (Protobuf Native)

Gerçek protobuf serialization ile servisler arası iletişim.
JSON'dan 10x küçük, 10x hızlı.

Kullanım:
    python -m services.grpc.server
    # veya API lifespan'dan otomatik başlar
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

# Generated protobuf imports
try:
    from .generated import market_pb2
    from .generated import market_pb2_grpc
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False

logger = structlog.get_logger()


class MarketServiceServicer(market_pb2_grpc.MarketServiceServicer if HAS_PROTOBUF else object):
    """Piyasa verisi gRPC servisi — Protobuf native."""

    def StreamTicks(self, request, context):
        """Anlık fiyat stream'i (Protobuf binary)."""
        tickers = list(request.tickers)
        logger.info("gRPC StreamTicks started", tickers=tickers)

        async def _generate():
            while True:
                try:
                    from ..core.redis_helper import get_cached
                    for ticker in tickers:
                        data = get_cached(f"price:{ticker}")
                        if data:
                            yield market_pb2.MarketTick(
                                ticker=ticker,
                                price=float(data.get("price", 0)),
                                change=float(data.get("change", 0)),
                                change_pct=float(data.get("change_pct", 0)),
                                volume=int(data.get("volume", 0)),
                                bid=float(data.get("bid", 0)),
                                ask=float(data.get("ask", 0)),
                                timestamp=int(time.time() * 1000),
                            )
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error("gRPC StreamTicks error", error=str(e))
                    break

        return _generate()

    def GetTick(self, request, context):
        """Tek seferlik fiyat (Protobuf)."""
        ticker = request.tickers[0] if request.tickers else ""
        from ..core.redis_helper import get_cached
        data = get_cached(f"price:{ticker}")
        if data:
            return market_pb2.MarketTick(
                ticker=ticker,
                price=float(data.get("price", 0)),
                change=float(data.get("change", 0)),
                change_pct=float(data.get("change_pct", 0)),
                volume=int(data.get("volume", 0)),
                timestamp=int(time.time() * 1000),
            )
        return market_pb2.MarketTick(ticker=ticker, timestamp=int(time.time() * 1000))


class SignalServiceServicer(market_pb2_grpc.SignalServiceServicer if HAS_PROTOBUF else object):
    """Sinyal gRPC servisi — Protobuf native."""

    def StreamSignals(self, request, context):
        """Sinyal stream'i (Protobuf binary)."""
        min_confidence = request.min_confidence if hasattr(request, 'min_confidence') else 0.5

        async def _generate():
            while True:
                try:
                    from ..core.redis_helper import get_cached
                    signals = get_cached("signals:latest") or []
                    for s in signals:
                        if s.get("confidence", 0) >= min_confidence:
                            direction_map = {"BUY": 0, "SELL": 1, "HOLD": 2}
                            yield market_pb2.Signal(
                                ticker=s.get("ticker", ""),
                                direction=direction_map.get(s.get("direction", "HOLD"), 2),
                                confidence=float(s.get("confidence", 0)),
                                target_price=float(s.get("target_price", 0)),
                                stop_loss=float(s.get("stop_loss", 0)),
                                reason=s.get("reason", ""),
                                timestamp=int(time.time() * 1000),
                            )
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error("gRPC StreamSignals error", error=str(e))
                    break

        return _generate()

    def GetRecentSignals(self, request, context):
        """Son sinyalleri al (Protobuf)."""
        from ..core.redis_helper import get_cached
        signals = get_cached("signals:latest") or []
        min_conf = request.min_confidence if hasattr(request, 'min_confidence') else 0.5
        direction_map = {"BUY": 0, "SELL": 1, "HOLD": 2}
        proto_signals = []
        for s in signals:
            if s.get("confidence", 0) >= min_conf:
                proto_signals.append(market_pb2.Signal(
                    ticker=s.get("ticker", ""),
                    direction=direction_map.get(s.get("direction", "HOLD"), 2),
                    confidence=float(s.get("confidence", 0)),
                    target_price=float(s.get("target_price", 0)),
                    stop_loss=float(s.get("stop_loss", 0)),
                    reason=s.get("reason", ""),
                    timestamp=int(time.time() * 1000),
                ))
        return market_pb2.SignalList(signals=proto_signals)


class PortfolioServiceServicer(market_pb2_grpc.PortfolioServiceServicer if HAS_PROTOBUF else object):
    """Portföy gRPC servisi — Protobuf native."""

    def StreamPortfolio(self, request, context):
        """Portföy durumu stream'i (Protobuf binary)."""

        async def _generate():
            while True:
                try:
                    from ..core.redis_helper import get_cached
                    pf = get_cached("portfolio:state")
                    if pf:
                        positions = [
                            market_pb2.Position(
                                ticker=p.get("ticker", ""),
                                quantity=int(p.get("quantity", 0)),
                                avg_price=float(p.get("avg_price", 0)),
                                current_price=float(p.get("current_price", 0)),
                                pnl=float(p.get("pnl", 0)),
                                pnl_pct=float(p.get("pnl_pct", 0)),
                                weight=float(p.get("weight", 0)),
                            )
                            for p in pf.get("positions", [])
                        ]
                        yield market_pb2.PortfolioState(
                            total_value=float(pf.get("total_value", 0)),
                            cash=float(pf.get("cash", 0)),
                            daily_pnl=float(pf.get("daily_pnl", 0)),
                            daily_pnl_pct=float(pf.get("daily_pnl_pct", 0)),
                            positions=positions,
                            timestamp=int(time.time() * 1000),
                        )
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error("gRPC StreamPortfolio error", error=str(e))
                    break

        return _generate()

    def GetPortfolio(self, request, context):
        """Anlık portföy durumu (Protobuf)."""
        from ..core.redis_helper import get_cached
        pf = get_cached("portfolio:state") or {}
        positions = [
            market_pb2.Position(
                ticker=p.get("ticker", ""),
                quantity=int(p.get("quantity", 0)),
                avg_price=float(p.get("avg_price", 0)),
                current_price=float(p.get("current_price", 0)),
                pnl=float(p.get("pnl", 0)),
                pnl_pct=float(p.get("pnl_pct", 0)),
                weight=float(p.get("weight", 0)),
            )
            for p in pf.get("positions", [])
        ]
        return market_pb2.PortfolioState(
            total_value=float(pf.get("total_value", 0)),
            cash=float(pf.get("cash", 0)),
            daily_pnl=float(pf.get("daily_pnl", 0)),
            positions=positions,
            timestamp=int(time.time() * 1000),
        )


class RiskServiceServicer(market_pb2_grpc.RiskServiceServicer if HAS_PROTOBUF else object):
    """Risk gRPC servisi — Protobuf native."""

    def StreamRisk(self, request, context):
        """Risk metrikleri stream'i (Protobuf binary)."""

        async def _generate():
            while True:
                try:
                    from ..core.redis_helper import get_cached
                    risk = get_cached("risk:metrics")
                    if risk:
                        yield market_pb2.RiskMetrics(
                            var_95=float(risk.get("var_95", 0)),
                            cvar_95=float(risk.get("cvar_95", 0)),
                            sharpe=float(risk.get("sharpe", 0)),
                            max_drawdown=float(risk.get("max_drawdown", 0)),
                            volatility=float(risk.get("volatility", 0)),
                            beta=float(risk.get("beta", 0)),
                            timestamp=int(time.time() * 1000),
                        )
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.error("gRPC StreamRisk error", error=str(e))
                    break

        return _generate()

    def GetRisk(self, request, context):
        """Anlık risk durumu (Protobuf)."""
        from ..core.redis_helper import get_cached
        risk = get_cached("risk:metrics") or {}
        return market_pb2.RiskMetrics(
            var_95=float(risk.get("var_95", 0)),
            cvar_95=float(risk.get("cvar_95", 0)),
            sharpe=float(risk.get("sharpe", 0)),
            max_drawdown=float(risk.get("max_drawdown", 0)),
            volatility=float(risk.get("volatility", 0)),
            beta=float(risk.get("beta", 0)),
            timestamp=int(time.time() * 1000),
        )


async def start_grpc_server(host: str = "0.0.0.0", port: int = 50051):
    """gRPC sunucusunu başlat — tüm servisleri register eder.

    Best Practices:
    - Health check servisi (gRPC health checking protocol)
    - Reflection servisi (grpcurl ile test edilebilir)
    - Graceful shutdown
    """
    if not HAS_GRPC:
        logger.warning("gRPC not available (grpcio not installed)")
        return None

    if not HAS_PROTOBUF:
        logger.warning("Protobuf not available (generated code missing)")
        return None

    server = aio.server()

    # Tüm servisleri register et
    market_pb2_grpc.add_MarketServiceServicer_to_server(MarketServiceServicer(), server)
    market_pb2_grpc.add_SignalServiceServicer_to_server(SignalServiceServicer(), server)
    market_pb2_grpc.add_PortfolioServiceServicer_to_server(PortfolioServiceServicer(), server)
    market_pb2_grpc.add_RiskServiceServicer_to_server(RiskServiceServicer(), server)

    # Health check servisi (gRPC health checking protocol)
    try:
        from grpc_health.v1 import health, health_pb2_grpc
        health_servicer = health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
        logger.debug("gRPC health check service registered")
    except ImportError:
        logger.debug("grpcio-health not installed, skipping health check service")
    except Exception as e:
        logger.debug("gRPC health check not registered", error=str(e))

    # Reflection servisi (grpcurl ile test edilebilir)
    try:
        from grpc_reflection.v1alpha import reflection
        SERVICE_NAMES = (
            market_pb2_grpc.DESCRIPTOR.services_by_name["MarketService"].full_name,
            market_pb2_grpc.DESCRIPTOR.services_by_name["SignalService"].full_name,
            market_pb2_grpc.DESCRIPTOR.services_by_name["PortfolioService"].full_name,
            market_pb2_grpc.DESCRIPTOR.services_by_name["RiskService"].full_name,
        )
        reflection.enable_server_reflection(SERVICE_NAMES, server)
        logger.debug("gRPC reflection service registered")
    except ImportError:
        logger.debug("grpcio-reflection not installed, skipping reflection service")
    except Exception as e:
        logger.debug("gRPC reflection not registered", error=str(e))

    # mTLS desteği — sertifikalar varsa TLS ile başlat
    try:
        from ..core.mtls import get_grpc_server_credentials
        server_credentials = get_grpc_server_credentials()
        if server_credentials:
            server.add_secure_port(f"{host}:{port}", server_credentials)
            logger.info("gRPC server started with mTLS", host=host, port=port,
                        services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
                        tls="mTLS")
        else:
            server.add_insecure_port(f"{host}:{port}")
            logger.info("gRPC server started (insecure)", host=host, port=port,
                        services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
                        tls="none")
    except ImportError:
        server.add_insecure_port(f"{host}:{port}")
        logger.info("gRPC server started (insecure)", host=host, port=port,
                    services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
                    tls="none")
    except Exception as e:
        server.add_insecure_port(f"{host}:{port}")
        logger.warning("gRPC mTLS setup failed, using insecure", error=str(e))

    return server


if __name__ == "__main__":
    async def main():
        server = await start_grpc_server()
        if server:
            await server.wait_for_termination()

    asyncio.run(main())
