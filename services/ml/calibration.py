"""ALPHA BIST — Model Calibration (Nihai).

Confidence calibration — Brier score, calibration curve,
Platt scaling, isotonic regression.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationResult:
    """Kalibrasyon sonucu."""
    is_calibrated: bool
    brier_score: float
    calibration_curve: List[Dict[str, float]]
    miscalibration: float  # Ortalama |beklenen - gerçek|
    overconfident: bool
    recommendation: str


class ModelCalibration:
    """Model confidence kalibrasyonu."""

    def __init__(self, n_bins: int = 10, overconfidence_threshold: float = 0.15):
        self.n_bins = n_bins
        self.overconfidence_threshold = overconfidence_threshold

    def check_calibration(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
    ) -> CalibrationResult:
        """Kalibrasyon kontrolü.

        Args:
            y_true: Gerçek etiketler (0/1)
            y_prob: Model olasılık tahminleri

        Returns:
            CalibrationResult
        """
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import brier_score_loss

        # Brier score
        try:
            brier = float(brier_score_loss(y_true, y_prob))
        except Exception:
            brier = 1.0

        # Calibration curve
        try:
            fraction_pos, mean_predicted = calibration_curve(
                y_true, y_prob, n_bins=self.n_bins, strategy="uniform"
            )
            curve = []
            for frac, mean_pred in zip(fraction_pos, mean_predicted):
                curve.append({
                    "mean_predicted": round(float(mean_pred), 4),
                    "fraction_positive": round(float(frac), 4),
                    "gap": round(abs(float(mean_pred) - float(frac)), 4),
                })
        except Exception:
            curve = []

        # Miscalibration
        if curve:
            miscalibration = float(np.mean([c["gap"] for c in curve]))
        else:
            miscalibration = 0.0

        # Overconfidence check
        overconfident = miscalibration > self.overconfidence_threshold

        # Recommendation
        if brier < 0.1:
            recommendation = "EXCELLENT"
        elif brier < 0.2:
            recommendation = "GOOD"
        elif brier < 0.3:
            recommendation = "NEEDS_CALIBRATION"
        else:
            recommendation = "POOR"

        return CalibrationResult(
            is_calibrated=miscalibration < self.overconfidence_threshold,
            brier_score=round(brier, 4),
            calibration_curve=curve,
            miscalibration=round(miscalibration, 4),
            overconfident=overconfident,
            recommendation=recommendation,
        )

    def calibrate_platt(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: Optional[np.ndarray] = None,
    ) -> Tuple[Any, np.ndarray]:
        """Platt scaling (sigmoid calibration).

        Args:
            y_true: Gerçek etiketler
            y_prob: Model olasılıkları (eğitim)
            y_prob_val: Model olasılıkları (kalibrasyon sonrası için)

        Returns:
            (calibrator, calibrated_probabilities)
        """
        from sklearn.linear_model import LogisticRegression

        calibrator = LogisticRegression()
        calibrator.fit(y_prob.reshape(-1, 1), y_true)

        if y_prob_val is not None:
            calibrated = calibrator.predict_proba(y_prob_val.reshape(-1, 1))[:, 1]
        else:
            calibrated = calibrator.predict_proba(y_prob.reshape(-1, 1))[:, 1]

        return calibrator, calibrated

    def calibrate_isotonic(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: Optional[np.ndarray] = None,
    ) -> Tuple[Any, np.ndarray]:
        """Isotonic regression calibration.

        Args:
            y_true: Gerçek etiketler
            y_prob: Model olasılıkları (eğitim)
            y_prob_val: Model olasılıkları (kalibrasyon sonrası için)

        Returns:
            (calibrator, calibrated_probabilities)
        """
        from sklearn.isotonic import IsotonicRegression

        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(y_prob, y_true)

        if y_prob_val is not None:
            calibrated = calibrator.predict(y_prob_val)
        else:
            calibrated = calibrator.predict(y_prob)

        return calibrator, calibrated
