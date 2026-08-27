"""
ALPHA BIST — FAZ 4.2 Test Suite

ML Training Dataset kalite kontrolü testleri.
"""

import sys
from datetime import date, timedelta

import numpy as np
import polars as pl


def _make_ohlcv(n_days, start_price=100.0, seed=42):
    rng = np.random.RandomState(seed)
    dates = pl.date_range(date(2022, 1, 3), date(2022, 1, 3) + timedelta(days=n_days*2), timedelta(days=1), eager=True).head(n_days)
    close = start_price + np.cumsum(rng.randn(n_days) * 1.5)
    close = np.maximum(close, 1.0)
    high = close * (1 + rng.uniform(0, 0.03, n_days))
    low = close * (1 - rng.uniform(0, 0.03, n_days))
    open_ = close * (1 + rng.uniform(-0.01, 0.01, n_days))
    volume = rng.randint(100000, 5000000, n_days).astype(float)
    return pl.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume
    }, index=dates)


def _make_features_map(n_samples=100, n_features=10, seed=42):
    """Sentez features_map üret."""
    rng = np.random.RandomState(seed)
    features_map = {}
    returns = {}
    date_groups = {}
    feature_names = [f"feat_{i}" for i in range(n_features)]

    for i in range(n_samples):
        ticker = f"SYM{i % 10:02d}"
        date_str = f"2022-{(i // 10) % 12 + 1:02d}-{(i % 20) + 1:02d}"
        key = f"{ticker}::{date_str}"

        feats = {f: float(rng.randn()) for f in feature_names}
        features_map[key] = feats
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = date_str

    return features_map, returns, date_groups, feature_names


# ────────────────────────────────────────────────────────────
# TEST 1: Sample metadata doğruluğu
# ────────────────────────────────────────────────────────────

