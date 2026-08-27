"""
ALPHA BIST — FAZ 8 Test Suite

Opportunity Discovery Engine testleri.
"""

import sys


def test_opportunity_engine():
    """Opportunity Discovery Engine testleri."""
    from services.scanner.opportunity_engine import opportunity_engine

    passed = 0
    failed = 0

    # Test features
    features_bull = {
        "price": 305.25,
        "return_1d": 1.5,
        "roc_5d": 5.0,
        "roc_20d": 12.0,
        "momentum_20d": 12.0,
        "price_acceleration": 2.0,
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
    }

    features_bear = {
        "price": 50.0,
        "return_1d": -2.0,
        "roc_5d": -5.0,
        "roc_20d": -10.0,
        "momentum_20d": -10.0,
        "price_acceleration": -1.0,
        "volume_zscore": -0.5,
        "volume_ratio_20d": 0.8,
        "rsi_14": 35,
        "macd_histogram": -0.3,
        "bb_position": 0.2,
        "adx": 20,
        "atr_14_pct": 4.0,
        "realized_vol_20d": 35,
        "amihud_illiquidity": 0.005,
        "correlation_to_index": 0.8,
        "trend_slope_20d": -2.0,
    }

    # 1. Bull hisse yüksek skor almalı
    score_bull = opportunity_engine.compute_opportunity_score("BULL_STOCK", features_bull, "BULL")
    assert score_bull.opportunity_score > 50
    assert score_bull.momentum_score > 50
    assert score_bull.volume_score > 50
    passed += 1
    print(f"  ✓ Bull stock: {score_bull.opportunity_score:.1f}")

    # 2. Bear hisse düşük skor almalı
    score_bear = opportunity_engine.compute_opportunity_score("BEAR_STOCK", features_bear, "BEAR")
    # Bear regime'de short yönü desteklenir
    assert score_bear.signal_direction == "SHORT"
    passed += 1
    print(f"  ✓ Bear stock: {score_bear.opportunity_score:.1f} ({score_bear.signal_direction})")

    # 3. Risk-adjusted score
    assert score_bull.risk_adjusted_score <= score_bull.opportunity_score
    passed += 1
    print("  ✓ Risk-adjusted score")

    # 4. Decomposition
    assert len(score_bull.decomposition) == 10
    assert sum(score_bull.decomposition.values()) > 0
    passed += 1
    print(f"  ✓ Decomposition: {score_bull.decomposition}")

    # 5. Evidence
    assert len(score_bull.evidence) > 0
    passed += 1
    print(f"  ✓ Evidence: {score_bull.evidence}")

    # 6. Signal type
    assert score_bull.signal_type in ["MOMENTUM", "VOLUME_ANOMALY", "BREAKOUT", "REGIME", "SPEC"]
    assert score_bull.signal_direction in ["LONG", "SHORT"]
    passed += 1
    print(f"  ✓ Signal: {score_bull.signal_type} {score_bull.signal_direction}")

    # 7. Universe scan
    universe = ["BULL1", "BULL2", "BEAR1"]
    features_map = {
        "BULL1": features_bull,
        "BULL2": {**features_bull, "price": 200},
        "BEAR1": features_bear,
    }
    results = opportunity_engine.scan_universe(universe, features_map, "BULL")
    assert len(results) == 3
    assert results[0].rank == 1
    assert results[0].risk_adjusted_score >= results[1].risk_adjusted_score
    passed += 1
    print(f"  ✓ Universe scan: {len(results)} stocks ranked")

    # 8. Top opportunities
    top = opportunity_engine.get_top_opportunities(results, limit=2, min_score=40)
    assert len(top) <= 2
    if top:
        assert "ticker" in top[0]
        assert "score" in top[0]
        assert "decomposition" in top[0]
    passed += 1
    print(f"  ✓ Top opportunities: {len(top)} stocks")

    # 9. Regime weight changes
    score_bull_regime = opportunity_engine.compute_opportunity_score("TEST", features_bull, "BULL")
    score_bear_regime = opportunity_engine.compute_opportunity_score("TEST", features_bull, "BEAR")
    # Aynı features ama farklı rejim → farklı skor
    assert score_bull_regime.opportunity_score != score_bear_regime.opportunity_score
    passed += 1
    print(
        f"  ✓ Regime weight changes (BULL={score_bull_regime.opportunity_score:.1f}, BEAR={score_bear_regime.opportunity_score:.1f})"
    )

    # 10. Confidence
    assert 0 <= score_bull.confidence <= 1
    passed += 1
    print(f"  ✓ Confidence: {score_bull.confidence:.2f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 8 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    print("\n--- Opportunity Discovery Engine ---")
    try:
        p, f = test_opportunity_engine()
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
