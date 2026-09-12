"""
ALPHA BIST — gRPC Client v2.0 (Protobuf Native)

Generated protobuf stub'ları ile servisler arası hızlı iletişim.
JSON'dan 10x küçük, 10x hızlı.

Kullanım:
    from services.grpc.client import MarketClient, SignalClient

    async with MarketClient() as client:
        async for tick in client.stream_ticks(["THYAO", "ASELS"]):
            print(tick)
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

try:
    import grpc
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
tracer = trace.get_tracer("alpha-bist.grpc_client")

# Sinyal yönü sabitleri (protobuf int → string)
_DIRECTION_REVERSE_MAP: dict[int, str] = {0: "BUY", 1: "SELL", 2: "HOLD"}

# Stream bekleme süreleri (saniye) — SSD yazma azaltma
_DEFAULT_STREAM_INTERVAL_SEC: float = 30.0
_DEFAULT_PORTFOLIO_STREAM_INTERVAL_SEC: float = 10.0

# Varsayılan gRPC deadline (saniye)
_DEFAULT_GRPC_DEADLINE_SEC: float = 10.0


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


def _get_correlation_metadata() -> list[tuple[str, str]]:
    """Correlation ID'yi gRPC metadata'ya ekler.

    Returns:
        gRPC metadata tuple listesi. Correlation ID yoksa boş liste.
    """
    try:
        from ..core.distributed_tracing import correlation_id_var

        cid = correlation_id_var.get()
        if cid:
            return [("x-correlation-id", cid)]
    except ImportError:
        logger.debug("distributed_tracing modülü bulunamadı")
    except Exception as e:
        logger.error("correlation_id metadata hatası", error=str(e))
    return []


class BaseGRPCClient:
    """gRPC istemci taban sınıfı — generated stub'lar ile.

    Load Balancing: round_robin policy ile birden fazla gRPC instance'a
    otomatik yük dağılımı. Tek instance varsa bile çalışır (noop).
    """

    def __init__(self, hosts: list[str] | None = None, port: int = 50051) -> None:
        """gRPC istemci taban sınıfı başlatıcısı.

        Args:
            hosts: gRPC sunucu adresleri. None ise GRPC_HOSTS ortam değişkeninden okunur.
            port: gRPC portu.

        Returns:
            None.
        """
        if hosts is None:
            import os

            raw = os.environ.get("GRPC_HOSTS", "localhost")
            hosts = [h.strip() for h in raw.split(",") if h.strip()]
        self.hosts = hosts
        self.port = port
        self._channel = None
        self._stub = None
        self._default_deadline = _DEFAULT_GRPC_DEADLINE_SEC

    def __repr__(self) -> str:
        """BaseGRPCClient kısa temsili.

        Returns:
            Host sayısı ve port bilgisi.
        """
        return f"BaseGRPCClient(hosts={len(self.hosts)}, port={self.port})"

    @otel_trace("grpc.connect")
    async def connect(self) -> bool:
        """gRPC sunucusuna bağlanır.

        mTLS credentials varsa güvenli bağlantı, yoksa insecure bağlantı kurar.
        Birden fazla host varsa round_robin load balancing uygulanır.

        Returns:
            True ise bağlantı başarılı, False ise başarısız.
        """
        if not HAS_GRPC:
            logger.warning("gRPC not available (grpcio not installed)")
            return False

        if not HAS_PROTOBUF:
            logger.warning("Protobuf not available (generated code missing)")
            return False

        try:
            # mTLS credentials kontrolü
            tls_credentials = None
            try:
                from ..core.mtls import get_grpc_client_credentials

                tls_credentials = get_grpc_client_credentials()
            except ImportError:
                logger.debug("Optional import not available in connect", exc_info=True)
            except Exception as e:
                logger.debug("mTLS credentials not available", error=str(e))

            # round_robin load balancing: birden fazla adrese bağlan,
            # her RPC çağrısında sırayla dağıtır.
            options = [
                ("grpc.enable_retries", 1),
                ("grpc.keepalive_time_ms", 10000),
                ("grpc.keepalive_timeout_ms", 5000),
            ]

            if len(self.hosts) > 1:
                targets = ",".join(f"{h}:{self.port}" for h in self.hosts)
                options.append(("grpc.service_config", '{"loadBalancingConfig": [{"round_robin": {}}]}'))
                target_uri = f"ipv4:///{targets}"
            else:
                target_uri = f"{self.hosts[0]}:{self.port}"

            if tls_credentials:
                self._channel = aio.secure_channel(target_uri, tls_credentials, options=options)
                logger.info(
                    "gRPC connected with mTLS", hosts=self.hosts, lb="round_robin" if len(self.hosts) > 1 else "single"
                )
            else:
                self._channel = aio.insecure_channel(target_uri, options=options)
                logger.info(
                    "gRPC connected (insecure)", hosts=self.hosts, lb="round_robin" if len(self.hosts) > 1 else "single"
                )

            await self._channel.channel_ready()
            return True
        except Exception as e:
            logger.warning("gRPC connection failed", hosts=self.hosts, port=self.port, error=str(e))
            return False

    @otel_trace("grpc.close")
    async def close(self) -> None:
        """gRPC bağlantısını kapatır.

        Returns:
            None.
        """
        if self._channel:
            try:
                await self._channel.close()
            except Exception:
                logger.warning("Caught Exception in close", exc_info=True)
            self._channel = None
            self._stub = None

    async def __aenter__(self) -> "BaseGRPCClient":
        """Async context manager girişi — bağlanır.

        Returns:
            self.
        """
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager çıkışı — bağlantıyı kapatır.

        Returns:
            None.
        """
        await self.close()


