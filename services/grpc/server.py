from typing import Any

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

import structlog

try:
    from grpc import aio

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

# Generated protobuf imports
try:
    from .generated import market_pb2, market_pb2_grpc

    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False

import functools

from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.grpc_server")

# Sinyal yönü sabitleri
_DIRECTION_MAP: dict[str, int] = {"BUY": 0, "SELL": 1, "HOLD": 2}

# Stream bekleme süreleri (saniye) — SSD yazma azaltma
_DEFAULT_STREAM_INTERVAL_SEC: float = 30.0
_DEFAULT_PORTFOLIO_STREAM_INTERVAL_SEC: float = 10.0


def otel_trace(span_name: str) -> Any:
    """OpenTelemetry span ile saran dekoratör.

    Args:
        span_name: Oluşturulacak span'ın adı.

    Returns:
        Dekore edilmiş fonksiyon.
    """

    def decorator(func: Any) -> Any:
        """Asıl dekoratör fonksiyonu."""
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Span içinde fonksiyon çalıştırır."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


def _extract_correlation_from_context(context: Any) -> None:
    """gRPC context'ten correlation_id'yi çıkar ve context variable'a kaydet.

    Args:
        context: gRPC servis context nesnesi.

    Returns:
        None.
    """
    try:
        from ..core.distributed_tracing import correlation_id_var

        metadata = dict(context.invocation_metadata())
        cid = metadata.get("x-correlation-id")
        if cid:
            correlation_id_var.set(cid)
    except ImportError:
        logger.debug("distributed_tracing modülü bulunamadı")
    except Exception as e:
        logger.error("correlation_id çıkarma hatası", error=str(e))


class MarketServiceServicer(market_pb2_grpc.MarketServiceServicer if HAS_PROTOBUF else object):
    """Piyasa verisi gRPC servisi — Protobuf native.

    Anlık fiyat stream'i ve tek seferlik fiyat sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """MarketServiceServicer kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "MarketServiceServicer()"

    @otel_trace("grpc.server.StreamTicks")
    def StreamTicks(self, request: Any, context: Any) -> Any:
        """Anlık fiyat stream'i (Protobuf binary).

        Args:
            request: Ticker listesi içeren istek.
            context: gRPC servis context'i.

        Returns:
            Async MarketTick iterator'ı.
        """
        _extract_correlation_from_context(context)
        tickers = list(request.tickers)
        logger.info("gRPC StreamTicks başlatıldı", tickers=tickers)

        async def _generate() -> Any:
            """Market tick'lerini üretir."""
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
                    await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
                except Exception as e:
                    logger.error("gRPC StreamTicks hatası", error=str(e))
                    break

        return _generate()

    @otel_trace("grpc.server.GetTick")
    def GetTick(self, request: Any, context: Any) -> Any:
        """Tek seferlik fiyat sorgusu (Protobuf).

        Args:
            request: Ticker listesi içeren istek.
            context: gRPC servis context'i.

        Returns:
            MarketTick protobuf mesajı.
        """
        _extract_correlation_from_context(context)
        tickers = list(request.tickers)
        if not tickers:
            logger.warning("GetTick boş ticker listesi")
            return market_pb2.MarketTick(timestamp=int(time.time() * 1000))

        ticker = tickers[0]
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
    """Sinyal gRPC servisi — Protobuf native.

    Sinyal stream'i ve son sinyalleri sorgulama sağlar.
    """

    def __repr__(self) -> str:
        """SignalServiceServicer kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "SignalServiceServicer()"

    @otel_trace("grpc.server.StreamSignals")
    def StreamSignals(self, request: Any, context: Any) -> Any:
        """Sinyal stream'i (Protobuf binary).

        Args:
            request: min_confidence filtresi içeren istek.
            context: gRPC servis context'i.

        Returns:
            Async Signal iterator'ı.
        """
        _extract_correlation_from_context(context)
        min_confidence = request.min_confidence if hasattr(request, "min_confidence") else 0.5

        async def _generate() -> Any:
            """Sinyalleri üretir."""
            while True:
                try:
                    from ..core.redis_helper import get_cached

                    signals = get_cached("signals:latest") or []
                    for s in signals:
                        if s.get("confidence", 0) >= min_confidence:
                            yield market_pb2.Signal(
                                ticker=s.get("ticker", ""),
                                direction=_DIRECTION_MAP.get(s.get("direction", "HOLD"), 2),
                                confidence=float(s.get("confidence", 0)),
                                target_price=float(s.get("target_price", 0)),
                                stop_loss=float(s.get("stop_loss", 0)),
                                reason=s.get("reason", ""),
                                timestamp=int(time.time() * 1000),
                            )
                    await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
                except Exception as e:
                    logger.error("gRPC StreamSignals hatası", error=str(e))
                    break

        return _generate()

    @otel_trace("grpc.server.GetRecentSignals")
    def GetRecentSignals(self, request: Any, context: Any) -> Any:
        """Son sinyalleri sorgula (Protobuf).

        Args:
            request: min_confidence filtresi içeren istek.
            context: gRPC servis context'i.

        Returns:
            SignalList protobuf mesajı.
        """
        _extract_correlation_from_context(context)
        from ..core.redis_helper import get_cached

        signals = get_cached("signals:latest") or []
        min_conf = request.min_confidence if hasattr(request, "min_confidence") else 0.5
        proto_signals = []
        for s in signals:
            if s.get("confidence", 0) >= min_conf:
                proto_signals.append(
                    market_pb2.Signal(
                        ticker=s.get("ticker", ""),
                        direction=_DIRECTION_MAP.get(s.get("direction", "HOLD"), 2),
                        confidence=float(s.get("confidence", 0)),
                        target_price=float(s.get("target_price", 0)),
                        stop_loss=float(s.get("stop_loss", 0)),
                        reason=s.get("reason", ""),
                        timestamp=int(time.time() * 1000),
                    )
                )
        return market_pb2.SignalList(signals=proto_signals)


class PortfolioServiceServicer(market_pb2_grpc.PortfolioServiceServicer if HAS_PROTOBUF else object):
    """Portföy gRPC servisi — Protobuf native.

    Portföy durumu stream'i ve anlık portföy sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """PortfolioServiceServicer kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "PortfolioServiceServicer()"

    @otel_trace("grpc.server.StreamPortfolio")
    def StreamPortfolio(self, request: Any, context: Any) -> Any:
        """Portföy durumu stream'i (Protobuf binary).

        Args:
            request: Boş istek.
            context: gRPC servis context'i.

        Returns:
            Async PortfolioState iterator'ı.
        """
        _extract_correlation_from_context(context)

        async def _generate() -> Any:
            """Portföy durumunu üretir."""
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
                    await asyncio.sleep(_DEFAULT_PORTFOLIO_STREAM_INTERVAL_SEC)
                except Exception as e:
                    logger.error("gRPC StreamPortfolio hatası", error=str(e))
                    break

        return _generate()

    @otel_trace("grpc.server.GetPortfolio")
    def GetPortfolio(self, request: Any, context: Any) -> Any:
        """Anlık portföy durumu sorgusu (Protobuf).

        Args:
            request: Boş istek.
            context: gRPC servis context'i.

        Returns:
            PortfolioState protobuf mesajı.
        """
        _extract_correlation_from_context(context)
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
            daily_pnl_pct=float(pf.get("daily_pnl_pct", 0)),
            positions=positions,
            timestamp=int(time.time() * 1000),
        )


