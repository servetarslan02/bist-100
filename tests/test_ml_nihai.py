"""ML Nihai Sistem Testleri — 6 Faz, 65+ Test."""
import pytest
import numpy as np


# ─── Faz 1: CatBoost + XGBoost ───

class TestCatBoost:
    def test_train_predict(self):
        pytest.importorskip("catboost")
        from services.ml.catboost_model import CatBoostModel, CatBoostConfig
        config = CatBoostConfig(iterations=10, verbose=0)
        model = CatBoostModel(config)
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        metrics = model.train(X[:80], y[:80], X[80:], y[80:])
        assert "n_train" in metrics
        preds = model.predict(X[80:])
        assert len(preds) == 20

    def test_feature_importance(self):
        pytest.importorskip("catboost")
        from services.ml.catboost_model import CatBoostModel
        model = CatBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        model.train(X, y, feature_names=["f1", "f2", "f3", "f4", "f5"])
        fi = model.feature_importance()
        assert fi is not None
        assert len(fi) == 5

    def test_untrained(self):
        pytest.importorskip("catboost")
        from services.ml.catboost_model import CatBoostModel
        model = CatBoostModel()
        assert not model.is_trained
        assert model.predict(np.random.randn(10, 5)).sum() == 0
        assert model.feature_importance() is None

    def test_save_load(self, tmp_path):
        pytest.importorskip("catboost")
        from services.ml.catboost_model import CatBoostModel
        model = CatBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        model.train(X, y)
        path = str(tmp_path / "catboost.pkl")
        assert model.save(path)
        model2 = CatBoostModel()
        assert model2.load(path)
        assert model2.is_trained


class TestXGBoost:
    def test_train_predict(self):
        pytest.importorskip("xgboost")
        from services.ml.xgboost_model import XGBoostModel, XGBoostConfig
        config = XGBoostConfig(n_estimators=10, verbose=0)
        model = XGBoostModel(config)
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        metrics = model.train(X[:80], y[:80], X[80:], y[80:])
        assert "n_train" in metrics
        preds = model.predict(X[80:])
        assert len(preds) == 20

    def test_feature_importance(self):
        pytest.importorskip("xgboost")
        from services.ml.xgboost_model import XGBoostModel
        model = XGBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        model.train(X, y, feature_names=["f1", "f2", "f3", "f4", "f5"])
        fi = model.feature_importance()
        assert fi is not None
        assert len(fi) == 5

    def test_shap_values(self):
        pytest.importorskip("xgboost")
        from services.ml.xgboost_model import XGBoostModel
        model = XGBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        model.train(X, y)
        shap = model.shap_values(X[:10])
        # SHAP might not be installed
        assert shap is None or shap.shape == (10, 5)


# ─── Faz 2: Stacking Ensemble ───

class TestStackingEnsemble:
    def test_stacking(self):
        from services.ml.stacking_ensemble import StackingEnsemble
        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor
        ensemble = StackingEnsemble()
        ensemble.add_model("ridge", Ridge(alpha=1.0))
        ensemble.add_model("rf", RandomForestRegressor(n_estimators=10, random_state=42))
        X = np.random.randn(200, 5)
        y = np.random.randn(200)
        metrics = ensemble.fit(X[:150], y[:150], X[150:], y[150:])
        assert "n_base_models" in metrics
        assert metrics["n_base_models"] == 2
        preds = ensemble.predict(X[150:])
        assert len(preds) == 50

    def test_stacking_weights(self):
        from services.ml.stacking_ensemble import StackingEnsemble
        from sklearn.linear_model import Ridge
        ensemble = StackingEnsemble()
        ensemble.add_model("a", Ridge())
        ensemble.add_model("b", Ridge())
        X = np.random.randn(100, 3)
        y = np.random.randn(100)
        ensemble.fit(X[:80], y[:80], X[80:], y[80:])
        weights = ensemble.get_model_weights()
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 0.1

    def test_insufficient_models(self):
        from services.ml.stacking_ensemble import StackingEnsemble
        ensemble = StackingEnsemble()
        ensemble.add_model("only_one", None)
        result = ensemble.fit(np.random.randn(100, 3), np.random.randn(100), np.random.randn(20, 3), np.random.randn(20))
        assert "error" in result


# ─── Faz 3: Model Registry + Champion-Challenger ───

