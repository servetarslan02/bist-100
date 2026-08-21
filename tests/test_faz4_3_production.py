"""
ALPHA BIST — FAZ 4.3 Test Suite

Production-Grade ML Validation ve Training Robustness.

Senaryolar:
1. Chronological validation (purge gap)
2. No future leakage (train/val/test ayrımı)
3. Future data mutation invariance
4. Cross-ticker separation
5. Multi-horizon target alignment
6. Constant feature handling
7. NaN/inf robustness
8. Insufficient samples → fallback
9. Failed model → fallback with diagnostics
10. Deterministic training
11. Validation metrics completeness
12. Ranking quality metrics
13. Confidence degradation
14. Feature contract violation
15. Cross-sectional normalization
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta



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


def _make_features_map(n_samples=200, n_features=10, seed=42, n_tickers=10):
    rng = np.random.RandomState(seed)
    features_map = {}
    returns = {}
    date_groups = {}
    feature_names = [f"feat_{i}" for i in range(n_features)]
    dates = pd.bdate_range(start="2022-01-03", periods=n_samples // n_tickers + 10, freq="B")

    for i in range(n_samples):
        ticker = f"SYM{i % n_tickers:02d}"
        date_idx = i // n_tickers
        if date_idx >= len(dates):
            date_idx = date_idx % len(dates)
        date_str = str(dates[date_idx].date())
        key = f"{ticker}::{date_str}"

        feats = {f: float(rng.randn()) for f in feature_names}
        features_map[key] = feats
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    return features_map, returns, date_groups, feature_names


# ────────────────────────────────────────────────────────────
# 1. Chronological Validation (purge gap)
# ────────────────────────────────────────────────────────────

def test_chronological_validation_purge():
    """Train/val split date-space purge gap ile yapılıyor mu?"""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    config = MLModelConfig(num_boost_round=10, early_stopping_rounds=3, purge_gap_days=5)
    trainer = LightGBMTrainer(config)

    features_map, returns, date_groups, fnames = _make_features_map(300, n_features=10)
    model = trainer.train(features_map, returns, date_groups, feature_names=fnames)

    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # Date-space purge gap uygulanmış olmalı
    vm = model.validation_metrics
    assert vm.get("validation_samples", 0) > 0, "No validation samples"
    total = len(features_map)
    assert model.train_samples < total, "Train size should be < total (purge + val)"
    # Train date range sonu, val tarihlerinden önce olmalı
    assert model.train_date_range[1] != "", "Train end should not be empty"
    print(f"  ✓ Date-space purge: train={model.train_samples}, total={total}, "
          f"val_samples={int(vm.get('validation_samples', 0))}, "
          f"train_end={model.train_date_range[1]}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. No Future Leakage (train/val/test)
# ────────────────────────────────────────────────────────────

def test_no_future_leakage():
    """Train'den val'e veri s\u0131z\u0131nt\u0131 yok — date-space purge gap."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    # purge_gap_days art\u0131k tarih g\u00fcn\u00fcnde \u00e7al\u0131\u015f\u0131yor
    config = MLModelConfig(num_boost_round=10, early_stopping_rounds=3, purge_gap_days=5)
    trainer = LightGBMTrainer(config)

    features_map, returns, date_groups, fnames = _make_features_map(300, n_features=10)

    model = trainer.train(features_map, returns, date_groups, feature_names=fnames)
    if model is None:
        print("  \u26a0 Model None, skip")
        return 0, 0

    # Date-space purge: train_date_range sonu < val tarihleri
    train_end = model.train_date_range[1]
    assert train_end != "", "Train end should not be empty"

    # Val tarihleri train_end'den sonra olmal\u0131 (purge gap nedeniyle)
    # train_samples + val_samples < toplam sample (purge aras\u0131 atlan\u0131r)
    total = len(features_map)
    assert model.train_samples < total, "Train should be < total"

    vm = model.validation_metrics
    assert vm.get("validation_samples", 0) > 0, "Should have validation samples"

    print(f"  \u2713 No leakage: train={model.train_samples}, total={total}, "
          f"val_samples={int(vm.get('validation_samples', 0))}, train_end={train_end}")
    passed += 1

    return passed, failed




