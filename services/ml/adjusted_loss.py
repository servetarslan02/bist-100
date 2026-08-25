"""
ALPHA BIST — Adjusted MSE Loss v1.0

ROADMAP v3.0: Yanlış yön tahminleri 11x ceza
- Asimetrik loss: Yanlış yön tahminler 11x daha ağır cezalandırılır
- Bu tek başına +0.44 Sharpe katkısı

KURAL: Yanlış yön tahminler çok pahalı!
"""

import numpy as np
from typing import Dict
import structlog

logger = structlog.get_logger()

class AdjustedMSELoss:
    """Asimetrik MSE Loss fonksiyonu."""

    def __init__(self, wrong_direction_penalty: float = 11.0):
        """
        Args:
            wrong_direction_penalty: Yanlış yön ceza çarpanı (varsayılan: 11x)
        """
        self._penalty = wrong_direction_penalty
        logger.info("AdjustedMSELoss initialized", penalty=wrong_direction_penalty)

    def calculate(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> Dict[str, float]:
        """
        Asimetrik MSE hesapla.

        Yanlış yön: (pred > 0, actual < 0) veya (pred < 0, actual > 0)
        → MSE * penalty

        Doğru yön: (pred > 0, actual > 0) veya (pred < 0, actual < 0)
        → Normal MSE
        """
        # Basit MSE
        simple_mse = np.mean((predictions - actuals) ** 2)

        # Yön kontrolü
        pred_direction = np.sign(predictions)
        actual_direction = np.sign(actuals)

        wrong_direction = (pred_direction != actual_direction) & (actuals != 0)

        # Asimetrik loss
        errors = (predictions - actuals) ** 2
        errors[wrong_direction] *= self._penalty

        adjusted_mse = np.mean(errors)

        # İstatistikler
        total = len(predictions)
        wrong_count = np.sum(wrong_direction)

        return {
            "simple_mse": float(simple_mse),
            "adjusted_mse": float(adjusted_mse),
            "wrong_direction_count": int(wrong_count),
            "wrong_direction_pct": round(wrong_count / total * 100, 1) if total else 0,
            "penalty_applied": self._penalty,
            "direction_accuracy": round((total - wrong_count) / total * 100, 1) if total else 0,
        }

    def calculate_per_sample(
        self,
        prediction: float,
        actual: float,
    ) -> Dict[str, float]:
        """Tek örnek için loss hesapla."""
        error = (prediction - actual) ** 2

        pred_dir = np.sign(prediction)
        actual_dir = np.sign(actual)

        is_wrong = pred_dir != actual_dir and actual != 0

        if is_wrong:
            error *= self._penalty

        return {
            "prediction": prediction,
            "actual": actual,
            "error": float(error),
            "is_wrong_direction": bool(is_wrong),
            "penalty_applied": self._penalty if is_wrong else 1.0,
        }

    def get_gradient(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> np.ndarray:
        """Gradient hesapla (model eğitimi için)."""
        pred_direction = np.sign(predictions)
        actual_direction = np.sign(actuals)
        wrong_direction = (pred_direction != actual_direction) & (actuals != 0)

        # dL/dy = 2 * (y_pred - y_true) * penalty (yanlış yön ise)
        gradient = 2 * (predictions - actuals)
        gradient[wrong_direction] *= self._penalty

        return gradient

# Singleton
adjusted_loss = AdjustedMSELoss()