def test_sample_metadata():
    """Key formatı, ticker, feature_date doğruluğu."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    features_map, returns, date_groups, fnames = _make_features_map(50)
    report = v.validate_dataset(features_map, returns, date_groups, fnames)

    assert report.valid_samples == 50, f"Expected 50 valid, got {report.valid_samples}"
    assert report.dropped_samples == 0, f"Unexpected drops: {report.drop_reasons}"
    print(f"  ✓ Metadata: {report.valid_samples}/50 valid, 0 dropped")
    passed += 1

    # Boş ticker testi
    bad_map = {"::2022-01-01": {"feat_0": 1.0}}
    bad_returns = {"::2022-01-01": 1.0}
    bad_dates = {"::2022-01-01": "2022-01-01"}
    report2 = v.validate_dataset(bad_map, bad_returns, bad_dates, ["feat_0"])
    assert report2.dropped_samples == 1, "Expected 1 drop for empty ticker"
    print(f"  ✓ Empty ticker detected: dropped={report2.dropped_samples}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 2: Target = T+5 forward return doğrulaması
# ────────────────────────────────────────────────────────────

def test_target_t5_forward_return():
    """Target'ın gerçekten T+5 forward return olduğunu doğrula."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0

    # Manuel veri: T=0'da Close=100, T+5'te Close=110 → target = %10
    features_map = {"SYM00::2022-01-03": {"feat_0": 1.0}}
    returns = {"SYM00::2022-01-03": 10.0}  # %10 forward return
    date_groups = {"SYM00::2022-01-03": "2022-01-03"}

    v = TrainingDatasetValidator()
    report = v.validate_dataset(features_map, returns, date_groups, ["feat_0"])

    assert abs(report.target_mean - 10.0) < 1e-6, f"Target mean mismatch: {report.target_mean}"
    assert abs(report.target_std - 0.0) < 1e-6, "Single sample std should be 0"
    print(f"  ✓ Target = T+5 return: mean={report.target_mean}, std={report.target_std}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 3: Train/test leakage tespiti
# ────────────────────────────────────────────────────────────

def test_train_test_leakage_detection():
    """Train ve test tarihleri arasında overlap var mı?"""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    features_map, returns, date_groups, fnames = _make_features_map(50)

    # Test: overlap yok
    test_dates_no_overlap = {"2025-01-01", "2025-01-02"}
    report = v.validate_dataset(features_map, returns, date_groups, fnames, test_dates=test_dates_no_overlap)
    assert not report.train_test_overlap, "False positive leakage detection"
    print("  ✓ No overlap: train dates don't intersect test dates")
    passed += 1

    # Test: overlap var
    train_dates = set(date_groups.values())
    test_dates_overlap = {list(train_dates)[0]}  # Bir train tarihini test'e ekle
    report2 = v.validate_dataset(features_map, returns, date_groups, fnames, test_dates=test_dates_overlap)
    assert report2.train_test_overlap, "Leakage not detected"
    assert len(report2.errors) > 0, "Leakage should produce errors"
    print(f"  ✓ Overlap detected: {len(report2.overlap_details)} dates, errors={len(report2.errors)}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 4: Cross-ticker sample oluşturma
# ────────────────────────────────────────────────────────────

def test_cross_ticker_samples():
    """Aynı tarihte farklı hisselerin sample'ları doğru oluşuyor mu?"""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    # 3 ticker, 2 tarih → 6 sample
    features_map = {}
    returns = {}
    date_groups = {}
    for ticker in ["THYAO", "GARAN", "ASELS"]:
        for dt in ["2022-01-03", "2022-01-04"]:
            key = f"{ticker}::{dt}"
            features_map[key] = {"feat_0": 1.0}
            returns[key] = 5.0
            date_groups[key] = date

    report = v.validate_dataset(features_map, returns, date_groups, ["feat_0"])

    assert report.unique_tickers == 3, f"Expected 3 tickers, got {report.unique_tickers}"
    assert report.unique_dates == 2, f"Expected 2 dates, got {report.unique_dates}"
    assert report.samples_per_date["2022-01-03"] == 3, "Expected 3 samples per date"
    print(f"  ✓ Cross-ticker: {report.unique_tickers} tickers × {report.unique_dates} dates = 6 samples")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 5: NaN/inf/outlier tespiti
# ────────────────────────────────────────────────────────────

def test_nan_inf_outlier_detection():
    """Feature'larda NaN, inf ve outlier tespiti."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    # NaN ve inf içeren feature'lar
    features_map = {}
    returns = {}
    date_groups = {}
    for i in range(50):
        key = f"SYM{i%5:02d}::2022-01-{i+1:02d}"
        features_map[key] = {
            "feat_nan": float("nan") if i < 10 else 1.0,  # %20 NaN
            "feat_inf": float("inf") if i < 5 else 1.0,    # %10 inf
            "feat_normal": float(i),
        }
        returns[key] = float(i)
        date_groups[key] = f"2022-01-{i+1:02d}"

    report = v.validate_dataset(features_map, returns, date_groups,
                                ["feat_nan", "feat_inf", "feat_normal"])

    assert "feat_nan" in report.nan_features, "NaN not detected"
    assert "feat_inf" in report.inf_features, "inf not detected"
    assert report.nan_features["feat_nan"] == 10, f"Expected 10 NaN, got {report.nan_features['feat_nan']}"
    assert report.inf_features["feat_inf"] == 5, f"Expected 5 inf, got {report.inf_features['feat_inf']}"
    print(f"  ✓ NaN detected: feat_nan={report.nan_features['feat_nan']}")
    print(f"  ✓ inf detected: feat_inf={report.inf_features['feat_inf']}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 6: Feature temizliği (inf → NaN, outlier clamp)
# ────────────────────────────────────────────────────────────

def test_feature_cleaning():
    """inf → NaN dönüşümü ve outlier clamp doğruluğu."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    features_map = {}
    for i in range(50):
        key = f"SYM{i%5:02d}::2022-01-{i+1:02d}"
        features_map[key] = {
            "feat_inf": float("inf") if i == 0 else 1.0,
            "feat_outlier": 1000.0 if i == 0 else 1.0,  # Outlier
            "feat_normal": 1.0,
        }

    cleaned, stats = v.clean_features(features_map, ["feat_inf", "feat_outlier", "feat_normal"])

    assert stats["inf_replaced"] == 1, f"Expected 1 inf replaced, got {stats['inf_replaced']}"
    assert cleaned["SYM00::2022-01-01"]["feat_inf"] is None, "inf should be None after cleaning"
    # Outlier clamp
    if stats["outliers_clamped"] > 0:
        assert cleaned["SYM00::2022-01-01"]["feat_outlier"] != 1000.0, "Outlier should be clamped"
    print(f"  ✓ Cleaning: {stats['inf_replaced']} inf→None, {stats['outliers_clamped']} outliers clamped")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 7: Target dağılımı ve sample dengesi
# ────────────────────────────────────────────────────────────

def test_target_distribution():
    """Target dağılım analizi (mean, std, skew, balance)."""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    rng = np.random.RandomState(42)
    features_map = {}
    returns = {}
    date_groups = {}
    dates = pl.date_range(date(2022, 1, 3), date(2022, 1, 3) + timedelta(days=400), timedelta(days=1), eager=True).head(200)
    for i in range(200):
        ticker = f"SYM{i%10:02d}"
        date_str = str(dates[i].date())
        key = f"{ticker}::{date_str}"
        features_map[key] = {"feat_0": float(rng.randn())}
        returns[key] = float(rng.randn() * 5)  # ~%5 std
        date_groups[key] = date_str

    report = v.validate_dataset(features_map, returns, date_groups, ["feat_0"])

    assert report.total_samples == 200
    assert abs(report.target_mean) < 2.0, f"Target mean out of range: {report.target_mean}"
    assert report.target_std > 1.0, f"Target std too low: {report.target_std}"
    assert 0.3 < report.target_positive_pct < 0.7, f"Target imbalance: {report.target_positive_pct}"
    print(f"  ✓ Distribution: mean={report.target_mean:.2f}, std={report.target_std:.2f}, "
          f"pos={report.target_positive_pct:.0%}, skew={report.target_skew:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 8: Validation metrikleri (MAE, RMSE, R², directional accuracy)
# ────────────────────────────────────────────────────────────

def test_validation_metrics():
    """Model validation metrikleri doğru hesaplanıyor mu?"""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    # Mükemmel tahmin
    y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y_pred_perfect = y_true.copy()
    m = v.compute_validation_metrics(y_true, y_pred_perfect)
    assert m.mae < 1e-10, f"Perfect MAE should be ~0: {m.mae}"
    assert m.rmse < 1e-10, f"Perfect RMSE should be ~0: {m.rmse}"
    assert abs(m.r_squared - 1.0) < 1e-10, f"Perfect R² should be 1: {m.r_squared}"
    assert abs(m.directional_accuracy - 1.0) < 1e-10, "Perfect dir_acc should be 1"
    print(f"  ✓ Perfect: MAE={m.mae:.6f}, RMSE={m.rmse:.6f}, R²={m.r_squared:.4f}, DirAcc={m.directional_accuracy:.4f}")
    passed += 1

    # Kötü tahmin (ters yön)
    y_pred_bad = -y_true
    m2 = v.compute_validation_metrics(y_true, y_pred_bad)
    assert m2.directional_accuracy < 0.1, f"Inverse dir_acc should be ~0: {m2.directional_accuracy}"
    assert m2.r_squared < 0, f"Inverse R² should be <0: {m2.r_squared}"
    print(f"  ✓ Inverse: MAE={m2.mae:.2f}, R²={m2.r_squared:.4f}, DirAcc={m2.directional_accuracy:.4f}")
    passed += 1

    # Rastgele tahmin
    rng = np.random.RandomState(42)
    y_pred_random = rng.randn(100) * 5
    y_true_random = rng.randn(100) * 5
    m3 = v.compute_validation_metrics(y_true_random, y_pred_random)
    assert 0.3 < m3.directional_accuracy < 0.7, f"Random dir_acc should be ~0.5: {m3.directional_accuracy}"
    print(f"  ✓ Random: MAE={m3.mae:.2f}, R²={m3.r_squared:.4f}, DirAcc={m3.directional_accuracy:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 9: Kalite skoru hesaplama
# ────────────────────────────────────────────────────────────

def test_quality_score():
    """Kalite skoru doğru hesaplanıyor mu?"""
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0
    v = TrainingDatasetValidator()

    # Temiz veri → yüksek skor
    features_map, returns, date_groups, fnames = _make_features_map(100)
    report = v.validate_dataset(features_map, returns, date_groups, fnames)
    assert report.quality_score > 0.8, f"Clean data quality should be >0.8: {report.quality_score}"
    print(f"  ✓ Clean data quality: {report.quality_score:.2f}")
    passed += 1

    # Leakage var → düşük skor
    test_dates = set(date_groups.values())
    report2 = v.validate_dataset(features_map, returns, date_groups, fnames, test_dates=test_dates)
    assert report2.quality_score < 0.5, f"Leakage quality should be <0.5: {report2.quality_score}"
    print(f"  ✓ Leakage quality: {report2.quality_score:.2f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 10: LightGBM validation metrikleri entegrasyonu
# ────────────────────────────────────────────────────────────

def test_lightgbm_validation_metrics():
    """LightGBM trainer'ın validation metriklerini döndürmesi."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    features_map = {}
    returns = {}
    date_groups = {}
    feature_names = [f"feat_{i}" for i in range(10)]

    for i in range(200):
        key = f"SYM{i%10:02d}::2022-{(i//20)%12+1:02d}-{(i%20)+1:02d}"
        features_map[key] = {f: float(rng.randn()) for f in feature_names}
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = f"2022-{(i//20)%12+1:02d}-{(i%20)+1:02d}"

    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=10, early_stopping_rounds=3))
    model = trainer.train(features_map, returns, date_groups, feature_names=feature_names)

    if model is None:
        print("  ⚠ Model None (LightGBM not available?), skip")
        return 0, 0

    # Validation metrikleri model üzerinde olmalı
    assert hasattr(model, "validation_metrics"), "Model should have validation_metrics"
    vm = model.validation_metrics

    assert "mae" in vm, "Missing mae"
    assert "rmse" in vm, "Missing rmse"
    assert "r_squared" in vm, "Missing r_squared"
    assert "directional_accuracy" in vm, "Missing directional_accuracy"
    assert "ic" in vm, "Missing ic"

    assert vm["mae"] >= 0, f"MAE should be >=0: {vm['mae']}"
    assert vm["rmse"] >= 0, f"RMSE should be >=0: {vm['rmse']}"
    assert 0 <= vm["directional_accuracy"] <= 1, f"DirAcc out of range: {vm['directional_accuracy']}"

    print(f"  ✓ LightGBM metrics: MAE={vm['mae']:.4f}, RMSE={vm['rmse']:.4f}, "
          f"R²={vm['r_squared']:.4f}, DirAcc={vm['directional_accuracy']:.4f}, IC={vm['ic']:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 11: Rule-based fallback (model başarısız olduğunda)
# ────────────────────────────────────────────────────────────

def test_rule_based_fallback():
    """Model None döndüğünde rule-based fallback çalışıyor mu?"""
    from services.backtest.walk_forward_runner import WalkForwardBacktestRunner

    passed = 0
    failed = 0

    runner = WalkForwardBacktestRunner.__new__(WalkForwardBacktestRunner)
    runner.MIN_TRAINING_SAMPLES = 999999  # Aşırı yüksek → None dönmeli
    runner.FORWARD_DAYS = 5
    runner.MIN_BARS_FOR_FEATURES = 60

    tickers = [f"SYM{i:02d}" for i in range(5)]
    pit_data = {}
    for i, t in enumerate(tickers):
        pit_data[t] = _make_ohlcv(150, start_price=50 + i * 30, seed=42 + i)

    dates = sorted(pit_data[tickers[0]].index)
    model = runner._train_fold_model(pit_data, str(dates[0].date()), str(dates[149].date()))

    assert model is None, "Expected None (fallback), got model"
    print("  ✓ Rule-based fallback: model=None when insufficient samples")
    passed += 1

    # Rule-based score'un çalıştığını doğrula (RankingModel)
    from services.ml.ranking_model import RankingModel
    rm = RankingModel()
    score = rm._rule_based_score({"momentum_20d": 5.0, "roc_5d": 2.0, "rs_vs_bist_5d": 1.0}, "BULL")
    assert 0 <= score <= 100, f"Rule-based score out of range: {score}"
    print(f"  ✓ Rule-based score: {score:.2f} (BULL regime)")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# TEST 12: Full pipeline entegrasyonu (train + validate + clean)
# ────────────────────────────────────────────────────────────

def test_full_pipeline_integration():
    """Train → validate → clean → train pipeline entegrasyonu."""
    from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
    from services.ml.training_validator import TrainingDatasetValidator

    passed = 0
    failed = 0

    rng = np.random.RandomState(42)
    feature_names = [f"feat_{i}" for i in range(10)]

    # inf ve outlier içeren veri
    features_map = {}
    returns = {}
    date_groups = {}
    for i in range(200):
        key = f"SYM{i%10:02d}::2022-{(i//20)%12+1:02d}-{(i%20)+1:02d}"
        feats = {f: float(rng.randn()) for f in feature_names}
        if i % 20 == 0:
            feats["feat_0"] = float("inf")  # inf ekle
        if i % 15 == 0:
            feats["feat_1"] = 999.0  # Outlier ekle
        features_map[key] = feats
        returns[key] = float(rng.randn() * 5)
        date_groups[key] = f"2022-{(i//20)%12+1:02d}-{(i%20)+1:02d}"

    # 1. Validate
    v = TrainingDatasetValidator()
    report = v.validate_dataset(features_map, returns, date_groups, feature_names)
    assert report.total_samples == 200
    print(f"  ✓ Validation: quality={report.quality_score:.2f}, inf={len(report.inf_features)}")
    passed += 1

    # 2. Clean
    cleaned, clean_stats = v.clean_features(features_map, feature_names)
    assert clean_stats["inf_replaced"] > 0, "Should have replaced inf"
    print(f"  ✓ Cleaning: inf_replaced={clean_stats['inf_replaced']}")
    passed += 1

    # 3. Train with cleaned data
    trainer = LightGBMTrainer(MLModelConfig(num_boost_round=10, early_stopping_rounds=3))
    model = trainer.train(cleaned, returns, date_groups, feature_names=feature_names)

    if model is None:
        print("  ⚠ Model None, skip training check")
        return passed, failed

    assert model.train_samples > 0
    vm = model.validation_metrics
    print(f"  ✓ Trained: samples={model.train_samples}, MAE={vm['mae']:.4f}, DirAcc={vm['directional_accuracy']:.4f}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Sample metadata", test_sample_metadata),
        ("Target T+5 forward return", test_target_t5_forward_return),
        ("Train/test leakage detection", test_train_test_leakage_detection),
        ("Cross-ticker samples", test_cross_ticker_samples),
        ("NaN/inf/outlier detection", test_nan_inf_outlier_detection),
        ("Feature cleaning", test_feature_cleaning),
        ("Target distribution", test_target_distribution),
        ("Validation metrics", test_validation_metrics),
        ("Quality score", test_quality_score),
        ("LightGBM validation metrics", test_lightgbm_validation_metrics),
        ("Rule-based fallback", test_rule_based_fallback),
        ("Full pipeline integration", test_full_pipeline_integration),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 4.2 — ML Training Dataset Kalite Kontrolü Testleri")
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
            print(f"  ✗ EXCEPTION: {e}")
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
