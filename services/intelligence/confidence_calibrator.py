"""
ALPHA BIST — Confidence Calibrator v1.0

Model confidence kalibrasyonu:
- Calibration curve hesaplama
- Brier score
- Overconfidence detection
- Automatic confidence adjustment
- Per-regime calibration

Kullanım:
    calibrator = ConfidenceCalibrator()
    calibrator.add_observation(0.8, True)   # %80 güven, gerçekleşti
    report = calibrator.calibrate()
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationBin:
    """Kalibrasyon bin'i."""
    bin_range: str           # "0.7-0.8"
    mean_prediction: float   # Ortalama tahmin
    mean_actual: float       # Gerçekleşen oran
    count: int               # Gözlem sayısı
    miscalibration: float    # |tahmin - gerçek|


@dataclass
class CalibrationReport:
    """Kalibrasyon raporu."""
    brier_score: float
    bins: List[CalibrationBin]
    overconfident: bool
    overconfidence_magnitude: float  # Ne kadar overconfident
    n_samples: int
    recommended_adjustment: float    # Confidence çarpanı
    regime: str = "ALL"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Observation:
    """Gözlem kaydı."""
    predicted_confidence: float
    actual_outcome: bool      # True = pozitif gerçekleşti
    regime: str = "UNKNOWN"
    ticker: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConfidenceCalibrator:
    """
    Confidence kalibrasyonu.

    Model %90 güven diyorsa, Gerçek %90 olmalı.
    Eğer gerçek %60 ise → overconfident.
    """

    def __init__(self, n_bins: int = 10, min_samples: int = 30):
        self._observations: deque = deque(maxlen=10000)
        self._n_bins = n_bins
        self._min_samples = min_samples

    def add_observation(
        self,
        predicted_confidence: float,
        actual_outcome: bool,
        regime: str = "UNKNOWN",
        ticker: str = "",
    ):
        """Gözlem ekle."""
        self._observations.append(Observation(
            predicted_confidence=max(0, min(1, predicted_confidence)),
            actual_outcome=actual_outcome,
            regime=regime,
            ticker=ticker,
        ))

    def add_batch(
        self,
        predictions: List[float],
        outcomes: List[bool],
        regimes: Optional[List[str]] = None,
    ):
        """Toplu gözlem ekle."""
        if regimes is None:
            regimes = ["UNKNOWN"] * len(predictions)

        for pred, outcome, regime in zip(predictions, outcomes, regimes):
            self.add_observation(pred, outcome, regime)

    def calibrate(self, regime: Optional[str] = None) -> CalibrationReport:
        """Kalibrasyon raporu üret.

        Args:
            regime: Belirli bir rejim için (None = tümü)

        Returns:
            CalibrationReport
        """
        # Filtrele
        if regime:
            obs = [o for o in self._observations if o.regime == regime]
        else:
            obs = self._observations

        if len(obs) < self._min_samples:
            return CalibrationReport(
                brier_score=1.0,
                bins=[],
                overconfident=False,
                overconfidence_magnitude=0,
                n_samples=len(obs),
                recommended_adjustment=1.0,
                regime=regime or "ALL",
            )

        predictions = np.array([o.predicted_confidence for o in obs])
        outcomes = np.array([1.0 if o.actual_outcome else 0.0 for o in obs])

        # Brier score
        brier = float(np.mean((predictions - outcomes) ** 2))

        # Calibration bins
        bins = np.linspace(0, 1, self._n_bins + 1)
        calibration_bins = []

        for i in range(self._n_bins):
            mask = (predictions >= bins[i]) & (predictions < bins[i + 1])
            if mask.sum() > 0:
                mean_pred = float(np.mean(predictions[mask]))
                mean_actual = float(np.mean(outcomes[mask]))
                calibration_bins.append(CalibrationBin(
                    bin_range=f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                    mean_prediction=round(mean_pred, 4),
                    mean_actual=round(mean_actual, 4),
                    count=int(mask.sum()),
                    miscalibration=round(abs(mean_pred - mean_actual), 4),
                ))

        # Overconfidence detection
        overconf_bins = [b for b in calibration_bins if b.mean_prediction > b.mean_actual + 0.1]
        overconfident = len(overconf_bins) > 0
        overconf_magnitude = max(
            (b.mean_prediction - b.mean_actual for b in overconf_bins),
            default=0.0,
        )

        # Önerilen ayarlama
        if overconfident and overconf_magnitude > 0.2:
            adjustment = 0.7  # %30 azalt
        elif overconfident and overconf_magnitude > 0.1:
            adjustment = 0.85  # %15 azalt
        elif brier > 0.3:
            adjustment = 0.9  # %10 azalt
        else:
            adjustment = 1.0  # Değişiklik yok

        return CalibrationReport(
            brier_score=round(brier, 4),
            bins=calibration_bins,
            overconfident=overconfident,
            overconfidence_magnitude=round(float(overconf_magnitude), 4),
            n_samples=len(obs),
            recommended_adjustment=round(adjustment, 4),
            regime=regime or "ALL",
        )

    def adjust_confidence(self, raw_confidence: float, regime: str = "UNKNOWN") -> float:
        """Confidence'ı kalibre et."""
        report = self.calibrate(regime)
        adjusted = raw_confidence * report.recommended_adjustment
        return max(0.0, min(1.0, adjusted))

    def get_hit_rate(self, regime: Optional[str] = None, threshold: float = 0.5) -> float:
        """Hit rate: threshold üstü tahminlerin doğruluk oranı."""
        if regime:
            obs = [o for o in self._observations if o.regime == regime]
        else:
            obs = self._observations

        if not obs:
            return 0.0

        high_conf = [o for o in obs if o.predicted_confidence >= threshold]
        if not high_conf:
            return 0.0

        correct = sum(1 for o in high_conf if o.actual_outcome)
        return round(correct / len(high_conf), 4)

    def get_regime_calibration(self) -> Dict[str, Dict]:
        """Rejim bazlı kalibrasyon."""
        regimes = set(o.regime for o in self._observations)
        result = {}
        for regime in regimes:
            report = self.calibrate(regime)
            if report.n_samples >= 10:
                result[regime] = {
                    "brier_score": report.brier_score,
                    "overconfident": report.overconfident,
                    "n_samples": report.n_samples,
                    "adjustment": report.recommended_adjustment,
                }
        return result

    def get_stats(self) -> Dict:
        """İstatistikler."""
        return {
            "total_observations": len(self._observations),
            "regimes": list(set(o.regime for o in self._observations)),
            "overall_brier": self.calibrate().brier_score if len(self._observations) >= self._min_samples else None,
        }

    def reset(self):
        """Sıfırla."""
        self._observations.clear()


# Singleton
confidence_calibrator = ConfidenceCalibrator()
