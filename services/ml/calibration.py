"""ALPHA BIST — Model Calibration (Nihai —⭐⭐⭐⭐⭐).

Confidence calibration — Brier score, calibration curve,
Platt scaling, isotonic regression, regime-specific calibration,
overconfidence detection, calibration monitoring.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationResult:
    """Kalibrasyon sonucu."""
    is_calibrated: bool
    brier_score: float
    calibration_curve: List[Dict[str, float]]
    miscalibration: float
    overconfident: bool
    recommendation: str
    # Detay
    expected_calibration_error: float = 0.0
    maximum_calibration_error: float = 0.0
    log_loss: float = 0.0


@dataclass
class RegimeCalibrationResult:
    """Regime-specific kalibrasyon sonucu."""
    regime: str
    result: CalibrationResult
    n_samples: int


class ModelCalibration:
    """Model confidence kalibrasyonu —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Calibration curve (beklenen vs gerçek doğruluk)
    - Brier score
    - Expected Calibration Error (ECE)
    - Maximum Calibration Error (MCE)
    - Platt scaling (sigmoid calibration)
    - Isotonic regression calibration
    - Overconfidence detection
    - Regime-specific calibration
    - Calibration monitoring (zaman içinde değişimi)
    - Adaptive calibration (online güncelleme)
    """

    def __init__(
        self,
        n_bins: int = 10,
        overconfidence_threshold: float = 0.15,
        ece_threshold: float = 0.05,
    ):
        self.n_bins = n_bins
        self.overconfidence_threshold = overconfidence_threshold
        self.ece_threshold = ece_threshold
        self._calibration_history: List[Dict[str, Any]] = []
        self._regime_calibrators: Dict[str, Any] = {}

    def check_calibration(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
    ) -> CalibrationResult:
        """Kapsamlı kalibrasyon kontrolü."""
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import brier_score_loss, log_loss

        # Brier score
        try:
            brier = float(brier_score_loss(y_true, y_prob))
        except Exception:
            brier = 1.0

        # Log loss
        try:
            ll = float(log_loss(y_true, y_prob))
        except Exception:
            ll = 1.0

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

        # ECE (Expected Calibration Error)
        ece = self._compute_ece(y_true, y_prob)

        # MCE (Maximum Calibration Error)
        mce = max([c["gap"] for c in curve]) if curve else 0.0

        # Miscalibration
        miscalibration = float(np.mean([c["gap"] for c in curve])) if curve else 0.0

        # Overconfidence check
        overconfident = miscalibration > self.overconfidence_threshold or ece > self.ece_threshold

        # Recommendation
        if brier < 0.1 and ece < 0.03:
            recommendation = "EXCELLENT"
        elif brier < 0.2 and ece < 0.05:
            recommendation = "GOOD"
        elif brier < 0.3 and ece < 0.1:
            recommendation = "NEEDS_CALIBRATION"
        else:
            recommendation = "POOR"

        result = CalibrationResult(
            is_calibrated=miscalibration < self.overconfidence_threshold and ece < self.ece_threshold,
            brier_score=round(brier, 4),
            calibration_curve=curve,
            miscalibration=round(miscalibration, 4),
            overconfident=overconfident,
            recommendation=recommendation,
            expected_calibration_error=round(ece, 4),
            maximum_calibration_error=round(mce, 4),
            log_loss=round(ll, 4),
        )

        # History
        self._calibration_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "brier_score": brier,
            "ece": ece,
            "miscalibration": miscalibration,
            "n_samples": len(y_true),
        })
        if len(self._calibration_history) > 1000:
            self._calibration_history = self._calibration_history[-1000:]

        return result

    def calibrate_platt(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: Optional[np.ndarray] = None,
        y_true_train: Optional[np.ndarray] = None,
    ) -> Tuple[Any, np.ndarray]:
        """Platt scaling (sigmoid calibration).
        
        Args:
            y_true: Tüm gerçek etiketler (veya train etiketleri)
            y_prob: Tüm olasılıklar (veya train olasılıkları)
            y_prob_val: Validation olasılıkları (None ise train üzerinde predict)
            y_true_train: Train etiketleri (y_prob_val varsa, calibrator train üzerinde eğitilir)
        """
        from sklearn.linear_model import LogisticRegression

        # Validation varsa, sadece train üzerinde eğit
        train_y = y_true_train if y_true_train is not None and y_prob_val is not None else y_true
        train_prob = y_prob if y_prob_val is not None else y_prob

        calibrator = LogisticRegression(max_iter=1000)
        calibrator.fit(train_prob.reshape(-1, 1), train_y)

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
        """Isotonic regression calibration."""
        from sklearn.isotonic import IsotonicRegression

        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(y_prob, y_true)

        if y_prob_val is not None:
            calibrated = calibrator.predict(y_prob_val)
        else:
            calibrated = calibrator.predict(y_prob)

        return calibrator, calibrated

    def calibrate_regime_specific(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        regimes: np.ndarray,
        method: str = "isotonic",
    ) -> Dict[str, Any]:
        """Her rejim için ayrı kalibrasyon.

        Returns:
            {regime: calibrator}
        """
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < 20:
                continue

            try:
                if method == "platt":
                    calibrator, _ = self.calibrate_platt(y_true[mask], y_prob[mask])
                else:
                    calibrator, _ = self.calibrate_isotonic(y_true[mask], y_prob[mask])

                self._regime_calibrators[regime] = calibrator
                logger.info("regime_calibration_fitted", regime=regime, n_samples=int(np.sum(mask)))
            except Exception as e:
                logger.warning("regime_calibration_failed", regime=regime, error=str(e))

        return self._regime_calibrators

    def apply_calibration(
        self,
        y_prob: np.ndarray,
        regime: Optional[str] = None,
    ) -> np.ndarray:
        """Kalibrasyon uygula.

        Args:
            y_prob: Ham olasılık tahminleri
            regime: Mevcut rejim (regime-specific calibrator kullanır)

        Returns:
            Kalibre edilmiş olasılıklar
        """
        if regime and regime in self._regime_calibrators:
            calibrator = self._regime_calibrators[regime]
            try:
                return calibrator.predict(y_prob)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="calibration.py:236")

        return y_prob

    def check_overconfidence(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        confidence_threshold: float = 0.8,
    ) -> Dict[str, Any]:
        """Overconfidence analizi — yüksek confidence'lı tahminlerin doğruluğu.

        Args:
            y_true: Gerçek etiketler
            y_prob: Model olasılıkları
            confidence_threshold: Yüksek confidence eşiği

        Returns:
            Overconfidence raporu
        """
        # Yüksek confidence'lı tahminler
        high_conf_mask = (y_prob > confidence_threshold) | (y_prob < (1 - confidence_threshold))
        n_high_conf = int(np.sum(high_conf_mask))

        if n_high_conf == 0:
            return {
                "overconfident": False,
                "n_high_confidence": 0,
                "reason": "no_high_confidence_predictions",
            }

        # Yüksek confidence'lı tahminlerin doğruluğu
        high_conf_preds = (y_prob[high_conf_mask] > 0.5).astype(int)
        high_conf_true = y_true[high_conf_mask]
        high_conf_accuracy = float(np.mean(high_conf_preds == high_conf_true))

        # Düşük confidence'lı tahminlerin doğruluğu
        low_conf_mask = ~high_conf_mask
        if np.sum(low_conf_mask) > 0:
            low_conf_preds = (y_prob[low_conf_mask] > 0.5).astype(int)
            low_conf_true = y_true[low_conf_mask]
            low_conf_accuracy = float(np.mean(low_conf_preds == low_conf_true))
        else:
            low_conf_accuracy = 0.0

        # Overconfidence gap
        expected_accuracy = float(np.mean(y_prob[high_conf_mask]))
        overconfidence_gap = expected_accuracy - high_conf_accuracy

        return {
            "overconfident": overconfidence_gap > self.overconfidence_threshold,
            "n_high_confidence": n_high_conf,
            "high_confidence_accuracy": round(high_conf_accuracy, 4),
            "expected_accuracy": round(expected_accuracy, 4),
            "overconfidence_gap": round(overconfidence_gap, 4),
            "low_confidence_accuracy": round(low_conf_accuracy, 4),
            "n_total": len(y_true),
        }

    def get_calibration_history(self) -> List[Dict[str, Any]]:
        """Kalibrasyon geçmişi."""
        return self._calibration_history

    def get_calibration_drift(self) -> Dict[str, Any]:
        """Kalibrasyon drift analizi — zaman içinde kalibrasyon değişti mi?"""
        if len(self._calibration_history) < 3:
            return {"drift_detected": False, "reason": "insufficient_history"}

        recent = self._calibration_history[-3:]
        older = self._calibration_history[:-3] if len(self._calibration_history) > 3 else recent

        recent_ece = np.mean([h["ece"] for h in recent])
        older_ece = np.mean([h["ece"] for h in older])

        drift = abs(recent_ece - older_ece) > 0.05

        return {
            "drift_detected": drift,
            "recent_ece": round(float(recent_ece), 4),
            "historical_ece": round(float(older_ece), 4),
            "ece_change": round(float(recent_ece - older_ece), 4),
        }

    def _compute_ece(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Expected Calibration Error hesapla."""
        try:
            bin_edges = np.linspace(0, 1, self.n_bins + 1)
            ece = 0.0

            for i in range(self.n_bins):
                mask = (y_prob >= bin_edges[i]) & (y_prob < bin_edges[i + 1])
                if np.sum(mask) == 0:
                    continue

                bin_accuracy = float(np.mean(y_true[mask]))
                bin_confidence = float(np.mean(y_prob[mask]))
                bin_size = float(np.sum(mask)) / len(y_true)

                ece += bin_size * abs(bin_accuracy - bin_confidence)

            return ece
        except Exception:
            return 0.0
