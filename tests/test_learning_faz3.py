import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Learning System Faz 3 Test Suite (Retrain Engine)

Walk-forward validated retrain testing:
- Walk-forward split oluşturma
- Walk-forward metric hesaplama
- Deflated Sharpe correction
- Model kabul/red kararları
- Feature preparation
- Edge cases (yetersiz veri, hatalı model, NaN veri)
- Retrain history ve raporlama
- Version ID üretimi
- Config-driven threshold'lar
"""

import sys
from datetime import datetime, timedelta

import numpy as np

# ===================== HELPERS =====================


class MockModel:
    """Test için basit model — güçlü sinyal."""

    def __init__(self):
        """Otomatik eklendi."""
        self._coef = None
        self._bias = 0.0

    def fit(self, X, y) -> Any:
        """Otomatik eklendi."""
        if len(X) > 0 and len(y) > 0:
            # Ridge regresyon (daha stabil)
            try:
                XtX = X.T @ X + np.eye(X.shape[1]) * 0.1
                self._coef = np.linalg.solve(XtX, X.T @ y)
                self._bias = np.mean(y) - np.mean(X @ self._coef)
            except Exception:
                self._coef = np.zeros(X.shape[1])

    def predict(self, X) -> Any:
        """Otomatik eklendi."""
        if self._coef is not None:
            return X @ self._coef + self._bias
        return np.zeros(len(X))


def mock_model_fn() -> Any:
    """Otomatik eklendi."""
    return MockModel()


def generate_test_data(n_samples=800, n_features=5, seed=42) -> Any:
    """Test verisi oluştur — deterministik, mükemmel korelasyon."""
    np.random.seed(seed)
    X = np.random.randn(n_samples, n_features)
    # y = ilk feature (mükemmel korelasyon)
    y = X[:, 0].copy()
    dates = [(datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_samples)]
    features = {f"feat_{i}": X[:, i] for i in range(n_features)}
    returns = {d: float(y[i]) for i, d in enumerate(dates)}
    return features, returns, dates


# ===================== VERSION ID =====================


def test_version_id_unique() -> Any:
    """Her version ID benzersiz olmalı."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    ids = set()
    for _ in range(100):
        vid = engine._generate_version_id()
        assert vid.startswith("retrain_")
        assert vid not in ids, f"Duplicate version ID: {vid}"
        ids.add(vid)
    logger.info(f"✅ Version ID uniqueness: {len(ids)} unique IDs")


def test_version_id_format() -> Any:
    """Version ID format doğru mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    vid = engine._generate_version_id()
    parts = vid.split("_")
    assert len(parts) >= 3, f"Invalid format: {vid}"
    assert parts[0] == "retrain"
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # HHMMSS
    logger.info(f"✅ Version ID format: {vid}")


# ===================== WALK-FORWARD SPLITS =====================


def test_wf_splits_generation() -> Any:
    """Walk-forward split'ler doğru oluşuyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain

    # 600 gün veri
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(600)]
    splits = engine._generate_wf_splits(dates, cfg)

    assert len(splits) > 0, "Split oluşmadı"
    for s in splits:
        assert s["train_start"] >= 0
        assert s["train_end"] > s["train_start"]
        assert s["test_start"] >= s["train_end"]
        assert s["test_end"] > s["test_start"]
    logger.info(f"✅ WF splits: {len(splits)} splits from 600 days")


def test_wf_splits_insufficient_data() -> Any:
    """Yetersiz veri ile split oluşmamalı."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain

    # Çok az veri
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(50)]
    splits = engine._generate_wf_splits(dates, cfg)

    assert len(splits) == 0, f"Split oluşmamalıydı ama {len(splits)} oluştu"
    logger.info("✅ WF splits insufficient data → 0 splits")


def test_wf_splits_purge_embargo() -> Any:
    """Purge ve embargo doğru uygulanıyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain

    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(600)]
    splits = engine._generate_wf_splits(dates, cfg)

    for s in splits:
        # Purge gap: train_end ile test_start arasında boşluk olmalı
        purge_gap = s["test_start"] - s["train_end"]
        assert purge_gap >= 0, f"Purge gap negatif: {purge_gap}"
    logger.info(f"✅ WF purge/embargo: gap={splits[0]['test_start'] - splits[0]['train_end']}")


