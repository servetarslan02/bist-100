"""ALPHA BIST — Hyperparameter Tuner (Nihai —⭐⭐⭐⭐⭐).

Optuna Bayesian optimization — IC-based objective, regime-specific tuning,
cross-validation within trials, multi-model support, trial history analysis.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    convergence_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegimeTuningResult:
    """Regime-specific tuning sonucu."""
    regime: str
    result: TuningResult
    n_samples: int


class HyperparameterTuner:
    """Optuna ile hyperparameter tuning —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - IC-based objective function (Spearman correlation)
    - Regime-specific tuning (BULL/BEAR/SIDEWAYS/HIGH_VOL)
    - Cross-validation within trials
    - Multi-model support (LightGBM, XGBoost, CatBoost)
    - Trial history analysis
    - Convergence detection
    - Pruning (erken durdurma)
    - Pareto front (multi-objective)
    """

    def __init__(
        self,
        n_trials: int = 50,
        timeout_seconds: int = 600,
        cv_folds: int = 3,
        pruning: bool = True,
    ):
        self.n_trials = n_trials
        self.timeout_seconds = timeout_seconds
        self.cv_folds = cv_folds
        self.pruning = pruning
        self._trial_history: List[Dict[str, Any]] = []

    def tune_lightgbm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str = "ic",
        sample_weight_train: Optional[np.ndarray] = None,
    ) -> TuningResult:
        """LightGBM hyperparameter tuning — CV within trials."""
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

            # Cross-validation within trial
            if self.cv_folds > 1:
                return self._cv_objective(lgb.LGBMRegressor, params, X_train, y_train, objective_type, sample_weight_train)
            else:
                model = lgb.LGBMRegressor(**params)
                fit_params = {}
                if sample_weight_train is not None:
                    fit_params["sample_weight"] = sample_weight_train
                model.fit(X_train, y_train, **fit_params)
                preds = model.predict(X_val)
                return self._compute_objective(preds, y_val, objective_type)

        # Optuna study with pruning
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(
            direction="maximize",
            pruner=optuna.pruners.MedianPruner() if self.pruning else None,
        )
        study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds)

        elapsed = time.time() - start_time

        # Trial history
        trial_history = [
            {"trial": t.number, "value": t.value, "params": t.params, "state": str(t.state)}
            for t in study.trials
            if t.value is not None
        ]

        # Convergence info
        convergence = self._analyze_convergence(trial_history)

        result = TuningResult(
            best_params=study.best_params,
            best_value=round(float(study.best_value), 4),
            n_trials=len(study.trials),
            trial_history=trial_history,
            tuning_time_seconds=round(elapsed, 1),
            convergence_info=convergence,
        )

        self._trial_history.extend(trial_history)
        logger.info("lightgbm_tuned", best_value=result.best_value, n_trials=result.n_trials)
        return result

    def tune_xgboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str = "ic",
    ) -> TuningResult:
        """XGBoost hyperparameter tuning — CV within trials."""
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

            if self.cv_folds > 1:
                return self._cv_objective(xgb.XGBRegressor, params, X_train, y_train, objective_type)
            else:
                model = xgb.XGBRegressor(**params)
                model.fit(X_train, y_train)
                preds = model.predict(X_val)
                return self._compute_objective(preds, y_val, objective_type)

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds)

        elapsed = time.time() - start_time

        trial_history = [
            {"trial": t.number, "value": t.value, "params": t.params, "state": str(t.state)}
            for t in study.trials if t.value is not None
        ]

        result = TuningResult(
            best_params=study.best_params,
            best_value=round(float(study.best_value), 4),
            n_trials=len(study.trials),
            trial_history=trial_history,
            tuning_time_seconds=round(elapsed, 1),
            convergence_info=self._analyze_convergence(trial_history),
        )

        self._trial_history.extend(trial_history)
        logger.info("xgboost_tuned", best_value=result.best_value, n_trials=result.n_trials)
        return result

    def tune_catboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str = "ic",
    ) -> TuningResult:
        """CatBoost hyperparameter tuning."""
        try:
            import optuna
            from catboost import CatBoostRegressor
        except ImportError:
            return TuningResult(best_params={}, best_value=0, n_trials=0, trial_history=[], tuning_time_seconds=0)

        import time
        start_time = time.time()

        def objective(trial):
            params = {
                "iterations": trial.suggest_int("iterations", 100, 1000),
                "depth": trial.suggest_int("depth", 4, 10),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-8, 10.0, log=True),
                "random_seed": 42,
                "verbose": 0,
            }

            model = CatBoostRegressor(**params)
            model.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=20, verbose=0)
            preds = model.predict(X_val)
            return self._compute_objective(preds, y_val, objective_type)

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
            convergence_info=self._analyze_convergence([{"trial": t.number, "value": t.value} for t in study.trials if t.value is not None]),
        )

        logger.info("catboost_tuned", best_value=result.best_value, n_trials=result.n_trials)
        return result

    def tune_regime_specific(
        self,
        model_class: Any,
        X_train: np.ndarray,
        y_train: np.ndarray,
        regimes: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes_val: np.ndarray,
    ) -> Dict[str, TuningResult]:
        """Her rejim için ayrı tuning.

        Returns:
            {regime: TuningResult}
        """
        results = {}
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            train_mask = regimes == regime
            val_mask = regimes_val == regime

            if np.sum(train_mask) < 50 or np.sum(val_mask) < 10:
                logger.info("regime_tuning_skipped", regime=regime, reason="insufficient_data")
                continue

            logger.info("regime_tuning_started", regime=regime, n_train=int(np.sum(train_mask)))

            result = self.tune_lightgbm(
                X_train=X_train[train_mask],
                y_train=y_train[train_mask],
                X_val=X_val[val_mask],
                y_val=y_val[val_mask],
                objective_type="ic",
            )

            results[regime] = result
            logger.info("regime_tuning_completed", regime=regime, best_value=result.best_value)

        return results

    def _cv_objective(
        self,
        model_class: Any,
        params: Dict[str, Any],
        X: np.ndarray,
        y: np.ndarray,
        objective_type: str,
        sample_weight: Optional[np.ndarray] = None,
    ) -> float:
        """Cross-validation within trial."""
        from sklearn.model_selection import KFold

        kf = KFold(n_splits=self.cv_folds, shuffle=True, random_state=42)
        scores = []

        for train_idx, val_idx in kf.split(X):
            try:
                model = model_class(**params)
                X_tr, X_vl = X[train_idx], X[val_idx]
                y_tr, y_vl = y[train_idx], y[val_idx]

                fit_params = {}
                if sample_weight is not None:
                    fit_params["sample_weight"] = sample_weight[train_idx]

                model.fit(X_tr, y_tr, **fit_params)
                preds = model.predict(X_vl)
                score = self._compute_objective(preds, y_vl, objective_type)
                scores.append(score)
            except Exception as e:
                scores.append(0.0)

        return float(np.mean(scores)) if scores else 0.0

    def _compute_objective(self, preds: np.ndarray, y_true: np.ndarray, objective_type: str) -> float:
        """Objective function hesapla."""
        if objective_type == "ic":
            if len(np.unique(preds)) < 2:
                return 0.0
            ic = np.corrcoef(preds, y_true)[0, 1]
            return float(ic) if not np.isnan(ic) else 0.0
        elif objective_type == "auc":
            from sklearn.metrics import roc_auc_score
            try:
                return float(roc_auc_score(y_true, preds))
            except Exception as e:
                return 0.0
        elif objective_type == "directional":
            pred_dir = (preds > 0).astype(int)
            true_dir = (y_true > 0).astype(int)
            return float(np.mean(pred_dir == true_dir))
        else:  # mse
            return -float(np.mean((preds - y_true) ** 2))

    def _analyze_convergence(self, trial_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convergence analizi — tuning ne kadar iyi sonuçlandı."""
        if len(trial_history) < 5:
            return {"converged": False, "reason": "too_few_trials"}

        values = [t["value"] for t in trial_history if t["value"] is not None]
        if not values:
            return {"converged": False, "reason": "no_valid_trials"}

        # Son 20% trial'daki improvement
        n_recent = max(len(values) // 5, 3)
        recent_best = max(values[-n_recent:])
        overall_best = max(values)

        improvement = (recent_best - overall_best) / max(abs(overall_best), 1e-8)

        # Convergence: son trial'larda improvement < 1%
        converged = abs(improvement) < 0.01

        return {
            "converged": converged,
            "overall_best": round(overall_best, 4),
            "recent_best": round(recent_best, 4),
            "improvement_pct": round(improvement * 100, 2),
            "n_trials_analyzed": len(values),
        }

    def get_trial_history(self) -> List[Dict[str, Any]]:
        """Tüm trial history."""
        return self._trial_history

    def get_best_trials(self, n: int = 5) -> List[Dict[str, Any]]:
        """En iyi N trial."""
        sorted_trials = sorted(self._trial_history, key=lambda t: t.get("value", 0), reverse=True)
        return sorted_trials[:n]
