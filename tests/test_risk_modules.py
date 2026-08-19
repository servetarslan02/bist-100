"""
ALPHA BIST — Risk Modules Test Suite v1.0

Tüm yeni risk modülleri için kapsamlı test'ler:
- VaR/CVaR
- Dynamic Risk Limits
- Stress Test
- Drawdown Response
- Tail Hedge
- Risk Parity
- Monitoring
"""

import pytest
import numpy as np
from datetime import datetime, timezone


# =====================================================
# VaR/CVaR TESTS
# =====================================================

class TestVaRCalculator:
    """VaR/CVaR hesaplama testleri."""

    def setup_method(self):
        from services.risk.var_cvar import VaRCalculator
        self.calc = VaRCalculator()
        # 252 günlük getiri verisi (yılda ~%10 getiri, %20 volatilite)
        np.random.seed(42)
        self.returns = np.random.normal(0.0004, 0.0127, 252)
        self.portfolio_value = 100000.0

    def test_parametric_var_95(self):
        var = self.calc.calculate_parametric_var(self.returns, 0.95, self.portfolio_value)
        assert var > 0, "VaR should be positive"
        assert var < self.portfolio_value * 0.2, "VaR should be reasonable (<20% of portfolio)"

    def test_parametric_var_99(self):
        var_95 = self.calc.calculate_parametric_var(self.returns, 0.95, self.portfolio_value)
        var_99 = self.calc.calculate_parametric_var(self.returns, 0.99, self.portfolio_value)
        assert var_99 > var_95, "VaR 99% should be greater than VaR 95%"

    def test_parametric_cvar(self):
        var = self.calc.calculate_parametric_var(self.returns, 0.95, self.portfolio_value)
        cvar = self.calc.calculate_parametric_cvar(self.returns, 0.95, self.portfolio_value)
        assert cvar > var, "CVaR should be greater than VaR"

    def test_historical_var(self):
        var = self.calc.calculate_historical_var(self.returns, 0.95, self.portfolio_value)
        assert var > 0, "Historical VaR should be positive"

    def test_historical_cvar(self):
        var = self.calc.calculate_historical_var(self.returns, 0.95, self.portfolio_value)
        cvar = self.calc.calculate_historical_cvar(self.returns, 0.95, self.portfolio_value)
        assert cvar >= var, "CVaR should be >= VaR"

    def test_monte_carlo_var(self):
        result = self.calc.calculate_monte_carlo_var(
            self.returns, 0.95, self.portfolio_value, n_simulations=5000, seed=42
        )
        assert result.var_95 > 0, "MC VaR should be positive"
        assert result.var_99 > result.var_95, "MC VaR 99% > VaR 95%"
        assert result.cvar_95 >= result.var_95, "MC CVaR >= VaR"
        assert result.n_simulations == 5000
        assert 50 in result.percentiles

    def test_component_var(self):
        weights = np.array([0.3, 0.3, 0.4])
        cov = np.array([
            [0.0004, 0.0001, 0.0002],
            [0.0001, 0.0009, 0.0003],
            [0.0002, 0.0003, 0.0016],
        ])
        tickers = ["THYAO", "GARAN", "ASELS"]
        results = self.calc.calculate_component_var(
            weights, cov, 0.95, self.portfolio_value, tickers
        )
        assert len(results) == 3
        assert all(r.ticker in tickers for r in results)
        # Component VaR'ların toplamı pozitif olmalı
        total = sum(r.component_var_95 for r in results)
        assert total > 0

    def test_full_var_report(self):
        report = self.calc.calculate_full_var_report(
            self.returns, self.portfolio_value, holding_period_days=1
        )
        assert "parametric" in report
        assert "historical" in report
        assert "monte_carlo" in report
        assert "consensus" in report
        assert report["consensus"]["var_95"] > 0

    def test_var_based_position_limit(self):
        limit = self.calc.calculate_var_based_position_limit(
            self.returns, max_var_pct=5.0, portfolio_value=self.portfolio_value
        )
        assert limit > 0
        assert limit <= self.portfolio_value

    def test_holding_period_scaling(self):
        var_1d = self.calc.calculate_parametric_var(self.returns, 0.95, self.portfolio_value, 1)
        var_5d = self.calc.calculate_parametric_var(self.returns, 0.95, self.portfolio_value, 5)
        assert var_5d > var_1d, "5-day VaR should be greater than 1-day VaR"

    def test_empty_returns(self):
        var = self.calc.calculate_historical_var(np.array([]), 0.95, self.portfolio_value)
        assert var == 0.0


