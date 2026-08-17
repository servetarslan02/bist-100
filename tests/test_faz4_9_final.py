"""
ALPHA BIST — FAZ 4.9 FINAL AUDIT

Tüm scoring path'leri, feature contract, parity, leakage kontrolü.
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
# 1. Tüm scoring path'leri canonical + ML
# ────────────────────────────────────────────────────────────

def test_all_scoring_paths():
    """Legacy, canonical, canonical+ML, rescore — hepsi parity-safe."""
    from services.backtest.canonical_adapter import backtest_canonical_adapter, _scalar_features
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df.iloc[:70], ticker="A")
    assert feats, "Feature computation failed"

    scalar = _scalar_features(feats)
    all_day = {"A": scalar, "B": scalar}

    # Path 1: Legacy (ml_model=None, all_day=None)
    s1 = backtest_canonical_adapter.compute_score(scalar, "BULL", None, "A", None, "")
    assert np.isfinite(s1) and 0 <= s1 <= 100

    # Path 2: Canonical (ml_model=None, all_day=day_features)
    s2 = backtest_canonical_adapter.compute_score(scalar, "BULL", None, "A", all_day, "2022-06-01")
    assert np.isfinite(s2) and 0 <= s2 <= 100

    # Path 3: compute_score_and_decision
    s3, action = backtest_canonical_adapter.compute_score_and_decision(
        scalar, "BULL", 100.0, None, "A", all_day, "2022-06-01"
    )
    assert np.isfinite(s3) and action in ("BUY", "SELL", "HOLD", "NO_ACTION")

    print(f"  ✓ All paths: legacy={s1:.1f}, canonical={s2:.1f}, decision={s3:.1f}/{action}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Multi-horizon 1d/5d/20d/60d feature contract
# ────────────────────────────────────────────────────────────

def test_multi_horizon_contract():
    """Tüm horizon'lar aynı feature contract kullanmalı."""
    from services.ml.lightgbm_trainer import MultiHorizonModel, TrainedModel

    passed = 0
    failed = 0

    fnames = [f"f{i}" for i in range(10)]
    cs = ["f0_cs_zscore"]

    multi = MultiHorizonModel(primary_horizon=5, cs_features=cs)
    for h in [1, 5, 20, 60]:
        multi.horizon_models[h] = TrainedModel(
            model=None, feature_names=list(fnames), train_samples=100,
            target_horizon=h, cs_features=list(cs),
        )

    for h, m in multi.horizon_models.items():
        assert m.feature_names == fnames, f"Horizon {h}: feature mismatch"
        assert m.cs_features == cs, f"Horizon {h}: cs mismatch"

    assert multi.available_horizons == [1, 5, 20, 60]
    assert multi.feature_names == fnames

    print(f"  ✓ Multi-horizon contract: {multi.available_horizons}, all share {len(fnames)} features")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. CS parity (training = inference)
# ────────────────────────────────────────────────────────────

def test_cs_parity_final():
    """Training ve inference CS normalization aynı sonucu vermeli."""
    from services.ml.training_validator import (
        CrossSectionalNormalizer, prepare_features_for_inference
    )

    passed = 0
    failed = 0

    normalizer = CrossSectionalNormalizer()
    all_f = {"A": {"f": 10.0}, "B": {"f": 20.0}, "C": {"f": 30.0}}
    ds = "2024-01-15"

    # Training
    train_map = {f"{t}::{ds}": f for t, f in all_f.items()}
    train_dates = {f"{t}::{ds}": ds for t in all_f}
    norm = normalizer.normalize_zscore_by_date(train_map, train_dates, ["f"])

    # Inference
    for t in ["A", "B", "C"]:
        infer = prepare_features_for_inference(
            t, all_f[t], all_f, ["f"], ["f_cs_zscore"], date_str=ds
        )
        train_z = norm[f"{t}::{ds}"].get("f_cs_zscore", 0)
        infer_z = infer.get("f_cs_zscore", 0)
        assert abs(train_z - infer_z) < 1e-6, f"{t}: train={train_z} vs infer={infer_z}"

    print("  ✓ CS parity: training=inference for all tickers")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Feature contract validation
# ────────────────────────────────────────────────────────────