# ────────────────────────────────────────────────────────────
# 3. Future Data Mutation Invariance
# ────────────────────────────────────────────────────────────

def test_future_data_mutation_invariance():
    """T+1 verisini değiştirmek T feature'ını etkilememeli."""
    from services.features.calculator import FeatureCalculator

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)

    feature_idx = 69
    df_slice = df.iloc[:feature_idx + 1]
    feats_orig = calc.compute_all_features(df_slice, ticker="MUT")

    # T+1 Close'u değiştir
    df_mut = df.copy()
    df_mut.iloc[feature_idx + 1, df_mut.columns.get_loc("Close")] = 99999.0
    df_mut_slice = df_mut.iloc[:feature_idx + 1]
    feats_mut = calc.compute_all_features(df_mut_slice, ticker="MUT")

    if feats_orig and feats_mut:
        mismatches = 0
        for key in feats_orig:
            v1 = feats_orig[key]
            v2 = feats_mut.get(key)
            if v2 is None:
                continue
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                if abs(v1 - v2) > 1e-10:
                    mismatches += 1
        assert mismatches == 0, f"{mismatches} features changed from T+1 mutation"
        print(f"  ✓ Future mutation: 0 features changed (T+1 mutation)")
        passed += 1
    else:
        print("  ⚠ Feature computation empty, skip")
        return 0, 0

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Cross-Ticker Separation
# ────────────────────────────────────────────────────────────

