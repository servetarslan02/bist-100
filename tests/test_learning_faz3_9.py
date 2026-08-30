import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Learning System Faz 3-9 Test Suite

Test edilen:
- Faz 3: Retrain Engine (Walk-forward integration)
- Faz 4: Feature Importance Tracker
- Faz 5: Shadow Mode + Champion-Challenger
- Faz 6: Model Registry
- Faz 7: Meta Learner
- Faz 8: Health Monitor
"""

import sys
from datetime import UTC

# ===================== FAZ 3: RETRAIN ENGINE =====================


def test_retrain_engine_init() -> Any:
    """Retrain engine başlatılıyor mu?"""
    from services.learning.retrain_engine import retrain_engine

    assert retrain_engine is not None
    report = retrain_engine.get_retrain_report()
    assert report["status"] == "No retrain data"
    logger.info("✅ Retrain engine init")


def test_retrain_engine_version_id() -> Any:
    """Version ID üretiliyor mu?"""
    from services.learning.retrain_engine import RetrainEngine

    engine = RetrainEngine()
    vid = engine._generate_version_id()
    assert vid.startswith("retrain_")
    assert len(vid) > 10
    logger.info(f"✅ Version ID: {vid}")


# ===================== FAZ 4: FEATURE TRACKER =====================


def test_feature_tracker_init() -> Any:
    """Feature tracker başlatılıyor mu?"""
    from services.learning.feature_tracker import feature_importance_tracker

    assert feature_importance_tracker is not None
    report = feature_importance_tracker.get_report()
    assert report["status"] == "OK"
    logger.info("✅ Feature tracker init")


def test_feature_tracker_trends() -> Any:
    """Feature trends çalışıyor mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    # Manuel veri ekle
    from datetime import datetime, timedelta

    for i in range(10):
        date = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
        tracker._history.append(
            type(
                "Record",
                (),
                {
                    "date": date,
                    "feature": "rsi_14",
                    "importance": 0.1 + i * 0.01,
                    "regime": "BULL",
                    "model_version": "v1",
                },
            )()
        )

    trends = tracker.get_trends(top_n=5)
    assert isinstance(trends, dict)
    logger.info(f"✅ Feature trends: {len(trends)} features")


def test_feature_tracker_report() -> Any:
    """Feature tracker raporu doğru mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    report = tracker.get_report()
    assert report["status"] == "OK"
    assert "total_records" in report
    logger.info("✅ Feature tracker report")


# ===================== FAZ 5: SHADOW MODE =====================


def test_shadow_manager_init() -> Any:
    """Shadow manager başlatılıyor mu?"""
    from services.learning.shadow_manager import shadow_manager

    assert shadow_manager is not None
    status = shadow_manager.get_status()
    assert status["active"] is False
    logger.info("✅ Shadow manager init")


def test_shadow_start_stop() -> Any:
    """Shadow mode başlat/durdur."""
    from services.learning.shadow_manager import ShadowModeManager

    manager = ShadowModeManager()
    manager.start_shadow("champion_v1", "challenger_v2")
    assert manager._shadow_active is True
    assert manager._champion_id == "champion_v1"

    manager.stop_shadow()
    assert manager._shadow_active is False
    logger.info("✅ Shadow start/stop")


def test_shadow_record_prediction() -> Any:
    """Shadow prediction kayıt."""
    from services.learning.shadow_manager import ShadowModeManager

    manager = ShadowModeManager()
    manager.start_shadow("c1", "c2")

    manager.record_prediction(
        "THYAO",
        {"direction": "LONG", "confidence": 0.8},
        {"direction": "LONG", "confidence": 0.85},
    )
    assert len(manager._predictions) == 1
    logger.info("✅ Shadow record prediction")


def test_shadow_evaluate_insufficient() -> Any:
    """Shadow evaluation yetersiz veri."""
    from services.learning.shadow_manager import ShadowModeManager

    manager = ShadowModeManager()
    manager.start_shadow("c1", "c2")

    result = manager.evaluate()
    assert result is None  # Yeterli veri yok
    logger.info("✅ Shadow evaluate insufficient")


def test_champion_challenger_init() -> Any:
    """Champion-challenger başlatılıyor mu?"""
    from services.learning.champion_challenger import champion_challenger

    assert champion_challenger is not None
    report = champion_challenger.get_report()
    assert report["current_champion"] is None
    logger.info("✅ Champion-challenger init")


def test_champion_challenger_promote() -> Any:
    """Champion promote çalışıyor mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("model_v2", "v2", {"sharpe": 1.5}, regime="BULL")

    champion = engine.get_champion()
    assert champion is not None
    assert champion.model_id == "model_v2"
    logger.info("✅ Champion promote")


