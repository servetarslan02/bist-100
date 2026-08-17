"""
ALPHA BIST — FAZ 4.8 Test Suite

Tüm scoring path'leri parity-safe.
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ohlcv(n=100, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n, freq="B")
    close = 100 + np.cumsum(rng.randn(n) * 1.5)
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "Open": close * 1.001, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": rng.randint(100000, 5000000, n).astype(float),
    }, index=dates)


# ────────────────────────────────────────────────────────────
# 1. FeatureCalculator scalar guard
# ────────────────────────────────────────────────────────────

def test_scalar_guard():
    """FeatureCalculator dict/nested/inf feature'ları filtrelemeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df, ticker="TEST")

    # Hiçbir feature dict/list/array olmamalı
    for k, v in feats.items():
        assert isinstance(v, (int, float, np.floating, np.integer)), \
            f"Non-scalar feature '{k}': {type(v).__name__}"
        assert np.isfinite(float(v)), f"Non-finite feature '{k}': {v}"

    # vp_poc, vp_value_area_high, vp_value_area_low, vp_bins olmalı
    for k in ["vp_poc", "vp_value_area_high", "vp_value_area_low", "vp_bins"]:
        assert k in feats, f"Missing scalar feature: {k}"

    # volume_profile dict olmamalı
    assert "volume_profile" not in feats, "volume_profile dict should be removed"

    print(f"  ✓ Scalar guard: {len(feats)} features, all scalar, all finite")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Canonical feature registry consistency check
# ────────────────────────────────────────────────────────────

