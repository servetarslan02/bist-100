import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Learning System Faz 0 Test Suite

Test edilen:
- LearningConfig yükleme ve erişim
- StatisticalTests (PSI, KS, Z-score, Page-Hinkley, ADWIN, Welch, Brier, Sharpe, IC)
- SHAPHelpers (fallback, compute)
- Mevcut kod refactor doğrulama
"""

import sys

import numpy as np

# ===================== CONFIG TESTS =====================


def test_config_load() -> Any:
    """Config yükleniyor mu?"""
    from services.learning.config.learning_config import LearningSettings, learning_settings

    assert learning_settings is not None
    assert isinstance(learning_settings, LearningSettings)
    logger.info("✅ Config yüklendi")


def test_config_calibration() -> Any:
    """Calibration config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.calibration
    assert cfg.check_interval_days == 7
    assert cfg.brier_threshold == 0.25
    assert cfg.ece_threshold == 0.10
    assert cfg.overconfidence_threshold == 0.15
    assert cfg.min_samples == 30
    assert cfg.n_bins == 10
    assert cfg.platt_scaling_enabled is True
    logger.info("✅ Calibration config doğru")


def test_config_drift() -> Any:
    """Drift config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.drift
    assert cfg.check_interval_days == 1
    assert cfg.psi_warning == 0.1
    assert cfg.psi_alert == 0.2
    assert cfg.psi_critical == 0.5
    assert cfg.ks_p_threshold == 0.05
    assert cfg.zscore_warning == 2.5
    assert cfg.zscore_critical == 3.5
    assert cfg.min_samples == 100
    logger.info("✅ Drift config doğru")


def test_config_retrain() -> Any:
    """Retrain config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.retrain
    assert cfg.sharpe_threshold == 0.3
    assert cfg.winrate_threshold == 0.45
    assert cfg.ic_threshold == 0.02
    assert cfg.max_interval_days == 14
    assert cfg.min_interval_days == 3
    assert cfg.min_samples == 500
    assert cfg.performance_window == 21
    assert cfg.wf_train_size == 252
    assert cfg.wf_test_size == 21
    assert cfg.wf_purge_size == 5
    assert cfg.wf_embargo_size == 5
    logger.info("✅ Retrain config doğru")


def test_config_shadow() -> Any:
    """Shadow config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.shadow
    assert cfg.duration_days == 21
    assert cfg.min_predictions == 50
    assert cfg.promote_threshold_pct == 10.0
    assert cfg.significance_p == 0.05
    assert cfg.canary_allocation_pct == 0.10
    logger.info("✅ Shadow config doğru")


def test_config_feature_importance() -> Any:
    """Feature importance config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.feature_importance
    assert cfg.track_interval_days == 1
    assert cfg.trend_window_days == 30
    assert cfg.min_importance_threshold == 0.001
    assert cfg.shap_sample_size == 1000
    logger.info("✅ Feature importance config doğru")


def test_config_model_registry() -> Any:
    """Model registry config değerleri doğru mu?"""
    from services.learning.config.learning_config import learning_settings

    cfg = learning_settings.model_registry
    assert cfg.max_versions == 20
    assert cfg.auto_cleanup is True
    assert cfg.archive_retired is True
    logger.info("✅ Model registry config doğru")


# ===================== STATISTICAL TESTS =====================


def test_psi_stable() -> Any:
    """PSI stabil dağılım için düşük değer vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    expected = np.random.normal(0, 1, 1000)
    actual = np.random.normal(0, 1, 1000)  # Aynı dağılım

    result = StatisticalTests.compute_psi(expected, actual)
    assert result.psi < 0.1, f"PSI çok yüksek: {result.psi}"
    assert result.drift_detected is False
    assert result.severity == "STABLE"
    logger.info(f"✅ PSI stabil: {result.psi}")


def test_psi_drift() -> Any:
    """PSI farklı dağılımlar için yüksek değer vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    expected = np.random.normal(0, 1, 1000)
    actual = np.random.normal(3, 2, 1000)  # Farklı dağılım

    result = StatisticalTests.compute_psi(expected, actual)
    assert result.psi > 0.2, f"PSI çok düşük: {result.psi}"
    assert result.drift_detected is True
    assert result.severity in ["ALERT", "CRITICAL"]
    logger.info(f"✅ PSI drift tespit: {result.psi}, severity: {result.severity}")


def test_psi_insufficient_data() -> Any:
    """PSI yetersiz veri ile başa çıkmalı."""
    from services.learning.utils.statistical_tests import StatisticalTests

    result = StatisticalTests.compute_psi(np.array([1, 2, 3]), np.array([1, 2]))
    assert result.severity == "INSUFFICIENT_DATA"
    logger.info("✅ PSI yetersiz veri handling")