def test_wf_splits_step_size() -> Any:
    """Step size doğru uygulanıyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain

    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(600)]
    splits = engine._generate_wf_splits(dates, cfg)

    if len(splits) >= 2:
        step = splits[1]["test_start"] - splits[0]["test_start"]
        assert step == cfg.wf_step_size, f"Step size yanlış: {step} != {cfg.wf_step_size}"
    logger.info(f"✅ WF step size: {cfg.wf_step_size}")


# ===================== FEATURE PREPARATION =====================


def test_prepare_features_dict() -> Any:
    """Dict of arrays → matrix dönüşümü doğru mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features = {
        "a": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        "b": np.array([10.0, 20.0, 30.0, 40.0, 50.0]),
    }

    X = engine._prepare_features(features, None)
    assert X.shape == (5, 2)
    assert X[0, 0] == 1.0
    assert X[0, 1] == 10.0
    logger.info(f"✅ Prepare features dict: shape={X.shape}")


def test_prepare_features_unequal_lengths() -> Any:
    """Farklı uzunluktaki feature'lar eşitlenmeli."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features = {
        "a": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        "b": np.array([10.0, 20.0, 30.0]),
    }

    X = engine._prepare_features(features, None)
    assert X.shape[0] == 3  # Kısa olan kadar
    assert X.shape[1] == 2
    logger.info(f"✅ Prepare features unequal: shape={X.shape}")


def test_prepare_features_custom_fn() -> Any:
    """Custom feature fonksiyonu çalışıyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features = {"a": np.array([1.0, 2.0, 3.0])}

    def custom_fn(fm) -> Any:
        """Otomatik eklendi."""
        return np.column_stack([fm["a"], fm["a"] ** 2])

    X = engine._prepare_features(features, custom_fn)
    assert X.shape == (3, 2)
    assert X[0, 1] == 1.0  # 1^2
    assert X[1, 1] == 4.0  # 2^2
    logger.info(f"✅ Prepare features custom fn: shape={X.shape}")