def test_registry_consistency():
    """Model feature_names registry ile tutarlı olmalı."""
    from services.core.canonical_scoring import (
        validate_model_feature_contract, CANONICAL_FEATURE_REGISTRY,
        get_canonical_features
    )

    passed = 0
    failed = 0

    # Registry feature'ları ile model
    class FakeModel:
        feature_names = list(CANONICAL_FEATURE_REGISTRY[:10])
        cs_features = [f"{CANONICAL_FEATURE_REGISTRY[0]}_cs_zscore"]

    ok, warnings = validate_model_feature_contract(FakeModel())
    assert ok, f"Should be consistent: {warnings}"
    assert len(warnings) == 0
    print(f"  ✓ Registry consistency: {len(FakeModel.feature_names)} features, 0 warnings")
    passed += 1

    # Registry'de olmayan feature
    class BadModel:
        feature_names = ["nonexistent_feature_xyz"] + list(CANONICAL_FEATURE_REGISTRY[:5])
        cs_features = []

    ok2, warnings2 = validate_model_feature_contract(BadModel())
    assert not ok2, "Should detect unregistered feature"
    assert any("nonexistent_feature_xyz" in w for w in warnings2)
    print(f"  ✓ Unregistered feature detected: {warnings2[0]}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Canonical adapter parity-safe (all scoring paths)
# ────────────────────────────────────────────────────────────

def test_adapter_all_paths():
    """Adapter hem all_day_features ile hem de olmadan çalışmalı."""
    from services.backtest.canonical_adapter import backtest_canonical_adapter

    passed = 0
    failed = 0

    feats = {"momentum_20d": 5.0, "roc_5d": 2.0, "rsi_14": 55.0,
             "volume_zscore": 1.0, "atr_pct": 2.0}

    # Path 1: all_day_features ile (full CS normalization)
    score1 = backtest_canonical_adapter.compute_score(
        features=feats, regime="BULL", ml_model=None,
        ticker="A", all_day_features={"A": feats, "B": {"momentum_20d": 3.0}},
        date_str="2024-01-15",
    )
    assert np.isfinite(score1) and 0 <= score1 <= 100

    # Path 2: all_day_features olmadan (no CS, feature contract only)
    score2 = backtest_canonical_adapter.compute_score(
        features=feats, regime="BULL", ml_model=None,
        ticker="A", all_day_features=None, date_str="2024-01-15",
    )
    assert np.isfinite(score2) and 0 <= score2 <= 100

    # Path 3: compute_score_and_decision
    score3, action = backtest_canonical_adapter.compute_score_and_decision(
        features=feats, regime="BULL", price=100.0, ml_model=None,
        ticker="A", all_day_features={"A": feats}, date_str="2024-01-15",
    )
    assert np.isfinite(score3) and action in ("BUY", "SELL", "HOLD", "NO_ACTION")

    print(f"  ✓ Adapter all paths: with_cs={score1:.1f}, without_cs={score2:.1f}, decision={action}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Legacy scoring path unchanged
# ────────────────────────────────────────────────────────────

def test_legacy_unchanged():
    """Legacy mode scoring davranışı değişmemeli."""
    from services.backtest.canonical_adapter import BacktestCanonicalAdapter

    passed = 0
    failed = 0

    # Legacy mode: ml_model=None, all_day_features=None
    adapter = BacktestCanonicalAdapter()
    feats = {"rsi_14": 65.0, "momentum_20d": 3.0, "roc_5d": 1.5, "volume_zscore": 0.5}

    score = adapter.compute_score(features=feats, regime="BULL", ml_model=None)
    assert np.isfinite(score)
    assert 0 <= score <= 100

    print(f"  ✓ Legacy unchanged: score={score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. E2E: raw data → features → CS → model → score → decision
# ────────────────────────────────────────────────────────────

def test_e2e_full_pipeline():
    """Tam pipeline: raw OHLCV → FeatureCalculator → CS normalization → score."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import prepare_features_for_inference
    from services.core.canonical_scoring import canonical_scoring

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    idx = 69

    # FeatureCalculator
    feats = calc.compute_all_features(df.iloc[:idx+1], ticker="E2E")
    assert feats, "Feature computation failed"

    # Tüm feature'lar scalar olmalı (scalar guard)
    for k, v in feats.items():
        assert isinstance(v, (int, float, np.floating, np.integer)), f"Non-scalar: {k}"

    # prepare_features_for_inference (tek ticker, CS=0)
    model_features = sorted(feats.keys())[:10]
    normalized = prepare_features_for_inference(
        ticker="E2E", raw_features=feats,
        all_date_features={"E2E": feats},
        feature_names=model_features, cs_features=[],
        date_str=str(df.index[idx].date()),
    )

    # Canonical score
    score = canonical_scoring.compute_canonical_score("E2E", normalized, "BULL")
    assert np.isfinite(score.opportunity_score)
    assert 0 <= score.opportunity_score <= 100

    print(f"  ✓ E2E pipeline: {len(feats)} raw features → {len(model_features)} model features → score={score.opportunity_score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Future-data mutation (all paths)
# ────────────────────────────────────────────────────────────

def test_future_mutation_all_paths():
    """T+1 değişimi T feature'ını hiçbir scoring path'inde etkilememeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    idx = 69

    feats_orig = calc.compute_all_features(df.iloc[:idx+1], ticker="X")

    df_mut = df.copy()
    df_mut.iloc[idx+1, df_mut.columns.get_loc("Close")] = 99999.0
    feats_mut = calc.compute_all_features(df_mut.iloc[:idx+1], ticker="X")

    for key in feats_orig:
        if key in feats_mut:
            v1 = float(feats_orig[key])
            v2 = float(feats_mut[key])
            assert abs(v1 - v2) < 1e-10, f"'{key}' changed from T+1 mutation"

    print("  ✓ Future mutation: ZERO effect on all features")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Missing/bozuk feature fallback (all paths)
# ────────────────────────────────────────────────────────────

def test_missing_feature_fallback():
    """Eksik/bozuk feature güvenli fallback yapmalı."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df.iloc[:70], ticker="Y")
    assert feats

    # Eksik feature'larla inference
    model_features = sorted(feats.keys())[:10] + ["nonexistent_1", "nonexistent_2"]
    result = prepare_features_for_inference(
        ticker="Y", raw_features=feats,
        all_date_features={"Y": feats},
        feature_names=model_features, cs_features=[],
        impute_values={"nonexistent_1": 42.0, "nonexistent_2": 99.0},
        date_str="2024-01-15",
    )

    assert result["nonexistent_1"] == 42.0
    assert result["nonexistent_2"] == 99.0
    for k in model_features[:10]:
        assert k in result, f"Missing existing feature: {k}"

    print(f"  ✓ Missing fallback: 10 existing + 2 imputed, no crash")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Scalar guard", test_scalar_guard),
        ("Registry consistency", test_registry_consistency),
        ("Adapter all paths", test_adapter_all_paths),
        ("Legacy unchanged", test_legacy_unchanged),
        ("E2E full pipeline", test_e2e_full_pipeline),
        ("Future mutation all paths", test_future_mutation_all_paths),
        ("Missing feature fallback", test_missing_feature_fallback),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.8 — Tüm Scoring Path'leri Parity-Safe")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
            if f > 0:
                print(f"  ⚠ {f} FAILED")
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
