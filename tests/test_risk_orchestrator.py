from typing import Any
"""
ALPHA BIST — Risk Orchestrator & Multi-Layer Risk Engine Test Suite

Kapsam:
1. Covariance Positive Semi-Definite (PSD) & Eigenvalue Floor Tests
2. Liquidity Risk Engine & L-VaR Tests (Kyle's Lambda, ADV participation, spread blowout)
3. RiskOrchestrator Pre-Trade Integration Tests (BIST rules, dynamic limits, drawdown action)
4. RiskOrchestrator Portfolio Risk Assessment Tests (VaR, L-VaR, Concentration, Stres Testi)
5. Streaming Real-Time Monitoring & Proximity Alert Tests
6. Edge Case & Fail-Closed Tests (NaN input, zero volume, singular covariance, extreme drawdowns)
"""

import numpy as np
import pytest

from services.core.market_session_fsm import BISTMarketPhase
from services.risk.covariance import (
    CovarianceEstimator,
    ensure_positive_semi_definite,
    is_positive_semi_definite,
)
from services.risk.liquidity_risk import (
    LiquidityRiskEngine,
)
from services.risk.monitoring import AlertType, RiskMonitor
from services.risk.orchestrator import (
    PreTradeOrderRequest,
    RiskOrchestrator,
)


# =====================================================
# 1. COVARIANCE PSD & NUMERICAL STABILITY TESTS
# =====================================================
class TestCovariancePSD:
    """Pozitif Yarı-Tanımlılık (PSD) ve özdeğer taban testleri."""

    def test_ensure_positive_semi_definite_on_indefinite_matrix(self) -> Any:
        """Otomatik eklendi."""
        # Matris with negative eigenvalue
        bad_matrix = np.array(
            [
                [1.0, 2.0],
                [2.0, 1.0],
            ]
        )  # Eigenvalues: 3.0 and -1.0
        assert not is_positive_semi_definite(bad_matrix)

        psd_matrix = ensure_positive_semi_definite(bad_matrix, min_eigenvalue=1e-5)
        assert is_positive_semi_definite(psd_matrix)
        eigvals = np.linalg.eigvalsh(psd_matrix)
        assert np.all(eigvals >= 1e-5)

    def test_covariance_estimator_singular_collinear_assets(self) -> Any:
        """Otomatik eklendi."""
        # Exactly collinear assets (rank deficient)
        np.random.seed(42)
        r1 = np.random.normal(0, 0.02, 100)
        r2 = r1 * 2.0  # Perfect collinearity
        r3 = r1 * -1.5
        returns = np.column_stack([r1, r2, r3])

        estimator = CovarianceEstimator(min_eigenvalue=1e-6)
        res = estimator.estimate(returns, ["A", "B", "C"])

        cov = res["covariance"]
        assert cov.shape == (3, 3)
        assert res["is_psd"] is True
        assert is_positive_semi_definite(cov)

    def test_covariance_estimator_single_asset_and_nans(self) -> Any:
        """Otomatik eklendi."""
        # Single asset
        r_single = np.array([[0.01], [0.02], [-0.01], [0.03]])
        estimator = CovarianceEstimator()
        res = estimator.estimate(r_single, ["THYAO"])
        assert res["covariance"].shape == (1, 1)
        assert res["covariance"][0, 0] > 0
        assert res["is_psd"] is True

        # NaN/Inf handling
        r_nan = np.array([[0.01, np.nan], [np.inf, 0.02], [-0.01, 0.01], [0.00, 0.00]])
        res_nan = estimator.estimate(r_nan, ["A", "B"])
        assert not np.isnan(res_nan["covariance"]).any()
        assert not np.isinf(res_nan["covariance"]).any()
        assert res_nan["is_psd"] is True


