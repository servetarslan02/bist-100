from typing import Any

"""
ALPHA BIST — gRPC & Protobuf Services Test Suite
Doğrulanan Özellikler:
1. Protobuf Mesaj Tipleri: MarketTick, OHLCV, Signal, PortfolioState, RiskMetrics, MarketRegime, Alert, StreamMessage
2. İkili (Binary) Serileştirme & Deserileştirme Roundtrip
3. Servicer Fonksiyonları: GetTick, Signal, Risk, Portfolio
4. Correlation Metadata Enjeksiyonu ve Dağıtık İzleme
5. BaseGRPCClient Yapılandırması: Load balancing host parsing ve default deadlines (10s)
"""

import pytest

from services.grpc.client import (
    BaseGRPCClient,
    _get_correlation_metadata,
)
from services.grpc.generated import market_pb2
from services.grpc.server import (
    MarketServiceServicer,
    RiskServiceServicer,
    SignalServiceServicer,
)


class TestProtobufSerialization:
    """Protobuf ikili serileştirme ve tip doğrulama testleri."""

    def test_market_tick_protobuf_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        tick = market_pb2.MarketTick(
            ticker="THYAO",
            price=305.50,
            change=5.25,
            change_pct=1.75,
            volume=1500000,
            bid=305.25,
            ask=305.50,
            timestamp=1700000000000,
        )
        serialized = tick.SerializeToString()
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0

        reconstructed = market_pb2.MarketTick()
        reconstructed.ParseFromString(serialized)
        assert reconstructed.ticker == "THYAO"
        assert reconstructed.price == pytest.approx(305.50)
        assert reconstructed.volume == 1500000

    def test_signal_protobuf_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        sig = market_pb2.Signal(
            ticker="ASELS",
            direction=market_pb2.Signal.Direction.BUY,
            confidence=0.88,
            target_price=75.0,
            stop_loss=62.5,
            reason="High Alpha Momentum + Quant Model Ensemble",
            timestamp=1700000000000,
        )
        serialized = sig.SerializeToString()
        reconstructed = market_pb2.Signal()
        reconstructed.ParseFromString(serialized)

        assert reconstructed.ticker == "ASELS"
        assert reconstructed.direction == market_pb2.Signal.Direction.BUY
        assert reconstructed.confidence == pytest.approx(0.88)
        assert reconstructed.target_price == pytest.approx(75.0)

    def test_portfolio_state_protobuf_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        pos1 = market_pb2.Position(
            ticker="THYAO",
            quantity=100,
            avg_price=280.0,
            current_price=305.0,
            pnl=2500.0,
            pnl_pct=8.92,
            weight=0.085,
        )
        state = market_pb2.PortfolioState(
            total_value=1000000.0,
            cash=150000.0,
            daily_pnl=12500.0,
            daily_pnl_pct=1.25,
            positions=[pos1],
            timestamp=1700000000000,
        )
        serialized = state.SerializeToString()
        reconstructed = market_pb2.PortfolioState()
        reconstructed.ParseFromString(serialized)

        assert reconstructed.total_value == pytest.approx(1000000.0)
        assert len(reconstructed.positions) == 1
        assert reconstructed.positions[0].ticker == "THYAO"

    def test_risk_metrics_protobuf_roundtrip(self) -> Any:
        """Otomatik eklendi."""
        risk = market_pb2.RiskMetrics(
            var_95=0.021,
            cvar_95=0.034,
            sharpe=2.45,
            max_drawdown=0.065,
            volatility=0.18,
            beta=0.92,
            timestamp=1700000000000,
        )
        serialized = risk.SerializeToString()
        reconstructed = market_pb2.RiskMetrics()
        reconstructed.ParseFromString(serialized)

        assert reconstructed.var_95 == pytest.approx(0.021)
        assert reconstructed.sharpe == pytest.approx(2.45)


class TestGRPCServicers:
    """gRPC servis işleyicileri (Servicers)."""

    def test_market_servicer_get_tick(self) -> Any:
        """Otomatik eklendi."""
        servicer = MarketServiceServicer()
        req = market_pb2.TickRequest(tickers=["THYAO"])
        res = servicer.GetTick(req, context=None)
        assert res.ticker == "THYAO"
        assert res.timestamp > 0

    def test_signal_servicer_get_recent_signals(self) -> Any:
        """Otomatik eklendi."""
        servicer = SignalServiceServicer()
        req = market_pb2.SignalRequest(tickers=["ASELS"], min_confidence=0.7)
        res = servicer.GetRecentSignals(req, context=None)
        assert isinstance(res, market_pb2.SignalList)

    def test_risk_servicer_get_risk(self) -> Any:
        """Otomatik eklendi."""
        servicer = RiskServiceServicer()
        req = market_pb2.RiskRequest(portfolio_id="main")
        res = servicer.GetRisk(req, context=None)
        assert isinstance(res, market_pb2.RiskMetrics)


class TestGRPCClientConfiguration:
    """gRPC İstemci yapılandırması ve metadata testleri."""

    def test_base_client_host_parsing_and_deadline(self) -> Any:
        """Otomatik eklendi."""
        client = BaseGRPCClient(hosts=["grpc-1:50051", "grpc-2:50051"], port=50051)
        assert len(client.hosts) == 2
        assert client.hosts[0] == "grpc-1:50051"
        assert client._default_deadline == 10.0

    def test_correlation_metadata_helper(self) -> Any:
        """Otomatik eklendi."""
        metadata = _get_correlation_metadata()
        assert isinstance(metadata, list)
