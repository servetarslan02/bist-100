"""ALPHA BIST — XGBoost Model."""
from typing import Dict, Any, Optional, Tuple
import numpy as np
import structlog
logger = structlog.get_logger()

class XGBoostModel:
    def __init__(self, params: Optional[Dict] = None):
        self._params = params or {"max_depth": 6, "learning_rate": 0.1, "n_estimators": 200, "objective": "binary:logistic"}
        self._model = None

    def train(self, X_train: np.ndarray, y_train: np.ndarray, X_val: Optional[np.ndarray] = None, y_val: Optional[np.ndarray] = None) -> Any:
        try:
            import xgboost as xgb
            self._model = xgb.XGBClassifier(**self._params)
            eval_set = [(X_val, y_val)] if X_val is not None else None
            self._model.fit(X_train, y_train, eval_set=eval_set, verbose=False)
            logger.info("XGBoost trained", n_samples=len(X_train))
            return self._model
        except ImportError:
            logger.warning("xgboost not installed")
            return None

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None: return np.zeros(len(X))
        return self._model.predict_proba(X)[:, 1]

    def feature_importance(self) -> Optional[np.ndarray]:
        if self._model is None: return None
        return self._model.feature_importances_

xgboost_model = XGBoostModel()