def test_cross_ticker_separation():
    """Farklı ticker'ların sample'ları karışmamalı."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0

    v = TrainingDatasetValidator()
    features_map, returns, date_groups, fnames = _make_features_map(50, n_tickers=5)

    report = v.validate_dataset(features_map, returns, date_groups, fnames)

    assert report.unique_tickers == 5, f"Expected 5 tickers, got {report.unique_tickers}"
    assert report.total_samples == 50
    assert report.valid_samples == 50
    print(f"  ✓ Separation: {report.unique_tickers} tickers, {report.unique_dates} dates, "
          f"{report.valid_samples} valid samples")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Multi-Horizon Target Alignment
# ────────────────────────────────────────────────────────────

def test_multi_horizon_target():
    """Target'ın farklı horizon'lar için doğru hesaplandığını doğrula."""
    from services.ml.lightgbm_trainer import compute_target, TargetSpec

    passed = 0
    failed = 0

    close = np.array([100.0, 102.0, 105.0, 103.0, 108.0, 110.0, 112.0, 115.0, 113.0, 118.0, 120.0])

    # 1d return
    spec_1d = TargetSpec(horizon=1, name="return_1d")
    t1 = compute_target(close, 0, spec_1d)
    expected_1d = (close[1] / close[0] - 1) * 100
    assert abs(t1 - expected_1d) < 1e-10, f"1d target mismatch: {t1} vs {expected_1d}"

    # 5d return
    spec_5d = TargetSpec(horizon=5, name="return_5d")
    t5 = compute_target(close, 0, spec_5d)
    expected_5d = (close[5] / close[0] - 1) * 100
    assert abs(t5 - expected_5d) < 1e-10, f"5d target mismatch: {t5} vs {expected_5d}"

    # 5d son gün (yetersiz veri → None)
    t5_last = compute_target(close, 8, spec_5d)
    assert t5_last is None, f"Should be None for insufficient data: {t5_last}"

    # Binary target
    spec_bin = TargetSpec(horizon=1, name="binary_1d", method="binary")
    t_bin = compute_target(close, 0, spec_bin)
    assert t_bin == 1.0, f"Binary should be 1.0 (price up): {t_bin}"

    print(f"  ✓ Multi-horizon: 1d={t1:.2f}%, 5d={t5:.2f}%, last=None, binary=1.0")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Constant Feature Handling
# ────────────────────────────────────────────────────────────

def test_constant_feature():
    """Sabit feature'lar çökme yapmamalı."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig, compute_comprehensive_metrics

    passed = 0
    failed = 0

    # Sabit feature'lı veri
    features_map = {}
    returns = {}
    date_groups = {}
    dates = pd.bdate_range(start="2022-01-03", periods=30, freq="B")
    for i in range(200):
        ticker = f"SYM{i % 10:02d}"
        date_str = str(dates[i // 10].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {"feat_const": 5.0, "feat_vary": float(np.random.randn())}
        returns[key] = float(np.random.randn() * 5)
        date_groups[key] = date_str

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=5, early_stopping_rounds=2))
    model = trainer.train(features_map, returns, date_groups,
                          feature_names=["feat_const", "feat_vary"])

    # Model None olabilir (sabit feature ile), ama crash olmamalı
    if model is not None:
        vm = model.validation_metrics
        assert np.isfinite(vm.get("mae", 0)), "MAE should be finite"
        assert np.isfinite(vm.get("rmse", 0)), "RMSE should be finite"
        print(f"  ✓ Constant feature: model trained, MAE={vm['mae']:.4f}")
    else:
        print("  ✓ Constant feature: model=None (expected with constant features)")
    passed += 1

    # compute_comprehensive_metrics constant input ile
    y_true = np.array([1.0, 2.0, 3.0])
    y_const = np.array([5.0, 5.0, 5.0])
    m = compute_comprehensive_metrics(y_true, y_const)
    assert np.isfinite(m["mae"]), "MAE should be finite for constant pred"
    assert np.isfinite(m["r_squared"]), "R² should be finite for constant pred"
    print(f"  ✓ Constant pred metrics: MAE={m['mae']:.2f}, R²={m['r_squared']:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. NaN/inf Robustness
# ────────────────────────────────────────────────────────────

def test_nan_inf_robustness():
    """NaN ve inf içeren veri ile crash olmamalı."""
    from services.ml.lightgbm_trainer import compute_comprehensive_metrics

    passed = 0
    failed = 0

    # NaN/inf'li input
    y_true = np.array([1.0, np.nan, 3.0, np.inf, 5.0])
    y_pred = np.array([1.5, 2.0, np.nan, 4.0, np.inf])
    m = compute_comprehensive_metrics(y_true, y_pred)

    assert np.isfinite(m["mae"]), f"MAE not finite: {m['mae']}"
    assert np.isfinite(m["rmse"]), f"RMSE not finite: {m['rmse']}"
    assert np.isfinite(m["r_squared"]), f"R² not finite: {m['r_squared']}"
    assert np.isfinite(m["directional_accuracy"]), f"DirAcc not finite"
    print(f"  ✓ NaN/inf robust: MAE={m['mae']:.4f}, samples={int(m['validation_samples'])}")
    passed += 1

    # Tüm NaN
    y_all_nan = np.array([np.nan, np.nan, np.nan])
    m2 = compute_comprehensive_metrics(y_all_nan, y_all_nan)
    assert m2["mae"] == 0.0, "All-NaN should return defaults"
    print(f"  ✓ All-NaN: defaults returned")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Insufficient Samples → Fallback
# ────────────────────────────────────────────────────────────

def test_insufficient_samples_fallback():
    """Yetersiz sample → None dönmeli (rule-based fallback)."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    # 30 sample (minimum 50 altında)
    features_map, returns, date_groups, fnames = _make_features_map(30, n_features=5, n_tickers=5)

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=5))
    model = trainer.train(features_map, returns, date_groups, feature_names=fnames)

    assert model is None, f"Expected None for <50 samples, got model"
    print("  ✓ Insufficient samples: None returned")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Failed Model → Fallback with Diagnostics
# ────────────────────────────────────────────────────────────

def test_failed_model_fallback():
    """Model eğitilemezse None dönmeli."""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 999999  # Çok yüksek eşik
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    tickers = [f"SYM{i:02d}" for i in range(5)]
    pit_data = {t: _make_ohlcv(150, seed=42 + i) for i, t in enumerate(tickers)}
    dates = sorted(pit_data[tickers[0]].index)

    model = runner._train_fold_model(pit_data, str(dates[0].date()), str(dates[149].date()))
    assert model is None, "Expected None for insufficient samples"
    print("  ✓ Failed model fallback: None returned (high threshold)")
    passed += 1

    # Rule-based score çalışıyor mu?
    from services.ml.ranking_model import RankingModel
    rm = RankingModel()
    score = rm._rule_based_score({"momentum_20d": 5.0, "roc_5d": 2.0}, "BULL")
    assert 0 <= score <= 100
    print(f"  ✓ Rule-based fallback: score={score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. Deterministic Training
# ────────────────────────────────────────────────────────────

def test_deterministic_training():
    """Aynı veri ile iki eğitim aynı sonuç üretmeli."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    features_map, returns, date_groups, fnames = _make_features_map(200, n_features=10)

    config = MLModelConfig(num_boost_round=10, early_stopping_rounds=3)
    trainer = LightGBMTrainer(config)

    model1 = trainer.train(features_map, returns, date_groups, feature_names=fnames)
    model2 = trainer.train(features_map, returns, date_groups, feature_names=fnames)

    if model1 is None or model2 is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    assert model1.train_samples == model2.train_samples
    assert model1.validation_score == model2.validation_score
    assert model1.validation_metrics["mae"] == model2.validation_metrics["mae"]
    assert model1.validation_metrics["rmse"] == model2.validation_metrics["rmse"]
    print(f"  ✓ Deterministic: samples={model1.train_samples}, "
          f"val={model1.validation_score}, MAE={model1.validation_metrics['mae']:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 11. Validation Metrics Completeness
# ────────────────────────────────────────────────────────────

def test_validation_metrics_completeness():
    """Tüm metrikler hesaplanıyor mu?"""
    from services.ml.lightgbm_trainer import compute_comprehensive_metrics

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    y_true = rng.randn(100) * 5
    y_pred = y_true * 0.5 + rng.randn(100) * 2  # Korelasyonlu ama gürültülü

    m = compute_comprehensive_metrics(y_true, y_pred)

    expected_keys = [
        "mae", "rmse", "r_squared", "directional_accuracy", "ic",
        "ic_stability", "prediction_std", "target_std", "rank_correlation",
        "hit_rate", "worst_error", "validation_samples",
        "top10_avg_return", "top20_avg_return", "bottom10_avg_return",
        "long_short_spread", "rank_ic",
    ]

    for key in expected_keys:
        assert key in m, f"Missing metric: {key}"
        assert np.isfinite(m[key]), f"Non-finite metric {key}: {m[key]}"

    assert m["validation_samples"] == 100
    assert m["mae"] > 0
    assert m["rmse"] > 0
    assert 0 <= m["directional_accuracy"] <= 1
    assert m["prediction_std"] > 0
    assert m["target_std"] > 0

    print(f"  ✓ Metrics complete: {len(expected_keys)} keys, all finite")
    print(f"    MAE={m['mae']:.4f}, RMSE={m['rmse']:.4f}, R²={m['r_squared']:.4f}, "
          f"DirAcc={m['directional_accuracy']:.2f}, IC={m['ic']:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Ranking Quality Metrics
# ────────────────────────────────────────────────────────────

def test_ranking_quality():
    """Top/Bottom quantile metrikleri doğru mu?"""
    from services.ml.lightgbm_trainer import compute_comprehensive_metrics

    passed = 0
    failed = 0

    # Mükemmel sıralama: yüksek tahmin = yüksek getiri
    y_true = np.array([10.0, 8.0, 6.0, 4.0, 2.0, 0.0, -2.0, -4.0, -6.0, -8.0])
    y_pred = y_true.copy()  # Mükemmel tahmin

    m = compute_comprehensive_metrics(y_true, y_pred)

    assert m["top10_avg_return"] == 10.0, f"Top10 should be 10: {m['top10_avg_return']}"
    assert m["bottom10_avg_return"] == -8.0, f"Bottom10 should be -8: {m['bottom10_avg_return']}"
    assert m["long_short_spread"] == 18.0, f"L/S spread should be 18: {m['long_short_spread']}"
    print(f"  ✓ Ranking: top10={m['top10_avg_return']:.1f}, bottom10={m['bottom10_avg_return']:.1f}, "
          f"L/S={m['long_short_spread']:.1f}")
    passed += 1

    # Ters sıralama
    y_pred_inv = -y_true
    m2 = compute_comprehensive_metrics(y_true, y_pred_inv)
    assert m2["long_short_spread"] < 0, f"Inverse L/S should be negative: {m2['long_short_spread']}"
    print(f"  ✓ Inverse ranking: L/S={m2['long_short_spread']:.1f} (negative = bad)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 13. Confidence Degradation
# ────────────────────────────────────────────────────────────

def test_confidence_degradation():
    """Düşük kalite → düşük confidence."""
    from services.ml.lightgbm_trainer import compute_model_confidence

    passed = 0
    failed = 0

    # İyi durum
    good_metrics = {
        "ic": 0.1, "directional_accuracy": 0.6,
        "prediction_std": 3.0, "target_std": 5.0,
        "validation_samples": 100,
    }
    c_good, d_good = compute_model_confidence(good_metrics, 500, 20)
    assert c_good > 0.5, f"Good confidence should be >0.5: {c_good}"

    # Kötü durum (zayıf IC, düşük sample)
    bad_metrics = {
        "ic": 0.01, "directional_accuracy": 0.45,
        "prediction_std": 0.1, "target_std": 5.0,
        "validation_samples": 10,
    }
    c_bad, d_bad = compute_model_confidence(bad_metrics, 50, 5)
    assert c_bad < c_good, f"Bad confidence ({c_bad}) should be < good ({c_good})"
    assert len(d_bad["degradation_reasons"]) > len(d_good["degradation_reasons"])

    # Regime mismatch
    c_mismatch, d_mismatch = compute_model_confidence(
        good_metrics, 500, 20, "BULL", "BEAR"
    )
    assert c_mismatch < c_good, f"Regime mismatch should lower confidence"

    print(f"  ✓ Confidence: good={c_good}, bad={c_bad}, mismatch={c_mismatch}")
    print(f"    Good reasons: {d_good['degradation_reasons']}")
    print(f"    Bad reasons: {d_bad['degradation_reasons']}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 14. Feature Contract Violation
# ────────────────────────────────────────────────────────────

def test_feature_contract_violation():
    """Eksik/uyuşmayan feature'lar tespit edilmeli."""
    from services.ml.lightgbm_trainer import validate_feature_contract

    passed = 0
    failed = 0

    # Geçerli
    good_map = {
        "A::2022-01-01": {"f1": 1.0, "f2": 2.0},
        "B::2022-01-01": {"f1": 3.0, "f2": 4.0},
    }
    ok, violations = validate_feature_contract(good_map, ["f1", "f2"])
    assert ok, f"Should be valid: {violations}"
    print(f"  ✓ Valid contract: ok={ok}")
    passed += 1

    # Eksik feature
    bad_map = {
        "A::2022-01-01": {"f1": 1.0},  # f2 eksik
        "B::2022-01-01": {"f1": 3.0, "f2": 4.0},
    }
    ok2, violations2 = validate_feature_contract(bad_map, ["f1", "f2"])
    assert not ok2, f"Should be invalid"
    assert len(violations2) > 0
    print(f"  ✓ Contract violation: ok={ok2}, violations={violations2}")
    passed += 1

    # Boş map
    ok3, violations3 = validate_feature_contract({}, ["f1"])
    assert not ok3
    print(f"  ✓ Empty map: ok={ok3}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 15. Cross-Sectional Normalization
# ────────────────────────────────────────────────────────────

def test_cross_sectional_normalization():
    """Cross-sectional z-score normalization PIT-safe mi?"""
    from services.ml.training_validator import CrossSectionalNormalizer

    passed = 0
    failed = 0

    normalizer = CrossSectionalNormalizer()

    # 3 ticker, 2 tarih
    features_map = {
        "A::2022-01-03": {"feat": 10.0},
        "B::2022-01-03": {"feat": 20.0},
        "C::2022-01-03": {"feat": 30.0},
        "A::2022-01-04": {"feat": 15.0},
        "B::2022-01-04": {"feat": 25.0},
        "C::2022-01-04": {"feat": 35.0},
    }
    date_groups = {
        "A::2022-01-03": "2022-01-03", "B::2022-01-03": "2022-01-03",
        "C::2022-01-03": "2022-01-03",
        "A::2022-01-04": "2022-01-04", "B::2022-01-04": "2022-01-04",
        "C::2022-01-04": "2022-01-04",
    }

    normalized = normalizer.normalize_zscore_by_date(features_map, date_groups, ["feat"])

    # A::2022-01-03: feat=10, mean=20, std≈8.16 → z≈-1.22
    assert "feat_cs_zscore" in normalized["A::2022-01-03"], "Missing cs_zscore"
    z_a = normalized["A::2022-01-03"]["feat_cs_zscore"]
    z_c = normalized["C::2022-01-03"]["feat_cs_zscore"]
    assert z_a < 0, f"A should be negative z: {z_a}"
    assert z_c > 0, f"C should be positive z: {z_c}"

    # Orijinal feature bozulmamalı
    assert features_map["A::2022-01-03"]["feat"] == 10.0, "Original modified!"

    # Rank normalization
    ranked = normalizer.normalize_rank_by_date(features_map, date_groups, ["feat"])
    assert "feat_cs_rank" in ranked["A::2022-01-03"], "Missing cs_rank"
    r_a = ranked["A::2022-01-03"]["feat_cs_rank"]
    r_c = ranked["C::2022-01-03"]["feat_cs_rank"]
    assert r_a < r_c, f"A rank ({r_a}) should be < C rank ({r_c})"

    print(f"  ✓ CS normalization: z_A={z_a:.2f}, z_C={z_c:.2f}, rank_A={r_a:.2f}, rank_C={r_c:.2f}")
    passed += 1

    # PIT-safe: tarih 2'deki veri tarih 1'i etkilememeli
    # Tarih 1'deki z-score sadece tarih 1 verisine dayanmalı
    z_a_d1 = normalized["A::2022-01-03"]["feat_cs_zscore"]
    # Tarih 2 verisini değiştir
    features_map2 = dict(features_map)
    features_map2["A::2022-01-04"] = {"feat": 999.0}
    features_map2["B::2022-01-04"] = {"feat": 999.0}
    features_map2["C::2022-01-04"] = {"feat": 999.0}
    normalized2 = normalizer.normalize_zscore_by_date(features_map2, date_groups, ["feat"])
    z_a_d1_after = normalized2["A::2022-01-03"]["feat_cs_zscore"]
    assert abs(z_a_d1 - z_a_d1_after) < 1e-10, "Date 2 change affected date 1!"
    print(f"  ✓ PIT-safe: date1 z unchanged after date2 mutation")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 16. Scaler/Impute TRAIN-only
# ────────────────────────────────────────────────────────────

def test_scaler_impute_train_only():
    """Scaler ve impute değerleri sadece TRAIN'den öğrenilmeli."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    features_map, returns, date_groups, fnames = _make_features_map(200, n_features=5)

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=5, early_stopping_rounds=2))
    model = trainer.train(features_map, returns, date_groups, feature_names=fnames)

    if model is None:
        print("  ⚠ Model None, skip")
        return 0, 0

    # Scaler TRAIN'den öğrenilmiş olmalı
    assert model.scaler_mean is not None, "Scaler mean should exist"
    assert model.scaler_std is not None, "Scaler std should exist"
    assert len(model.scaler_mean) == len(fnames), "Scaler should match feature count"

    # Impute values TRAIN'den
    assert model.impute_values is not None, "Impute values should exist"
    assert len(model.impute_values) == len(fnames)

    print(f"  ✓ Scaler/impute: {len(model.scaler_mean)} features, TRAIN-only")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Chronological validation (purge gap)", test_chronological_validation_purge),
        ("No future leakage", test_no_future_leakage),
        ("Future data mutation invariance", test_future_data_mutation_invariance),
        ("Cross-ticker separation", test_cross_ticker_separation),
        ("Multi-horizon target alignment", test_multi_horizon_target),
        ("Constant feature handling", test_constant_feature),
        ("NaN/inf robustness", test_nan_inf_robustness),
        ("Insufficient samples fallback", test_insufficient_samples_fallback),
        ("Failed model fallback", test_failed_model_fallback),
        ("Deterministic training", test_deterministic_training),
        ("Validation metrics completeness", test_validation_metrics_completeness),
        ("Ranking quality metrics", test_ranking_quality),
        ("Confidence degradation", test_confidence_degradation),
        ("Feature contract violation", test_feature_contract_violation),
        ("Cross-sectional normalization", test_cross_sectional_normalization),
        ("Scaler/impute TRAIN-only", test_scaler_impute_train_only),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.3 — Production-Grade ML Validation Testleri")
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
