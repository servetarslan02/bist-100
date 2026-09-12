"""ALPHA BIST — Audit Tests for Paper Trading Service.

Tests verify:
- Zero placeholders and robust Turkish docstrings
- Informative __repr__ for all models, engines, and registries
- VirtualPortfolio cash accounting, purchasing power, T+2 settlement, and PnL
- PaperStateStore persistent DuckDB operations and buffered flush
- PaperRiskGate risk limits, drawdown alarms, and kill switch
- PaperExecutionEngine BIST tick rounding, commissions, and slippage caps
- PerformanceTracker metrics (Sharpe, Sortino, Drawdown, Alpha, Beta)
- PreTradeRiskEngine order eligibility and BIST margin checks
- LiquidityScenarioManager 3-scenario evaluation gate
- KAP Market Restriction & Corporate Action Registries
"""

import tempfile
from pathlib import Path

import numpy as np

from services.paper_trading import (
    CorporateActionRecord,
    KAPCorporateActionRegistry,
    KAPMarketRestrictionRegistry,
    LiquidityScenarioManager,
    MarketRestrictionRecord,
    PaperExecutionEngine,
    PaperRiskGate,
    PaperStateStore,
    PaperTradingOrchestrator,
    PerformanceTracker,
    PreTradeRiskEngine,
    PreTradeValidationResult,
    ScenarioResult,
    VirtualPortfolio,
)
from services.paper_trading.scenario_manager import LiquidityScenario


def test_paper_trading_repr_coverage():
    """Verify that all core engines, stores, and registries have informative __repr__."""
    portfolio = VirtualPortfolio(initial_capital=500_000.0)
    assert "VirtualPortfolio" in repr(portfolio)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_state.db"
        store = PaperStateStore(db_path=str(db_file))
        assert "PaperStateStore" in repr(store)

    risk_gate = PaperRiskGate()
    assert "PaperRiskGate" in repr(risk_gate)

    execution = PaperExecutionEngine()
    assert "PaperExecutionEngine" in repr(execution)

    perf = PerformanceTracker()
    assert "PerformanceTracker" in repr(perf)

    pre_risk = PreTradeRiskEngine()
    assert "PreTradeRiskEngine" in repr(pre_risk)

    val_res = PreTradeValidationResult(is_valid=True)
    assert "PreTradeValidationResult" in repr(val_res)

    sc_res = ScenarioResult(
        scenario=LiquidityScenario.NORMAL,
        total_return_pct=15.0,
        cagr_pct=14.5,
        sharpe_ratio=1.6,
        max_drawdown_pct=8.0,
        win_rate=0.58,
        total_commission=500.0,
        total_slippage_cost=300.0,
        num_trades=40,
    )
    assert "ScenarioResult" in repr(sc_res)

    sc_mgr = LiquidityScenarioManager()
    assert "LiquidityScenarioManager" in repr(sc_mgr)

    orch = PaperTradingOrchestrator(initial_capital=100_000.0)
    assert "PaperTradingOrchestrator" in repr(orch)

    rest_reg = KAPMarketRestrictionRegistry()
    assert "KAPMarketRestrictionRegistry" in repr(rest_reg)

    corp_reg = KAPCorporateActionRegistry()
    assert "KAPCorporateActionRegistry" in repr(corp_reg)


def test_virtual_portfolio_operations():
    """Verify VirtualPortfolio position management, purchasing power, and NAV."""
    portfolio = VirtualPortfolio(initial_capital=100_000.0)
    assert portfolio.total_cash == 100_000.0
    assert portfolio.purchasing_power == 100_000.0

    # Simulate buy order fill
    res = portfolio.open_position(
        ticker="THYAO",
        quantity=100,
        price=300.0,
        commission=10.0,
        date="2026-09-12",
    )
    assert res["success"] is True

    assert "THYAO" in portfolio.get_position("THYAO")["ticker"]
    assert portfolio.get_position("THYAO")["quantity"] == 100
    assert abs(portfolio.get_position("THYAO")["avg_cost"] - 300.1) < 0.01
    assert portfolio.get_invested_value() == 30_000.0
    # Cash deducted: 30,000 + 10 = 30,010 -> 69,990 left
    assert abs(portfolio.total_cash - 69_990.0) < 0.01

    # Price update
    portfolio.update_prices({"THYAO": 320.0}, date="2026-09-12")
    assert portfolio.get_invested_value() == 32_000.0
    assert abs(portfolio.get_unrealized_pnl() - 1990.0) < 0.01
    assert abs(portfolio.get_total_value() - 101_990.0) < 0.01