# =====================================================
# DYNAMIC RISK LIMITS TESTS
# =====================================================

class TestDynamicRiskLimits:
    """Dinamik risk limitleri testleri."""

    def setup_method(self):
        from services.risk.dynamic_limits import DynamicRiskLimits
        self.dl = DynamicRiskLimits()

    def test_normal_conditions(self):
        limits = self.dl.get_limits(
            annualized_volatility=0.20, regime="SIDEWAYS", current_drawdown_pct=0
        )
        assert limits.max_position_pct > 0
        assert limits.max_exposure_pct > 0
        assert limits.kelly_fraction > 0

    def test_high_volatility_tightens(self):
        normal = self.dl.get_limits(annualized_volatility=0.20, regime="SIDEWAYS")
        high_vol = self.dl.get_limits(annualized_volatility=0.40, regime="SIDEWAYS")
        assert high_vol.max_position_pct < normal.max_position_pct

    def test_bear_regime_tightens(self):
        sideways = self.dl.get_limits(regime="SIDEWAYS")
        bear = self.dl.get_limits(regime="BEAR")
        assert bear.max_position_pct < sideways.max_position_pct
        assert bear.kelly_fraction < sideways.kelly_fraction

    def test_crisis_regime_tightens_most(self):
        crisis = self.dl.get_limits(regime="CRISIS")
        bear = self.dl.get_limits(regime="BEAR")
        assert crisis.max_position_pct < bear.max_position_pct

    def test_drawdown_reduces_limits(self):
        no_dd = self.dl.get_limits(current_drawdown_pct=0)
        with_dd = self.dl.get_limits(current_drawdown_pct=10)
        assert with_dd.max_position_pct < no_dd.max_position_pct

    def test_vix_high_tightens(self):
        low_vix = self.dl.get_limits(vix_level=15)
        high_vix = self.dl.get_limits(vix_level=35)
        assert high_vix.max_position_pct < low_vix.max_position_pct

    def test_drawdown_action(self):
        assert self.dl.get_drawdown_action(2) is None
        action = self.dl.get_drawdown_action(6)
        assert action is not None
        assert action["action"] == "REDUCE_SIZE"
        action = self.dl.get_drawdown_action(20)
        assert action["action"] == "HALT_SYSTEM"

    def test_compare_limits(self):
        from services.risk.dynamic_limits import RiskLimits
        static = RiskLimits()
        dynamic = self.dl.get_limits(regime="BEAR")
        comparison = self.dl.compare_limits(static, dynamic)
        assert "max_position_pct" in comparison


# =====================================================
# STRESS TEST TESTS
# =====================================================

class TestStressTestEngine:
    """Stres testi testleri."""

    def setup_method(self):
        from services.risk.stress_test import StressTestEngine
        self.engine = StressTestEngine()
        self.portfolio = {
            "total_value": 1000000,
            "positions": [
                {"ticker": "THYAO", "value": 300000, "sector": "INDUSTRY"},
                {"ticker": "GARAN", "value": 250000, "sector": "BANKING"},
                {"ticker": "ASELS", "value": 200000, "sector": "TECHNOLOGY"},
                {"ticker": "EREGL", "value": 150000, "sector": "INDUSTRY"},
                {"ticker": "AKBNK", "value": 100000, "sector": "BANKING"},
            ],
        }

    def test_scenario_2008(self):
        result = self.engine.run_scenario(self.portfolio, "2008_GLOBAL_CRISIS")
        assert result.total_impact_pct < 0, "2008 should be negative"
        assert result.total_impact_amount < 0
        assert result.worst_position != ""

    def test_scenario_2020(self):
        result = self.engine.run_scenario(self.portfolio, "2020_COVID")
        assert result.total_impact_pct < 0

    def test_run_all_scenarios(self):
        report = self.engine.run_all_scenarios(self.portfolio)
        assert len(report.scenarios) > 0
        assert report.worst_scenario is not None
        assert report.risk_score >= 0 and report.risk_score <= 100
        assert len(report.recommendations) > 0

    def test_monte_carlo_stress(self):
        returns = np.random.normal(0.0004, 0.0127, 252)
        result = self.engine.run_monte_carlo_stress(
            self.portfolio, returns, n_simulations=1000, seed=42
        )
        assert result["n_simulations"] == 1000
        assert result["portfolio_value"] == 1000000
        assert "percentiles" in result
        assert result["prob_loss"] > 0

    def test_breaking_point(self):
        result = self.engine.find_breaking_point(self.portfolio, max_loss_pct=20)
        assert "breaking_scenarios" in result
        assert "is_robust" in result

    def test_unknown_scenario(self):
        result = self.engine.run_scenario(self.portfolio, "UNKNOWN_SCENARIO")
        assert result.total_impact_pct == 0


