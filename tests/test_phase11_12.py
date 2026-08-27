"""
ALPHA BIST — FAZ 11-12 Test Suite

Position Sizing, Reconciliation, Backtest Engine, Walk-Forward testleri.
"""

import sys


def test_position_sizing():
    """Position Sizing testleri."""
    from services.risk.position_sizing import position_sizer

    passed = 0
    failed = 0

    # 1. Basic position sizing
    result = position_sizer.calculate(
        ticker="THYAO", entry_price=305.25, stop_price=290.0,
        portfolio_value=100000, max_position_pct=10, max_risk_per_trade_pct=2.0,
        confidence=0.8, volatility=0.25,
    )
    assert result.shares > 0
    assert result.position_value > 0
    assert result.position_pct <= 10
    assert result.risk_pct <= 2.0
    assert result.method == "RISK_BUDGET"
    passed += 1
    print(f"  ✓ Basic: {result.shares} shares, {result.position_pct:.1f}% portfolio, {result.risk_pct:.1f}% risk")

    # 2. Max position limit
    result2 = position_sizer.calculate(
        ticker="TEST", entry_price=10, stop_price=9.5,
        portfolio_value=100000, max_position_pct=5, max_risk_per_trade_pct=10.0,
        confidence=1.0, volatility=0.25,
    )
    assert result2.position_pct <= 5.0
    passed += 1
    print(f"  ✓ Max position limit: {result2.position_pct:.1f}% (limit 5%)")

    # 3. Zero stop distance
    result3 = position_sizer.calculate(
        ticker="TEST", entry_price=100, stop_price=100,
        portfolio_value=100000,
    )
    assert result3.shares == 0
    assert result3.method == "INVALID"
    passed += 1
    print(f"  ✓ Zero stop: {result3.method}")

    # 4. High correlation adjustment
    result4 = position_sizer.calculate(
        ticker="TEST", entry_price=100, stop_price=95,
        portfolio_value=100000, correlation_to_portfolio=0.9,
    )
    result4b = position_sizer.calculate(
        ticker="TEST", entry_price=100, stop_price=95,
        portfolio_value=100000, correlation_to_portfolio=0.3,
    )
    assert result4.shares <= result4b.shares
    passed += 1
    print(f"  ✓ Correlation adjustment: high={result4.shares}, low={result4b.shares}")

    return passed, failed


def test_reconciliation():
    """Reconciliation Engine testleri."""
    from services.risk.reconciliation import reconciliation_engine

    passed = 0
    failed = 0

    # 1. Consistent portfolio
    result = reconciliation_engine.reconcile(
        portfolio_id=1,
        ledger_cash=50000, ledger_positions_value=50000, ledger_equity=100000,
        db_cash=50000, db_positions_value=50000, db_equity=100000,
    )
    assert result.is_consistent
    assert len(result.errors) == 0
    passed += 1
    print(f"  ✓ Consistent: {result.is_consistent}")

    # 2. Cash mismatch
    result2 = reconciliation_engine.reconcile(
        portfolio_id=1,
        ledger_cash=50000, ledger_positions_value=50000, ledger_equity=100000,
        db_cash=49000, db_positions_value=50000, db_equity=100000,
    )
    assert not result2.is_consistent
    assert any("Cash" in e for e in result2.errors)
    passed += 1
    print(f"  ✓ Cash mismatch detected: {result2.cash_diff}")

    # 3. Equity equation mismatch
    result3 = reconciliation_engine.reconcile(
        portfolio_id=1,
        ledger_cash=50000, ledger_positions_value=50000, ledger_equity=100000,
        db_cash=50000, db_positions_value=50000, db_equity=99000,
    )
    assert not result3.is_consistent
    passed += 1
    print("  ✓ Equation mismatch detected")

    return passed, failed


def test_backtest_engine():
    """Backtest Engine testleri."""
    from services.backtest.engine import backtest_engine

    passed = 0
    failed = 0

    # 1. Basic backtest
    signals = [
        {"date": "2024-01-15", "ticker": "THYAO", "action": "BUY", "price": 300, "confidence": 0.8},
        {"date": "2024-02-15", "ticker": "THYAO", "action": "SELL", "price": 320, "confidence": 0.5},
        {"date": "2024-03-15", "ticker": "ASELS", "action": "BUY", "price": 40, "confidence": 0.7},
        {"date": "2024-04-15", "ticker": "ASELS", "action": "SELL", "price": 38, "confidence": 0.3},
    ]
    result = backtest_engine.run_backtest(
        strategy_name="Test", signals=signals, price_data={}, initial_capital=100000,
    )
    assert result.initial_capital == 100000
    assert result.final_capital > 0
    assert len(result.trades) == 2
    assert result.metrics.total_trades == 2
    passed += 1
    print(f"  ✓ Basic backtest: {len(result.trades)} trades, return={result.metrics.total_return_pct:.2f}%")

    # 2. Win rate
    assert result.metrics.win_rate > 0
    passed += 1
    print(f"  ✓ Win rate: {result.metrics.win_rate:.2%}")

    # 3. Equity curve
    assert len(result.equity_curve) > 0
    assert result.equity_curve[0] == 100000
    passed += 1
    print(f"  ✓ Equity curve: {len(result.equity_curve)} points")

    # 4. Drawdown curve
    assert len(result.drawdown_curve) > 0
    assert max(result.drawdown_curve) >= 0
    passed += 1
    print(f"  ✓ Max drawdown: {result.metrics.max_drawdown_pct:.2f}%")

    # 5. Profit factor
    assert result.metrics.profit_factor > 0
    passed += 1
    print(f"  ✓ Profit factor: {result.metrics.profit_factor:.2f}")

    return passed, failed


def test_walk_forward():
    """Walk-Forward Validation testleri."""
    from services.backtest.walk_forward import walk_forward_engine

    passed = 0
    failed = 0

    # Generate test signals
    signals = []
    for i in range(500):
        signals.append({
            "date": f"2024-{(i//30)+1:02d}-{(i%30)+1:02d}",
            "ticker": "TEST",
            "action": "BUY" if i % 3 == 0 else "SELL",
            "price": 100 + i * 0.1,
            "pnl_pct": 1.0 if i % 3 == 0 else -0.5,
            "pnl": 100 if i % 3 == 0 else -50,
        })

    result = walk_forward_engine.run_walk_forward(
        signals=signals, price_data={}, train_days=100, test_days=30, step_days=15,
    )
    assert result.total_folds > 0
    passed += 1
    print(f"  ✓ Walk-forward: {result.total_folds} folds")

    assert isinstance(result.avg_test_return, float)
    passed += 1
    print(f"  ✓ Avg test return: {result.avg_test_return:.2f}%")

    assert 0 <= result.stability_score <= 1
    passed += 1
    print(f"  ✓ Stability: {result.stability_score:.2f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 11-12 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Position Sizing", test_position_sizing),
        ("Reconciliation", test_reconciliation),
        ("Backtest Engine", test_backtest_engine),
        ("Walk-Forward", test_walk_forward),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
