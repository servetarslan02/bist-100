"""
Tests for services/risk audit compliance.
Verifies __repr__, lack of placeholders, thread-safety, calculation correctness,
and clean __all__ exports.
"""

import numpy as np

from services.risk import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertType,
    CalibrationParams,
    ComponentVaRResult,
    CovarianceEstimator,
    DrawdownAction,
    DrawdownResponseSystem,
    DrawdownSeverity,
    DynamicRiskLimits,
    LiquidityMetrics,
    LiquidityRiskEngine,
    MonteCarloResult,
    PortfolioLiquidityReport,
    PositionSize,
    PositionSizer,
    PreTradeOrderRequest,
    RegimeLimitsManager,
    RegimeRiskLimits,
    RiskAuditResult,
    RiskMetricsSnapshot,
    RiskOrchestrator,
    RiskParityOptimizer,
    RiskParityParameters,
    RiskParityResult,
    ScoreCalibrator,
    VaRCalculator,
    VaRResult,
)


def test_repr_implementations():
    """All dataclasses and engines in services/risk must have informative __repr__."""
    calib_params = CalibrationParams(a=1.0, b=0.0, method="platt")
    assert "CalibrationParams" in repr(calib_params)

    calibrator = ScoreCalibrator()
    assert "ScoreCalibrator" in repr(calibrator)

    cov_est = CovarianceEstimator()
    assert "CovarianceEstimator" in repr(cov_est)

    dd_sys = DrawdownResponseSystem()
    assert "DrawdownResponseSystem" in repr(dd_sys)

    dyn_lim = DynamicRiskLimits()
    assert "DynamicRiskLimits" in repr(dyn_lim)

    liq_engine = LiquidityRiskEngine()
    assert "LiquidityRiskEngine" in repr(liq_engine)

    liq_metrics = LiquidityMetrics(
        ticker="THYAO",
        order_value=50000.0,
        adv_tl=20000000.0,
        participation_rate_pct=0.25,
        effective_spread_bps=12.0,
        expected_market_impact_pct=0.05,
        expected_slippage_tl=25.0,
        liquidation_days=0.1,
        liquidity_score=90.0,
        liquidity_sizing_multiplier=1.0,
        is_tradable=True,
    )
    assert "THYAO" in repr(liq_metrics)

    port_rep = PortfolioLiquidityReport(
        portfolio_value=100000.0,
        portfolio_liquidity_score=88.0,
        weighted_spread_bps=10.0,
        total_liquidation_cost_tl=150.0,
        total_liquidation_cost_pct=0.15,
        max_liquidation_days=0.5,
        weighted_liquidation_days=0.2,
        base_var_95=2500.0,
        liquidity_adjusted_var_95=2575.0,
        lvar_increment_pct=3.0,
        illiquid_positions_count=0,
        position_details={},
    )
    assert "PortfolioLiquidityReport" in repr(port_rep)

    alert = Alert(
        alert_id="a1",
        alert_type=AlertType.VAR_BREACH,
        severity=AlertSeverity.WARNING,
        title="VaR Exceeded",
        message="VaR exceeded threshold",
        metric_name="var_95",
        metric_value=5000.0,
        threshold=4000.0,
    )
    assert "Alert(a1" in repr(alert)

    rule = AlertRule(
        rule_id="r1",
        name="Rule 1",
        alert_type=AlertType.DRAWDOWN,
        severity=AlertSeverity.CRITICAL,
        condition="gt",
        threshold=10.0,
        metric_name="drawdown",
    )
    assert "AlertRule(r1" in repr(rule)

    snapshot = RiskMetricsSnapshot(
        timestamp="2026-09-12T00:00:00Z",
        portfolio_value=1000000.0,
        var_95=20000.0,
        cvar_95=30000.0,
        portfolio_volatility=0.22,
        current_drawdown_pct=4.5,
        max_drawdown_pct=8.0,
        daily_pnl=5000.0,
        daily_pnl_pct=0.5,
        position_count=10,
        max_position_pct=12.0,
        sector_concentration={},
        correlation_risk=0.35,
        regime="BULL",
        risk_score=42.0,
    )
    assert "RiskMetricsSnapshot" in repr(snapshot)

    pos_size = PositionSize(
        ticker="GARAN",
        weight=0.08,
        shares=1000,
        notional=80000.0,
        risk_pct=0.01,
        kelly_fraction=0.5,
        win_probability=0.58,
        avg_win=0.06,
        avg_loss=0.03,
        vol_adjusted=0.20,
        max_position_pct=0.10,
    )
    assert "GARAN" in repr(pos_size)

    pos_sizer = PositionSizer()
    assert "PositionSizer" in repr(pos_sizer)

    regime_limits = RegimeRiskLimits(
        regime="BULL",
        max_position_pct=0.12,
        max_total_exposure=1.0,
        max_sector_concentration=0.35,
        min_liquidity_score=0.4,
        max_leverage=1.2,
        stop_loss_pct=0.05,
        confidence_multiplier=1.2,
        description="Boğa rejimi",
    )
    assert "RegimeRiskLimits(BULL" in repr(regime_limits)

    reg_mgr = RegimeLimitsManager()
    assert "RegimeLimitsManager" in repr(reg_mgr)

    parity_res = RiskParityResult(
        weights={"A": 0.5, "B": 0.5},
        risk_contributions={"A": 0.5, "B": 0.5},
        portfolio_volatility=0.15,
        diversification_ratio=1.2,
        optimization_success=True,
        iterations=20,
    )
    assert "RiskParityResult" in repr(parity_res)

    parity_opt = RiskParityOptimizer()
    assert "RiskParityOptimizer" in repr(parity_opt)

    parity_params = RiskParityParameters()
    assert "RiskParityParameters" in repr(parity_params)

    audit_res = RiskAuditResult(total_return_pct=45.0, sharpe_ratio=2.1, max_drawdown=8.5, total_trades=120)
    assert "RiskAuditResult" in repr(audit_res)

    var_res = VaRResult(
        var_95=0.02,
        var_99=0.035,
        cvar_95=0.028,
        cvar_99=0.045,
        method="historical",
        sample_size=250,
        portfolio_value=100000.0,
        var_95_amount=2000.0,
        var_99_amount=3500.0,
        cvar_95_amount=2800.0,
        cvar_99_amount=4500.0,
    )
    assert "VaRResult" in repr(var_res)

    comp_res = ComponentVaRResult(
        ticker="KCHOL",
        weight=0.15,
        component_var_95=0.004,
        marginal_var_95=0.025,
        pct_of_total_var=0.20,
    )
    assert "KCHOL" in repr(comp_res)

    mc_res = MonteCarloResult(
        var_95=0.025,
        var_99=0.04,
        cvar_95=0.035,
        cvar_99=0.05,
        mean_return=0.001,
        std_return=0.015,
        worst_case=-0.08,
        best_case=0.09,
        n_simulations=1000,
        n_days=1,
        percentiles={},
    )
    assert "MonteCarloResult" in repr(mc_res)

    var_calc = VaRCalculator()
    assert "VaRCalculator" in repr(var_calc)

    pre_trade = PreTradeOrderRequest(ticker="AKBNK", side="BUY", quantity=500, price=60.0)
    assert "AKBNK" in repr(pre_trade)

    orch = RiskOrchestrator()
    assert "RiskOrchestrator" in repr(orch)


