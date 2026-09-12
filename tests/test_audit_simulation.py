"""
ALPHA BIST — Simulation Service Kapsamlı Denetim ve Doğrulama Testleri
"""

import numpy as np
import pytest

from services.simulation.auction_engine import (
    AuctionOrder,
    AuctionResult,
    CallAuctionEngine,
    call_auction_engine,
)
from services.simulation.enhanced_execution import (
    EnhancedExecutionSimulator,
    LiquidityProfile,
    MarketImpactResult,
    RegimeAwareSlippage,
    SquareRootMarketImpact,
    enhanced_execution,
)
from services.simulation.enhanced_stress_test import (
    EnhancedStressTestEngine,
    StressResult,
    StressScenario,
    enhanced_stress_test,
)
from services.simulation.execution_simulator import (
    ExecutionSimulator,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    execution_simulator,
)
from services.simulation.main import SimulationEngine
from services.simulation.monte_carlo_enhanced import (
    CorrelatedMonteCarlo,
    JumpDiffusionMonteCarlo,
    MonteCarloResult,
    RegimeConditionedMonteCarlo,
    correlated_mc,
    jump_diffusion_mc,
    regime_mc,
)
from services.simulation.order_book import (
    OrderBookLevel,
    OrderBookSimulator,
    OrderBookSnapshot,
    order_book_sim,
)


def test_call_auction_engine_equilibrium_and_repr():
    """CallAuctionEngine denge fiyatı, eşleşme ve __repr__ doğrulaması."""
    engine = CallAuctionEngine()
    assert "CallAuctionEngine" in repr(engine)

    orders = [
        AuctionOrder("o1", "THYAO", "BUY", 1000, 305.0, False, 1.0),
        AuctionOrder("o2", "THYAO", "BUY", 500, 300.0, False, 2.0),
        AuctionOrder("o3", "THYAO", "SELL", 800, 295.0, False, 1.5),
        AuctionOrder("o4", "THYAO", "SELL", 600, 310.0, False, 2.5),
    ]
    assert "AuctionOrder" in repr(orders[0])

    result = engine.calculate_equilibrium(orders, reference_price=300.0)
    assert isinstance(result, AuctionResult)
    assert "AuctionResult" in repr(result)
    assert result.matched_volume > 0
    assert result.equilibrium_price > 0
    assert len(result.matched_trades) > 0
    # Out of money or remaining orders should be in unfilled_orders
    assert len(result.unfilled_orders) > 0


def test_execution_simulator_and_guards():
    """ExecutionSimulator sipariş yürütme, slippage, komisyon ve sınır kontrolleri."""
    sim = ExecutionSimulator()
    assert "ExecutionSimulator" in repr(sim)

    # Geçerli market alım emri
    order = Order(
        order_id="ord-01",
        portfolio_id=1,
        instrument_id=101,
        ticker="GARAN",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=500,
    )
    assert "Order" in repr(order)

    executed = sim.execute_order(order, market_price=100.0, avg_volume=500000)
    assert executed.status == OrderStatus.FILLED
    assert executed.filled_quantity == 500
    assert executed.avg_fill_price >= 100.0  # Alışta slippage yukarı
    assert executed.commission > 0.0

    fill = sim.create_fill(executed)
    assert isinstance(fill, Fill)
    assert "Fill" in repr(fill)
    assert fill.quantity == 500

    # Negatif miktar guard kontrolü
    bad_qty_order = Order(
        order_id="ord-bad",
        portfolio_id=1,
        instrument_id=101,
        ticker="GARAN",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=-10,
    )
    rejected_qty = sim.execute_order(bad_qty_order, market_price=100.0)
    assert rejected_qty.status == OrderStatus.REJECTED

    # Negatif fiyat guard kontrolü
    bad_price_order = Order(
        order_id="ord-bad-p",
        portfolio_id=1,
        instrument_id=101,
        ticker="GARAN",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
    )
    failed_price = sim.execute_order(bad_price_order, market_price=-50.0)
    assert failed_price.status == OrderStatus.FAILED


def test_order_book_simulator():
    """OrderBook ve OrderBookSnapshot metotları ve hesaplama doğrulaması."""
    ob_sim = OrderBookSimulator(depth_levels=5)
    assert "OrderBookSimulator" in repr(ob_sim)

    snapshot = ob_sim.generate_book(mid_price=100.0, avg_volume=200000, volatility=0.20)
    assert isinstance(snapshot, OrderBookSnapshot)
    assert "OrderBookSnapshot" in repr(snapshot)
    assert len(snapshot.bids) == 5
    assert len(snapshot.asks) == 5
    assert "OrderBookLevel" in repr(snapshot.bids[0])

    assert snapshot.best_bid > 0
    assert snapshot.best_ask > 0
    assert snapshot.best_ask >= snapshot.best_bid
    assert snapshot.mid_price > 0
    assert snapshot.spread >= 0
    assert snapshot.spread_pct >= 0
    assert snapshot.total_depth > 0
    assert -1.0 <= snapshot.imbalance <= 1.0

    # Market emri simülasyonu
    fill_res = ob_sim.simulate_market_order(snapshot, side="BUY", quantity=250)
    assert fill_res["fill_quantity"] == 250
    assert fill_res["avg_price"] >= snapshot.best_ask
    assert fill_res["cost"] > 0

    score_res = ob_sim.calculate_liquidity_score(snapshot)
    assert 0 <= score_res["liquidity_score"] <= 100