class RiskServiceServicer(market_pb2_grpc.RiskServiceServicer if HAS_PROTOBUF else object):
    """Risk gRPC servisi — Protobuf native.

    Risk metrikleri stream'i ve anlık risk sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """RiskServiceServicer kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "RiskServiceServicer()"

    @otel_trace("grpc.server.StreamRisk")
    def StreamRisk(self, request: Any, context: Any) -> Any:
        """Risk metrikleri stream'i (Protobuf binary).

        Args:
            request: Boş istek.
            context: gRPC servis context'i.

        Returns:
            Async RiskMetrics iterator'ı.
        """
        _extract_correlation_from_context(context)

        async def _generate() -> Any:
            """Risk metriklerini üretir."""
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
                    await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
                except Exception as e:
                    logger.error("gRPC StreamRisk hatası", error=str(e))
                    break

        return _generate()

    @otel_trace("grpc.server.GetRisk")
    def GetRisk(self, request: Any, context: Any) -> Any:
        """Anlık risk durumu sorgusu (Protobuf).

        Args:
            request: Boş istek.
            context: gRPC servis context'i.

        Returns:
            RiskMetrics protobuf mesajı.
        """
        _extract_correlation_from_context(context)
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


async def start_grpc_server(host: str = "0.0.0.0", port: int = 50051) -> Any:
    """gRPC sunucusunu başlatır — tüm servisleri register eder.

    Health check, reflection ve mTLS desteği ile kurumsal seviye sunucu.

    Args:
        host: Sunucu adresi. Varsayılan "0.0.0.0".
        port: Sunucu portu. Varsayılan 50051.

    Returns:
        gRPC sunucu nesnesi veya None (grpcio/protobuf yoksa).

    Raises:
        Yok — eksik bağımlılıklar warning ile loglanır.
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
            logger.info(
                "gRPC server started with mTLS",
                host=host,
                port=port,
                services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
                tls="mTLS",
            )
        else:
            server.add_insecure_port(f"{host}:{port}")
            logger.info(
                "gRPC server started (insecure)",
                host=host,
                port=port,
                services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
                tls="none",
            )
    except ImportError:
        server.add_insecure_port(f"{host}:{port}")
        logger.info(
            "gRPC server started (insecure)",
            host=host,
            port=port,
            services=["MarketService", "SignalService", "PortfolioService", "RiskService"],
            tls="none",
        )
    except Exception as e:
        server.add_insecure_port(f"{host}:{port}")
        logger.warning("gRPC mTLS setup failed, using insecure", error=str(e))

    return server


if __name__ == "__main__":

    async def main() -> None:
        """gRPC sunucusunu başlatır ve çalıştırır."""
        server = await start_grpc_server()
        if server:
            await server.wait_for_termination()

    asyncio.run(main())


__all__: list[str] = [
    "MarketServiceServicer",
    "SignalServiceServicer",
    "PortfolioServiceServicer",
    "RiskServiceServicer",
    "start_grpc_server",
]