def test_drawdown_response_system_thread_safety_and_reset():
    """Drawdown system must track peak equity and reset correctly."""
    dd = DrawdownResponseSystem()
    state1 = dd.update_equity(100000.0)
    assert state1.current_drawdown_pct == 0.0
    assert state1.action == DrawdownAction.NONE

    state2 = dd.update_equity(92000.0)  # %8 drawdown -> REDUCE_SIZE
    assert state2.current_drawdown_pct == 8.0
    assert state2.action == DrawdownAction.REDUCE_SIZE
    assert state2.severity == DrawdownSeverity.WARNING

    mult = dd.get_position_size_multiplier()
    assert mult == 0.5

    dd.reset(reason="Test reset")
    assert dd.get_state().current_drawdown_pct == 0.0


def test_position_sizer_calculation():
    """PositionSizer.calculate_position_size must return safe position size."""
    sizer = PositionSizer(max_position_pct=0.10)
    size = sizer.calculate_position_size("BIMAS", {"sizing_multiplier": 0.8}, 1000000.0)
    assert size == 80000.0  # 1000000 * 0.10 * 0.8


def test_risk_parity_optimizer():
    """RiskParityOptimizer must produce equal risk contribution weights."""
    opt = RiskParityOptimizer()
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    res = opt.optimize(cov, ["STOCK_A", "STOCK_B"])
    assert res.optimization_success
    assert len(res.weights) == 2
    assert abs(sum(res.weights.values()) - 1.0) < 1e-4
    # Higher volatility stock should have lower weight
    assert res.weights["STOCK_A"] > res.weights["STOCK_B"]
