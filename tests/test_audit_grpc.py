"""ALPHA BIST — gRPC Servis Katmanı Kapsamlı Denetim Testleri.

Bu test modülü `services/grpc/` altındaki tüm istemci ve sunucu bileşenlerini test eder:
- `client.py`: BaseGRPCClient, MarketClient, SignalClient, PortfolioClient, RiskClient.
- `server.py`: Servicer sınıfları, temsil metodları ve sunucu başlatma.
- `__init__.py`: Dışa aktarılan sınıflar ve fonksiyonlar.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.grpc as grpc_pkg
from services.grpc.client import (
    BaseGRPCClient,
    MarketClient,
    PortfolioClient,
    RiskClient,
    SignalClient,
)
from services.grpc.server import (
    MarketServiceServicer,
    PortfolioServiceServicer,
    RiskServiceServicer,
    SignalServiceServicer,
    start_grpc_server,
)


def test_grpc_package_exports() -> None:
    """gRPC paketinin tüm modül seviyesi sembolleri eksiksiz dışa aktardığını doğrular."""
    assert hasattr(grpc_pkg, "MarketClient")
    assert hasattr(grpc_pkg, "SignalClient")
    assert hasattr(grpc_pkg, "PortfolioClient")
    assert hasattr(grpc_pkg, "RiskClient")
    assert hasattr(grpc_pkg, "start_grpc_server")


def test_grpc_client_repr_and_init() -> None:
    """gRPC istemci sınıflarının başlatılmasını ve __repr__ temsillerini doğrular."""
    base_client = BaseGRPCClient(hosts=["127.0.0.1"], port=50051)
    assert "BaseGRPCClient" in repr(base_client)
    assert base_client.port == 50051

    market_client = MarketClient()
    assert "MarketClient" in repr(market_client)

    signal_client = SignalClient()
    assert "SignalClient" in repr(signal_client)

    portfolio_client = PortfolioClient()
    assert "PortfolioClient" in repr(portfolio_client)

    risk_client = RiskClient()
    assert "RiskClient" in repr(risk_client)


def test_grpc_servicer_classes() -> None:
    """gRPC sunucu servis sınıflarının başlatılmasını ve temsillerini doğrular."""
    market_servicer = MarketServiceServicer()
    assert repr(market_servicer) == "MarketServiceServicer()"

    signal_servicer = SignalServiceServicer()
    assert repr(signal_servicer) == "SignalServiceServicer()"

    portfolio_servicer = PortfolioServiceServicer()
    assert repr(portfolio_servicer) == "PortfolioServiceServicer()"

    risk_servicer = RiskServiceServicer()
    assert repr(risk_servicer) == "RiskServiceServicer()"


@pytest.mark.asyncio
async def test_market_client_fallback() -> None:
    """MarketClient bağlı değilken Redis fallback üzerinden fiyat döndürdüğünü doğrular."""
    client = MarketClient()
    with patch("services.core.redis_helper.get_cached", return_value={"price": 285.5, "change": 1.2}):
        tick = await client.get_tick("THYAO")
        assert tick["price"] == 285.5


@pytest.mark.asyncio
async def test_signal_client_fallback() -> None:
    """SignalClient bağlı değilken Redis fallback üzerinden sinyalleri aldığını doğrular."""
    client = SignalClient()
    with patch("services.core.redis_helper.get_cached", return_value=[{"ticker": "ASELS", "direction": "BUY", "confidence": 0.9}]):
        recent_signals = await client.get_recent_signals(min_confidence=0.5)
        assert len(recent_signals) == 1
        assert recent_signals[0]["ticker"] == "ASELS"

        latest_signals = await client.get_latest_signals(min_confidence=0.5)
        assert len(latest_signals) == 1


@pytest.mark.asyncio
async def test_start_grpc_server_flow() -> None:
    """start_grpc_server fonksiyonunun başlatma akışını doğrular."""
    # gRPC paketi yüklü olmadığında None döndüğünü doğrular
    with patch("services.grpc.server.HAS_GRPC", False):
        server = await start_grpc_server(host="0.0.0.0", port=50051)
        assert server is None

    # gRPC paketi ve protobuf taklit edildiğinde server nesnesi döndüğünü doğrular
    mock_srv = AsyncMock()
    mock_aio = MagicMock()
    mock_aio.server.return_value = mock_srv
    mock_pb2_grpc = MagicMock()
    with (
        patch("services.grpc.server.HAS_GRPC", True),
        patch("services.grpc.server.HAS_PROTOBUF", True),
        patch("services.grpc.server.aio", mock_aio),
        patch("services.grpc.server.market_pb2_grpc", mock_pb2_grpc),
    ):
        server = await start_grpc_server(host="0.0.0.0", port=50051)
        assert server is not None