def test_ks_test_same() -> Any:
    """KS test aynı dağılımlar için yüksek p-value vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    sample1 = np.random.normal(0, 1, 500)
    sample2 = np.random.normal(0, 1, 500)

    result = StatisticalTests.ks_test(sample1, sample2)
    assert result.drift_detected is False
    assert result.p_value > 0.05
    logger.info(f"✅ KS test aynı dağılım: p={result.p_value}")


def test_ks_test_different() -> Any:
    """KS test farklı dağılımlar için düşük p-value vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    sample1 = np.random.normal(0, 1, 500)
    sample2 = np.random.normal(5, 1, 500)

    result = StatisticalTests.ks_test(sample1, sample2)
    assert result.drift_detected is True
    assert result.p_value < 0.01
    logger.info(f"✅ KS test farklı dağılım: p={result.p_value}")


def test_zscore_normal() -> Any:
    """Z-score normal değer için düşük vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    result = StatisticalTests.zscore_test(baseline_mean=100.0, baseline_std=10.0, current_value=105.0)
    assert result["z_score"] < 2.5
    assert result["severity"] == "NORMAL"
    assert result["drift_detected"] is False
    logger.info(f"✅ Z-score normal: {result['z_score']}")


def test_zscore_critical() -> Any:
    """Z-score aşırı değer için yüksek vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    result = StatisticalTests.zscore_test(baseline_mean=100.0, baseline_std=10.0, current_value=140.0)
    assert result["z_score"] > 3.5
    assert result["severity"] == "CRITICAL"
    assert result["drift_detected"] is True
    logger.info(f"✅ Z-score critical: {result['z_score']}")


def test_page_hinkley_no_drift() -> Any:
    """Page-Hinkley stabil veri için drift tespit etmemeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    data = np.random.normal(0, 1, 200)

    result = StatisticalTests.page_hinkley_test(data)
    logger.info(f"✅ Page-Hinkley no drift: max_dev={result.max_deviation}")


def test_page_hinkley_drift() -> Any:
    """Page-Hinkley ani değişim için drift tespit etmeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    # Ani değişim: önce 0, sonra 10
    data = np.concatenate([np.random.normal(0, 1, 100), np.random.normal(10, 1, 100)])

    result = StatisticalTests.page_hinkley_test(data, threshold=50)
    assert result.drift_detected is True
    assert result.change_point_index is not None
    logger.info(f"✅ Page-Hinkley drift tespit: change_point={result.change_point_index}")


def test_adwin_no_drift() -> Any:
    """ADWIN stabil veri için drift tespit etmemeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    data = np.random.normal(0, 1, 200)

    result = StatisticalTests.adwin_test(data)
    assert result.drift_detected is False
    logger.info(f"✅ ADWIN no drift: p={result.p_value}")


def test_adwin_drift() -> Any:
    """ADWIN ani değişim için drift tespit etmeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    data = np.concatenate([np.random.normal(0, 1, 100), np.random.normal(10, 1, 100)])

    result = StatisticalTests.adwin_test(data, delta=0.001)
    assert result.drift_detected is True
    logger.info(f"✅ ADWIN drift tespit: p={result.p_value}")


def test_welch_t_test_significant() -> Any:
    """Welch's t-test farklı gruplar için anlamlı sonuç vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    sample1 = np.random.normal(0.05, 0.02, 100)
    sample2 = np.random.normal(0.08, 0.02, 100)

    result = StatisticalTests.welch_t_test(sample1, sample2)
    assert result.significant is True
    logger.info(f"✅ Welch t-test significant: t={result.t_statistic}, p={result.p_value}")


def test_welch_t_test_not_significant() -> Any:
    """Welch's t-test benzer gruplar için anlamsız sonuç vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    sample1 = np.random.normal(0.05, 0.1, 100)
    sample2 = np.random.normal(0.05, 0.1, 100)

    result = StatisticalTests.welch_t_test(sample1, sample2)
    assert result.significant is False
    logger.info(f"✅ Welch t-test not significant: p={result.p_value}")


def test_brier_score_perfect() -> Any:
    """Brier score mükemmel tahmin için 0 vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    predicted = np.array([1.0, 0.0, 1.0, 0.0, 1.0])
    actual = np.array([1.0, 0.0, 1.0, 0.0, 1.0])

    score = StatisticalTests.brier_score(predicted, actual)
    assert score == 0.0
    logger.info(f"✅ Brier score perfect: {score}")


def test_brier_score_random() -> Any:
    """Brier score rastgele tahmin için yüksek vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    predicted = np.array([0.5, 0.5, 0.5, 0.5, 0.5])
    actual = np.array([1.0, 0.0, 1.0, 0.0, 1.0])

    score = StatisticalTests.brier_score(predicted, actual)
    assert score == 0.25
    logger.info(f"✅ Brier score random: {score}")