class MarketClient(BaseGRPCClient):
    """Piyasa verisi gRPC istemcisi — Protobuf native.

    Anlık fiyat stream'i ve tek seferlik fiyat sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """MarketClient kısa temsili.

        Returns:
            Host sayısı ve stub durumu.
        """
        return f"MarketClient(hosts={len(self.hosts)}, connected={self._stub is not None})"

    async def connect(self) -> bool:
        """Market servis stub'ını oluşturur ve bağlanır.

        Returns:
            True ise bağlantı başarılı, False ise başarısız.
        """
        if await super().connect():
            self._stub = market_pb2_grpc.MarketServiceStub(self._channel)
            return True
        return False

    async def stream_ticks(self, tickers: list[str]) -> AsyncIterator[dict[str, Any]]:
        """Anlık fiyat stream'i (Protobuf binary).

        Args:
            tickers: Ticker listesi.

        Returns:
            Fiyat dict'leri AsyncIterator'ı.
        """
        if not self._stub:
            logger.warning("MarketClient bağlı değil, Redis fallback")
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
                await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
            return

        request = market_pb2.TickRequest(tickers=tickers)
        metadata = _get_correlation_metadata()
        try:
            async for tick in self._stub.StreamTicks(request, metadata=metadata):
                yield {
                    "ticker": tick.ticker,
                    "price": tick.price,
                    "change": tick.change,
                    "change_pct": tick.change_pct,
                    "volume": tick.volume,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "timestamp": tick.timestamp,
                }
        except grpc.RpcError as e:
            logger.error("gRPC StreamTicks error", code=e.code(), details=e.details())

    @otel_trace("grpc.market.get_tick")
    async def get_tick(self, ticker: str) -> dict[str, Any]:
        """Tek seferlik fiyat sorgusu (Protobuf).

        Args:
            ticker: Hisse senedi kodu.

        Returns:
            Fiyat dict'i. Hata durumunda error anahtarı içerir.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            data = get_cached(f"price:{ticker}")
            return data or {"ticker": ticker, "price": 0}

        request = market_pb2.TickRequest(tickers=[ticker])
        metadata = _get_correlation_metadata()
        try:
            tick = await self._stub.GetTick(request, metadata=metadata, timeout=self._default_deadline)
            return {
                "ticker": tick.ticker,
                "price": tick.price,
                "change": tick.change,
                "change_pct": tick.change_pct,
                "volume": tick.volume,
                "timestamp": tick.timestamp,
            }
        except grpc.RpcError as e:
            logger.error("gRPC GetTick error", code=e.code(), details=e.details())
            return {"ticker": ticker, "price": 0, "error": str(e.details())}