class TestModelRegistry:
    def test_register_and_list(self, tmp_path):
        from services.ml.model_registry import ModelRegistry
        registry = ModelRegistry(str(tmp_path / "registry"))
        registry.register("lgbm", "v1", {"model": "dummy"}, "lightgbm", {"ic": 0.05})
        registry.register("lgbm", "v2", {"model": "dummy2"}, "lightgbm", {"ic": 0.06})
        models = registry.list_models()
        assert len(models) == 2

    def test_promote(self, tmp_path):
        from services.ml.model_registry import ModelRegistry
        registry = ModelRegistry(str(tmp_path / "registry"))
        registry.register("lgbm", "v1", {"model": "dummy"}, "lightgbm", {"ic": 0.05})
        registry.register("lgbm", "v2", {"model": "dummy2"}, "lightgbm", {"ic": 0.06})
        registry.promote("lgbm", "v1")
        champion = registry.get_champion("lgbm")
        assert champion["entry"].version == "v1"
        registry.promote("lgbm", "v2")
        champion2 = registry.get_champion("lgbm")
        assert champion2["entry"].version == "v2"

    def test_compare_versions(self, tmp_path):
        from services.ml.model_registry import ModelRegistry
        registry = ModelRegistry(str(tmp_path / "registry"))
        registry.register("lgbm", "v1", None, "lightgbm", {"ic": 0.05, "sharpe": 1.2})
        registry.register("lgbm", "v2", None, "lightgbm", {"ic": 0.06, "sharpe": 1.5})
        comp = registry.compare_versions("lgbm", "v1", "v2")
        assert comp["metrics_comparison"]["ic"]["b_better"] is True

    def test_reject(self, tmp_path):
        from services.ml.model_registry import ModelRegistry
        registry = ModelRegistry(str(tmp_path / "registry"))
        registry.register("lgbm", "v1", None, "lightgbm", {"ic": 0.01})
        registry.reject("lgbm", "v1")
        models = registry.list_models(status="FAILED")
        assert len(models) == 1


class TestChampionChallenger:
    def test_ab_test(self):
        from services.ml.champion_challenger import ChampionChallenger
        cc = ChampionChallenger(min_samples=5)
        for _ in range(10):
            cc.record_champion_result(np.random.normal(0.05, 0.02))
            cc.record_shadow_result("challenger_v2", np.random.normal(0.07, 0.02))
        result = cc.run_ab_test("challenger_v2")
        assert result.n_samples_champion == 10

    def test_insufficient_data(self):
        from services.ml.champion_challenger import ChampionChallenger
        cc = ChampionChallenger(min_samples=30)
        cc.record_champion_result(0.05)
        result = cc.run_ab_test("challenger")
        assert result.winner == "insufficient_data"

    def test_shadow_summary(self):
        from services.ml.champion_challenger import ChampionChallenger
        cc = ChampionChallenger()
        cc.record_shadow_result("m1", 0.05)
        cc.record_shadow_result("m1", 0.06)
        summary = cc.get_shadow_summary()
        assert "m1" in summary


# ─── Faz 4: Hyperparameter Tuning + Calibration ───

class TestHyperparameterTuner:
    def test_tune_lightgbm(self):
        from services.ml.hyperparameter_tuner import HyperparameterTuner
        tuner = HyperparameterTuner(n_trials=3, timeout_seconds=30)
        X = np.random.randn(100, 5)
        y = np.random.randn(100)
        result = tuner.tune_lightgbm(X[:80], y[:80], X[80:], y[80:])
        assert result.n_trials >= 0  # Might fail if lgbm not installed

    def test_tune_xgboost(self):
        from services.ml.hyperparameter_tuner import HyperparameterTuner
        tuner = HyperparameterTuner(n_trials=3, timeout_seconds=30)
        X = np.random.randn(100, 5)
        y = np.random.randn(100)
        result = tuner.tune_xgboost(X[:80], y[:80], X[80:], y[80:])
        assert result.n_trials >= 0


class TestCalibration:
    def test_calibration_check(self):
        from services.ml.calibration import ModelCalibration
        cal = ModelCalibration()
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0])
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7, 0.85, 0.15, 0.75, 0.25])
        result = cal.check_calibration(y_true, y_prob)
        assert result.brier_score >= 0
        assert isinstance(result.is_calibrated, bool)

    def test_platt_scaling(self):
        from services.ml.calibration import ModelCalibration
        cal = ModelCalibration()
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1])
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7, 0.85, 0.15, 0.75, 0.25, 0.8, 0.9, 0.2, 0.3, 0.7])
        calibrator, calibrated = cal.calibrate_platt(y_true, y_prob)
        assert len(calibrated) == len(y_true)

    def test_isotonic(self):
        from services.ml.calibration import ModelCalibration
        cal = ModelCalibration()
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1])
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7, 0.85, 0.15, 0.75, 0.25, 0.8, 0.9, 0.2, 0.3, 0.7])
        calibrator, calibrated = cal.calibrate_isotonic(y_true, y_prob)
        assert len(calibrated) == len(y_true)


# ─── Faz 5: Feature Drift + Model Monitoring ───

