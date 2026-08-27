"""ALPHA BIST - ML Models (LightGBM/XGBoost Ensemble)"""

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class SecurityError(Exception):
    """Güvenlik doğrulama hatası."""
    pass


@dataclass
class ModelConfig:
    """Configuration for an ML model."""
    name: str
    model_type: str  # "lightgbm", "xgboost", "pytorch"
    target: str  # "return_5d", "return_20d", "direction", "volatility"
    features: list[str] = field(default_factory=list)
    hyperparams: dict[str, Any] = field(default_factory=dict)
    version: str = "v1"
    description: str = ""


# Default feature set
DEFAULT_FEATURES = [
    # Returns
    "return_1d", "return_5d", "return_10d", "return_20d",

    # Volume
    "volume_ratio_5d", "volume_ratio_20d", "volume_zscore", "volume_trend",

    # Momentum
    "roc_5d", "roc_10d", "roc_20d", "momentum_5d", "momentum_20d", "price_acceleration",

    # Volatility
    "atr_14_pct", "realized_vol_5d", "realized_vol_20d", "bb_width", "bb_position", "volatility_ratio",

    # Technical
    "rsi_14", "macd_histogram", "stochastic_k", "adx", "cci", "williams_r", "mfi",

    # Trend
    "price_vs_sma20", "price_vs_sma50", "trend_slope_20d",

    # Pattern
    "gap_pct", "daily_range_pct", "consecutive_up", "near_20d_high", "near_20d_low",
]

# Model configurations
MODEL_CONFIGS = {
    "momentum_5d": ModelConfig(
        name="momentum_5d",
        model_type="lightgbm",
        target="return_5d",
        features=DEFAULT_FEATURES,
        hyperparams={
            "n_estimators": 500,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 50,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "random_state": 42,
        },
        description="5-day return prediction",
    ),
    "momentum_20d": ModelConfig(
        name="momentum_20d",
        model_type="lightgbm",
        target="return_20d",
        features=DEFAULT_FEATURES,
        hyperparams={
            "n_estimators": 500,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 50,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "random_state": 42,
        },
        description="20-day return prediction",
    ),
    "breakout": ModelConfig(
        name="breakout",
        model_type="lightgbm",
        target="breakout_signal",
        features=DEFAULT_FEATURES + ["near_20d_high", "volume_zscore", "bb_position"],
        hyperparams={
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 30,
            "random_state": 42,
        },
        description="Breakout signal prediction",
    ),
    "anomaly": ModelConfig(
        name="anomaly",
        model_type="lightgbm",
        target="anomaly_score",
        features=DEFAULT_FEATURES + ["volume_zscore", "volatility_ratio"],
        hyperparams={
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 30,
            "random_state": 42,
        },
        description="Anomaly detection",
    ),
    "risk": ModelConfig(
        name="risk",
        model_type="lightgbm",
        target="max_drawdown_20d",
        features=DEFAULT_FEATURES,
        hyperparams={
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 30,
            "random_state": 42,
        },
        description="Risk (max drawdown) prediction",
    ),
}


class AlphaModel:
    """Base model wrapper for ALPHA BIST ML models."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model = None
        self.is_trained = False
        self.feature_importance: dict[str, float] = {}
        self.metrics: dict[str, float] = {}

    def train(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None = None, y_val: np.ndarray | None = None):
        """Train the model."""
        raise NotImplementedError

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions."""
        if not self.is_trained or self.model is None:
            raise RuntimeError(f"Model {self.config.name} is not trained")

        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Make probability predictions (for classification)."""
        if not self.is_trained or self.model is None:
            raise RuntimeError(f"Model {self.config.name} is not trained")

        if hasattr(self.model, "predict_proba"):
            return self.model.predict_proba(X)
        return self.model.predict(X)

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance."""
        if not self.is_trained or self.model is None:
            return {}

        if hasattr(self.model, "feature_importances_"):
            importance = self.model.feature_importances_
            return dict(zip(self.config.features, importance, strict=False))

        return {}

    def save(self, path: str):
        """Save model to disk."""
        model_path = Path(path)
        model_path.parent.mkdir(parents=True, exist_ok=True)

        with open(model_path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "config": self.config,
                "metrics": self.metrics,
                "feature_importance": self.feature_importance,
                "is_trained": self.is_trained,
            }, f)

        # Hash dosyası oluştur (pickle deserilization güvenliği)
        try:
            import hashlib
            with open(path, "rb") as hf:
                file_hash = hashlib.sha256(hf.read()).hexdigest()
            hash_path = path + ".sha256"
            with open(hash_path, "w") as hf:
                hf.write(file_hash)
        except Exception:
            logger.debug("Hash generation skipped", path=path)

        logger.info("Model saved", path=path, name=self.config.name)

    def load(self, path: str):
        """Load model from disk."""
        # Hash doğrulama
        hash_path = path + ".sha256"
        try:
            import hashlib
            import os
            if os.path.exists(hash_path):
                expected_hash = open(hash_path).read().strip()
                actual_hash = hashlib.sha256(open(path, "rb").read()).hexdigest()
                if actual_hash != expected_hash:
                    raise SecurityError(f"Model hash mismatch — possible tampering: {path}")
        except SecurityError:
            raise
        except Exception:
            pass  # Hash dosyası yoksa doğrulama atlanır

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.model = data["model"]
        self.config = data["config"]
        self.metrics = data.get("metrics", {})
        self.feature_importance = data.get("feature_importance", {})
        self.is_trained = data.get("is_trained", True)

        logger.info("Model loaded", path=path, name=self.config.name)