def test_prepare_features_empty() -> Any:
    """Boş feature map hata vermeli."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    try:
        engine._prepare_features({}, None)
        raise AssertionError("Hata vermeliydi")
    except ValueError:
        logger.info("✅ Prepare features empty → ValueError")


# ===================== WF METRIC EVALUATION =====================


def test_evaluate_wf_metrics_pass() -> Any:
    """İyi metriklerle retrain kabul edilmeli."""
    from services.learning.config.learning_config import learning_settings
    from services.learning.retrain_engine import RetrainEngine, WalkForwardMetrics

    engine = RetrainEngine()
    cfg = learning_settings.retrain

    metrics = WalkForwardMetrics(
        avg_correlation=0.3,
        std_correlation=0.1,
        avg_direction_accuracy=58.0,
        std_direction_accuracy=5.0,
        avg_sharpe=1.5,
        deflated_sharpe=0.8,
        total_splits=10,
        passed_splits=8,
        pass_rate=0.8,
    )

    accepted, reason = engine._evaluate_wf_metrics(metrics, cfg)
    assert accepted is True
    assert reason == "Validation passed"
    logger.info(f"✅ WF metrics pass: {reason}")


def test_evaluate_wf_metrics_low_correlation() -> Any:
    """Düşük korelasyonla retrain reddedilmeli."""
    from services.learning.config.learning_config import learning_settings
    from services.learning.retrain_engine import RetrainEngine, WalkForwardMetrics

    engine = RetrainEngine()
    cfg = learning_settings.retrain

    metrics = WalkForwardMetrics(
        avg_correlation=0.01,
        std_correlation=0.05,
        avg_direction_accuracy=58.0,
        std_direction_accuracy=5.0,
        avg_sharpe=1.5,
        deflated_sharpe=0.8,
        total_splits=10,
        passed_splits=8,
        pass_rate=0.8,
    )

    accepted, reason = engine._evaluate_wf_metrics(metrics, cfg)
    assert accepted is False
    assert "Correlation" in reason
    logger.info(f"✅ WF metrics low correlation → rejected: {reason}")


def test_evaluate_wf_metrics_low_accuracy() -> Any:
    """Düşük doğrulukla retrain reddedilmeli."""
    from services.learning.config.learning_config import learning_settings
    from services.learning.retrain_engine import RetrainEngine, WalkForwardMetrics

    engine = RetrainEngine()
    cfg = learning_settings.retrain

    metrics = WalkForwardMetrics(
        avg_correlation=0.3,
        std_correlation=0.1,
        avg_direction_accuracy=48.0,
        std_direction_accuracy=5.0,
        avg_sharpe=1.5,
        deflated_sharpe=0.8,
        total_splits=10,
        passed_splits=8,
        pass_rate=0.8,
    )

    accepted, reason = engine._evaluate_wf_metrics(metrics, cfg)
    assert accepted is False
    assert "accuracy" in reason.lower()
    logger.info(f"✅ WF metrics low accuracy → rejected: {reason}")


def test_evaluate_wf_metrics_low_pass_rate() -> Any:
    """Düşük pass rate ile retrain reddedilmeli."""
    from services.learning.config.learning_config import learning_settings
    from services.learning.retrain_engine import RetrainEngine, WalkForwardMetrics

    engine = RetrainEngine()
    cfg = learning_settings.retrain

    metrics = WalkForwardMetrics(
        avg_correlation=0.3,
        std_correlation=0.1,
        avg_direction_accuracy=58.0,
        std_direction_accuracy=5.0,
        avg_sharpe=1.5,
        deflated_sharpe=0.8,
        total_splits=10,
        passed_splits=2,
        pass_rate=0.2,
    )

    accepted, reason = engine._evaluate_wf_metrics(metrics, cfg)
    assert accepted is False
    assert "Pass rate" in reason
    logger.info(f"✅ WF metrics low pass rate → rejected: {reason}")


# ===================== FULL RETRAIN =====================


def test_full_retrain_success() -> Any:
    """Tam retrain başarılı olmalı."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features, returns, dates = generate_test_data(n_samples=800, n_features=5)

    result = engine.validate_and_retrain(
        model_fn=mock_model_fn,
        features_map=features,
        returns=returns,
        dates=dates,
        regime="BULL",
    )

    assert result.success is True
    assert result.shadow_started is True
    assert result.wf_metrics is not None
    assert result.training_samples > 0
    assert result.version_id.startswith("retrain_")
    logger.info(
        f"✅ Full retrain success: version={result.version_id}, "
        f"samples={result.training_samples}, "
        f"wf_corr={result.wf_metrics.avg_correlation}"
    )


def test_full_retrain_insufficient_data() -> Any:
    """Yetersiz veri ile retrain başarısız olmalı."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features, returns, dates = generate_test_data(n_samples=50, n_features=2)

    result = engine.validate_and_retrain(
        model_fn=mock_model_fn,
        features_map=features,
        returns=returns,
        dates=dates,
    )

    assert result.success is False
    assert "failed" in result.reason.lower() or "insufficient" in result.reason.lower()
    logger.info(f"✅ Full retrain insufficient → failed: {result.reason}")


def test_full_retrain_with_nan() -> Any:
    """NaN veri ile retrain başa çıkmalı."""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features, returns, dates = generate_test_data(n_samples=800, n_features=3)

    # NaN ekle
    features["feat_0"][10] = np.nan
    features["feat_1"][20] = np.inf

    result = engine.validate_and_retrain(
        model_fn=mock_model_fn,
        features_map=features,
        returns=returns,
        dates=dates,
    )

    # NaN temizlenip devam etmeli
    assert result.success is True or "Insufficient" in result.reason
    logger.info(f"✅ Full retrain with NaN: success={result.success}")


def test_full_retrain_history() -> Any:
    """Retrain history doğru tutuluyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features, returns, dates = generate_test_data(n_samples=800, n_features=3)

    # 2 retrain
    for seed in [42, 43]:
        f, r, d = generate_test_data(n_samples=800, n_features=3, seed=seed)
        engine.validate_and_retrain(mock_model_fn, f, r, d)

    assert len(engine._retrain_history) >= 1
    assert engine._retrain_count >= 1
    logger.info(f"✅ Retrain history: {len(engine._retrain_history)} records, {engine._retrain_count} retrains")