def test_enhanced_execution_simulator():
    """SquareRootMarketImpact, RegimeAwareSlippage ve EnhancedExecutionSimulator."""
    impact_model = SquareRootMarketImpact(eta=0.3)
    assert "SquareRootMarketImpact" in repr(impact_model)
    impact = impact_model.calculate(order_value=50000, adv_value=10000000, volatility=0.25)
    assert 0.0 < impact <= 0.05

    regime_model = RegimeAwareSlippage()
    assert "RegimeAwareSlippage" in repr(regime_model)
    adjusted_slip = regime_model.adjust_slippage(base_slippage=0.005, regime="PANIC")
    assert adjusted_slip > 0.005

    exec_sim = EnhancedExecutionSimulator()
    assert "EnhancedExecutionSimulator" in repr(exec_sim)

    liq = LiquidityProfile(avg_daily_volume=2000000, spread_pct=0.15)
    assert "LiquidityProfile" in repr(liq)

    order = Order(
        order_id="ord-enh",
        portfolio_id=1,
        instrument_id=102,
        ticker="AKBNK",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
    )

    res = exec_sim.execute_order(order, market_price=50.0, liquidity=liq, regime="BULL")
    assert res["fill_quantity"] == 1000
    assert res["fill_price"] >= 50.0
    assert res["commission"] >= 1.0


def test_enhanced_stress_test_engine():
    """EnhancedStressTestEngine senaryo çalıştırma ve breaking point analizi."""
    engine = EnhancedStressTestEngine()
    assert "EnhancedStressTestEngine" in repr(engine)
    assert len(engine.scenarios) >= 8
    assert "StressScenario" in repr(engine.scenarios[0])

    positions = [
        {"ticker": "THYAO", "value": 150000, "sector": "AVIATION", "beta": 1.2, "usd_sensitivity": 0.6},
        {"ticker": "KCHOL", "value": 200000, "sector": "HOLDING", "beta": 0.9, "usd_sensitivity": 0.4},
        {"ticker": "EREGL", "value": 150000, "sector": "METAL", "beta": 0.8, "usd_sensitivity": 0.7},
    ]

    results = engine.run_stress_test(portfolio_value=500000, positions=positions)
    assert len(results) == len(engine.scenarios)
    assert isinstance(results[0], StressResult)
    assert "StressResult" in repr(results[0])
    assert results[0].portfolio_impact_pct != 0

    breaking = engine.find_breaking_point(portfolio_value=500000, positions=positions, max_loss_pct=15.0)
    assert "breaking_scenarios" in breaking
    assert "is_robust" in breaking

    summary = engine.get_scenario_summary(results)
    assert summary["total_scenarios"] == len(results)

    # Özel senaryo ekleme
    engine.add_custom_scenario(
        name="Geopolitical Conflict",
        market_shock=-0.18,
        sector_impacts={"AVIATION": -0.25, "DEFENSE": 0.15},
    )
    assert len(engine.scenarios) == len(results) + 1


def test_monte_carlo_enhanced():
    """Jump-diffusion, Correlated ve Regime-conditioned Monte Carlo doğrulaması."""
    jd = JumpDiffusionMonteCarlo()
    assert "JumpDiffusionMonteCarlo" in repr(jd)
    jd_res = jd.simulate(
        current_price=100.0,
        daily_return=0.001,
        daily_vol=0.02,
        num_sims=500,
        horizon=10,
        seed=42,
    )
    assert isinstance(jd_res, MonteCarloResult)
    assert "MonteCarloResult" in repr(jd_res)
    assert jd_res.expected_return_pct is not None
    assert jd_res.var_95 is not None

    corr_mc = CorrelatedMonteCarlo()
    assert "CorrelatedMonteCarlo" in repr(corr_mc)
    prices = np.array([100.0, 50.0])
    # 2 assets, 50 days of synthetic returns
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.02, (50, 2))
    weights = np.array([0.6, 0.4])

    port_res = corr_mc.simulate_portfolio(
        tickers=["AAA", "BBB"],
        prices=prices,
        returns_matrix=returns,
        weights=weights,
        num_sims=300,
        horizon=5,
        seed=42,
    )
    assert "portfolio" in port_res
    assert "expected_return_pct" in port_res["portfolio"]

    reg_mc = RegimeConditionedMonteCarlo()
    assert "RegimeConditionedMonteCarlo" in repr(reg_mc)
    reg_res = reg_mc.simulate(
        current_price=100.0,
        daily_return=0.001,
        daily_vol=0.02,
        regime="BULL",
        num_sims=300,
        horizon=5,
        seed=42,
    )
    assert "Regime-Conditioned" in reg_res.model


def test_simulation_engine_repr():
    """SimulationEngine başlatma ve temsil testi."""
    engine = SimulationEngine()
    assert "SimulationEngine(running=False)" in repr(engine)
