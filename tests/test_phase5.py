"""
ALPHA BIST — FAZ 5 Test Suite

Monte Carlo Engine, Probability Engine testleri.
"""

import sys


def test_monte_carlo():
    """Monte Carlo Engine testleri."""
    from services.intelligence.monte_carlo import monte_carlo_engine

    passed = 0
    failed = 0

    # 1. Basic simulation
    result = monte_carlo_engine.simulate_price_paths(
        ticker="THYAO",
        current_price=305.25,
        expected_return_annual=0.15,
        volatility_annual=0.25,
        horizon_days=20,
        num_simulations=10000,
        seed=42,
    )
    assert result.current_price == 305.25
    assert result.horizon_days == 20
    assert result.num_simulations == 10000
    assert result.p10 < result.p25 < result.p50 < result.p75 < result.p90
    assert 0 < result.prob_positive < 1
    passed += 1
    print(f"  ✓ Basic simulation (P50={result.p50:.2f}, P(+%)={result.prob_positive:.2%})")

    # 2. Percentile ordering
    assert result.p10 < result.p50 < result.p90
    assert result.var_95 < 0  # VaR negatif (kayıp)
    assert result.cvar_95 < result.var_95  # CVaR daha kötü
    passed += 1
    print(f"  ✓ Percentile ordering (P10={result.p10:.2f}, P90={result.p90:.2f})")

    # 3. Probability consistency
    assert result.prob_minus_10pct <= result.prob_minus_5pct  # %10 kayıp < %5 kayıp
    assert result.prob_plus_10pct <= result.prob_plus_5pct    # %10 kazanç < %5 kazanç
    passed += 1
    print("  ✓ Probability consistency")

    # 4. High volatility → wider distribution
    result_high_vol = monte_carlo_engine.simulate_price_paths(
        ticker="TEST", current_price=100,
        expected_return_annual=0.15, volatility_annual=0.50,
        horizon_days=20, num_simulations=10000, seed=42,
    )
    spread_high = result_high_vol.p90 - result_high_vol.p10
    spread_low = result.p90 - result.p10
    # Normalize by price
    assert (spread_high / 100) > (spread_low / 305.25)
    passed += 1
    print("  ✓ High volatility → wider spread")

    # 5. Sample paths
    assert result.sample_paths is not None
    assert len(result.sample_paths) <= 100
    passed += 1
    print(f"  ✓ Sample paths ({len(result.sample_paths)} paths)")

    # 6. Dynamic scenario count
    count = monte_carlo_engine.compute_dynamic_scenario_count(
        volatility=0.25, model_uncertainty=0.3,
        portfolio_size=100000, compute_budget_ms=1000,
    )
    assert count >= 1000
    passed += 1
    print(f"  ✓ Dynamic scenario count: {count}")

    return passed, failed


def test_probability_engine():
    """Probability Engine testleri."""
    from services.intelligence.probability import (
        PredictionOutcome,
        probability_engine,
    )

    passed = 0
    failed = 0

    # 1. Return distribution
    import numpy as np
    np.random.seed(42)
    returns = list(np.random.normal(0.05, 2.0, 252))  # 1 yıl günlük getiri

    dist = probability_engine.compute_return_distribution("THYAO", returns, horizon_days=20)
    assert dist.ticker == "THYAO"
    assert dist.std_return > 0
    assert dist.percentiles[10] < dist.percentiles[50] < dist.percentiles[90]
    passed += 1
    print(f"  ✓ Return distribution (mean={dist.mean_return:.2f}, std={dist.std_return:.2f})")

    # 2. Hit rate
    predictions = [
        PredictionOutcome(0.8, True, "A", "2026-01-01", 5),
        PredictionOutcome(0.7, True, "B", "2026-01-01", 5),
        PredictionOutcome(0.3, False, "C", "2026-01-01", 5),
        PredictionOutcome(0.4, False, "D", "2026-01-01", 5),
        PredictionOutcome(0.6, True, "E", "2026-01-01", 5),
    ]
    hit_rate = probability_engine.compute_hit_rate(predictions)
    assert hit_rate == 1.0  # Tüm tahminler doğru
    passed += 1
    print(f"  ✓ Hit rate: {hit_rate:.2%}")

    # 3. Hit rate with errors
    predictions_wrong = [
        PredictionOutcome(0.8, False, "A", "2026-01-01", 5),  # Yanlış
        PredictionOutcome(0.7, True, "B", "2026-01-01", 5),   # Doğru
        PredictionOutcome(0.3, True, "C", "2026-01-01", 5),   # Yanlış
    ]
    hit_rate2 = probability_engine.compute_hit_rate(predictions_wrong)
    assert hit_rate2 < 1.0
    passed += 1
    print(f"  ✓ Hit rate with errors: {hit_rate2:.2%}")

    # 4. Calibration
    # İyi kalibre edilmiş tahminler
    np.random.seed(42)
    good_predictions = []
    for _ in range(100):
        prob = np.random.uniform(0.3, 0.9)
        actual = np.random.random() < prob  # Olasılığa göre gerçekleşir
        good_predictions.append(PredictionOutcome(prob, actual, "TEST", "2026-01-01", 5))

    cal = probability_engine.compute_calibration(good_predictions)
    assert cal.brier_score < 0.3  # İyi kalibrasyon
    assert 0 <= cal.calibration_error <= 1
    passed += 1
    print(f"  ✓ Calibration (Brier={cal.brier_score:.3f}, ECE={cal.calibration_error:.3f})")

    # 5. Probability from features
    features = {
        "roc_5d": 5.0, "momentum_20d": 10.0,
        "volume_zscore": 3.0, "realized_vol_20d": 15.0,
        "trend_slope_20d": 2.0, "rsi_14": 55.0,
    }
    prob = probability_engine.compute_probability_from_features(features)
    assert 0 <= prob["probability_positive"] <= 1
    assert 0 <= prob["confidence"] <= 1
    assert prob["probability_positive"] > 0.5  # Pozitif features → yüksek olasılık
    passed += 1
    print(f"  ✓ Probability from features: {prob['probability_positive']:.2%}")

    # 6. Negative features
    features_neg = {
        "roc_5d": -5.0, "momentum_20d": -10.0,
        "volume_zscore": -1.0, "realized_vol_20d": 40.0,
        "trend_slope_20d": -3.0, "rsi_14": 25.0,
    }
    prob_neg = probability_engine.compute_probability_from_features(features_neg)
    assert prob_neg["probability_positive"] < 0.5
    passed += 1
    print(f"  ✓ Negative features: {prob_neg['probability_positive']:.2%}")

    # 7. Empty predictions
    empty_hit = probability_engine.compute_hit_rate([])
    assert empty_hit == 0.0
    empty_cal = probability_engine.compute_calibration([])
    assert empty_cal.brier_score == 0.0
    passed += 1
    print("  ✓ Empty predictions handled")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 5 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Monte Carlo Engine", test_monte_carlo),
        ("Probability Engine", test_probability_engine),
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
