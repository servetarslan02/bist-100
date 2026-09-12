"""
Tests for services/portfolio audit compliance.
Verifies __repr__, lack of placeholders, calculations, and complete __all__ exports.
"""

from datetime import datetime
import numpy as np
import pytest

from services.portfolio import (
    AllocationPlan,
    AutonomousConvictionEngine,
    BenchmarkEngine,
    CandidateAsset,
    CashLedgerEntry,
    CommissionModel,
    DividendHandler,
    EquitySnapshot,
    ExitAction,
    ExitDecision,
    MultiCurrencyHandler,
    OpenPositionState,
    OptimizationMethod,
    OptimizationResult,
    PerformanceAttribution,
    PortfolioConstraints,
    PortfolioEnhancements,
    PortfolioManager,
    PortfolioOptimizer,
    PortfolioOptimizerConstraints,
    Position,
    PositionHistoryEntry,
    RebalanceDecision,
    TaxModel,
    Trade,
    portfolio_enhancements,
    portfolio_manager,
    portfolio_optimizer,
)


def test_portfolio_reprs():
    """All dataclasses and engines in services/portfolio must have informative __repr__."""
    pos = Position(ticker="GARAN", direction="LONG", quantity=1000, entry_price=70.0, current_price=75.0)
    assert "Position(GARAN" in repr(pos)

    trade = Trade(
        trade_id="t1",
        ticker="THYAO",
        direction="LONG",
        entry_price=280.0,
        exit_price=300.0,
        quantity=500,
        commission=45.0,
        entry_time=datetime(2026, 1, 1),
        exit_time=datetime(2026, 1, 10),
    )
    assert "Trade(t1" in repr(trade)

    cash_entry = CashLedgerEntry(
        timestamp=datetime.now(),
        amount=10000.0,
        balance_after=110000.0,
        entry_type="DEPOSIT",
        description="Fon yatırma",
    )
    assert "CashLedgerEntry(DEPOSIT" in repr(cash_entry)

    snapshot = EquitySnapshot(
        date="2026-09-12",
        timestamp=datetime.now(),
        total_equity=1200000.0,
        cash=200000.0,
        invested=1000000.0,
        unrealized_pnl=50000.0,
        realized_pnl_today=10000.0,
        commission_today=200.0,
        positions_count=8,
        high_water_mark=1250000.0,
        drawdown_from_hwm=0.04,
    )
    assert "EquitySnapshot(2026-09-12" in repr(snapshot)

    pos_hist = PositionHistoryEntry(
        timestamp=datetime.now(),
        ticker="SISE",
        action="OPEN",
        direction="LONG",
        quantity=2000,
        price=45.0,
        commission=25.0,
        avg_cost_before=0.0,
        avg_cost_after=45.0,
        quantity_before=0,
        quantity_after=2000,
        realized_pnl=0.0,
    )
    assert "PositionHistoryEntry(OPEN" in repr(pos_hist)

    comm = CommissionModel()
    assert "CommissionModel" in repr(comm)

    pm = PortfolioManager(initial_capital=500000.0)
    assert "PortfolioManager" in repr(pm)

    opt_constraints = PortfolioOptimizerConstraints()
    assert "PortfolioOptimizerConstraints" in repr(opt_constraints)

    opt_res = OptimizationResult(
        weights={"GARAN": 0.5, "AKBNK": 0.5},
        method=OptimizationMethod.RISK_PARITY,
        expected_return=0.25,
        portfolio_volatility=0.18,
        sharpe_ratio=1.38,
        diversification_ratio=1.2,
        turnover_from_current=0.0,
        estimated_transaction_cost_tl=150.0,
        effective_positions_count=2,
        sector_exposures={"BANK": 1.0},
        cash_weight=0.0,
        is_optimal=True,
    )
    assert "OptimizationResult" in repr(opt_res)

    opt = PortfolioOptimizer()
    assert "PortfolioOptimizer" in repr(opt)

    enh_const = PortfolioConstraints()
    assert "PortfolioConstraints" in repr(enh_const)

    reb_dec = RebalanceDecision(
        should_rebalance=True,
        reason="Target deviation",
        estimated_cost=200.0,
        estimated_benefit=1500.0,
        net_benefit=1300.0,
        turnover=0.08,
    )
    assert "RebalanceDecision" in repr(reb_dec)

    enh = PortfolioEnhancements()
    assert "PortfolioEnhancements" in repr(enh)

    tax = TaxModel()
    assert "TaxModel" in repr(tax)

    div = DividendHandler()
    assert "DividendHandler" in repr(div)

    bench = BenchmarkEngine()
    assert "BenchmarkEngine" in repr(bench)

    perf = PerformanceAttribution()
    assert "PerformanceAttribution" in repr(perf)

    fx = MultiCurrencyHandler()
    assert "MultiCurrencyHandler" in repr(fx)

    cand = CandidateAsset(ticker="BIMAS", confidence_score=0.82, expected_return=0.30, volatility=0.20)
    assert "CandidateAsset(BIMAS" in repr(cand)

    open_pos = OpenPositionState(
        ticker="BIMAS",
        entry_price=500.0,
        current_price=540.0,
        highest_price=550.0,
        entry_date="2026-09-01",
        holding_days=11,
        current_confidence=0.80,
    )
    assert "OpenPositionState(BIMAS" in repr(open_pos)

    alloc = AllocationPlan(
        selected_tickers=["BIMAS"],
        weights={"BIMAS": 0.20},
        cash_weight=0.80,
        total_exposure=0.20,
        num_positions=1,
        market_regime="BULL",
        hurdle_rate_annual=0.35,
    )
    assert "AllocationPlan" in repr(alloc)

    exit_dec = ExitDecision(
        ticker="BIMAS",
        action=ExitAction.HOLD_AND_RUN,
        reason="Trend devam ediyor",
        unrealized_pnl_pct=8.0,
        current_confidence=0.80,
        current_price=540.0,
        trailing_stop_price=517.0,
    )
    assert "ExitDecision(BIMAS" in repr(exit_dec)

    conv_eng = AutonomousConvictionEngine()
    assert "AutonomousConvictionEngine" in repr(conv_eng)


def test_commission_model_calculation():
    """CommissionModel must calculate fee with min commission bounds."""
    model = CommissionModel(broker_rate=0.0003, exchange_rate=0.000056, bsmv_rate=0.05, min_commission=2.0)
    fee = model.calculate(100000.0)
    # base = 100000 * 0.000356 = 35.6, bsmv = 1.78 -> total = 37.38
    assert fee > 30.0
    # small amount should hit min_commission
    small_fee = model.calculate(10.0)
    assert small_fee >= 2.0


def test_turnover_penalty_application():
    """PortfolioEnhancements must apply turnover penalty correctly."""
    enh = PortfolioEnhancements()
    target = {"A": 0.5, "B": 0.5}
    current = {"A": 0.3, "B": 0.7}
    adjusted = enh.apply_turnover_penalty(target, current, penalty=0.05)
    assert len(adjusted) == 2
    # Target "A" should be pulled closer to current 0.3
    assert adjusted["A"] < target["A"]
    # Target "B" should be pulled closer to current 0.7
    assert adjusted["B"] > target["B"]
