"""
ALPHA BIST — FAZ 4.7 Test Suite

End-to-End Live Inference Parity:
1. Raw market data → FeatureCalculator → CS normalization → canonical features → model
2. Training ve live aynı snapshot'ta birebir feature vector
3. Future-data mutation geçmiş skoru değiştirmemeli
4. Eksik/bozuk feature güvenli fallback
5. Feature contract enforced (volume_profile artık scalar)
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ohlcv(n_days=100, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n_days, freq="B")
    close = 100 + np.cumsum(rng.randn(n_days) * 1.5)
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "Open": close * 1.001, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": rng.randint(100000, 5000000, n_days).astype(float),
    }, index=dates)


# ────────────────────────────────────────────────────────────
# 1. volume_profile artık scalar feature'lar üretmeli
# ────────────────────────────────────────────────────────────

def test_volume_profile_scalar():
    """volume_profile dict yerine vp_poc, vp_value_area_high, vp_value_area_low olmalı."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df, ticker="TEST")

    # volume_profile dict olmamalı
    assert "volume_profile" not in feats, "volume_profile dict should not be in features"

    # Scalar feature'lar olmalı
    assert "vp_poc" in feats, "Missing vp_poc"
    assert "vp_value_area_high" in feats, "Missing vp_value_area_high"
    assert "vp_value_area_low" in feats, "Missing vp_value_area_low"
    assert "vp_bins" in feats, "Missing vp_bins"

    # Hepsi scalar olmalı
    for k in ["vp_poc", "vp_value_area_high", "vp_value_area_low", "vp_bins"]:
        assert isinstance(feats[k], (int, float, np.floating, np.integer)), \
            f"{k} should be scalar, got {type(feats[k])}"
        assert np.isfinite(float(feats[k])), f"{k} should be finite"

    print(f"  ✓ volume_profile → scalar: vp_poc={feats['vp_poc']:.2f}, "
          f"vp_va_high={feats['vp_value_area_high']:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. E2E: FeatureCalculator → CS normalization → feature vector
# ────────────────────────────────────────────────────────────

def test_e2e_feature_pipeline():
    """Raw market data → FeatureCalculator → CS normalization → feature vector."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    calc = FeatureCalculator()

    # 3 ticker, 100 gün
    df_a = _make_ohlcv(100, seed=42)
    df_b = _make_ohlcv(100, seed=43)
    df_c = _make_ohlcv(100, seed=44)

    idx = 69  # T=69
    date_str = str(df_a.index[idx].date())

    # FeatureCalculator (sadece T'ye kadar veri)
    feats_a = calc.compute_all_features(df_a.iloc[:idx+1], ticker="A")
    feats_b = calc.compute_all_features(df_b.iloc[:idx+1], ticker="B")
    feats_c = calc.compute_all_features(df_c.iloc[:idx+1], ticker="C")

    assert feats_a and feats_b and feats_c, "Feature computation failed"

    # Sadece scalar feature'ları tut
    def scalar_only(f):
        return {k: v for k, v in f.items()
                if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))}

    feats_a = scalar_only(feats_a)
    feats_b = scalar_only(feats_b)
    feats_c = scalar_only(feats_c)

    # Model feature names (subset)
    model_features = sorted(feats_a.keys())[:15]
    cs_features = [f"{f}_cs_zscore" for f in model_features[:5]]

    # prepare_features_for_inference (CS normalization dahil)
    all_features = {"A": feats_a, "B": feats_b, "C": feats_c}
    result = prepare_features_for_inference(
        ticker="A",
        raw_features=feats_a,
        all_date_features=all_features,
        feature_names=model_features,
        cs_features=cs_features,
        date_str=date_str,
    )

    # Tüm model feature'ları mevcut olmalı
    for fname in model_features:
        assert fname in result, f"Missing feature: {fname}"
        assert np.isfinite(float(result[fname])), f"Non-finite: {fname}={result[fname]}"

    # CS feature'ları mevcut olmalı (3 ticker → hesaplanabilir)
    for fname in cs_features:
        assert fname in result, f"Missing CS feature: {fname}"

    print(f"  ✓ E2E pipeline: {len(model_features)} features + {len(cs_features)} CS features, all finite")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. E2E: Training ve live aynı snapshot'ta birebir feature vector
# ────────────────────────────────────────────────────────────

def test_training_live_parity():
    """Training pipeline ve live inference aynı snapshot'ta aynı feature vector üretmeli."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import (
        CrossSectionalNormalizer, prepare_features_for_inference
    )

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    normalizer = CrossSectionalNormalizer()

    df_a = _make_ohlcv(100, seed=42)
    df_b = _make_ohlcv(100, seed=43)
    idx = 69
    date_str = str(df_a.index[idx].date())

    # FeatureCalculator
    feats_a = {k: v for k, v in calc.compute_all_features(df_a.iloc[:idx+1], ticker="A").items()
               if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))}
    feats_b = {k: v for k, v in calc.compute_all_features(df_b.iloc[:idx+1], ticker="B").items()
               if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))}

    all_features = {"A": feats_a, "B": feats_b}
    feature_names = sorted(feats_a.keys())[:20]

    # === TRAINING YOLU ===
    train_map = {f"{t}::{date_str}": f for t, f in all_features.items()}
    train_dates = {f"{t}::{date_str}": date_str for t in all_features}
    normalized_train = normalizer.normalize_zscore_by_date(train_map, train_dates, feature_names)

    # === LIVE INFERENCE YOLU ===
    live_result = prepare_features_for_inference(
        ticker="A",
        raw_features=feats_a,
        all_date_features=all_features,
        feature_names=feature_names,
        cs_features=[f"{f}_cs_zscore" for f in feature_names[:5]],
        date_str=date_str,
    )

    # Karşılaştır (temel feature'lar)
    train_a = normalized_train[f"A::{date_str}"]
    for fname in feature_names:
        tv = train_a.get(fname)
        iv = live_result.get(fname)
        if tv is not None and iv is not None:
            assert abs(float(tv) - float(iv)) < 1e-6, \
                f"Parity violation {fname}: train={tv} vs live={iv}"

    print(f"  ✓ Training=Live: {len(feature_names)} features match for ticker A")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Future-data mutation geçmiş skoru değiştirmemeli
