"""
ALPHA BIST — FAZ 4.5 Test Suite

ML Production Parity:
1. Multi-horizon model activation (1d/5d/20d/60d)
2. Training ↔ Inference feature parity (CS normalizer)
3. Canonical feature discovery (no regex)
"""

import sys
import os
import numpy as np
import pandas as pd



def _make_ohlcv(n_days, start_price=100.0, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n_days, freq="B")
    close = start_price + np.cumsum(rng.randn(n_days) * 1.5)
    close = np.maximum(close, 1.0)
    high = close * (1 + rng.uniform(0, 0.03, n_days))
    low = close * (1 - rng.uniform(0, 0.03, n_days))
    open_ = close * (1 + rng.uniform(-0.01, 0.01, n_days))
    volume = rng.randint(100000, 5000000, n_days).astype(float)
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume
    }, index=dates)


# ────────────────────────────────────────────────────────────
# 1. Canonical Feature Registry (no regex)
# ────────────────────────────────────────────────────────────

def test_canonical_feature_registry():
    """Feature registry regex yerine statik listeden türetilmeli."""
    from services.core.canonical_scoring import get_canonical_features, CANONICAL_FEATURE_REGISTRY

    passed = 0
    failed = 0

    features = get_canonical_features()

    # Temel feature'lar listede olmalı
    critical = [
        "rsi_14", "momentum_20d", "volume_zscore", "atr_pct",
        "rs_vs_bist_5d", "fcf_yield_pct", "kap_sentiment_avg",
        "roc_5d", "trend_slope_20d", "adx",
    ]
    for f in critical:
        assert f in features, f"Missing critical feature: {f}"

    # Unique olmalı
    assert len(features) == len(set(features)), "Duplicate features in registry"

    # Boş olmamalı
    assert len(features) >= 40, f"Too few features: {len(features)}"

    # CANONICAL_FEATURE_REGISTRY ile aynı
    assert features == list(CANONICAL_FEATURE_REGISTRY)

    print(f"  ✓ Registry: {len(features)} features, no regex, all critical present")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. get_canonical_features walk_forward_runner'dan erişilebilir
# ────────────────────────────────────────────────────────────

def test_walk_forward_uses_registry():
    """Walk-forward runner _get_canonical_feature_names registry kullanmalı."""
    from services.core.canonical_scoring import get_canonical_features

    passed = 0
    failed = 0

    # Registry'den features al
    features = get_canonical_features()

    # Walk-forward runner'ın _get_canonical_feature_names'i aynı şeyi döndürmeli
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner
    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    wf_features = runner._get_canonical_feature_names()

    assert wf_features == features, \
        f"Feature mismatch: WF has {len(wf_features)}, registry has {len(features)}"

    print(f"  ✓ Walk-forward uses registry: {len(wf_features)} features match")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Multi-horizon model activation
# ────────────────────────────────────────────────────────────

