"""ALPHA BIST — Ensemble Model."""
import numpy as np
from typing import Dict, List, Callable
import structlog
logger = structlog.get_logger()

class EnsembleModel:
    def predict(self, models: Dict[str, Callable], weights: Dict[str, float], X: np.ndarray) -> np.ndarray:
        """Ağırlıklı ensemble prediction."""
        total_weight = 0.0
        weighted_sum = np.zeros(len(X))
        for name, fn in models.items():
            w = weights.get(name, 1.0)
            try:
                preds = fn(X)
                if len(preds) == len(X):
                    weighted_sum += preds * w
                    total_weight += w
            except Exception as e:
                logger.warning("Ensemble model failed", model=name, error=str(e))
        return weighted_sum / total_weight if total_weight > 0 else np.full(len(X), 0.5)

    def predict_with_confidence(self, models: Dict[str, Callable], weights: Dict[str, float], X: np.ndarray):
        """Ensemble prediction + confidence (model agreement)."""
        all_preds = []
        for name, fn in models.items():
            try:
                preds = fn(X)
                if len(preds) == len(X): all_preds.append(preds)
            except: pass
        if not all_preds: return np.full(len(X), 0.5), np.zeros(len(X))
        preds_matrix = np.array(all_preds)
        mean_pred = np.mean(preds_matrix, axis=0)
        confidence = 1.0 - np.std(preds_matrix, axis=0)
        return mean_pred, np.clip(confidence, 0, 1)

ensemble_model = EnsembleModel()
