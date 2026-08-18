"""ALPHA BIST — CatBoost Model (Nihai).

CatBoost entegrasyonu — kategorik feature handling, early stopping,
adjusted loss desteği.
"""
import os
import pickle
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class CatBoostConfig:
    """CatBoost model konfigürasyonu."""
    iterations: int = 500
    depth: int = 6
    learning_rate: float = 0.1
    l2_leaf_reg: float = 3.0
    loss_function: str = "Logloss"
    eval_metric: str = "AUC"
    verbose: int = 0
    early_stopping_rounds: int = 50
    random_seed: int = 42
    cat_features: List[int] = field(default_factory=list)


class CatBoostModel:
    """CatBoost model — kategorik feature handling."""

    def __init__(self, config: Optional[CatBoostConfig] = None):
        self._config = config or CatBoostConfig()
        self._model = None
        self._is_classifier = self._config.loss_function in ["Logloss", "CrossEntropy"]
        self._feature_names = None
        self._training_metrics = {}

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
        cat_features: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """CatBoost model eğit.

        Args:
            X_train: Eğitim verisi
            y_train: Eğitim label
            X_val: Validation verisi
            y_val: Validation label
            feature_names: Feature isimleri
            cat_features: Kategorik feature indeksleri

        Returns:
            Training metrics
        """
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
        except ImportError:
            logger.warning("catboost not installed — pip install catboost")
            return {"error": "catboost not installed"}

        self._feature_names = feature_names
        cat_idx = cat_features or self._config.cat_features

        # Model seçimi
        if self._is_classifier:
            model = CatBoostClassifier(
                iterations=self._config.iterations,
                depth=self._config.depth,
                learning_rate=self._config.learning_rate,
                l2_leaf_reg=self._config.l2_leaf_reg,
                loss_function=self._config.loss_function,
                eval_metric=self._config.eval_metric,
                verbose=self._config.verbose,
                random_seed=self._config.random_seed,
            )
        else:
            model = CatBoostRegressor(
                iterations=self._config.iterations,
                depth=self._config.depth,
                learning_rate=self._config.learning_rate,
                l2_leaf_reg=self._config.l2_leaf_reg,
                loss_function="RMSE",
                eval_metric="RMSE",
                verbose=self._config.verbose,
                random_seed=self._config.random_seed,
            )

        # Eğitim
        eval_set = (X_val, y_val) if X_val is not None else None
        model.fit(
            X_train, y_train,
            eval_set=eval_set,
            cat_features=cat_idx if cat_idx else None,
            early_stopping_rounds=self._config.early_stopping_rounds if eval_set else None,
        )

        self._model = model

        # Metrics
        self._training_metrics = {
            "n_train": len(X_train),
            "n_val": len(X_val) if X_val is not None else 0,
            "best_iteration": model.best_iteration_ if hasattr(model, "best_iteration_") else self._config.iterations,
            "feature_count": X_train.shape[1],
        }

        if eval_set is not None:
            val_pred = self.predict(X_val)
            from sklearn.metrics import roc_auc_score, accuracy_score
            try:
                self._training_metrics["val_auc"] = round(float(roc_auc_score(y_val, val_pred)), 4)
                self._training_metrics["val_accuracy"] = round(float(accuracy_score(y_val, (val_pred > 0.5).astype(int))), 4)
            except Exception:
                pass

        logger.info("catboost_trained", **self._training_metrics)
        return self._training_metrics

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Tahmin yap."""
        if self._model is None:
            return np.zeros(len(X))

        if self._is_classifier:
            return self._model.predict_proba(X)[:, 1]
        else:
            return self._model.predict(X)

    def feature_importance(self, importance_type: str = "FeatureImportance") -> Optional[Dict[str, float]]:
        """Feature importance döndür."""
        if self._model is None:
            return None

        try:
            importance = self._model.feature_importances_
            if self._feature_names:
                return dict(zip(self._feature_names, importance.tolist()))
            return {f"f{i}": float(v) for i, v in enumerate(importance)}
        except Exception:
            return None

    def save(self, path: str) -> bool:
        """Modeli kaydet."""
        if self._model is None:
            return False
        try:
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump({
                    "model": self._model,
                    "config": self._config,
                    "metrics": self._training_metrics,
                    "feature_names": self._feature_names,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }, f)
            return True
        except Exception as e:
            logger.error("catboost_save_failed", error=str(e))
            return False

    def load(self, path: str) -> bool:
        """Modeli yükle."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._config = data.get("config", self._config)
            self._training_metrics = data.get("metrics", {})
            self._feature_names = data.get("feature_names")
            return True
        except Exception as e:
            logger.error("catboost_load_failed", error=str(e))
            return False

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    @property
    def metrics(self) -> Dict[str, Any]:
        return self._training_metrics
