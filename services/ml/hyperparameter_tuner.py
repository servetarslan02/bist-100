"""ALPHA BIST — Hyperparameter Tuner (Nihai).

Optuna Bayesian optimization — IC-based objective, regime-specific tuning.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class TuningResult:
    """Tuning sonucu."""
    best_params: Dict[str, Any]
    best_value: float
    n_trials: int
    trial_history: List[Dict[str, Any]]
    tuning_time_seconds: float


class HyperparameterTuner:
    """Optuna ile hyperparameter tuning."""

    def __init__(self, n_trials: int = 50, timeout_seconds: int = 600):
        self.n_trials = n_trials
        self.timeout_seconds = timeout_seconds
        self._study = None

    def tune_lightgbm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str = "ic",  # ic, auc, mse
    ) -> TuningResult:
        """LightGBM hyperparameter tuning.

        Args:
            X_train: Eğitim verisi
            y_train: Eğitim label
            X_val: Validation verisi
            y_val: Validation label
            objective_type: Optimizasyon hedefi

        Returns:
            TuningResult with best params
        """
        try:
            import optuna
            import lightgbm as lgb
        except ImportError:
            logger.warning("optuna or lightgbm not installed")
            return TuningResult(best_params={}, best_value=0, n_trials=0, trial_history=[], tuning_time_seconds=0)

        import time
        start_time = time.time()

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
                "max_depth": trial.suggest_int("max_depth", 3, 10),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "num_leaves": trial.suggest_int("num_leaves", 20, 100),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
                "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
                "verbose": -1,
            }

            model = lgb.LGBMRegressor(**params)
            model.fit(X_train, y_train)
            preds = model.predict(X_val)

            if objective_type == "ic":
                ic = np.corrcoef(preds, y_val)[0, 1]
                return ic if not np.isnan(ic) else 0
            elif objective_type == "auc":
                from sklearn.metrics import roc_auc_score
                try:
                    return float(roc_auc_score(y_val, preds))
                except Exception:
                    return 0
            else:  # mse
                return -float(np.mean((preds - y_val) ** 2))

        # Optuna study
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds)

        elapsed = time.time() - start_time

        # Trial history
        trial_history = [
            {"trial": t.number, "value": t.value, "params": t.params}
            for t in study.trials
            if t.value is not None
        ]

        result = TuningResult(
            best_params=study.best_params,
            best_value=round(float(study.best_value), 4),
            n_trials=len(study.trials),
            trial_history=trial_history,
            tuning_time_seconds=round(elapsed, 1),
        )

        logger.info("lightgbm_tuned", best_value=result.best_value, n_trials=result.n_trials)
        return result

    def tune_xgboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> TuningResult:
        """XGBoost hyperparameter tuning."""
        try:
            import optuna
            import xgboost as xgb
        except ImportError:
            return TuningResult(best_params={}, best_value=0, n_trials=0, trial_history=[], tuning_time_seconds=0)

        import time
        start_time = time.time()

        def objective(trial):
            params = {
                "max_depth": trial.suggest_int("max_depth", 3, 10),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
                "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
                "verbosity": 0,
            }

            model = xgb.XGBRegressor(**params)
            model.fit(X_train, y_train)
            preds = model.predict(X_val)

            ic = np.corrcoef(preds, y_val)[0, 1]
            return ic if not np.isnan(ic) else 0

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds)

        elapsed = time.time() - start_time

        result = TuningResult(
            best_params=study.best_params,
            best_value=round(float(study.best_value), 4),
            n_trials=len(study.trials),
            trial_history=[{"trial": t.number, "value": t.value, "params": t.params} for t in study.trials if t.value is not None],
            tuning_time_seconds=round(elapsed, 1),
        )

        logger.info("xgboost_tuned", best_value=result.best_value, n_trials=result.n_trials)
        return result