def test_champion_challenger_reject() -> Any:
    """Champion reject çalışıyor mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.reject("model_v3", "Low performance", {"sharpe": 0.1})

    assert len(engine._rejected_challengers) == 1
    logger.info("✅ Champion reject")


def test_champion_challenger_rollback() -> Any:
    """Champion rollback çalışıyor mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("model_v1", "v1", {"sharpe": 1.0})
    engine.promote("model_v2", "v2", {"sharpe": 1.5})

    # Rollback to v1
    result = engine.rollback("v1")
    assert result is True
    assert engine.get_champion().version == "v1"
    logger.info("✅ Champion rollback")


# ===================== FAZ 6: MODEL REGISTRY =====================


def test_model_registry_init() -> Any:
    """Model registry başlatılıyor mu?"""
    from services.learning.model_registry import model_registry

    assert model_registry is not None
    report = model_registry.get_report()
    assert report["total_versions"] == 0
    logger.info("✅ Model registry init")


def test_model_registry_register() -> Any:
    """Model kayıt çalışıyor mu?"""
    from services.learning.model_registry import ModelRegistry

    registry = ModelRegistry()
    record = registry.register(
        model_id="lgbm_v1",
        version="v1.0",
        metrics={"sharpe": 1.2, "ic": 0.05},
        features=["rsi", "momentum"],
        hyperparameters={"n_estimators": 100},
        training_data_info={"samples": 1000},
        regime="BULL",
    )

    assert record.model_id == "lgbm_v1"
    assert record.status == "CANDIDATE"
    logger.info("✅ Model register")


def test_model_registry_promote() -> Any:
    """Model promote çalışıyor mu?"""
    from services.learning.model_registry import ModelRegistry

    registry = ModelRegistry()
    registry.register("m1", "v1", {}, [], {}, {}, status="CANDIDATE")
    registry.promote_to_champion("v1")

    champion = registry.get_champion()
    assert champion is not None
    assert champion.status == "CHAMPION"
    logger.info("✅ Model registry promote")


def test_model_registry_rollback() -> Any:
    """Model rollback çalışıyor mu?"""
    from services.learning.model_registry import ModelRegistry

    registry = ModelRegistry()
    registry.register("m1", "v1", {}, [], {}, {}, status="CANDIDATE")
    registry.promote_to_champion("v1")
    registry.register("m2", "v2", {}, [], {}, {}, status="CANDIDATE")
    registry.promote_to_champion("v2")

    # Rollback
    result = registry.rollback("v1")
    assert result is True
    logger.info("✅ Model registry rollback")


def test_model_registry_versions() -> Any:
    """Model versions listesi doğru mu?"""
    from services.learning.model_registry import ModelRegistry

    registry = ModelRegistry()
    registry.register("m1", "v1", {}, [], {}, {})
    registry.register("m2", "v2", {}, [], {}, {})

    versions = registry.get_all_versions()
    assert len(versions) == 2
    logger.info("✅ Model registry versions")


# ===================== FAZ 7: META LEARNER =====================


def test_meta_learner_init() -> Any:
    """Meta learner başlatılıyor mu?"""
    from services.learning.meta_learner import meta_learner

    assert meta_learner is not None
    report = meta_learner.get_report()
    assert report["total_records"] == 0
    logger.info("✅ Meta learner init")