# ===================== REPORT =====================


def test_retrain_report_empty() -> Any:
    """Boş rapor doğru mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    report = engine.get_retrain_report()
    assert report["status"] == "No retrain data"
    logger.info("✅ Retrain report empty")


def test_retrain_report_after_retrain() -> Any:
    """Retrain sonrası rapor doğru mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    features, returns, dates = generate_test_data(n_samples=800, n_features=3)
    engine.validate_and_retrain(mock_model_fn, features, returns, dates)

    report = engine.get_retrain_report()
    assert report["status"] == "OK"
    assert "last_retrain" in report
    assert "wf_metrics" in report
    assert report["total_retrains"] >= 1
    logger.info(f"✅ Retrain report: {report['total_retrains']} retrains")


# ===================== CONFIG INTEGRATION =====================


def test_config_wf_params() -> Any:
    """Walk-forward parametreleri config'den okunuyor mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain
    assert cfg.wf_train_size == 252
    assert cfg.wf_test_size == 21
    assert cfg.wf_purge_size == 5
    assert cfg.wf_embargo_size == 5
    assert cfg.wf_step_size == 21
    assert cfg.wf_min_correlation == 0.05
    assert cfg.wf_min_direction_accuracy == 52.0
    logger.info(f"✅ Config WF params: train={cfg.wf_train_size}, test={cfg.wf_test_size}")


def test_config_retrain_thresholds() -> Any:
    """Retrain eşikleri config'den okunuyor mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain
    assert cfg.sharpe_threshold == 0.3
    assert cfg.winrate_threshold == 0.45
    assert cfg.min_samples == 500
    logger.info(f"✅ Config retrain thresholds: sharpe={cfg.sharpe_threshold}, wr={cfg.winrate_threshold}")


# ===================== MAIN =====================


def run_all_tests() -> Any:
    """Otomatik eklendi."""
    tests = [
        test_version_id_unique,
        test_version_id_format,
        test_wf_splits_generation,
        test_wf_splits_insufficient_data,
        test_wf_splits_purge_embargo,
        test_wf_splits_step_size,
        test_prepare_features_dict,
        test_prepare_features_unequal_lengths,
        test_prepare_features_custom_fn,
        test_prepare_features_empty,
        test_evaluate_wf_metrics_pass,
        test_evaluate_wf_metrics_low_correlation,
        test_evaluate_wf_metrics_low_accuracy,
        test_evaluate_wf_metrics_low_pass_rate,
        test_full_retrain_success,
        test_full_retrain_insufficient_data,
        test_full_retrain_with_nan,
        test_full_retrain_history,
        test_retrain_report_empty,
        test_retrain_report_after_retrain,
        test_config_wf_params,
        test_config_retrain_thresholds,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            logger.info(f"❌ {test.__name__}: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 FAZ 3 TEST SONUÇLARI (Retrain Engine)")
    logger.info(f"{'=' * 60}")
    logger.info(f"✅ Geçen: {passed}")
    logger.info(f"❌ Başarısız: {failed}")
    logger.info(f"📈 Toplam: {passed + failed}")

    if errors:
        logger.info("\n🔍 Hatalar:")
        for name, err in errors:
            logger.info(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