# =====================================================
# DRAWDOWN RESPONSE TESTS
# =====================================================

class TestDrawdownResponseSystem:
    """Drawdown response testleri."""

    def setup_method(self):
        from services.risk.drawdown_response import DrawdownResponseSystem, DrawdownAction
        self.dds = DrawdownResponseSystem()
        self.DrawdownAction = DrawdownAction

    def test_initial_state(self):
        state = self.dds.get_state()
        assert state.current_drawdown_pct == 0.0

    def test_peak_updates(self):
        self.dds.update_equity(100000)
        assert self.dds._peak_equity == 100000
        self.dds.update_equity(110000)
        assert self.dds._peak_equity == 110000

    def test_no_action_small_drawdown(self):
        self.dds.update_equity(100000)
        state = self.dds.update_equity(97000)  # 3% DD
        assert state.action == self.DrawdownAction.NONE

    def test_reduce_size_at_5pct(self):
        self.dds.update_equity(100000)
        state = self.dds.update_equity(94000)  # 6% DD
        assert state.action == self.DrawdownAction.REDUCE_SIZE
        assert state.position_scale == 0.5

    def test_stop_new_at_10pct(self):
        self.dds.update_equity(100000)
        state = self.dds.update_equity(89000)  # 11% DD
        assert state.action == self.DrawdownAction.STOP_NEW
        assert not self.dds.is_trading_allowed()

    def test_halt_at_20pct(self):
        self.dds.update_equity(100000)
        state = self.dds.update_equity(79000)  # 21% DD
        assert state.action == self.DrawdownAction.HALT_SYSTEM
        assert self.dds.is_system_halted()

    def test_position_multiplier(self):
        self.dds.update_equity(100000)
        assert self.dds.get_position_size_multiplier() == 1.0
        self.dds.update_equity(94000)  # 6% DD
        assert self.dds.get_position_size_multiplier() == 0.5

    def test_events_recorded(self):
        self.dds.update_equity(100000)
        self.dds.update_equity(94000)  # Triggers REDUCE_SIZE
        events = self.dds.get_events()
        assert len(events) > 0

    def test_alert_message(self):
        from services.risk.drawdown_response import DrawdownSeverity
        self.dds.update_equity(100000)
        state = self.dds.update_equity(94000)
        msg = self.dds.get_alert_message(state)
        assert msg is not None
        assert "DRAWDOWN" in msg


# =====================================================
# TAIL HEDGE TESTS
# =====================================================

class TestTailRiskHedger:
    """Tail risk hedging testleri."""

    def setup_method(self):
        from services.risk.tail_hedge import TailRiskHedger
        self.hedger = TailRiskHedger()

    def test_normal_conditions_no_hedge(self):
        rec = self.hedger.analyze(
            portfolio_value=1000000, vix_level=15, regime="SIDEWAYS"
        )
        assert rec.hedge_ratio < 0.3  # Normal conditions → low hedge

    def test_crisis_high_hedge(self):
        rec = self.hedger.analyze(
            portfolio_value=1000000, vix_level=40, regime="CRISIS",
            current_drawdown_pct=15
        )
        assert rec.hedge_ratio > 0.5  # Crisis → high hedge
        assert rec.protection_level in ["HIGH", "MEDIUM"]

    def test_crisis_alpha_detection(self):
        signal = self.hedger.detect_crisis_alpha(
            vix_level=35, market_return_5d=-0.05, gold_return_5d=0.03
        )
        assert signal.signal_strength > 0.5
        assert signal.regime in ["ELEVATED", "CRISIS"]

    def test_cost_benefit_analysis(self):
        result = self.hedger.calculate_hedge_cost_benefit(
            portfolio_value=1000000,
            hedge_cost_pct=1.0,
            max_loss_without_hedge_pct=30.0,
            max_loss_with_hedge_pct=10.0,
        )
        assert result["worth_hedging"] is True
        assert result["net_savings"] > 0

    def test_recommendations_have_instruments(self):
        rec = self.hedger.analyze(portfolio_value=1000000, vix_level=30, regime="BEAR")
        assert len(rec.instruments) > 0