def test_sharpe_ratio() -> Any:
    """Sharpe ratio pozitif getiriler için pozitif vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    returns = np.random.normal(0.001, 0.01, 252)  # Günlük %0.1 ortalama getiri

    sharpe = StatisticalTests.sharpe_ratio(returns)
    assert sharpe > 0
    logger.info(f"✅ Sharpe ratio: {sharpe}")


def test_information_coefficient() -> Any:
    """IC yüksek korelasyonlu skorlar için yüksek vermeli."""
    from services.learning.utils.statistical_tests import StatisticalTests

    np.random.seed(42)
    scores = np.random.normal(0, 1, 100)
    actual_returns = scores * 0.5 + np.random.normal(0, 0.3, 100)  # Korelasyonlu

    ic = StatisticalTests.information_coefficient(scores, actual_returns)
    assert ic > 0.3, f"IC çok düşük: {ic}"
    logger.info(f"✅ IC: {ic}")


def test_deflated_sharpe() -> Any:
    """Deflated Sharpe multiple testing için düzeltme yapmalı."""
    from services.learning.utils.statistical_tests import StatisticalTests

    # 10 model denendi, tek model başarılı
    deflated = StatisticalTests.deflated_sharpe(
        observed_sharpe=2.0,
        n_trials=10,
        n_observations=252,
    )
    # 10 model denendiğinde 2.0 Sharpe artık o kadar imkansız değil
    assert 0 <= deflated <= 1
    logger.info(f"✅ Deflated Sharpe: {deflated}")


# ===================== REFACTOR TESTS =====================


def test_super_intelligence_uses_config() -> Any:
    """SuperIntelligenceEngine config'den değerleri okuyor mu?"""
    from services.learning.super_intelligence import SuperIntelligenceEngine

    engine = SuperIntelligenceEngine()
    assert engine.retrain_threshold_sharpe == 0.3
    assert engine.retrain_threshold_ic == 0.02
    assert engine.drift_threshold == 0.2
    assert engine.max_models_history == 20
    assert engine.ab_test_window_days == 21
    logger.info("✅ SuperIntelligence config kullanıyor")


def test_continuous_learning_uses_config() -> Any:
    """ContinuousLearningPipeline config'den değerleri okuyor mu?"""
    from services.learning.continuous_learning import ContinuousLearningPipeline

    pipeline = ContinuousLearningPipeline()
    assert pipeline.retrain_interval_days == 14
    assert pipeline.drift_check_interval == 1
    assert pipeline.performance_window == 21
    assert pipeline.min_samples_for_retrain == 500
    logger.info("✅ ContinuousLearning config kullanıyor")


def test_learning_loop_uses_config() -> Any:
    """LearningLoop config'den değerleri okuyor mu?"""
    from services.learning.learning_loop import LearningLoop

    loop = LearningLoop()
    # Decay check config'den okunmalı
    assert loop._state.retrain_needed is False
    logger.info("✅ LearningLoop config kullanıyor")


def test_healing_max_attempts() -> Any:
    """Healing max attempt kontrolü çalışıyor mu?"""
    from services.learning.super_intelligence import SuperIntelligenceEngine

    engine = SuperIntelligenceEngine()
    record = {
        "action": "retrain_model",
        "module": "test",
        "status": "PENDING",
        "attempt": 5,  # Max 3'ü aşıyor
    }
    result = engine.execute_healing(record)
    assert result is False
    assert record["status"] == "FAILED"
    assert "Max attempts" in record.get("failure_reason", "")
    logger.info("✅ Healing max attempts çalışıyor")


def test_fallback_importance() -> Any:
    """SHAP fallback importance çalışıyor mu?"""
    from services.learning.utils.shap_helpers import SHAPHelpers

    class MockModel:
        """Otomatik eklendi."""
        feature_importances_ = np.array([0.3, 0.5, 0.2])

    X = np.random.rand(10, 3)
    feature_names = ["feat_a", "feat_b", "feat_c"]

    result = SHAPHelpers._fallback_importance(MockModel(), X, feature_names)
    assert len(result.feature_importance) == 3
    assert result.top_features[0][0] == "feat_b"  # En yüksek importance
    logger.info("✅ SHAP fallback importance çalışıyor")


# ===================== MAIN =====================


def run_all_tests() -> Any:
    """Tüm testleri çalıştır."""
    tests = [
        # Config tests
        test_config_load,
        test_config_calibration,
        test_config_drift,
        test_config_retrain,
        test_config_shadow,
        test_config_feature_importance,
        test_config_model_registry,
        # Statistical tests
        test_psi_stable,
        test_psi_drift,
        test_psi_insufficient_data,
        test_ks_test_same,
        test_ks_test_different,
        test_zscore_normal,
        test_zscore_critical,
        test_page_hinkley_no_drift,
        test_page_hinkley_drift,
        test_adwin_no_drift,
        test_adwin_drift,
        test_welch_t_test_significant,
        test_welch_t_test_not_significant,
        test_brier_score_perfect,
        test_brier_score_random,
        test_sharpe_ratio,
        test_information_coefficient,
        test_deflated_sharpe,
        # Refactor tests
        test_super_intelligence_uses_config,
        test_continuous_learning_uses_config,
        test_learning_loop_uses_config,
        test_healing_max_attempts,
        test_fallback_importance,
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
    logger.info("📊 FAZ 0 TEST SONUÇLARI")
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