class SignalClient(BaseGRPCClient):
    """Sinyal gRPC istemcisi — Protobuf native.

    Sinyal stream'i ve son sinyalleri sorgulama sağlar.
    """

    def __repr__(self) -> str:
        """SignalClient kısa temsili.

        Returns:
            Host sayısı ve stub durumu.
        """
        return f"SignalClient(hosts={len(self.hosts)}, connected={self._stub is not None})"

    async def connect(self) -> bool:
        """Signal servis stub'ını oluşturur ve bağlanır.

        Returns:
            True ise bağlantı başarılı, False ise başarısız.
        """
        if await super().connect():
            self._stub = market_pb2_grpc.SignalServiceStub(self._channel)
            return True
        return False

    async def stream_signals(self, min_confidence: float = 0.5) -> AsyncIterator[dict[str, Any]]:
        """Sinyal stream'i (Protobuf binary).

        Args:
            min_confidence: Minimum güven skoru filtresi.

        Returns:
            Sinyal dict'leri AsyncIterator'ı.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            while True:
                signals = get_cached("signals:latest") or []
                for signal in signals:
                    if signal.get("confidence", 0) >= min_confidence:
                        yield signal
                await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
            return

        request = market_pb2.SignalRequest(min_confidence=min_confidence)
        metadata = _get_correlation_metadata()
        try:
            async for signal in self._stub.StreamSignals(request, metadata=metadata):
                yield {
                    "ticker": signal.ticker,
                    "direction": _DIRECTION_REVERSE_MAP.get(signal.direction, "HOLD"),
                    "confidence": signal.confidence,
                    "target_price": signal.target_price,
                    "stop_loss": signal.stop_loss,
                    "reason": signal.reason,
                    "timestamp": signal.timestamp,
                }
        except grpc.RpcError as e:
            logger.error("gRPC StreamSignals hatası", code=e.code(), details=e.details())

    @otel_trace("grpc.signal.get_recent_signals")
    async def get_recent_signals(self, min_confidence: float = 0.5) -> list[dict[str, Any]]:
        """Son sinyalleri sorgula (Protobuf).

        Args:
            min_confidence: Minimum güven skoru filtresi.

        Returns:
            Sinyal dict'leri listesi.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            signals = get_cached("signals:latest") or []
            return [s for s in signals if s.get("confidence", 0) >= min_confidence]

        request = market_pb2.SignalRequest(min_confidence=min_confidence)
        metadata = _get_correlation_metadata()
        try:
            response = await self._stub.GetRecentSignals(request, metadata=metadata, timeout=self._default_deadline)
            return [
                {
                    "ticker": s.ticker,
                    "direction": _DIRECTION_REVERSE_MAP.get(s.direction, "HOLD"),
                    "confidence": s.confidence,
                    "target_price": s.target_price,
                    "stop_loss": s.stop_loss,
                    "reason": s.reason,
                    "timestamp": s.timestamp,
                }
                for s in response.signals
            ]
        except grpc.RpcError as e:
            logger.error("gRPC GetRecentSignals hatası", code=e.code(), details=e.details())
            return []