# =====================================================
# 2. LIQUIDITY RISK & L-VAR TESTS
# =====================================================
class TestLiquidityRiskEngine:
    """Likidite riski ve piyasa etkisi testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.engine = LiquidityRiskEngine(max_adv_participation_pct=5.0)

    def test_evaluate_order_liquidity_liquid_stock(self) -> Any:
        """Otomatik eklendi."""
        # THYAO (High ADV, low spread)
        metrics = self.engine.evaluate_order_liquidity(
            ticker="THYAO",
            order_value=50_000.0,
            price=300.0,
            adv_tl=2_000_000_000.0,  # 2 Milyar TL ADV
            spread_bps=5.0,  # 5 bps spread
        )
        assert metrics.is_tradable is True
        assert metrics.liquidity_score >= 80.0
        assert metrics.liquidity_sizing_multiplier == 1.0
        assert metrics.participation_rate_pct < 0.01
        assert metrics.liquidation_days < 0.1

    def test_evaluate_order_liquidity_illiquid_stock(self) -> Any:
        """Otomatik eklendi."""
        # Illiquid small-cap (Low ADV, wide spread, gross settlement)
        metrics = self.engine.evaluate_order_liquidity(
            ticker="SMALL",
            order_value=500_000.0,
            price=15.0,
            adv_tl=1_000_000.0,  # 1M TL ADV (Order is 50% of ADV)
            spread_bps=80.0,  # 80 bps wide spread
            is_gross_settlement=True,
        )
        assert metrics.participation_rate_pct == 50.0
        assert metrics.is_tradable is False  # Rejected because >25% ADV
        assert metrics.liquidity_score < 40.0
        assert metrics.liquidity_sizing_multiplier <= 0.50
        assert len(metrics.warnings) >= 2

    def test_calculate_portfolio_liquidity_and_lvar(self) -> Any:
        """Otomatik eklendi."""
        positions = [
            {"ticker": "THYAO", "value": 500_000.0, "adv_tl": 2_000_000_000.0, "spread_bps": 5.0},
            {"ticker": "GARAN", "value": 500_000.0, "adv_tl": 1_500_000_000.0, "spread_bps": 6.0},
        ]
        total_val = 1_000_000.0
        base_var = 40_000.0

        report = self.engine.calculate_portfolio_liquidity(
            positions=positions,
            total_portfolio_value=total_val,
            base_var_95=base_var,
        )
        assert report.portfolio_liquidity_score > 70.0
        assert report.liquidity_adjusted_var_95 >= base_var  # L-VaR >= Base VaR
        assert report.max_liquidation_days < 1.0


# =====================================================
# 3. RISK ORCHESTRATOR TESTS
# =====================================================
class TestRiskOrchestrator:
    """Merkezi RiskOrchestrator entegrasyon testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.orchestrator = RiskOrchestrator()

    def test_evaluate_pre_trade_valid_order(self) -> Any:
        """Otomatik eklendi."""
        req = PreTradeOrderRequest(
            ticker="THYAO",
            side="BUY",
            quantity=100,
            price=300.0,
            reference_price=300.0,
            market_phase=BISTMarketPhase.CONTINUOUS_AUCTION,
            model_confidence=0.75,
            adv_tl=2_000_000_000.0,
        )
        portfolio_state = {
            "total_value": 1_000_000.0,
            "cash": 500_000.0,
            "positions": {},
        }
        decision = self.orchestrator.evaluate_pre_trade(req, portfolio_state, regime="BULL")
        assert decision.allowed is True
        assert decision.checks_passed > 0
        assert decision.checks_failed == 0

    def test_evaluate_pre_trade_blocks_on_insufficient_cash(self) -> Any:
        """Otomatik eklendi."""
        req = PreTradeOrderRequest(
            ticker="THYAO",
            side="BUY",
            quantity=1000,
            price=300.0,  # 300,000 TL
            reference_price=300.0,
            market_phase=BISTMarketPhase.CONTINUOUS_AUCTION,
        )
        portfolio_state = {
            "total_value": 500_000.0,
            "cash": 10_000.0,  # Only 10k cash available
            "positions": {},
        }
        decision = self.orchestrator.evaluate_pre_trade(req, portfolio_state)
        assert decision.allowed is False
        assert decision.checks_failed >= 1
        assert "INSUFFICIENT_FUNDS" in decision.details.get("bist_rejection", "")

    def test_evaluate_pre_trade_blocks_on_kill_switch(self) -> Any:
        """Otomatik eklendi."""
        self.orchestrator.trigger_emergency_kill_switch(reason="Test acil durum")
        assert self.orchestrator.is_trading_allowed() is False

        req = PreTradeOrderRequest(
            ticker="THYAO",
            side="BUY",
            quantity=10,
            price=300.0,
        )
        portfolio_state = {"total_value": 100_000.0, "cash": 50_000.0, "positions": {}}
        decision = self.orchestrator.evaluate_pre_trade(req, portfolio_state)
        assert decision.allowed is False
        assert "KILL SWITCH" in decision.reason

        # Reset kill switch
        self.orchestrator.reset_kill_switch()
        assert self.orchestrator.is_trading_allowed() is True

    def test_assess_portfolio_risk_full_report(self) -> Any:
        """Otomatik eklendi."""
        np.random.seed(42)
        returns = np.random.normal(0.0008, 0.015, 252)
        portfolio = {
            "total_value": 200_000.0,
            "weights": {"THYAO": 0.4, "GARAN": 0.3, "ASELS": 0.3},
            "positions": [
                {"ticker": "THYAO", "value": 80_000.0, "adv_tl": 2_000_000_000.0},
                {"ticker": "GARAN", "value": 60_000.0, "adv_tl": 1_500_000_000.0},
                {"ticker": "ASELS", "value": 60_000.0, "adv_tl": 1_000_000_000.0},
            ],
        }
        report = self.orchestrator.assess_portfolio_risk(
            portfolio=portfolio,
            returns_history=returns,
            regime="SIDEWAYS",
        )
        assert "var_cvar" in report
        assert "liquidity" in report
        assert "concentration" in report
        assert "stress_test" in report
        assert "tail_hedge" in report
        assert "composite_risk_score" in report
        assert 0.0 <= report["composite_risk_score"] <= 100.0