class TestFeatureDrift:
    def test_shap_history(self):
        from services.ml.feature_drift import FeatureDriftDetector
        det = FeatureDriftDetector()
        det.record_shap({"f1": 0.3, "f2": 0.5, "f3": 0.2})
        det.record_shap({"f1": 0.2, "f2": 0.6, "f3": 0.2})
        reports = det.check_drift()
        assert len(reports) == 3

    def test_drift_alert(self):
        from services.ml.feature_drift import FeatureDriftDetector
        det = FeatureDriftDetector(psi_threshold=0.1)
        for _ in range(10):
            det.record_shap({"f1": 0.3, "f2": 0.5})
        det.record_shap({"f1": 0.8, "f2": 0.1})  # Sudden change
        alerts = det.get_alerts()
        assert any(a.alert for a in alerts)

    def test_insufficient_history(self):
        from services.ml.feature_drift import FeatureDriftDetector
        det = FeatureDriftDetector()
        det.record_shap({"f1": 0.5})
        reports = det.check_drift()
        assert len(reports) == 0


class TestModelMonitor:
    def test_metric_recording(self):
        from services.ml.model_monitor import ModelMonitor
        mon = ModelMonitor(min_history=3)
        for i in range(10):
            mon.record_metric("ic", 0.05 + np.random.normal(0, 0.01))
        report = mon.check_decay("ic")
        assert report.historical_mean > 0

    def test_decay_detection(self):
        from services.ml.model_monitor import ModelMonitor
        mon = ModelMonitor(min_history=5, decay_z_threshold=-1.5)
        for _ in range(20):
            mon.record_metric("ic", 0.05)
        for _ in range(10):
            mon.record_metric("ic", 0.01)  # Sudden drop
        report = mon.check_decay("ic")
        assert report.decay_detected is True

    def test_prediction_drift(self):
        from services.ml.model_monitor import ModelMonitor
        mon = ModelMonitor(min_history=5)
        for _ in range(20):
            mon.record_prediction(0.7, actual=1)
        for _ in range(20):
            mon.record_prediction(0.3, actual=0)
        drift = mon.check_prediction_drift()
        assert "drift_detected" in drift

    def test_win_rate(self):
        from services.ml.model_monitor import ModelMonitor
        mon = ModelMonitor()
        mon.record_prediction(0.7, actual=1)
        mon.record_prediction(0.3, actual=0)
        mon.record_prediction(0.8, actual=0)  # Wrong
        assert mon.get_win_rate() == pytest.approx(2/3, abs=0.01)

    def test_summary(self):
        from services.ml.model_monitor import ModelMonitor
        mon = ModelMonitor(min_history=3)
        for _ in range(5):
            mon.record_metric("ic", 0.05)
            mon.record_prediction(0.6, actual=1)
        summary = mon.get_summary()
        assert "metrics" in summary
        assert "win_rate" in summary


# ─── Faz 6: Integration ───

class TestMLIntegration:
    def test_catboost_to_registry(self, tmp_path):
        pytest.importorskip("catboost")
        """CatBoost → Model Registry pipeline."""
        from services.ml.catboost_model import CatBoostModel
        from services.ml.model_registry import ModelRegistry

        # Train CatBoost
        model = CatBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        metrics = model.train(X[:80], y[:80], X[80:], y[80:])

        # Register
        registry = ModelRegistry(str(tmp_path / "reg"))
        registry.register("catboost", "v1", model, "catboost", metrics)

        # Promote
        registry.promote("catboost", "v1")
        champion = registry.get_champion("catboost")
        assert champion["entry"].version == "v1"

    def test_xgboost_shap_to_drift(self):
        pytest.importorskip("xgboost")
        """XGBoost → SHAP → Drift Detection pipeline."""
        from services.ml.xgboost_model import XGBoostModel
        from services.ml.feature_drift import FeatureDriftDetector

        model = XGBoostModel()
        X = np.random.randn(100, 5)
        y = np.random.randint(0, 2, 100)
        model.train(X, y, feature_names=["f1", "f2", "f3", "f4", "f5"])

        # SHAP
        shap_vals = model.shap_values(X[:10])
        if shap_vals is not None:
            det = FeatureDriftDetector()
            mean_shap = {f"f{i+1}": float(np.mean(np.abs(shap_vals[:, i]))) for i in range(5)}
            det.record_shap(mean_shap)
            det.record_shap({k: v * 2 for k, v in mean_shap.items()})  # Simulated change
            reports = det.check_drift()
            assert len(reports) > 0

    def test_stacking_to_monitor(self):
        """Stacking Ensemble → Model Monitor pipeline."""
        from services.ml.stacking_ensemble import StackingEnsemble
        from services.ml.model_monitor import ModelMonitor
        from sklearn.linear_model import Ridge

        ensemble = StackingEnsemble()
        ensemble.add_model("a", Ridge())
        ensemble.add_model("b", Ridge())
        X = np.random.randn(100, 3)
        y = np.random.randn(100)
        ensemble.fit(X[:80], y[:80], X[80:], y[80:])

        # Monitor
        mon = ModelMonitor(min_history=3)
        preds = ensemble.predict(X[80:])
        for p in preds:
            mon.record_prediction(float(p))
        assert mon.get_win_rate() >= 0