class PortfolioClient(BaseGRPCClient):
    """Portföy gRPC istemcisi — Protobuf native.

    Portföy durumu stream'i ve anlık portföy sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """PortfolioClient kısa temsili.

        Returns:
            Host sayısı ve stub durumu.
        """
        return f"PortfolioClient(hosts={len(self.hosts)}, connected={self._stub is not None})"

    async def connect(self) -> bool:
        """Portfolio servis stub'ını oluşturur ve bağlanır.

        Returns:
            True ise bağlantı başarılı, False ise başarısız.
        """
        if await super().connect():
            self._stub = market_pb2_grpc.PortfolioServiceStub(self._channel)
            return True
        return False

    @otel_trace("grpc.portfolio.get_portfolio")
    async def get_portfolio(self) -> dict[str, Any]:
        """Anlık portföy durumu sorgusu (Protobuf).

        Returns:
            Portföy dict'i. Hata durumunda error anahtarı içerir.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            return get_cached("portfolio:state") or {}

        request = market_pb2.PortfolioRequest(portfolio_id="default")
        metadata = _get_correlation_metadata()
        try:
            pf = await self._stub.GetPortfolio(request, metadata=metadata, timeout=self._default_deadline)
            return {
                "total_value": pf.total_value,
                "cash": pf.cash,
                "daily_pnl": pf.daily_pnl,
                "daily_pnl_pct": pf.daily_pnl_pct,
                "positions": [
                    {
                        "ticker": p.ticker,
                        "quantity": p.quantity,
                        "avg_price": p.avg_price,
                        "current_price": p.current_price,
                        "pnl": p.pnl,
                        "pnl_pct": p.pnl_pct,
                        "weight": p.weight,
                    }
                    for p in pf.positions
                ],
                "timestamp": pf.timestamp,
            }
        except grpc.RpcError as e:
            logger.error("gRPC GetPortfolio error", code=e.code(), details=e.details())
            return {"error": str(e.details())}

    async def stream_portfolio(self) -> AsyncIterator[dict[str, Any]]:
        """Portföy durumu stream'i (Protobuf binary).

        Returns:
            Portföy dict'leri AsyncIterator'ı.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            while True:
                pf = get_cached("portfolio:state")
                if pf:
                    yield pf
                await asyncio.sleep(_DEFAULT_PORTFOLIO_STREAM_INTERVAL_SEC)
            return

        request = market_pb2.PortfolioRequest(portfolio_id="default")
        metadata = _get_correlation_metadata()
        try:
            async for pf in self._stub.StreamPortfolio(request, metadata=metadata):
                yield {
                    "cash": pf.cash,
                    "daily_pnl": pf.daily_pnl,
                    "positions": [
                        {
                            "ticker": p.ticker,
                            "quantity": p.quantity,
                            "avg_price": p.avg_price,
                            "current_price": p.current_price,
                            "pnl": p.pnl,
                            "pnl_pct": p.pnl_pct,
                            "weight": p.weight,
                        }
                        for p in pf.positions
                    ],
                    "timestamp": pf.timestamp,
                }
        except grpc.RpcError as e:
            logger.error("gRPC StreamPortfolio error", code=e.code(), details=e.details())


class RiskClient(BaseGRPCClient):
    """Risk gRPC istemcisi — Protobuf native.

    Risk metrikleri stream'i ve anlık risk sorgusu sağlar.
    """

    def __repr__(self) -> str:
        """RiskClient kısa temsili.

        Returns:
            Host sayısı ve stub durumu.
        """
        return f"RiskClient(hosts={len(self.hosts)}, connected={self._stub is not None})"

    async def connect(self) -> bool:
        """Risk servis stub'ını oluşturur ve bağlanır.

        Returns:
            True ise bağlantı başarılı, False ise başarısız.
        """
        if await super().connect():
            self._stub = market_pb2_grpc.RiskServiceStub(self._channel)
            return True
        return False

    @otel_trace("grpc.risk.get_risk")
    async def get_risk(self) -> dict[str, Any]:
        """Anlık risk durumu sorgusu (Protobuf).

        Returns:
            Risk metrikleri dict'i. Hata durumunda error anahtarı içerir.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            return get_cached("risk:metrics") or {}

        request = market_pb2.RiskRequest(portfolio_id="default")
        metadata = _get_correlation_metadata()
        try:
            risk = await self._stub.GetRisk(request, metadata=metadata, timeout=self._default_deadline)
            return {
                "var_95": risk.var_95,
                "cvar_95": risk.cvar_95,
                "sharpe": risk.sharpe,
                "max_drawdown": risk.max_drawdown,
                "volatility": risk.volatility,
                "beta": risk.beta,
                "timestamp": risk.timestamp,
            }
        except grpc.RpcError as e:
            logger.error("gRPC GetRisk error", code=e.code(), details=e.details())
            return {"error": str(e.details())}

    async def stream_risk(self) -> AsyncIterator[dict[str, Any]]:
        """Risk metrikleri stream'i (Protobuf binary).

        Returns:
            Risk metrikleri dict'leri AsyncIterator'ı.
        """
        if not self._stub:
            from ..core.redis_helper import get_cached

            while True:
                risk = get_cached("risk:metrics")
                if risk:
                    yield risk
                await asyncio.sleep(_DEFAULT_STREAM_INTERVAL_SEC)
            return

        request = market_pb2.RiskRequest(portfolio_id="default")
        metadata = _get_correlation_metadata()
        try:
            async for risk in self._stub.StreamRisk(request, metadata=metadata):
                yield {
                    "var_95": risk.var_95,
                    "cvar_95": risk.cvar_95,
                    "sharpe": risk.sharpe,
                    "max_drawdown": risk.max_drawdown,
                    "volatility": risk.volatility,
                    "beta": risk.beta,
                    "timestamp": risk.timestamp,
                }
        except grpc.RpcError as e:
            logger.error("gRPC StreamRisk hatası", code=e.code(), details=e.details())


__all__: list[str] = [
    "BaseGRPCClient",
    "MarketClient",
    "SignalClient",
    "PortfolioClient",
    "RiskClient",
]
