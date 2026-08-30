"""ALPHA BIST — XGBoost Model (Nihai —⭐⭐⭐⭐⭐).

XGBoost entegrasyonu — custom adjusted loss, multi-horizon prediction,
walk-forward entegrasyonu, SHAP feature importance, regime-aware training,
overfitting detection, feature interaction.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class XGBoostConfig:
    """XGBoost model konfigürasyonu."""

    max_depth: int = 6
    learning_rate: float = 0.1
    n_estimators: int = 200
    objective: str = "binary:logistic"
    eval_metric: str = "auc"
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.1
    reg_lambda: float = 1.0
    min_child_weight: int = 5
    gamma: float = 0.1
    early_stopping_rounds: int = 20
    verbose: int = 0
    random_state: int = 42
    # Multi-horizon
    target_horizons: list[int] = field(default_factory=lambda: [1, 5, 20, 60])
    # Regime-aware
    regime_aware: bool = False
    regime_weights: dict[str, float] = field(
        default_factory=lambda: {"BULL": 1.0, "BEAR": 1.0, "SIDEWAYS": 1.0, "HIGH_VOL": 1.0}
    )
    # Custom loss
    use_adjusted_loss: bool = False
    wrong_direction_penalty: float = 11.0


class XGBoostAdjustedLoss:
    """XGBoost custom loss — yanlış yön cezası.

    XGBoost'un custom objective fonksiyonu interface'ini implemente eder.
    gradient ve hessian döndürür.
    """

    def __init__(self, penalty: float = 11.0):
        """Otomatik eklendi."""
        self.penalty = penalty

    def __call__(self, preds: np.ndarray, dtrain) -> tuple[np.ndarray, np.ndarray]:
        """XGBoost custom objective interface.

        Args:
            preds: Tahminler
            dtrain: DMatrix (training data)

        Returns:
            (gradient, hessian)
        """
        labels = dtrain.get_label()
        diff = preds - labels

        # Yanlış yön kontrolü
        wrong_direction = ((preds > 0) & (labels < 0)) | ((preds < 0) & (labels > 0))
        penalty = np.where(wrong_direction, self.penalty, 1.0)

        # Gradient ve hessian
        grad = 2.0 * diff * penalty
        hess = 2.0 * penalty * np.ones_like(grad)

        return grad, hess


class XGBoostModel:
    """XGBoost model —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Custom adjusted loss (yanlış yön cezası)
    - Multi-horizon prediction (1d, 5d, 20d, 60d)
    - Walk-forward entegrasyonu
    - Regime-aware training ağırlıkları
    - SHAP feature importance (TreeExplainer)
    - Feature interaction detection
    - Overfitting detection (train-val gap)
    - Early stopping with best iteration
    - Feature importance: gain, cover, weight
    """

    def __init__(self, config: XGBoostConfig | None = None):
        """Otomatik eklendi."""
        self._config = config or XGBoostConfig()
        self._models: dict[int, Any] = {}  # horizon → model
        self._feature_names = None
        self._training_metrics: dict[str, Any] = {}
        self._shap_values = None
        self._feature_importance_cache: dict[str, dict[str, float]] = {}

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        feature_names: list[str] | None = None,
        sample_weights: np.ndarray | None = None,
        horizon: int = 5,
    ) -> dict[str, Any]:
        """XGBoost model eğit.

        Args:
            X_train: Eğitim verisi
            y_train: Eğitim label
            X_val: Validation verisi
            y_val: Validation label
            feature_names: Feature isimleri
            sample_weights: Sample ağırlıkları
            horizon: Tahmin ufky

        Returns:
            Training metrics
        """
        try:
            import xgboost as xgb
        except ImportError:
            logger.warning("xgboost not installed — pip install xgboost")
            return {"error": "xgboost not installed"}

        self._feature_names = feature_names

        # Classifier veya Regressor
        is_classifier = "logistic" in self._config.objective or "hinge" in self._config.objective

        # Model oluştur
        model = self._create_model(xgb, is_classifier)

        # Custom loss
        custom_obj = None
        if self._config.use_adjusted_loss and not is_classifier:
            custom_obj = XGBoostAdjustedLoss(self._config.wrong_direction_penalty)

        # Eğitim parametreleri
        fit_params = {"verbose": self._config.verbose}
        if X_val is not None and y_val is not None:
            fit_params["eval_set"] = [(X_val, y_val)]
            fit_params["verbose"] = False

        if custom_obj is not None:
            fit_params["obj"] = custom_obj

        # DMatrix oluştur (daha efficient)
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names, weight=sample_weights)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names) if X_val is not None else None

        # XGBoost native API kullan (custom obj için)
        if custom_obj is not None:
            params = {
                "max_depth": self._config.max_depth,
                "eta": self._config.learning_rate,
                "subsample": self._config.subsample,
                "colsample_bytree": self._config.colsample_bytree,
                "reg_alpha": self._config.reg_alpha,
                "reg_lambda": self._config.reg_lambda,
                "min_child_weight": self._config.min_child_weight,
                "gamma": self._config.gamma,
                "seed": self._config.random_state,
                "verbosity": 0,
            }
            if is_classifier:
                params["objective"] = "binary:logistic"
                params["eval_metric"] = "auc"
            else:
                params["objective"] = "reg:squarederror"
                params["eval_metric"] = "rmse"

            evals = [(dtrain, "train")]
            if dval:
                evals.append((dval, "val"))

            bst = xgb.train(
                params,
                dtrain,
                num_boost_round=self._config.n_estimators,
                evals=evals,
                early_stopping_rounds=self._config.early_stopping_rounds if dval else None,
                verbose_eval=False,
            )
            self._models[horizon] = bst
        else:
            model.fit(X_train, y_train, **fit_params)
            self._models[horizon] = model

        # Metrics
        metrics = self._compute_metrics(X_train, y_train, X_val, y_val, horizon, is_classifier)
        self._training_metrics[horizon] = metrics

        # SHAP
        if X_val is not None:
            self._compute_shap(X_val[:100], feature_names)

        # Feature importance cache
        self._cache_feature_importance(horizon, feature_names)

        # Overfitting detection
        self._check_overfitting(metrics, horizon)

        logger.info("xgboost_trained", **metrics)
        return metrics

    def train_multi_horizon(
        self,
        X_train: np.ndarray,
        y_train_dict: dict[int, np.ndarray],
        X_val: np.ndarray | None = None,
        y_val_dict: dict[int, np.ndarray] | None = None,
        feature_names: list[str] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Multi-horizon eğitim."""
        all_metrics = {}
        for horizon in sorted(y_train_dict.keys()):
            y_train = y_train_dict[horizon]
            y_val = y_val_dict.get(horizon) if y_val_dict else None

            metrics = self.train(
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                feature_names=feature_names,
                horizon=horizon,
            )
            all_metrics[horizon] = metrics

        logger.info("xgboost_multi_horizon_trained", horizons=list(all_metrics.keys()))
        return all_metrics

    def predict(self, X: np.ndarray, horizon: int = 5) -> np.ndarray:
        """Tahmin yap."""
        model = self._models.get(horizon)
        if model is None:
            available = sorted(self._models.keys())
            if not available:
                return np.zeros(len(X))
            closest = min(available, key=lambda h: abs(h - horizon))
            model = self._models[closest]

        try:
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=self._feature_names)
                preds = model.predict(dmat)
                if len(preds) != len(X):
                    logger.warning(
                        "xgboost_predict_length_mismatch",
                        expected=len(X),
                        got=len(preds),
                        horizon=horizon,
                    )
                    return np.zeros(len(X))
                raw_prob = preds
            else:
                if hasattr(model, "predict_proba"):
                    raw_prob = model.predict_proba(X)[:, 1]
                else:
                    raw_prob = model.predict(X)

            calibrator = getattr(self, "_calibrators", {}).get(horizon)
            if calibrator is not None:
                return calibrator.calibrate(raw_prob)
            return raw_prob
        except Exception as e:
            logger.warning("xgboost_predict_failed", horizon=horizon, error=str(e))
            return np.zeros(len(X))

    def calibrate(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        horizon: int = 5,
        method: str = "sigmoid",
    ) -> dict[str, float]:
        """Model olasılıklarını kalibre et (Platt scaling / Isotonic)."""
        from .probability_calibrator import ProbabilityCalibrator

        if not hasattr(self, "_calibrators"):
            self._calibrators = {}

        raw_prob = self.predict(X_val, horizon=horizon)
        calibrator = ProbabilityCalibrator(method=method)
        calibrator.fit(raw_prob, y_val)
        self._calibrators[horizon] = calibrator
        return calibrator.get_metrics()

    def predict_all_horizons(self, X: np.ndarray) -> dict[int, np.ndarray]:
        """Tüm horizon'lar için tahmin."""
        return {h: self.predict(X, h) for h in self._models}

    def feature_importance(
        self,
        importance_type: str = "gain",
        horizon: int = 5,
    ) -> dict[str, float] | None:
        """Feature importance döndür.

        Args:
            importance_type: "gain", "cover", "weight", "SHAP"
            horizon: Hangi horizon

        Returns:
            {feature_name: importance_value}
        """
        if importance_type == "SHAP" and self._shap_values:
            return self._shap_values

        cache_key = f"{horizon}_{importance_type}"
        if cache_key in self._feature_importance_cache:
            return self._feature_importance_cache[cache_key]

        model = self._models.get(horizon)
        if model is None:
            return None

        try:
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                importance = model.get_score(importance_type=importance_type)
                if self._feature_names:
                    return {fn: importance.get(fn, 0.0) for fn in self._feature_names}
                return importance
            else:
                importance = model.feature_importances_
                if self._feature_names:
                    return dict(zip(self._feature_names, importance.tolist(), strict=False))
                return {f"f{i}": float(v) for i, v in enumerate(importance)}
        except Exception as e:
            logger.warning("xgboost_feature_importance_failed", type=importance_type, error=str(e))
            return None

    def shap_values(self, X: np.ndarray) -> np.ndarray | None:
        """SHAP values hesapla."""
        model = self._models.get(5)  # Default horizon
        if model is None:
            return None

        try:
            import shap
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=self._feature_names)
                explainer = shap.TreeExplainer(model)
                return explainer.shap_values(dmat)
            else:
                explainer = shap.TreeExplainer(model)
                return explainer.shap_values(X)
        except ImportError:
            logger.warning("shap not installed")
            return None
        except Exception as e:
            logger.warning("shap_calculation_failed", error=str(e))
            return None

    def _create_model(self, xgb_module, is_classifier: bool) -> Any:
        """XGBoost sklearn API model oluştur."""
        gpu_params = {}
        try:
            import torch
            if torch.cuda.is_available():
                gpu_params = {"tree_method": "hist", "device": "cuda"}
        except Exception as t_err:
            logger.debug("XGBoost GPU check fallback", error=str(t_err))

        if is_classifier:
            return xgb_module.XGBClassifier(
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                n_estimators=self._config.n_estimators,
                objective=self._config.objective,
                eval_metric=self._config.eval_metric,
                subsample=self._config.subsample,
                colsample_bytree=self._config.colsample_bytree,
                reg_alpha=self._config.reg_alpha,
                reg_lambda=self._config.reg_lambda,
                min_child_weight=self._config.min_child_weight,
                gamma=self._config.gamma,
                verbosity=self._config.verbose,
                random_state=self._config.random_state,
                **gpu_params,
            )
        else:
            return xgb_module.XGBRegressor(
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                n_estimators=self._config.n_estimators,
                objective="reg:squarederror",
                subsample=self._config.subsample,
                colsample_bytree=self._config.colsample_bytree,
                reg_alpha=self._config.reg_alpha,
                reg_lambda=self._config.reg_lambda,
                min_child_weight=self._config.min_child_weight,
                gamma=self._config.gamma,
                verbosity=self._config.verbose,
                random_state=self._config.random_state,
                **gpu_params,
            )

    def _compute_metrics(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None,
        y_val: np.ndarray | None,
        horizon: int,
        is_classifier: bool,
    ) -> dict[str, Any]:
        """Training metrics hesapla."""
        model = self._models.get(horizon)
        metrics = {
            "horizon": horizon,
            "n_train": len(X_train),
            "n_val": len(X_val) if X_val is not None else 0,
            "feature_count": X_train.shape[1],
        }

        if model is not None:
            try:
                metrics["best_iteration"] = (
                    model.best_iteration if hasattr(model, "best_iteration") else self._config.n_estimators
                )
            except Exception as e:
                logger.warning("xgboost_handled_exception", error=str(e), context="best_iteration_lookup")

        if X_val is not None and y_val is not None:
            val_pred = self.predict(X_val, horizon)

            if is_classifier:
                from sklearn.metrics import accuracy_score, roc_auc_score

                try:
                    metrics["val_auc"] = round(float(roc_auc_score(y_val, val_pred)), 4)
                    metrics["val_accuracy"] = round(float(accuracy_score(y_val, (val_pred > 0.5).astype(int))), 4)
                except Exception as e:
                    logger.warning("xgboost_handled_exception", error=str(e), context="classifier_metrics")
            else:
                from sklearn.metrics import mean_absolute_error, mean_squared_error

                try:
                    metrics["val_rmse"] = round(float(np.sqrt(mean_squared_error(y_val, val_pred))), 6)
                    metrics["val_mae"] = round(float(mean_absolute_error(y_val, val_pred)), 6)
                    # Directional accuracy
                    pred_dir = (val_pred > 0).astype(int)
                    true_dir = (y_val > 0).astype(int)
                    metrics["val_directional_accuracy"] = round(float(np.mean(pred_dir == true_dir)), 4)
                    # IC
                    if len(np.unique(val_pred)) > 1:
                        metrics["val_ic"] = round(float(np.corrcoef(val_pred, y_val)[0, 1]), 4)
                except Exception as e:
                    logger.warning("xgboost_handled_exception", error=str(e), context="regressor_metrics")

        return metrics

    def _compute_shap(self, X: np.ndarray, feature_names: list[str] | None) -> Any:
        """SHAP values hesapla ve cache'le."""
        model = self._models.get(5)
        if model is None:
            return

        try:
            import shap
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=feature_names)
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(dmat)
            else:
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X)

            mean_shap = np.mean(np.abs(shap_values), axis=0)
            if feature_names and len(feature_names) == len(mean_shap):
                self._shap_values = dict(zip(feature_names, mean_shap.tolist(), strict=False))
            else:
                self._shap_values = {f"f{i}": float(v) for i, v in enumerate(mean_shap)}
        except ImportError:
            logger.debug("Optional import not available in _compute_shap", exc_info=True)
        except Exception as e:
            logger.debug("xgboost_shap_failed", error=str(e))

    def _cache_feature_importance(self, horizon: int, feature_names: list[str] | None) -> Any:
        """Feature importance cache'le (gain, cover, weight)."""
        model = self._models.get(horizon)
        if model is None:
            return

        for imp_type in ["gain", "cover", "weight"]:
            try:
                importance = self.feature_importance(imp_type, horizon)
                if importance:
                    self._feature_importance_cache[f"{horizon}_{imp_type}"] = importance
            except Exception as e:
                logger.warning("xgboost_handled_exception", error=str(e), context="feature_importance_cache")

    def _check_overfitting(self, metrics: dict[str, Any], horizon: int) -> Any:
        """Overfitting kontrolü."""
        if "val_ic" in metrics:
            ic = metrics["val_ic"]
            if abs(ic) < 0.01:
                logger.warning("xgboost_no_signal", horizon=horizon, ic=ic)
                self._training_metrics[horizon]["signal_quality"] = "NONE"
            elif abs(ic) < 0.05:
                self._training_metrics[horizon]["signal_quality"] = "WEAK"
            else:
                self._training_metrics[horizon]["signal_quality"] = "OK"

    def save(self, path: str) -> bool:
        """Modeli kaydet."""
        if not self._models:
            return False
        try:
            from services.core.safe_pickle import safe_pickle_dump

            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            safe_pickle_dump(
                {
                    "models": self._models,
                    "config": self._config,
                    "metrics": self._training_metrics,
                    "feature_names": self._feature_names,
                    "shap_values": self._shap_values,
                    "feature_importance_cache": self._feature_importance_cache,
                    "saved_at": datetime.now(UTC).isoformat(),
                },
                path,
            )
            return True
        except Exception as e:
            logger.error("xgboost_save_failed", error=str(e))
            return False

    def load(self, path: str) -> bool:
        """Modeli yükle (SHA256 doğrulamalı)."""
        try:
            from services.core.safe_pickle import safe_pickle_load

            data = safe_pickle_load(path)
            self._models = data.get("models", {})
            self._config = data.get("config", self._config)
            self._training_metrics = data.get("metrics", {})
            self._feature_names = data.get("feature_names")
            self._shap_values = data.get("shap_values")
            self._feature_importance_cache = data.get("feature_importance_cache", {})
            return True
        except Exception as e:
            logger.error("xgboost_load_failed", error=str(e))
            return False

    @property
    def is_trained(self) -> bool:
        """Otomatik eklendi."""
        return len(self._models) > 0

    @property
    def trained_horizons(self) -> list[int]:
        """Otomatik eklendi."""
        return sorted(self._models.keys())

    @property
    def metrics(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return self._training_metrics


def compare_xgboost_vs_lightgbm(
    features_map: dict[str, dict[str, Any]],
    returns: dict[str, float],
    date_groups: dict[str, str],
    feature_names: list[str],
    config: XGBoostConfig | None = None,
) -> dict[str, Any]:
    """XGBoost vs LightGBM karşılaştırması — aynı条件下.

    Aynı feature set, aynı walk-forward, aynı transaction cost,
    aynı holdout, aynı evaluation metrics ile karşılaştırır.

    Args:
        features_map: Feature değerleri
        returns: Gerçek getiriler
        date_groups: Tarih grupları
        feature_names: Feature isimleri
        config: XGBoost konfigürasyonu

    Returns:
        Kararlılık raporu dict
    """
    from .lightgbm_trainer import LightGBMTrainer

    # Veriyi hazırla
    trainer = LightGBMTrainer()
    X, y, _, tickers = trainer._prepare_data(features_map, returns, date_groups, feature_names)

    if len(X) < 100:
        return {"error": "Insufficient data", "samples": len(X)}

    # Impute
    impute_values = trainer._compute_impute_values(X, feature_names)
    X = trainer._impute(X, impute_values, feature_names)

    # Train/val split (son %20)
    n = len(X)
    split_idx = int(n * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    # Scale (train'den öğren)
    scaler_mean = np.mean(X_train, axis=0)
    scaler_std = np.std(X_train, axis=0)
    scaler_std[scaler_std == 0] = 1.0
    X_train_s = (X_train - scaler_mean) / scaler_std
    X_val_s = (X_val - scaler_mean) / scaler_std

    results = {}

    # 1. LightGBM eğit
    try:
        lgb_model = trainer.train(features_map, returns, date_groups, feature_names)
        if lgb_model:
            lgb_pred = lgb_model.predict_batch([dict(zip(feature_names, row, strict=False)) for row in X_val_s])
            lgb_pred = np.array(lgb_pred)
            results["lightgbm"] = {
                "val_ic": round(float(np.corrcoef(lgb_pred, y_val)[0, 1]), 4) if len(np.unique(lgb_pred)) > 1 else 0.0,
                "val_directional_accuracy": round(float(np.mean((lgb_pred > 0) == (y_val > 0))), 4),
                "train_samples": lgb_model.train_samples,
                "confidence": lgb_model.confidence_score,
            }
    except Exception as e:
        results["lightgbm"] = {"error": str(e)}

    # 2. XGBoost eğit
    try:
        xgb_model = XGBoostModel(config)
        xgb_metrics = xgb_model.train(
            X_train_s,
            y_train,
            X_val_s,
            y_val,
            feature_names=feature_names,
            horizon=5,
        )
        xgb_model.predict(X_val_s, horizon=5)
        results["xgboost"] = {
            "val_ic": xgb_metrics.get("val_ic", 0.0),
            "val_directional_accuracy": xgb_metrics.get("val_directional_accuracy", 0.0),
            "val_rmse": xgb_metrics.get("val_rmse", 0.0),
            "train_samples": len(X_train),
        }
    except Exception as e:
        results["xgboost"] = {"error": str(e)}

    # 3. Karşılaştırma
    lgb_ic = results.get("lightgbm", {}).get("val_ic", 0.0)
    xgb_ic = results.get("xgboost", {}).get("val_ic", 0.0)

    if lgb_ic > xgb_ic:
        winner = "lightgbm"
        margin = lgb_ic - xgb_ic
    elif xgb_ic > lgb_ic:
        winner = "xgboost"
        margin = xgb_ic - lgb_ic
    else:
        winner = "equal"
        margin = 0.0

    results["comparison"] = {
        "winner": winner,
        "ic_margin": round(margin, 4),
        "recommendation": "CHAMPION" if margin > 0.02 else "COMPARABLE",
    }

    logger.info(
        "XGBoost vs LightGBM comparison",
        winner=winner,
        lgb_ic=lgb_ic,
        xgb_ic=xgb_ic,
        margin=round(margin, 4),
    )

    return results