class LightGBMModel(AlphaModel):
    """LightGBM model wrapper."""

    def __init__(self, config: ModelConfig):
        super().__init__(config)

    def train(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None = None, y_val: np.ndarray | None = None):
        """Train LightGBM model."""
        import lightgbm as lgb

        params = self.config.hyperparams.copy()

        # Determine if classification or regression
        is_classification = len(np.unique(y)) <= 10 and all(v in [0, 1] for v in np.unique(y))

        if is_classification:
            self.model = lgb.LGBMClassifier(**params)
        else:
            self.model = lgb.LGBMRegressor(**params)

        # Train
        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None
        callbacks = [lgb.log_evaluation(period=100)]

        self.model.fit(
            X, y,
            eval_set=eval_set,
            callbacks=callbacks,
        )

        self.is_trained = True
        self.feature_importance = self.get_feature_importance()

        logger.info("LightGBM model trained", name=self.config.name, features=len(self.config.features))


class XGBoostModel(AlphaModel):
    """XGBoost model wrapper."""

    def __init__(self, config: ModelConfig):
        super().__init__(config)

    def train(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None = None, y_val: np.ndarray | None = None):
        """Train XGBoost model."""
        import xgboost as xgb

        params = self.config.hyperparams.copy()

        is_classification = len(np.unique(y)) <= 10 and all(v in [0, 1] for v in np.unique(y))

        if is_classification:
            self.model = xgb.XGBClassifier(**params)
        else:
            self.model = xgb.XGBRegressor(**params)

        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None

        self.model.fit(
            X, y,
            eval_set=eval_set,
            verbose=False,
        )

        self.is_trained = True
        self.feature_importance = self.get_feature_importance()

        logger.info("XGBoost model trained", name=self.config.name, features=len(self.config.features))


class ModelEnsemble:
    """Ensemble of multiple models for consensus predictions."""

    def __init__(self):
        self.models: dict[str, AlphaModel] = {}

    def add_model(self, model: AlphaModel):
        """Add a model to the ensemble."""
        self.models[model.config.name] = model
        logger.info("Model added to ensemble", name=model.config.name)

    def predict_consensus(self, X: np.ndarray) -> dict[str, Any]:
        """Get consensus prediction from all models."""
        predictions = {}
        confidences = {}

        for name, model in self.models.items():
            if not model.is_trained:
                continue

            try:
                pred = model.predict(X)
                predictions[name] = float(pred[0]) if len(pred) > 0 else 0

                # Confidence from feature importance
                importance = model.get_feature_importance()
                confidences[name] = np.mean(list(importance.values())) if importance else 0.5

            except Exception as e:
                logger.warning("Model prediction failed", name=name, error=str(e))

        if not predictions:
            return {"consensus": 0, "confidence": 0, "models": {}}

        # Weighted average
        weights = np.array(list(confidences.values()))
        weights = weights / weights.sum() if weights.sum() > 0 else np.ones(len(weights)) / len(weights)

        values = np.array(list(predictions.values()))
        consensus = np.average(values, weights=weights)

        return {
            "consensus": float(consensus),
            "confidence": float(np.mean(list(confidences.values()))),
            "models": predictions,
            "weights": dict(zip(predictions.keys(), weights.tolist(), strict=False)),
        }


# Singleton ensemble
model_ensemble = ModelEnsemble()
