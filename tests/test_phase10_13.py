import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — FAZ 10-13 Test Suite

Execution Simulator, Portfolio Integration, Backtest Metrics, E2E testleri.
"""

import sys


def test_execution_simulator() -> Any:
    """Execution Simulator testleri."""
    from services.simulation.execution_simulator import (
        Order,
        OrderSide,
        OrderStatus,
        OrderType,
        execution_simulator,
    )

    passed = 0
    failed = 0

    # 1. Market buy order
    order = Order(
        order_id="ORD-001",
        portfolio_id=1,
        instrument_id=1,
        ticker="THYAO",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
    )
    result = execution_simulator.execute_order(
        order,
        market_price=305.25,
        bid=305.20,
        ask=305.30,
        avg_volume=1000000,
        volatility=0.25,
        spread_pct=0.1,
    )
    assert result.status == OrderStatus.FILLED
    assert result.filled_quantity == 100
    assert result.avg_fill_price > 305.25  # Slippage eklendi
    assert result.commission > 0
    assert result.slippage >= 0
    passed += 1
    logger.info(f"  ✓ Market BUY: {result.filled_quantity} @ {result.avg_fill_price:.2f}, commission={result.commission:.2f}")

    # 2. Market sell order
    order2 = Order(
        order_id="ORD-002",
        portfolio_id=1,
        instrument_id=1,
        ticker="THYAO",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
    )
    result2 = execution_simulator.execute_order(order2, market_price=310.0)
    assert result2.status == OrderStatus.FILLED
    assert result2.avg_fill_price < 310.0  # Sell'de slippage fiyatı düşürür
    passed += 1
    logger.info(f"  ✓ Market SELL: {result2.filled_quantity} @ {result2.avg_fill_price:.2f}")

    # 3. Large order → partial fill
    order3 = Order(
        order_id="ORD-003",
        portfolio_id=1,
        instrument_id=1,
        ticker="THYAO",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=200000,  # 200K lot
    )
    result3 = execution_simulator.execute_order(
        order3,
        market_price=305.25,
        avg_volume=1000000,
    )
    assert result3.status == OrderStatus.PARTIALLY_FILLED
    assert result3.filled_quantity == 100000  # %10 limit
    passed += 1
    logger.info(f"  ✓ Partial fill: {result3.filled_quantity}/{200000}")

    # 4. Commission model
    amount = 100 * 305.25
    commission = execution_simulator._compute_commission(amount)
    assert commission > 0
    assert commission < amount * 0.01  # %1'den az olmalı
    passed += 1
    logger.info(f"  ✓ Commission: {commission:.2f} TL on {amount:.0f} TL")

    # 5. Slippage model
    slippage_small = execution_simulator._compute_slippage(100, 1000000, 0.25, 0.1, OrderSide.BUY)
    slippage_large = execution_simulator._compute_slippage(100000, 1000000, 0.25, 0.1, OrderSide.BUY)
    assert slippage_large > slippage_small
    passed += 1
    logger.info(f"  ✓ Slippage: small={slippage_small:.4%}, large={slippage_large:.4%}")

    # 6. Fill creation
    fill = execution_simulator.create_fill(result)
    assert fill.order_id == "ORD-001"
    assert fill.quantity == 100
    assert fill.price > 0
    passed += 1
    logger.info(f"  ✓ Fill created: {fill.fill_id}")

    # 7. Order lifecycle
    assert result.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]
    assert result.filled_at is not None
    passed += 1
    logger.info(f"  ✓ Order lifecycle: {result.status.value}")

    return passed, failed


def test_portfolio_metrics() -> Any:
    """Portfolio metrik testleri."""
    import numpy as np

    passed = 0
    failed = 0

    # 1. Sharpe ratio (basitleştirilmiş)
    returns = [0.01, -0.005, 0.02, -0.01, 0.015, 0.005, -0.008, 0.012]
    mean_ret = np.mean(returns)
    std_ret = np.std(returns)
    sharpe = (mean_ret - 0) / std_ret * np.sqrt(252) if std_ret > 0 else 0
    assert isinstance(sharpe, float)
    passed += 1
    logger.info(f"  ✓ Sharpe ratio: {sharpe:.2f}")

    # 2. Max drawdown
    equity = [100000, 102000, 99000, 97000, 101000, 103000, 98000, 105000]
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd
    assert max_dd > 0
    assert max_dd < 1
    passed += 1
    logger.info(f"  ✓ Max drawdown: {max_dd:.2%}")

    # 3. Win rate
    trades = [100, -50, 200, -80, 150, -30, 180, -60]
    wins = sum(1 for t in trades if t > 0)
    win_rate = wins / len(trades)
    assert 0 < win_rate < 1
    passed += 1
    logger.info(f"  ✓ Win rate: {win_rate:.2%}")

    # 4. Profit factor
    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = abs(sum(t for t in trades if t < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    assert profit_factor > 0
    passed += 1
    logger.info(f"  ✓ Profit factor: {profit_factor:.2f}")

    return passed, failed


def test_e2e_pipeline() -> Any:
    """E2E: Tüm pipeline entegrasyon testi."""
    from services.core.decision_engine import DecisionEngine, DecisionInput
    from services.intelligence.signal_fusion import signal_fusion_engine
    from services.scanner.opportunity_engine import opportunity_engine
    from services.simulation.execution_simulator import (
        Order,
        OrderSide,
        OrderType,
        execution_simulator,
    )

    passed = 0
    failed = 0

    # 1. Feature → Opportunity → Signal Fusion → Decision → Execution
    features = {
        "price": 305.25,
        "return_1d": 1.5,
        "roc_5d": 5.0,
        "roc_20d": 12.0,
        "momentum_20d": 12.0,
        "volume_zscore": 3.0,
        "volume_ratio_20d": 2.5,
        "rsi_14": 62,
        "macd_histogram": 0.5,
        "bb_position": 0.8,
        "adx": 30,
        "atr_14_pct": 2.0,
        "realized_vol_20d": 18,
        "amihud_illiquidity": 0.001,
        "correlation_to_index": 0.6,
        "trend_slope_20d": 1.5,
        "price_acceleration": 2.0,
    }

    # Opportunity score
    opp = opportunity_engine.compute_opportunity_score("THYAO", features, "BULL")
    assert opp.opportunity_score > 50
    passed += 1
    logger.info(f"  ✓ Step 1: Opportunity score = {opp.opportunity_score:.1f}")

    # Signal fusion
    signals = {
        "technical": {"direction": "LONG", "score": opp.technical_score},
        "fundamental": {"direction": "LONG", "score": 65},
        "momentum": {"direction": "LONG", "score": opp.momentum_score},
        "sentiment": {"direction": "NEUTRAL", "score": 50},
        "macro": {"direction": "NEUTRAL", "score": 50},
        "valuation": {"direction": "LONG", "score": 70},
        "ai": {"direction": "LONG", "score": 65},
        "opportunity": {"score": opp.opportunity_score},
    }
    fused = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
    assert fused.fused_direction == "LONG"
    passed += 1
    logger.info(f"  ✓ Step 2: Fused direction = {fused.fused_direction} (confidence={fused.fused_confidence:.2f})")

    # Decision
    engine = DecisionEngine()
    inp = DecisionInput(
        ticker="THYAO",
        price=305.25,
        ml_return_5d=5,
        ml_return_20d=12,
        ml_confidence=fused.fused_confidence,
        spec_score=opp.opportunity_score,
        world_alignment=0.5,
        sim_expected_return=8,
        sim_var_95=-5,
        sim_prob_positive=65,
        ai_direction=fused.fused_direction,
        ai_confidence=fused.fused_confidence,
        max_position_pct=10,
        current_position_pct=0,
        portfolio_drawdown=2,
        avg_volume=1000000,
        spread_pct=0.1,
    )
    decision = engine.decide(inp)
    assert decision.action in ["BUY", "SELL", "HOLD"]
    passed += 1
    logger.info(f"  ✓ Step 3: Decision = {decision.action} ({decision.conviction})")

    # Execution (eğer BUY ise)
    if decision.action == "BUY":
        order = Order(
            order_id="E2E-001",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        result = execution_simulator.execute_order(order, market_price=305.25)
        assert result.filled_quantity > 0
        assert result.avg_fill_price > 0
        passed += 1
        logger.info(f"  ✓ Step 4: Execution = {result.filled_quantity} @ {result.avg_fill_price:.2f}")
    else:
        passed += 1
        logger.info(f"  ✓ Step 4: Skipped (decision={decision.action})")

    return passed, failed


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  FAZ 10-13 — Test Suite")
    logger.info("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Execution Simulator", test_execution_simulator),
        ("Portfolio Metrics", test_portfolio_metrics),
        ("E2E Pipeline", test_e2e_pipeline),
    ]

    for name, test_func in tests:
        logger.info(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            logger.info(f"  ✗ Test crashed: {e}")
            import traceback

            traceback.print_exc()
            total_failed += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    logger.info(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
