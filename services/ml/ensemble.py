"""ALPHA BIST — Ensemble Model (Nihai).

Ağırlıklı ortalama + stacking ensemble desteği.
Eski weighted average korunurken, stacking_ensemble.py ile entegrasyon eklendi.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
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
        models: dict[str, Callable],
        weights: dict[str, float],
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
        if not models:
            logger.warning("ensemble_no_models")
            return np.full(len(X), np.nan)

        total_weight = 0.0
        weighted_sum = np.zeros(len(X))
        failed_models = []

        for name, fn in models.items():
            w = weights.get(name, 1.0)
            try:
                preds = fn(X)
                if len(preds) != len(X):
                    logger.warning("ensemble_prediction_length_mismatch", model=name, expected=len(X), got=len(preds))
                    failed_models.append(name)
                    continue
                if not np.all(np.isfinite(preds)):
                    logger.warning("ensemble_prediction_non_finite", model=name)
                    preds = np.nan_to_num(preds, nan=0.0, posinf=0.0, neginf=0.0)
                weighted_sum += preds * w
                total_weight += w
            except Exception as e:
                logger.warning("ensemble_model_failed", model=name, error=str(e))
                failed_models.append(name)

        if failed_models:
            logger.info("ensemble_failed_models", failed=failed_models, succeeded=len(models) - len(failed_models))

        if total_weight <= 0:
            logger.error("ensemble_all_models_failed", model_count=len(models))
            return np.full(len(X), np.nan)

        return weighted_sum / total_weight

    def predict_with_confidence(
        self,
        models: dict[str, Callable],
        weights: dict[str, float],
        X: np.ndarray,
    ) -> tuple:
        """Ensemble prediction + confidence (model agreement).

        Confidence: 0-1 arası. Hesaplama:
        - Her sample icin model tahminlerinin std'si alinir
        - std / max_possible_std ile normalize edilir
        - confidence = 1 - normalized_std

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
                if len(preds) == len(X) and np.all(np.isfinite(preds)):
                    all_preds.append(preds)
                else:
                    logger.warning("ensemble_confidence_skip", model=name)
            except Exception as e:
                logger.warning("ensemble_confidence_failed", model=name, error=str(e))

        if not all_preds:
            return np.full(len(X), np.nan), np.zeros(len(X))

        preds_matrix = np.array(all_preds)
        mean_pred = np.mean(preds_matrix, axis=0)

        # Confidence: 1 - normalized_std
        # Tahminler 0-1 arası ise max_std = 0.5, degilse tahmin aralığına göre hesapla
        pred_range = np.max(preds_matrix) - np.min(preds_matrix)
        max_possible_std = max(pred_range / 2, 1e-6)
        pred_std = np.std(preds_matrix, axis=0)
        confidence = 1.0 - (pred_std / max_possible_std)

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
        if not hasattr(stacking_ensemble, "is_fitted") or not stacking_ensemble.is_fitted:
            logger.warning("stacking_not_fitted")
            return np.full(len(X), 0.5)

        return stacking_ensemble.predict(X)

    def predict_dynamic(
        self,
        models: dict[str, Callable],
        X: np.ndarray,
        regime: str = "NORMAL",
        regime_weights: dict[str, dict[str, float]] | None = None,
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
        valid_regimes = {"BULL", "BEAR", "SIDEWAYS", "HIGH_VOL", "NORMAL"}
        if regime not in valid_regimes:
            logger.warning("ensemble_unknown_regime", regime=regime, valid=sorted(valid_regimes))

        if regime_weights is None:
            weights = {name: 1.0 for name in models}
        else:
            weights = regime_weights.get(regime, {name: 1.0 for name in models})

        return self.predict(models, weights, X)


# Singleton
ensemble_model = EnsembleModel()