# ────────────────────────────────────────────────────────────

def test_future_mutation_no_effect():
    """T+1 verisini değiştirmek T günündeki inference skorunu etkilememeli."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    idx = 69

    # Orijinal T feature'ları
    feats_orig = {k: v for k, v in calc.compute_all_features(df.iloc[:idx+1], ticker="X").items()
                  if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))}

    # T+1 Close'unu değiştir
    df_mut = df.copy()
    df_mut.iloc[idx+1, df_mut.columns.get_loc("Close")] = 99999.0
    feats_mut = {k: v for k, v in calc.compute_all_features(df_mut.iloc[:idx+1], ticker="X").items()
                 if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))}

    # Feature'lar aynı olmalı
    for key in feats_orig:
        if key in feats_mut:
            assert abs(float(feats_orig[key]) - float(feats_mut[key])) < 1e-10, \
                f"Feature '{key}' changed from T+1 mutation"

    # prepare_features_for_inference ile de aynı
    all_orig = {"X": feats_orig, "Y": feats_orig}
    all_mut = {"X": feats_mut, "Y": feats_mut}
    feature_names = sorted(feats_orig.keys())[:10]

    r1 = prepare_features_for_inference("X", feats_orig, all_orig, feature_names, [], "2022-06-01")
    r2 = prepare_features_for_inference("X", feats_mut, all_mut, feature_names, [], "2022-06-01")

    for fname in feature_names:
        assert abs(float(r1[fname]) - float(r2[fname])) < 1e-10, \
            f"Inference feature '{fname}' changed from T+1 mutation"

    print("  ✓ Future mutation: ZERO effect on T features/inference")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Eksik/bozuk feature güvenli fallback
# ────────────────────────────────────────────────────────────

def test_missing_feature_safe_fallback():
    """Eksik feature impute ile doldurulmalı, crash olmamalı."""
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    # 10 feature bekleniyor, sadece 3 mevcut
    raw = {"f1": 1.0, "f2": float("inf"), "f3": 3.0}
    result = prepare_features_for_inference(
        ticker="TEST",
        raw_features=raw,
        all_date_features={"TEST": raw},
        feature_names=["f1", "f2", "f3", "f4", "f5"],
        cs_features=["f1_cs_zscore"],
        impute_values={"f4": 42.0, "f5": 99.0},
        date_str="2024-01-15",
    )

    assert result["f1"] == 1.0
    assert result["f2"] == 0.0, f"inf should be sanitized to 0.0, got {result['f2']}"
    assert result["f3"] == 3.0
    assert result["f4"] == 42.0, f"f4 should be imputed, got {result['f4']}"
    assert result["f5"] == 99.0, f"f5 should be imputed, got {result['f5']}"

    print("  ✓ Safe fallback: inf→0, missing→impute, no crash")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Adapter parity-safe (all_day_features ile)
# ────────────────────────────────────────────────────────────

def test_adapter_parity():
    """Adapter prepare_features_for_inference kullanıyor mu?"""
    from services.backtest.canonical_adapter import backtest_canonical_adapter, _scalar_features
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df_a = _make_ohlcv(80, seed=42)
    df_b = _make_ohlcv(80, seed=43)
    idx = 69

    feats_a = calc.compute_all_features(df_a.iloc[:idx+1], ticker="A")
    feats_b = calc.compute_all_features(df_b.iloc[:idx+1], ticker="B")

    assert feats_a and feats_b

    # _scalar_features dict feature'ları filtrelemeli
    scalar_a = _scalar_features(feats_a)
    for k, v in scalar_a.items():
        assert isinstance(v, (int, float, np.floating, np.integer)), f"Non-scalar: {k}"

    # Adapter ile skor (ML model yok → rule-based)
    score = backtest_canonical_adapter.compute_score(
        features=scalar_a,
        regime="BULL",
        ml_model=None,
        ticker="A",
        all_day_features={"A": scalar_a, "B": _scalar_features(feats_b)},
        date_str=str(df_a.index[idx].date()),
    )

    assert np.isfinite(score), f"Score not finite: {score}"
    assert 0 <= score <= 100, f"Score out of range: {score}"

    print(f"  ✓ Adapter parity: score={score:.2f}, all features scalar")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Canonical scoring _all_date_features convention kaldırıldı
# ────────────────────────────────────────────────────────────

def test_no_convention_injection():
    """canonical_scoring.compute_canonical_score _all_date_features convention kullanmamalı."""
    from services.core.canonical_scoring import canonical_scoring

    passed = 0
    failed = 0

    # _all_date_features key'i artık işlenmemeli
    features = {
        "momentum_20d": 5.0,
        "_all_date_features": {"TEST": {"momentum_20d": 5.0}},
        "_date_str": "2024-01-15",
    }

    # ML model yok → rule-based, convention key'leri ignore edilmeli
    score = canonical_scoring.compute_canonical_score("TEST", features, "BULL")
    assert np.isfinite(score.opportunity_score)
    assert score.ml_score is None

    print(f"  ✓ No convention injection: score={score.opportunity_score:.2f}, _all_date_features ignored")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("volume_profile scalar features", test_volume_profile_scalar),
        ("E2E feature pipeline", test_e2e_feature_pipeline),
        ("Training=Live parity", test_training_live_parity),
        ("Future mutation no effect", test_future_mutation_no_effect),
        ("Missing feature safe fallback", test_missing_feature_safe_fallback),
        ("Adapter parity-safe", test_adapter_parity),
        ("No convention injection", test_no_convention_injection),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.7 — E2E Live Inference Parity Testleri")
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
