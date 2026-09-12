"""
ALPHA BIST — Confidence Calibrator v1.1

Model confidence kalibrasyonu:
- Calibration curve hesaplama
- Brier score
- Overconfidence detection
- Automatic confidence adjustment
- Per-regime calibration
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_N_BINS: int = 10
DEFAULT_MIN_SAMPLES: int = 30
MAX_OBSERVATIONS: int = 10_000
OVERCONFIDENCE_THRESHOLD: float = 0.1
OVERCONFIDENCE_STRONG_THRESHOLD: float = 0.2
BRIER_POOR_THRESHOLD: float = 0.3
ADJUSTMENT_STRONG: float = 0.70       # %30 azalt
ADJUSTMENT_MODERATE: float = 0.85     # %15 azalt
ADJUSTMENT_SLIGHT: float = 0.90       # %10 azalt
ADJUSTMENT_NONE: float = 1.00         # değişiklik yok
MIN_REGIME_SAMPLES: int = 10
DEFAULT_HIT_RATE_THRESHOLD: float = 0.5

__all__ = [
    "CalibrationBin",
    "CalibrationReport",
    "Observation",
    "ConfidenceCalibrator",
    "confidence_calibrator",
]


@dataclass
class CalibrationBin:
    """Kalibrasyon bin'i.

    Belirli bir güven aralığındaki tahminlerin gerçekleşme oranını temsil eder.
    """

    bin_range: str
    mean_prediction: float
    mean_actual: float
    count: int
    miscalibration: float

    def __repr__(self) -> str:
        return (
            f"<CalibrationBin range={self.bin_range} "
            f"pred={self.mean_prediction:.3f} actual={self.mean_actual:.3f} "
            f"n={self.count}>"
        )


@dataclass
class CalibrationReport:
    """Kalibrasyon raporu.

    Brier skoru, bin bazlı kalibrasyon ve overconfidence analizi içerir.
    """

    brier_score: float
    bins: list[CalibrationBin]
    overconfident: bool
    overconfidence_magnitude: float
    n_samples: int
    recommended_adjustment: float
    regime: str = "ALL"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<CalibrationReport regime={self.regime!r} brier={self.brier_score:.4f} "
            f"overconf={self.overconfident} adj={self.recommended_adjustment:.2f} "
            f"n={self.n_samples}>"
        )


@dataclass
class Observation:
    """Gözlem kaydı.

    Tek bir tahmin-sonuç çiftini ve bağlam bilgisini tutar.
    """

    predicted_confidence: float
    actual_outcome: bool
    regime: str = "UNKNOWN"
    ticker: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<Observation conf={self.predicted_confidence:.3f} "
            f"hit={self.actual_outcome} regime={self.regime!r}>"
        )


class ConfidenceCalibrator:
    """Confidence kalibrasyon motoru.

    Model %90 güven diyorsa, Gerçek %90 olmalıdır.
    Eğer gerçek %60 ise → overconfident.
    """

    def __repr__(self) -> str:
        return f"<ConfidenceCalibrator observations={len(self._observations)}>"

    def __init__(self, n_bins: int = DEFAULT_N_BINS, min_samples: int = DEFAULT_MIN_SAMPLES) -> None:
        """Kalibratörü başlat.

        Args:
            n_bins: Kalibrasyon histogram bin sayısı.
            min_samples: Rapor üretmek için minimum gözlem sayısı.
        """
        self._observations: deque[Observation] = deque(maxlen=MAX_OBSERVATIONS)
        self._n_bins = n_bins
        self._min_samples = min_samples

    def add_observation(
        self,
        predicted_confidence: float,
        actual_outcome: bool,
        regime: str = "UNKNOWN",
        ticker: str = "",
    ) -> None:
        """Tek gözlem ekle.

        Args:
            predicted_confidence: Model güven skoru (0-1).
            actual_outcome: Tahmin gerçekleşti mi.
            regime: Piyasa rejimi.
            ticker: Varlık kodu.

        Raises:
            ValueError: predicted_confidence 0-1 aralığı dışındaysa.
        """
        if not 0.0 <= predicted_confidence <= 1.0:
            raise ValueError(f"predicted_confidence 0-1 aralığında olmalıdır: {predicted_confidence}")

        self._observations.append(
            Observation(
                predicted_confidence=predicted_confidence,
                actual_outcome=actual_outcome,
                regime=regime,
                ticker=ticker,
            )
        )

    def add_batch(
        self,
        predictions: list[float],
        outcomes: list[bool],
        regimes: list[str] | None = None,
    ) -> None:
        """Toplu gözlem ekle.

        Args:
            predictions: Güven skorları listesi.
            outcomes: Gerçekleşme sonuçları listesi.
            regimes: Rejim listesi (opsiyonel).

        Raises:
            ValueError: Listeler farklı uzunlukta ise.
        """
        if regimes is not None and len(regimes) != len(predictions):
            raise ValueError("predictions ve regimes listeleri aynı uzunlukta olmalıdır.")

        if regimes is None:
            regimes = ["UNKNOWN"] * len(predictions)

        for pred, outcome, regime in zip(predictions, outcomes, regimes, strict=False):
            self.add_observation(pred, outcome, regime)

    def calibrate(self, regime: str | None = None) -> CalibrationReport:
        """Kalibrasyon raporu üret.

        Args:
            regime: Belirli bir rejim için filtre (None = tümü).

        Returns:
            CalibrationReport: Brier skoru, bin'ler ve overconfidence analizi.
        """
        obs = [o for o in self._observations if o.regime == regime] if regime else list(self._observations)

        if len(obs) < self._min_samples:
            logger.warning("kalibrasyon_yetersiz_veri", n=len(obs), minimum=self._min_samples)
            return CalibrationReport(
                brier_score=1.0,
                bins=[],
                overconfident=False,
                overconfidence_magnitude=0.0,
                n_samples=len(obs),
                recommended_adjustment=ADJUSTMENT_NONE,
                regime=regime or "ALL",
            )

        predictions = np.array([o.predicted_confidence for o in obs])
        outcomes = np.array([1.0 if o.actual_outcome else 0.0 for o in obs])

        # Brier score
        brier = float(np.mean((predictions - outcomes) ** 2))

        # Calibration bins
        bins_edges = np.linspace(0, 1, self._n_bins + 1)
        calibration_bins: list[CalibrationBin] = []

        for i in range(self._n_bins):
            mask = (predictions >= bins_edges[i]) & (predictions < bins_edges[i + 1])
            if mask.sum() > 0:
                mean_pred = float(np.mean(predictions[mask]))
                mean_actual = float(np.mean(outcomes[mask]))
                calibration_bins.append(
                    CalibrationBin(
                        bin_range=f"{bins_edges[i]:.1f}-{bins_edges[i + 1]:.1f}",
                        mean_prediction=round(mean_pred, 4),
                        mean_actual=round(mean_actual, 4),
                        count=int(mask.sum()),
                        miscalibration=round(abs(mean_pred - mean_actual), 4),
                    )
                )

        # Overconfidence detection
        overconf_bins = [
            b for b in calibration_bins
            if b.mean_prediction > b.mean_actual + OVERCONFIDENCE_THRESHOLD
        ]
        overconfident = len(overconf_bins) > 0
        overconf_magnitude = max(
            (b.mean_prediction - b.mean_actual for b in overconf_bins),
            default=0.0,
        )

        # Önerilen ayarlama
        if overconfident and overconf_magnitude > OVERCONFIDENCE_STRONG_THRESHOLD:
            adjustment = ADJUSTMENT_STRONG
        elif overconfident and overconf_magnitude > OVERCONFIDENCE_THRESHOLD:
            adjustment = ADJUSTMENT_MODERATE
        elif brier > BRIER_POOR_THRESHOLD:
            adjustment = ADJUSTMENT_SLIGHT
        else:
            adjustment = ADJUSTMENT_NONE

        logger.info(
            "kalibrasyon_raporu",
            regime=regime or "ALL",
            brier=round(brier, 4),
            overconfident=overconfident,
            adjustment=adjustment,
            n_samples=len(obs),
        )

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
        """Confidence'ı kalibre et.

        Args:
            raw_confidence: Ham güven skoru (0-1).
            regime: Piyasa rejimi.

        Returns:
            Kalibre edilmiş güven skoru (0-1).
        """
        report = self.calibrate(regime)
        adjusted = raw_confidence * report.recommended_adjustment
        return max(0.0, min(1.0, adjusted))

    def get_hit_rate(self, regime: str | None = None, threshold: float = DEFAULT_HIT_RATE_THRESHOLD) -> float:
        """Hit rate hesapla.

        Args:
            regime: Filtrelenecek rejim (None = tümü).
            threshold: Güven eşiği.

        Returns:
            Eşik üstü tahminlerin doğruluk oranı (0-1).
        """
        obs = [o for o in self._observations if o.regime == regime] if regime else list(self._observations)

        if not obs:
            return 0.0

        high_conf = [o for o in obs if o.predicted_confidence >= threshold]
        if not high_conf:
            return 0.0

        correct = sum(1 for o in high_conf if o.actual_outcome)
        return round(correct / len(high_conf), 4)

    def get_regime_calibration(self) -> dict[str, dict[str, Any]]:
        """Rejim bazlı kalibrasyon özetini döndür.

        Returns:
            Rejim adı → kalibrasyon metrikleri sözlüğü.
        """
        regimes = set(o.regime for o in self._observations)
        result: dict[str, dict[str, Any]] = {}
        for regime in regimes:
            report = self.calibrate(regime)
            if report.n_samples >= MIN_REGIME_SAMPLES:
                result[regime] = {
                    "brier_score": report.brier_score,
                    "overconfident": report.overconfident,
                    "n_samples": report.n_samples,
                    "adjustment": report.recommended_adjustment,
                }
        return result

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndür.

        Returns:
            Toplam gözlem, rejimler ve genel Brier skoru.
        """
        return {
            "total_observations": len(self._observations),
            "regimes": list(set(o.regime for o in self._observations)),
            "overall_brier": (
                self.calibrate().brier_score
                if len(self._observations) >= self._min_samples
                else None
            ),
        }

    def reset(self) -> None:
        """Tüm gözlemleri sıfırla."""
        self._observations.clear()
        logger.info("kalibrasyon_sifirlandi")


# Singleton
confidence_calibrator = ConfidenceCalibrator()