def test_meta_learner_record() -> Any:
    """Meta learner performans kayıt."""
    from services.learning.meta_learner import MetaLearner

    learner = MetaLearner()
    learner.record_performance("model_v1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    learner.record_performance("model_v1", "BULL", {"sharpe": 1.3, "win_rate": 0.58, "ic": 0.04})

    assert len(learner._model_history) == 2
    logger.info("✅ Meta learner record")


def test_meta_learner_select_best() -> Any:
    """Meta learner en iyi model seçimi."""
    from services.learning.meta_learner import MetaLearner

    learner = MetaLearner()
    learner.record_performance("model_v1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    learner.record_performance("model_v2", "BULL", {"sharpe": 0.8, "win_rate": 0.52, "ic": 0.03})

    best = learner.select_best_model("BULL")
    assert best == "model_v1"
    logger.info(f"✅ Meta learner select best: {best}")


def test_meta_learner_ensemble_weights() -> Any:
    """Meta learner ensemble weights doğru mu?"""
    from services.learning.meta_learner import MetaLearner

    learner = MetaLearner()
    learner.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    learner.record_performance("m2", "BULL", {"sharpe": 0.5, "win_rate": 0.5, "ic": 0.02})

    weights = learner.calculate_ensemble_weights(["m1", "m2"], "BULL")
    assert weights["m1"] > weights["m2"]
    assert abs(sum(weights.values()) - 1.0) < 0.01
    logger.info(f"✅ Ensemble weights: {weights}")


def test_meta_learner_decay_prediction() -> Any:
    """Meta learner decay prediction."""
    from services.learning.meta_learner import MetaLearner

    learner = MetaLearner()
    # Azalan performans
    for i in range(40):
        learner.record_performance("model_v1", "BULL", {"sharpe": 1.5 - i * 0.03, "win_rate": 0.6, "ic": 0.05})

    result = learner.predict_decay("model_v1")
    logger.info(f"✅ Decay prediction: {result}")


def test_meta_learner_regime_summary() -> Any:
    """Meta learner regime summary doğru mu?"""
    from services.learning.meta_learner import MetaLearner

    learner = MetaLearner()
    learner.record_performance("m1", "BULL", {"sharpe": 1.5, "win_rate": 0.6, "ic": 0.05})
    learner.record_performance("m1", "BEAR", {"sharpe": 0.3, "win_rate": 0.45, "ic": 0.01})

    summary = learner.get_regime_summary()
    assert "BULL" in summary
    assert "BEAR" in summary
    logger.info(f"✅ Regime summary: {list(summary.keys())}")


# ===================== FAZ 8: HEALTH MONITOR =====================


def test_health_monitor_init() -> Any:
    """Health monitor başlatılıyor mu?"""
    from services.learning.health_monitor import learning_health_monitor

    assert learning_health_monitor is not None
    report = learning_health_monitor.get_report()
    assert report["status"] == "OK"
    logger.info("✅ Health monitor init")


def test_health_check() -> Any:
    """Health check çalışıyor mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    monitor = LearningHealthMonitor()
    report = monitor.check_health()
    assert report.overall_status in ["HEALTHY", "WARNING", "CRITICAL"]
    assert len(report.modules) > 0
    logger.info(f"✅ Health check: {report.overall_status}, modules: {len(report.modules)}")


def test_health_restart_request() -> Any:
    """Restart request çalışıyor mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    monitor = LearningHealthMonitor()
    monitor.request_restart("test_module")

    requests = monitor.get_restart_requests()
    assert "test_module" in requests

    # İkinci çağrıda temizlenmiş olmalı
    requests2 = monitor.get_restart_requests()
    assert len(requests2) == 0
    logger.info("✅ Health restart request")


def test_health_error_recording() -> Any:
    """Hata kaydetme çalışıyor mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    monitor = LearningHealthMonitor()
    monitor.record_error("test_module", "Test error")

    assert len(monitor._error_history) == 1
    assert monitor._error_history[0]["module"] == "test_module"
    logger.info("✅ Health error recording")


# ===================== MAIN =====================


def run_all_tests() -> Any:
    """Tüm testleri çalıştır."""
    tests = [
        # Faz 3
        test_retrain_engine_init,
        test_retrain_engine_version_id,
        # Faz 4
        test_feature_tracker_init,
        test_feature_tracker_trends,
        test_feature_tracker_report,
        # Faz 5
        test_shadow_manager_init,
        test_shadow_start_stop,
        test_shadow_record_prediction,
        test_shadow_evaluate_insufficient,
        test_champion_challenger_init,
        test_champion_challenger_promote,
        test_champion_challenger_reject,
        test_champion_challenger_rollback,
        # Faz 6
        test_model_registry_init,
        test_model_registry_register,
        test_model_registry_promote,
        test_model_registry_rollback,
        test_model_registry_versions,
        # Faz 7
        test_meta_learner_init,
        test_meta_learner_record,
        test_meta_learner_select_best,
        test_meta_learner_ensemble_weights,
        test_meta_learner_decay_prediction,
        test_meta_learner_regime_summary,
        # Faz 8
        test_health_monitor_init,
        test_health_check,
        test_health_restart_request,
        test_health_error_recording,
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
    logger.info("📊 FAZ 3-9 TEST SONUÇLARI")
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