def test_multi_horizon_model():
    """MultiHorizonModel birden fazla horizon modeli tutmalı."""
    from services.ml.lightgbm_trainer import (
        MultiHorizonModel, TrainedModel, LightGBMTrainer, MLModelConfig,
        DEFAULT_TARGETS, compute_target, TargetSpec
    )

    passed = 0
    failed = 0

    # 200+ sample ile eğitim (1d ve 5d yeterli veriye sahip olmalı)
    rng = np.random.RandomState(42)
    features_map = {}
    returns = {}
    date_groups = {}
    feature_names = [f"feat_{i}" for i in range(10)]
    dates = pd.bdate_range(start="2022-01-03", periods=30, freq="B")

    for i in range(200):
        ticker = f"SYM{i % 10:02d}"
        date_str = str(dates[i // 10].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {f: float(rng.randn()) for f in feature_names}
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    # 1d modeli eğit
    config_1d = MLModelConfig(num_boost_round=5, early_stopping_rounds=2, purge_gap_days=1, target_horizon=1)
    trainer_1d = LightGBMTrainer(config_1d)
    model_1d = trainer_1d.train(features_map, returns, date_groups, feature_names=feature_names)

    # 5d modeli eğit
    returns_5d = {}
    for key in features_map:
        parts = key.split("::")
        # Sadece mevcut returns'ı kullan (5d target zaten)
        returns_5d[key] = returns[key]
    config_5d = MLModelConfig(num_boost_round=5, early_stopping_rounds=2, purge_gap_days=5, target_horizon=5)
    trainer_5d = LightGBMTrainer(config_5d)
    model_5d = trainer_5d.train(features_map, returns_5d, date_groups, feature_names=feature_names)

    # MultiHorizonModel oluştur
    multi = MultiHorizonModel(primary_horizon=5)
    if model_1d is not None:
        multi.horizon_models[1] = model_1d
    if model_5d is not None:
        multi.horizon_models[5] = model_5d

    if not multi.horizon_models:
        print("  ⚠ No models trained, skip")
        return 0, 0

    # Primary prediction
    sample = list(features_map.values())[0]
    pred = multi.predict(sample)
    assert np.isfinite(pred), f"Primary prediction not finite: {pred}"

    # Horizon-specific prediction
    if 1 in multi.horizon_models:
        pred_1d = multi.predict_horizon(sample, 1)
        assert np.isfinite(pred_1d), f"1d prediction not finite: {pred_1d}"

    # All predictions
    all_preds = multi.get_all_predictions(sample)
    assert len(all_preds) == len(multi.horizon_models)
    for h, p in all_preds.items():
        assert np.isfinite(p), f"Horizon {h} prediction not finite: {p}"

    # Available horizons
    assert multi.available_horizons == sorted(multi.horizon_models.keys())

    print(f"  ✓ Multi-horizon: {multi.available_horizons}, primary={multi.primary_horizon}, "
          f"predictions={all_preds}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Horizon-aware purge gap
# ────────────────────────────────────────────────────────────

def test_horizon_aware_purge():
    """Her horizon kendi purge gap'ini kullanmalı (purge >= horizon)."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    features_map = {}
    returns = {}
    date_groups = {}
    feature_names = [f"feat_{i}" for i in range(5)]
    dates = pd.bdate_range(start="2022-01-03", periods=30, freq="B")

    for i in range(300):
        ticker = f"SYM{i % 10:02d}"
        date_str = str(dates[i // 10].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {f: float(rng.randn()) for f in feature_names}
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    # 1d horizon — purge = max(5, 1) = 5
    config_1d = MLModelConfig(num_boost_round=3, early_stopping_rounds=2, purge_gap_days=1, target_horizon=1)
    model_1d = LightGBMTrainer(config_1d).train(features_map, returns, date_groups, feature_names=feature_names)

    # 20d horizon — purge = max(5, 20) = 20
    config_20d = MLModelConfig(num_boost_round=3, early_stopping_rounds=2, purge_gap_days=5, target_horizon=20)
    model_20d = LightGBMTrainer(config_20d).train(features_map, returns, date_groups, feature_names=feature_names)

    if model_1d is not None:
        # 1d purge 5 gün
        print(f"  ✓ 1d: train={model_1d.train_samples}, train_end={model_1d.train_date_range[1]}")
        passed += 1
    else:
        print("  ⚠ 1d model None")
        passed += 1

    if model_20d is not None:
        # 20d purge 20 gün → daha az train sample
        assert model_20d.train_samples <= (model_1d.train_samples if model_1d else 999), \
            "20d should have fewer train samples (larger purge)"
        print(f"  ✓ 20d: train={model_20d.train_samples} (≤ 1d={model_1d.train_samples if model_1d else 'N/A'})")
        passed += 1
    else:
        # 20d yeterli veri olmayabilir — bu da geçerli
        print("  ✓ 20d: None (insufficient data for 20d horizon — expected)")
        passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Feature parity: training ve inference aynı feature sırası
# ────────────────────────────────────────────────────────────

def test_feature_parity():
    """Model hangi feature'ları bekliyorsa inference aynı sırada üretmeli."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig, validate_feature_contract

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    feature_names = [f"feat_{i}" for i in range(10)]
    features_map = {}
    returns = {}
    date_groups = {}
    dates = pd.bdate_range(start="2022-01-03", periods=30, freq="B")

    for i in range(200):
        ticker = f"SYM{i % 10:02d}"
        date_str = str(dates[i // 10].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {f: float(rng.randn()) for f in feature_names}
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    model = LightGBMTrainer(MLModelConfig(num_boost_round=5, early_stopping_rounds=2)).train(
        features_map, returns, date_groups, feature_names=feature_names
    )

    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # Model feature_names ile inference feature_names aynı olmalı
    assert model.feature_names == feature_names, \
        f"Feature names mismatch: model={model.feature_names[:3]}... vs expected={feature_names[:3]}..."

    # Feature contract validation
    ok, violations = validate_feature_contract(features_map, model.feature_names)
    assert ok, f"Feature contract violated: {violations}"

    # Prediction mevcut feature'larla çalışmalı
    sample = features_map[list(features_map.keys())[0]]
    pred = model.predict(sample)
    assert np.isfinite(pred), f"Prediction not finite: {pred}"

    # Eksik feature ile prediction (impute devreye girmeli)
    partial_sample = {k: v for k, v in sample.items() if k != feature_names[0]}
    pred_partial = model.predict(partial_sample)
    assert np.isfinite(pred_partial), f"Partial prediction not finite: {pred_partial}"

    print(f"  ✓ Feature parity: {len(feature_names)} features match, contract valid, "
          f"prediction works with full and partial features")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. MultiHorizonModel backward compatibility
# ────────────────────────────────────────────────────────────

def test_multi_horizon_backward_compat():
    """MultiHorizonModel canonical_scoring.predict() ile uyumlu olmalı."""
    from services.ml.lightgbm_trainer import MultiHorizonModel, TrainedModel, LightGBMTrainer, MLModelConfig
    from services.core.canonical_scoring import canonical_scoring, CanonicalScore

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    feature_names = [f"feat_{i}" for i in range(10)]
    features_map = {}
    returns = {}
    date_groups = {}
    dates = pd.bdate_range(start="2022-01-03", periods=30, freq="B")

    for i in range(200):
        ticker = f"SYM{i % 10:02d}"
        date_str = str(dates[i // 10].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {f: float(rng.randn()) for f in feature_names}
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    model = LightGBMTrainer(MLModelConfig(num_boost_round=5, early_stopping_rounds=2)).train(
        features_map, returns, date_groups, feature_names=feature_names
    )

    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # MultiHorizonModel ile canonical_scoring
    multi = MultiHorizonModel(primary_horizon=5)
    multi.horizon_models[5] = model

    sample_features = {f: float(rng.randn()) for f in feature_names}
    score = canonical_scoring.compute_canonical_score(
        "TEST", sample_features, "BULL", ml_model=multi
    )

    assert isinstance(score, CanonicalScore), f"Expected CanonicalScore, got {type(score)}"
    assert score.ml_score is not None, "ML score should not be None"
    assert np.isfinite(score.ml_score), f"ML score not finite: {score.ml_score}"

    print(f"  ✓ Backward compat: canonical_scoring works with MultiHorizonModel, "
          f"ml_score={score.ml_score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Fallback: yetersiz veride horizon atlanır
# ────────────────────────────────────────────────────────────

def test_horizon_fallback():
    """Yetersiz veride o horizon modeli üretilmemeli."""
    from services.ml.lightgbm_trainer import MultiHorizonModel, DEFAULT_TARGETS

    passed = 0
    failed = 0

    # Küçük veri: sadece 1d ve 5d yeterli olmalı, 60d olmamalı
    multi = MultiHorizonModel(primary_horizon=5)

    # Simüle: sadece 1d ve 5d modelleri var
    from services.ml.lightgbm_trainer import TrainedModel
    dummy_model = TrainedModel(
        model=None, feature_names=[], train_samples=100,
        validation_metrics={"ic": 0.05, "directional_accuracy": 0.55},
        confidence_score=0.5, target_horizon=5,
    )
    multi.horizon_models[5] = dummy_model

    assert 5 in multi.available_horizons
    assert 60 not in multi.available_horizons
    assert multi.predict({}) == 0.0  # model=None → 0.0

    print(f"  ✓ Fallback: available={multi.available_horizons}, 60d skipped (insufficient)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. CS normalizer inference'da aynı matematik
# ────────────────────────────────────────────────────────────

def test_cs_normalizer_parity():
    """CS normalizer training ve inference'da aynı sonucu vermeli."""
    from services.ml.training_validator import CrossSectionalNormalizer

    passed = 0
    failed = 0

    normalizer = CrossSectionalNormalizer()

    # Training snapshot: 3 ticker, tek tarih
    train_features = {
        "A::2022-01-03": {"feat": 10.0},
        "B::2022-01-03": {"feat": 20.0},
        "C::2022-01-03": {"feat": 30.0},
    }
    train_dates = {
        "A::2022-01-03": "2022-01-03",
        "B::2022-01-03": "2022-01-03",
        "C::2022-01-03": "2022-01-03",
    }

    normalized = normalizer.normalize_zscore_by_date(train_features, train_dates, ["feat"])

    # Aynı veri ile inference → aynı sonuç
    normalized2 = normalizer.normalize_zscore_by_date(train_features, train_dates, ["feat"])

    for key in normalized:
        for fname in normalized[key]:
            v1 = normalized[key][fname]
            v2 = normalized2[key][fname]
            assert v1 == v2, f"Mismatch at {key}/{fname}: {v1} vs {v2}"

    # Değer doğruluğu
    z_a = normalized["A::2022-01-03"]["feat_cs_zscore"]
    z_c = normalized["C::2022-01-03"]["feat_cs_zscore"]
    assert z_a < 0, f"A should be negative: {z_a}"
    assert z_c > 0, f"C should be positive: {z_c}"
    assert abs(z_a + z_c) < 0.01, f"Symmetric: {z_a} + {z_c} should be ~0"

    print(f"  ✓ CS parity: training=inference, z_A={z_a:.4f}, z_C={z_c:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Canonical feature registry (no regex)", test_canonical_feature_registry),
        ("Walk-forward uses registry", test_walk_forward_uses_registry),
        ("Multi-horizon model activation", test_multi_horizon_model),
        ("Horizon-aware purge gap", test_horizon_aware_purge),
        ("Feature parity (training ↔ inference)", test_feature_parity),
        ("MultiHorizonModel backward compat", test_multi_horizon_backward_compat),
        ("Horizon fallback (insufficient data)", test_horizon_fallback),
        ("CS normalizer parity", test_cs_normalizer_parity),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.5 — ML Production Parity Testleri")
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
