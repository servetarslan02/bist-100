"""ALPHA BIST — Ensemble Model (Nihai).

Ağırlıklı ortalama + stacking ensemble desteği.
Eski weighted average korunurken, stacking_ensemble.py ile entegrasyon eklendi.
"""
import numpy as np
from typing import Dict, Callable, Optional, Any
import structlog

logger = structlog.get_logger()


class EnsembleModel:
    """Ensemble prediction — weighted average + stacking desteği.

    Kullanım:
        1. Basit: weighted average (eski davranış)
        2. Gelişmiş: stacking_ensemble.StackingEnsemble ile entegrasyon
    """

    def predict(
        self,
        models: Dict[str, Callable],
        weights: Dict[str, float],
        X: np.ndarray,
    ) -> np.ndarray:
        """Ağırlıklı ensemble prediction.

        Args:
            models: {model_name: predict_fn}
            weights: {model_name: weight}
            X: Feature matrix

        Returns:
            Ağırlıklı ortalama tahminler
        """
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
                logger.warning("ensemble_model_failed", model=name, error=str(e))

        return weighted_sum / total_weight if total_weight > 0 else np.full(len(X), 0.5)

    def predict_with_confidence(
        self,
        models: Dict[str, Callable],
        weights: Dict[str, float],
        X: np.ndarray,
    ) -> tuple:
        """Ensemble prediction + confidence (model agreement).

        Args:
            models: {model_name: predict_fn}
            weights: {model_name: weight}
            X: Feature matrix

        Returns:
            (predictions, confidence) — confidence: 0-1 arası, yüksek = modeller uzlaşıyor
        """
        all_preds = []

        for name, fn in models.items():
            try:
                preds = fn(X)
                if len(preds) == len(X):
                    all_preds.append(preds)
            except Exception as e:
                logger.warning("ensemble_confidence_failed", model=name, error=str(e))

        if not all_preds:
            return np.full(len(X), 0.5), np.zeros(len(X))

        preds_matrix = np.array(all_preds)
        mean_pred = np.mean(preds_matrix, axis=0)
        confidence = 1.0 - np.std(preds_matrix, axis=0)

        return mean_pred, np.clip(confidence, 0, 1)

    def predict_stacking(
        self,
        stacking_ensemble: Any,
        X: np.ndarray,
    ) -> np.ndarray:
        """Stacking ensemble ile tahmin.

        StackingEnsemble objesi kullanarak meta-learner tabanlı tahmin.

        Args:
            stacking_ensemble: StackingEnsemble instance (eğitilmiş olmalı)
            X: Feature matrix

        Returns:
            Meta-learner tahminleri
        """
        if not hasattr(stacking_ensemble, 'is_fitted') or not stacking_ensemble.is_fitted:
            logger.warning("stacking_not_fitted")
            return np.full(len(X), 0.5)

        return stacking_ensemble.predict(X)

    def predict_dynamic(
        self,
        models: Dict[str, Callable],
        X: np.ndarray,
        regime: str = "NORMAL",
        regime_weights: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> np.ndarray:
        """Rejime göre dinamik ağırlıklı ensemble.

        Args:
            models: {model_name: predict_fn}
            X: Feature matrix
            regime: Mevcut piyasa rejimi (BULL, BEAR, SIDEWAYS, HIGH_VOL)
            regime_weights: {regime: {model_name: weight}}

        Returns:
            Rejime göre ağırlıklı tahmin
        """
        if regime_weights is None:
            # Varsayılan eşit ağırlık
            weights = {name: 1.0 for name in models}
        else:
            weights = regime_weights.get(regime, {name: 1.0 for name in models})

        return self.predict(models, weights, X)


# Singleton
ensemble_model = EnsembleModel()