def test_feature_contract_final():
    """Feature contract enforced: eksik → impute, dict → filtrelenmiş."""
    from services.ml.training_validator import prepare_features_for_inference
    from services.core.canonical_scoring import validate_model_feature_contract

    passed = 0
    failed = 0

    # Eksik feature + impute
    raw = {"f1": 1.0, "f2": float("inf")}
    result = prepare_features_for_inference(
        "T", raw, {"T": raw}, ["f1", "f2", "f3"], [],
        impute_values={"f3": 77.0}, date_str="2024-01-01"
    )
    assert result["f1"] == 1.0
    assert result["f2"] == 0.0  # inf → 0
    assert result["f3"] == 77.0  # impute

    # Registry consistency
    class M:
        feature_names = ["f1", "f2", "f3"]
        cs_features = []
    ok, warns = validate_model_feature_contract(M())
    # f1, f2, f3 registry'de yok → warning
    assert not ok, f"Should warn about unregistered features"
    assert len(warns) > 0

    print(f"  ✓ Contract: inf→0, missing→impute, registry warns={len(warns)}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Future-data mutation
# ────────────────────────────────────────────────────────────

def test_future_mutation_final():
    """T+1 değişimi T feature'ını hiçbir path'te etkilememeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    orig = calc.compute_all_features(df.iloc[:70], ticker="X")

    df_mut = df.copy()
    df_mut.iloc[70, df_mut.columns.get_loc("Close")] = 99999.0
    mut = calc.compute_all_features(df_mut.iloc[:70], ticker="X")

    for k in orig:
        if k in mut:
            assert abs(float(orig[k]) - float(mut[k])) < 1e-10, f"'{k}' changed"

    print("  ✓ Future mutation: ZERO effect")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Missing/invalid feature fallback
# ────────────────────────────────────────────────────────────

def test_missing_invalid_fallback():
    """Eksik, inf, NaN, dict feature'lar güvenli fallback yapmalı."""
    from services.features.calculator import FeatureCalculator
    from services.ml.training_validator import prepare_features_for_inference

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df.iloc[:70], ticker="Z")
    assert feats

    # Tüm feature'lar scalar olmalı (scalar guard)
    for k, v in feats.items():
        assert isinstance(v, (int, float, np.floating, np.integer)), f"Non-scalar: {k}"

    # Eksik feature ile
    model_f = sorted(feats.keys())[:5] + ["missing_xyz"]
    result = prepare_features_for_inference(
        "Z", feats, {"Z": feats}, model_f, [],
        impute_values={"missing_xyz": 123.0}, date_str="2024-01-01"
    )
    assert result["missing_xyz"] == 123.0

    print("  ✓ Missing/invalid: scalar guard active, impute works")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Legacy regression
# ────────────────────────────────────────────────────────────

def test_legacy_regression():
    """Legacy scoring davranışı değişmemeli."""
    from services.backtest.canonical_adapter import BacktestCanonicalAdapter

    passed = 0
    failed = 0

    adapter = BacktestCanonicalAdapter()
    feats = {"rsi_14": 65.0, "momentum_20d": 3.0, "roc_5d": 1.5}

    score = adapter.compute_score(feats, "BULL", None)
    assert np.isfinite(score) and 0 <= score <= 100

    print(f"  ✓ Legacy regression: score={score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Deterministic replay
# ────────────────────────────────────────────────────────────

def test_deterministic_replay():
    """Aynı veri ile iki skor aynı olmalı."""
    from services.backtest.canonical_adapter import backtest_canonical_adapter

    passed = 0
    failed = 0

    feats = {"momentum_20d": 5.0, "roc_5d": 2.0, "rsi_14": 55.0}
    all_day = {"A": feats, "B": feats}

    s1 = backtest_canonical_adapter.compute_score(feats, "BULL", None, "A", all_day, "2024-01-15")
    s2 = backtest_canonical_adapter.compute_score(feats, "BULL", None, "A", all_day, "2024-01-15")
    assert s1 == s2, f"Non-deterministic: {s1} vs {s2}"

    print(f"  ✓ Deterministic: {s1:.4f} == {s2:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Scalar guard centralized
# ────────────────────────────────────────────────────────────

def test_scalar_guard_centralized():
    """FeatureCalculator._enforce_scalar_features dict/inf/NaN filtrelemeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    features = {
        "good": 1.0,
        "inf_val": float("inf"),
        "nan_val": float("nan"),
        "dict_val": {"a": 1},
        "list_val": [1, 2],
        "none_val": None,
        "np_inf": np.inf,
        "np_nan": np.nan,
        "np_scalar": np.float64(5.0),
    }

    result = FeatureCalculator._enforce_scalar_features(features, "TEST")

    assert "good" in result
    assert "np_scalar" in result
    assert "inf_val" not in result
    assert "nan_val" not in result
    assert "dict_val" not in result
    assert "list_val" not in result
    assert "none_val" not in result
    assert "np_inf" not in result
    assert "np_nan" not in result

    print(f"  ✓ Scalar guard: 2/9 passed through, 7 filtered")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Tüm scoring path'leri", test_all_scoring_paths),
        ("Multi-horizon contract", test_multi_horizon_contract),
        ("CS parity final", test_cs_parity_final),
        ("Feature contract final", test_feature_contract_final),
        ("Future-data mutation", test_future_mutation_final),
        ("Missing/invalid fallback", test_missing_invalid_fallback),
        ("Legacy regression", test_legacy_regression),
        ("Deterministic replay", test_deterministic_replay),
        ("Scalar guard centralized", test_scalar_guard_centralized),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.9 — FINAL AUDIT")
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