# =====================================================
# RISK PARITY TESTS
# =====================================================

class TestRiskParityOptimizer:
    """Risk parity testleri."""

    def setup_method(self):
        from services.risk.risk_parity import RiskParityOptimizer
        self.optimizer = RiskParityOptimizer()
        self.cov = np.array([
            [0.0004, 0.0001, 0.0002],
            [0.0001, 0.0009, 0.0003],
            [0.0002, 0.0003, 0.0016],
        ])
        self.tickers = ["THYAO", "GARAN", "ASELS"]

    def test_equal_risk_contribution(self):
        result = self.optimizer.optimize(self.cov, self.tickers)
        assert result.optimization_success
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

        # Risk contributions should be roughly equal
        rcs = list(result.risk_contributions.values())
        assert max(rcs) - min(rcs) < 20, "Risk contributions should be roughly equal"

    def test_single_asset(self):
        cov = np.array([[0.0004]])
        result = self.optimizer.optimize(cov, ["THYAO"])
        assert result.weights["THYAO"] == 1.0

    def test_custom_risk_budgets(self):
        budgets = {"THYAO": 0.5, "GARAN": 0.3, "ASELS": 0.2}
        result = self.optimizer.compute_risk_budget_weights(
            self.cov, self.tickers, budgets
        )
        assert result.optimization_success

    def test_compare_with_equal_weight(self):
        comparison = self.optimizer.compare_with_equal_weight(self.cov, self.tickers)
        assert "risk_parity" in comparison
        assert "equal_weight" in comparison

    def test_diversification_ratio(self):
        result = self.optimizer.optimize(self.cov, self.tickers)
        assert result.diversification_ratio > 1.0, "Diversification ratio should be > 1"


# =====================================================
# MONITORING TESTS
# =====================================================

