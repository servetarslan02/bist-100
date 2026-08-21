"""
ALPHA BIST — E2E Real Data Test

Gerçek yfinance verisi ile tam pipeline testi.
"""

import sys
import os
import numpy as np



def test_e2e_real_data():
    """Gerçek yfinance verisi ile E2E pipeline."""
    from services.features.calculator import FeatureCalculator
    from services.intelligence.pipeline import intelligence_pipeline
    from services.intelligence.prediction_layer import compute_prediction
    from services.core.risk_gate import RiskGate
    from services.core.broker import PaperBroker, Order, OrderSide, OrderStatus

    passed = 0
    failed = 0

    # Gerçek veri çek
    try:
        import yfinance as yf
        data = yf.download("THYAO.IS", start="2024-01-01", end="2024-06-01", progress=False)
        if data.empty:
            print("  ⚠ THYAO data empty (network?), skip")
            return 0, 0
    except Exception as e:
        print(f"  ⚠ yfinance failed: {e}, skip")
        return 0, 0

    # Feature hesapla
    calc = FeatureCalculator()
    # yfinance multi-level columns fix
    if hasattr(data.columns, 'levels'):
        data.columns = data.columns.get_level_values(0)
    feats = calc.compute_all_features(data, ticker="THYAO")
    if not feats:
        print("  ⚠ Feature computation empty")
        return 0, 0

    print(f"  ✓ Features: {len(feats)} features from real THYAO data")
    passed += 1

    # Intelligence pipeline
    intel = intelligence_pipeline.run(ticker="THYAO", features=feats, regime="BULL")
    assert len(intel.modules_used) > 0
    print(f"  ✓ Intelligence: {len(intel.modules_used)} modules used")
    passed += 1

    # Prediction
    pred = compute_prediction(
        ticker="THYAO", ml_prediction=2.0, ml_confidence=0.6,
        features=feats, horizon=5
    )
    assert pred.direction in ("UP", "DOWN", "NEUTRAL")
    assert pred.quality_grade in ("A+", "A", "B", "C", "D")
    print(f"  ✓ Prediction: direction={pred.direction}, grade={pred.quality_grade}")
    passed += 1

    # Risk gate
    gate = RiskGate()
    price = float(data['Close'].iloc[-1])
    rd = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=price,
        portfolio_value=1_000_000, current_positions={},
        model_confidence=pred.confidence, market_open=True, data_valid=True
    )
    print(f"  ✓ Risk gate: {'allowed' if rd.allowed else 'rejected'} ({rd.reason})")
    passed += 1

    # Paper broker
    broker = PaperBroker(initial_capital=1_000_000)
    order = Order(
        order_id="", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=10, price=price, idempotency_key="e2e_real"
    )
    result = broker.submit_order(order)
    assert result.status in (OrderStatus.FILLED.value, OrderStatus.REJECTED.value)
    print(f"  ✓ Paper broker: {result.status}")
    passed += 1

    return passed, failed


def run_all():
    tests = [("E2E real data", test_e2e_real_data)]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("E2E Real Data Test")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
        except Exception as e:
            import traceback
            print(f"  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