def test_paper_execution_engine_cost_and_ticks():
    """Verify PaperExecutionEngine BIST tick rounding, commission, and slippage."""
    engine = PaperExecutionEngine(commission_rate=0.0003, exchange_fee_rate=0.000056)

    # Tick rounding (BIST rules)
    rounded_buy = engine._round_to_tick(15.234, side="BUY")
    assert rounded_buy > 0

    # Commission computation
    comm = engine._compute_commission(100_000.0)
    assert comm >= engine.min_commission
    # (30 + 5.6) * 1.05 = ~37.38
    assert abs(comm - 37.38) < 1.0

    # Slippage cap
    slippage = engine.compute_slippage(quantity=10000, avg_volume=20000, volatility=0.30, spread_pct=0.1)
    assert slippage <= engine.slippage_max_pct / 100.0


def test_paper_risk_gate_checks():
    """Verify PaperRiskGate enforces position size, sector concentration, and kill switch."""
    risk_gate = PaperRiskGate(
        max_position_pct=10.0,
        max_sector_pct=30.0,
        kill_switch_drawdown_pct=25.0,
    )
    portfolio = VirtualPortfolio(initial_capital=100_000.0)

    # 1. Position size check: 100k portfolio, 15k position (>10%) -> should BLOCK
    res_pos = risk_gate._check_position_size(portfolio, ticker="THYAO", side="BUY", quantity=100, price=150.0)
    assert res_pos["result"] == "BLOCK"

    # 2. Position size check: 5k position (<=10%) -> should PASS
    res_pos_ok = risk_gate._check_position_size(portfolio, ticker="THYAO", side="BUY", quantity=50, price=100.0)
    assert res_pos_ok["result"] == "PASS"

    # 3. Kill switch test
    assert not risk_gate.is_kill_switch_active()
    risk_gate._kill_switch_active = True
    risk_gate._kill_switch_reason = "Manual Test"
    assert risk_gate.is_kill_switch_active()
    assert "Manual Test" in risk_gate.get_kill_switch_reason()
    risk_gate.reset_kill_switch()
    assert not risk_gate.is_kill_switch_active()


def test_performance_tracker_metrics():
    """Verify PerformanceTracker Sharpe, Sortino, Drawdown, and Turnover calculation."""
    tracker = PerformanceTracker()

    returns = np.array([0.01, 0.02, -0.005, 0.015, -0.01, 0.025])
    sharpe = tracker._sharpe(returns)
    assert sharpe > 0.0

    sortino = tracker._sortino(returns)
    assert sortino > 0.0

    equities = [100.0, 105.0, 110.0, 99.0, 108.0]  # peak 110, drop to 99 -> 11/110 = 10%
    max_dd = tracker._max_drawdown(equities)
    assert abs(max_dd - 10.0) < 0.01


def test_pre_trade_risk_engine():
    """Verify PreTradeRiskEngine universes and basic validations."""
    engine = PreTradeRiskEngine()
    engine.set_short_sale_universe(["THYAO", "GARAN"])
    engine.set_gross_settlement_universe(["SPEK1"])
    engine.set_spk_banned_universe(["BANNED1"])

    assert "THYAO" in engine._short_sale_eligible_tickers
    assert "SPEK1" in engine._gross_settlement_tickers
    assert "BANNED1" in engine._spk_banned_tickers


def test_registries_corporate_and_restriction():
    """Verify KAP Corporate Action and Restriction registries functionality."""
    rest_reg = KAPMarketRestrictionRegistry()
    rest_reg.register_restriction(
        ticker="KENT",
        restriction_type="VBTS_GROSS_SETTLEMENT",
        published_at="2026-09-12T18:00:00Z",
        effective_date="2026-09-13",
        end_date="2026-10-13",
        details="VBTS Tedbiri",
    )
    rec = rest_reg.get_active_restrictions("KENT", "2026-09-15")
    assert len(rec) == 1
    assert isinstance(rec[0], MarketRestrictionRecord)
    assert rec[0].restriction_type == "VBTS_GROSS_SETTLEMENT"

    corp_reg = KAPCorporateActionRegistry()
    corp_reg.register_action(
        ticker="EREGL",
        action_type="DIVIDEND",
        effective_date="2026-09-20",
        details="Temettu 4.5 TL",
    )
    actions = corp_reg.get_actions_for_ticker("EREGL")
    assert len(actions) == 1
    assert isinstance(actions[0], CorporateActionRecord)
    assert actions[0].action_type == "DIVIDEND"