class TestRiskMonitor:
    """Risk monitoring testleri."""

    def setup_method(self):
        from services.risk.monitoring import RiskMonitor, RiskMetricsSnapshot
        self.monitor = RiskMonitor()
        self.RiskMetricsSnapshot = RiskMetricsSnapshot

    def test_default_rules_loaded(self):
        rules = self.monitor.get_rules()
        assert len(rules) > 0
        assert any(r.rule_id == "var_95_breach" for r in rules)

    def test_alert_on_high_var(self):
        metrics = self.RiskMetricsSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=100000,
            var_95=6000,  # 6% > 5% threshold
            cvar_95=8000,
            portfolio_volatility=0.015,
            current_drawdown_pct=2.0,
            max_drawdown_pct=5.0,
            daily_pnl=0,
            daily_pnl_pct=0,
            position_count=5,
            max_position_pct=15.0,
            sector_concentration={},
            correlation_risk=0.5,
            regime="SIDEWAYS",
            risk_score=50,
        )
        alerts = self.monitor.check_metrics(metrics)
        assert any(a.alert_type.value == "VAR_BREACH" for a in alerts)

    def test_alert_on_drawdown(self):
        metrics = self.RiskMetricsSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=100000,
            var_95=2000,
            cvar_95=3000,
            portfolio_volatility=0.015,
            current_drawdown_pct=16.0,  # > 15% threshold
            max_drawdown_pct=16.0,
            daily_pnl=-2000,
            daily_pnl_pct=-2.0,
            position_count=5,
            max_position_pct=15.0,
            sector_concentration={},
            correlation_risk=0.5,
            regime="BEAR",
            risk_score=60,
        )
        alerts = self.monitor.check_metrics(metrics)
        assert any(a.alert_type.value == "DRAWDOWN" for a in alerts)

    def test_no_alert_normal_conditions(self):
        metrics = self.RiskMetricsSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=100000,
            var_95=2000,  # 2% < 5% threshold
            cvar_95=3000,
            portfolio_volatility=0.012,
            current_drawdown_pct=1.0,
            max_drawdown_pct=3.0,
            daily_pnl=500,
            daily_pnl_pct=0.5,
            position_count=5,
            max_position_pct=10.0,
            sector_concentration={},
            correlation_risk=0.3,
            regime="SIDEWAYS",
            risk_score=30,
        )
        alerts = self.monitor.check_metrics(metrics)
        assert len(alerts) == 0

    def test_custom_rule(self):
        from services.risk.monitoring import AlertRule, AlertType, AlertSeverity
        rule = AlertRule(
            rule_id="custom_test",
            name="Custom Test Rule",
            alert_type=AlertType.CUSTOM,
            severity=AlertSeverity.INFO,
            condition="gt",
            threshold=100,
            metric_name="position_count",
        )
        self.monitor.add_rule(rule)
        assert len(self.monitor.get_rules()) > 8  # Default + custom

    def test_alert_summary(self):
        summary = self.monitor.get_alert_summary()
        assert "total_alerts" in summary
        assert "by_severity" in summary

    def test_callback_registered(self):
        callback_called = []
        self.monitor.register_callback(lambda a: callback_called.append(a))

        metrics = self.RiskMetricsSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=100000,
            var_95=6000,  # Triggers alert
            cvar_95=8000,
            portfolio_volatility=0.015,
            current_drawdown_pct=2.0,
            max_drawdown_pct=5.0,
            daily_pnl=0,
            daily_pnl_pct=0,
            position_count=5,
            max_position_pct=15.0,
            sector_concentration={},
            correlation_risk=0.5,
            regime="SIDEWAYS",
            risk_score=50,
        )
        self.monitor.check_metrics(metrics)
        assert len(callback_called) > 0


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestRiskIntegration:
    """Entegrasyon testleri — modüller arası etkileşim."""

    def test_var_informs_position_sizing(self):
        """VaR sonucu position sizing'ı etkilemeli."""
        from services.risk.var_cvar import VaRCalculator
        calc = VaRCalculator()
        returns = np.random.normal(0.0004, 0.0127, 252)

        limit = calc.calculate_var_based_position_limit(
            returns, max_var_pct=5.0, portfolio_value=100000
        )
        assert limit > 0
        assert limit <= 100000

    def test_dynamic_limits_with_stress_test(self):
        """Stres testi sonuçları dinamik limitleri etkilemeli."""
        from services.risk.dynamic_limits import DynamicRiskLimits
        from services.risk.stress_test import StressTestEngine

        dl = DynamicRiskLimits()
        st = StressTestEngine()

        portfolio = {
            "total_value": 1000000,
            "positions": [
                {"ticker": "THYAO", "value": 500000, "sector": "INDUSTRY"},
                {"ticker": "GARAN", "value": 500000, "sector": "BANKING"},
            ],
        }

        report = st.run_all_scenarios(portfolio)
        # Kötü senaryo varsa limitler sıkılaşmalı
        if report.risk_score > 50:
            limits = dl.get_limits(regime="BEAR")
            assert limits.max_position_pct < 10.0

    def test_drawdown_affects_position_size(self):
        """Drawdown pozisyon boyutunu etkilemeli."""
        from services.risk.drawdown_response import DrawdownResponseSystem
        dds = DrawdownResponseSystem()

        dds.update_equity(100000)
        assert dds.get_position_size_multiplier() == 1.0

        dds.update_equity(94000)  # 6% DD
        assert dds.get_position_size_multiplier() == 0.5

    def test_monitoring_catches_all_alerts(self):
        """Monitoring tüm kritik durumları yakalamalı."""
        from services.risk.monitoring import RiskMonitor, RiskMetricsSnapshot
        monitor = RiskMonitor()

        # Birden fazla kritik durum
        metrics = RiskMetricsSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=100000,
            var_95=6000,      # VaR breach
            cvar_95=10000,    # CVaR breach
            portfolio_volatility=0.035,  # High vol
            current_drawdown_pct=16.0,   # Drawdown critical
            max_drawdown_pct=16.0,
            daily_pnl=-6000,  # Daily loss
            daily_pnl_pct=-6.0,
            position_count=3,
            max_position_pct=30.0,  # Concentration
            sector_concentration={"BANKING": 50},
            correlation_risk=0.8,
            regime="CRISIS",
            risk_score=85,    # High risk score
        )
        alerts = monitor.check_metrics(metrics)
        # Birden fazla alert tetiklenmeli
        assert len(alerts) >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