# =====================================================
# 4. STREAMING REAL-TIME MONITORING TESTS
# =====================================================
class TestStreamingRiskMonitoring:
    """Canlı fiyat tick'leri ve limit yakınlık uyarı testleri."""

    def test_limit_proximity_alerts(self) -> Any:
        """Otomatik eklendi."""
        monitor = RiskMonitor()

        # Fiyat tavana çok yakın (Ref: 100, Tavan: 110, Fiyat: 109.5)
        alerts = monitor.ingest_price_tick(
            ticker="THYAO",
            price=109.5,
            reference_price=100.0,
            price_margin_pct=10.0,
        )
        assert len(alerts) >= 1
        assert alerts[0].title == "Tavan Fiyat Yakınlığı Uyarısı"
        assert alerts[0].ticker == "THYAO"

        # Fiyat tabana çok yakın (Ref: 100, Taban: 90, Fiyat: 90.5)
        alerts_down = monitor.ingest_price_tick(
            ticker="GARAN",
            price=90.5,
            reference_price=100.0,
            price_margin_pct=10.0,
        )
        assert len(alerts_down) >= 1
        assert alerts_down[0].title == "Taban Fiyat Yakınlığı Uyarısı"

    def test_spread_blowout_alert(self) -> Any:
        """Otomatik eklendi."""
        monitor = RiskMonitor()
        # Spread 200 bps (%2.0)
        alerts = monitor.ingest_price_tick(
            ticker="PETKM",
            price=20.0,
            best_bid=19.80,
            best_ask=20.20,
        )
        assert len(alerts) >= 1
        assert alerts[0].alert_type == AlertType.LIQUIDITY
        assert "Spread Açılması" in alerts[0].title


# =====================================================
# 5. EDGE CASE TESTS
# =====================================================
class TestEdgeCases:
    """Uç durum ve sıfır bölme koruma testleri."""

    def test_zero_portfolio_value_safety(self) -> Any:
        """Otomatik eklendi."""
        orchestrator = RiskOrchestrator()
        empty_portfolio = {"total_value": 0.0, "weights": {}, "positions": []}
        report = orchestrator.assess_portfolio_risk(empty_portfolio)
        assert report["portfolio_value"] == 0.0
        assert report["composite_risk_score"] >= 0.0

    def test_negative_price_order_rejection(self) -> Any:
        """Otomatik eklendi."""
        orchestrator = RiskOrchestrator()
        req = PreTradeOrderRequest(
            ticker="THYAO",
            side="BUY",
            quantity=10,
            price=-15.0,  # Negative price
        )
        decision = orchestrator.evaluate_pre_trade(req, {"total_value": 100_000.0, "cash": 50_000.0})
        assert decision.allowed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
