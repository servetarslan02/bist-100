"""
ALPHA BIST — Confidence Calibration Engine v1.0

Model confidence kalibrasyonu:
- Brier score hesaplama
- Expected Calibration Error (ECE)
- Overconfidence / Underconfidence tespit
- Platt scaling ile otomatik confidence adjustment
- Regime-specific calibration
- Reliability diagram data

KURAL: Model %90 confidence veriyorsa, gerçekten %90 olmalı.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict, deque
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class CalibrationBin:
    """Tek calibration bin'i."""
    bin_lower: float
    bin_upper: float
    avg_predicted: float
    avg_actual: float
    count: int
    miscalibration: float  # |predicted - actual|


@dataclass
class CalibrationResult:
    """Calibration sonucu."""
    timestamp: str
    brier_score: float
    ece: float  # Expected Calibration Error
    mce: float  # Maximum Calibration Error
    overconfident: bool
    underconfident: bool
    bins: List[CalibrationBin]
    regime_calibration: Dict[str, Dict]  # regime → {brier, ece, overconfident}
    suggested_adjustment: float  # Platt scaling adjustment
    sample_count: int
    confidence: str  # HIGH, MEDIUM, LOW (sonuca güven)


@dataclass
class PlattScalingParams:
    """Platt scaling parametreleri."""
    a: float  # Sigmoid parametresi
    b: float  # Sigmoid parametresi
    fitted: bool = False


class ConfidenceCalibrator:
    """Model confidence kalibrasyon motoru."""

    def __init__(self):
        self._calibration_history: deque = deque(maxlen=1000)
        self._platt_params: Dict[str, PlattScalingParams] = {}  # regime → params
        self._last_calibration: Optional[CalibrationResult] = None

    def calibrate(
        self,
        predictions: List[Dict],
        n_bins: Optional[int] = None,
        regime: Optional[str] = None,
    ) -> CalibrationResult:
        """Calibration analizi yap.

        Args:
            predictions: [{confidence: float, outcome: 0|1, regime: str}]
            n_bins: Bin sayısı (config default)
            regime: Spesifik rejim filtresi

        Returns:
            CalibrationResult
        """
        cfg = learning_settings.calibration
        n_bins = n_bins or cfg.n_bins

        # Filtrele
        if regime:
            filtered = [p for p in predictions if p.get("regime") == regime]
        else:
            filtered = predictions

        # Minimum sample kontrolü
        if len(filtered) < cfg.min_samples:
            logger.warning("Insufficient calibration data",
                         count=len(filtered), min_required=cfg.min_samples)
            return self._empty_result(len(filtered), regime)

        # Confidence ve outcome'ları çıkar
        confidences = np.array([p["confidence"] for p in filtered])
        outcomes = np.array([float(p["outcome"]) for p in filtered])

        # Confidence sınırları [0, 1]
        confidences = np.clip(confidences, 0, 1)

        # 1. Brier score
        brier = self._brier_score(confidences, outcomes)

        # 2. Calibration bins
        bins = self._create_bins(confidences, outcomes, n_bins)

        # 3. ECE ve MCE
        ece = self._expected_calibration_error(bins, len(filtered))
        mce = self._max_calibration_error(bins)

        # 4. Overconfidence / Underconfidence
        overconfident = self._check_overconfidence(bins)
        underconfident = self._check_underconfidence(bins)

        # 5. Platt scaling önerisi
        suggested_adj = self._suggest_platt_adjustment(bins, confidences, outcomes)

        # 6. Rejim bazlı calibration
        regime_cal = self._calibrate_by_regime(filtered, n_bins)

        # 7. Confidence seviyesi
        confidence_level = self._assess_confidence(len(filtered), ece)

        result = CalibrationResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            brier_score=round(brier, 4),
            ece=round(ece, 4),
            mce=round(mce, 4),
            overconfident=overconfident,
            underconfident=underconfident,
            bins=bins,
            regime_calibration=regime_cal,
            suggested_adjustment=round(suggested_adj, 4),
            sample_count=len(filtered),
            confidence=confidence_level,
        )

        self._calibration_history.append(result)
        if len(self._calibration_history) > 1000:
            self._calibration_history = self._calibration_history[-1000:]
        self._last_calibration = result

        logger.info("Calibration completed",
                   brier=round(brier, 4), ece=round(ece, 4),
                   overconfident=overconfident, samples=len(filtered))

        return result

    def adjust_confidence(
        self,
        raw_confidence: float,
        regime: Optional[str] = None,
    ) -> float:
        """Platt scaling ile confidence ayarla.

        Overconfident model için confidence'ı düşürür.
        Underconfident model için confidence'ı artırır.

        Args:
            raw_confidence: Ham model confidence'ı [0, 1]
            regime: Rejim (rejim-specific params varsa)

        Returns:
            Ayarlanmış confidence [0, 1]
        """
        raw_confidence = max(0.0, min(1.0, raw_confidence))

        # Platt params ara (rejim-specific veya global)
        params = None
        if regime:
            params = self._platt_params.get(regime)
        if params is None:
            params = self._platt_params.get("global")

        if params and params.fitted:
            # Platt scaling: P(y=1|f) = 1 / (1 + exp(a*f + b))
            adjusted = 1.0 / (1.0 + np.exp(params.a * raw_confidence + params.b))
            return max(0.0, min(1.0, adjusted))

        # Son calibration sonucundan basit adjustment
        if self._last_calibration and self._last_calibration.overconfident:
            adj = self._last_calibration.suggested_adjustment
            adjusted = raw_confidence + adj
            return max(0.0, min(1.0, adjusted))

        return raw_confidence

    def fit_platt_scaling(
        self,
        predictions: List[Dict],
        regime: Optional[str] = None,
    ) -> PlattScalingParams:
        """Platt scaling parametrelerini fit et.

        Platt scaling: P(y=1|f) = 1 / (1 + exp(a*f + b))
        Sigmoid fonksiyonu ile confidence'ı kalibre eder.

        Args:
            predictions: [{confidence, outcome}]
            regime: Rejim

        Returns:
            PlattScalingParams
        """
        if len(predictions) < 30:
            return PlattScalingParams(a=0, b=0, fitted=False)

        confidences = np.array([p["confidence"] for p in predictions])
        outcomes = np.array([float(p["outcome"]) for p in predictions])

        # Platt scaling için label smoothing
        # y' = (N+1)/(N+2) if y=1, 1/(N+2) if y=0
        n_pos = np.sum(outcomes == 1)
        n_neg = np.sum(outcomes == 0)

        targets = np.where(outcomes == 1,
                          (n_pos + 1) / (n_pos + 2),
                          1 / (n_neg + 2))

        # Sigmoid fit: minimize cross-entropy
        # f = confidence, target = smoothed outcome
        # P(y=1|f) = 1 / (1 + exp(a*f + b))
        from scipy.optimize import minimize

        def loss(params):
            a, b = params
            f = a * confidences + b
            # Numerik stabilite
            f = np.clip(f, -500, 500)
            p = 1.0 / (1.0 + np.exp(f))
            p = np.clip(p, 1e-10, 1 - 1e-10)
            # Cross-entropy loss
            ce = -np.mean(targets * np.log(p) + (1 - targets) * np.log(1 - p))
            return ce

        result = minimize(loss, x0=[-1.0, 0.0], method='Nelder-Mead')
        a_opt, b_opt = result.x

        params = PlattScalingParams(a=round(a_opt, 4), b=round(b_opt, 4), fitted=True)

        # Kaydet
        key = regime or "global"
        self._platt_params[key] = params

        logger.info("Platt scaling fitted", a=params.a, b=params.b,
                   regime=regime, samples=len(predictions))

        return params

    def get_calibration_report(self) -> Dict[str, Any]:
        """Calibration raporu."""
        if not self._last_calibration:
            return {"status": "No calibration data"}

        cal = self._last_calibration
        return {
            "status": "OK",
            "timestamp": cal.timestamp,
            "metrics": {
                "brier_score": cal.brier_score,
                "ece": cal.ece,
                "mce": cal.mce,
            },
            "diagnosis": {
                "overconfident": cal.overconfident,
                "underconfident": cal.underconfident,
                "suggested_adjustment": cal.suggested_adjustment,
            },
            "sample_count": cal.sample_count,
            "confidence": cal.confidence,
            "platt_params": {
                k: {"a": v.a, "b": v.b, "fitted": v.fitted}
                for k, v in self._platt_params.items()
            },
            "history_count": len(self._calibration_history),
        }

    # ===================== INTERNAL =====================

    def _brier_score(self, confidences: np.ndarray, outcomes: np.ndarray) -> float:
        """Brier score: mean((confidence - outcome)²). Düşük = iyi."""
        return float(np.mean((confidences - outcomes) ** 2))

    def _create_bins(
        self,
        confidences: np.ndarray,
        outcomes: np.ndarray,
        n_bins: int,
    ) -> List[CalibrationBin]:
        """Calibration bin'leri oluştur."""
        bins = []
        bin_edges = np.linspace(0, 1, n_bins + 1)

        for i in range(n_bins):
            lower = bin_edges[i]
            upper = bin_edges[i + 1]

            # Bin'e ait predictions
            if i == n_bins - 1:
                mask = (confidences >= lower) & (confidences <= upper)
            else:
                mask = (confidences >= lower) & (confidences < upper)

            count = int(np.sum(mask))
            if count == 0:
                continue

            avg_pred = float(np.mean(confidences[mask]))
            avg_actual = float(np.mean(outcomes[mask]))
            miscal = abs(avg_pred - avg_actual)

            bins.append(CalibrationBin(
                bin_lower=round(lower, 2),
                bin_upper=round(upper, 2),
                avg_predicted=round(avg_pred, 4),
                avg_actual=round(avg_actual, 4),
                count=count,
                miscalibration=round(miscal, 4),
            ))

        return bins

    def _expected_calibration_error(
        self,
        bins: List[CalibrationBin],
        total_count: int,
    ) -> float:
        """ECE: Ağırlıklı ortalama miscalibration."""
        if not bins or total_count == 0:
            return 0.0

        ece = sum(b.miscalibration * b.count for b in bins) / total_count
        return float(ece)

    def _max_calibration_error(self, bins: List[CalibrationBin]) -> float:
        """MCE: En kötü bin miscalibration."""
        if not bins:
            return 0.0
        return float(max(b.miscalibration for b in bins))

    def _check_overconfidence(self, bins: List[CalibrationBin]) -> bool:
        """Overconfidence: predicted > actual (çok fazla güveniyor)."""
        cfg = learning_settings.calibration
        for b in bins:
            if b.avg_predicted > b.avg_actual + cfg.overconfidence_threshold:
                return True
        return False

    def _check_underconfidence(self, bins: List[CalibrationBin]) -> bool:
        """Underconfidence: actual > predicted (yeterince güvenmiyor)."""
        cfg = learning_settings.calibration
        for b in bins:
            if b.avg_actual > b.avg_predicted + cfg.overconfidence_threshold:
                return True
        return False

    def _suggest_platt_adjustment(
        self,
        bins: List[CalibrationBin],
        confidences: np.ndarray,
        outcomes: np.ndarray,
    ) -> float:
        """Platt scaling adjustment önerisi."""
        if not bins:
            return 0.0

        # Genel eğilim: overconfident mi underconfident mi?
        avg_predicted = np.mean(confidences)
        avg_actual = np.mean(outcomes)

        # Negatif adjustment = overconfident (düşür)
        # Pozitif adjustment = underconfident (artır)
        adjustment = avg_actual - avg_predicted

        # Sınırla (-0.3 ile +0.3 arası)
        return max(-0.3, min(0.3, float(adjustment)))

    def _calibrate_by_regime(
        self,
        predictions: List[Dict],
        n_bins: int,
    ) -> Dict[str, Dict]:
        """Rejim bazlı calibration."""
        regime_groups = defaultdict(list)
        for p in predictions:
            regime = p.get("regime", "UNKNOWN")
            regime_groups[regime].append(p)

        regime_results = {}
        for regime, preds in regime_groups.items():
            if len(preds) < 10:
                continue

            confidences = np.array([p["confidence"] for p in preds])
            outcomes = np.array([float(p["outcome"]) for p in preds])
            confidences = np.clip(confidences, 0, 1)

            brier = self._brier_score(confidences, outcomes)
            bins = self._create_bins(confidences, outcomes, n_bins)
            ece = self._expected_calibration_error(bins, len(preds))
            overconf = self._check_overconfidence(bins)

            regime_results[regime] = {
                "brier_score": round(brier, 4),
                "ece": round(ece, 4),
                "overconfident": overconf,
                "sample_count": len(preds),
            }

        return regime_results

    def _assess_confidence(self, sample_count: int, ece: float) -> str:
        """Sonuca güven seviyesi."""
        if sample_count >= 200 and ece < 0.05:
            return "HIGH"
        elif sample_count >= 50 and ece < 0.15:
            return "MEDIUM"
        return "LOW"

    def _empty_result(self, count: int, regime: Optional[str]) -> CalibrationResult:
        """Boş calibration sonucu."""
        return CalibrationResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            brier_score=0.0,
            ece=0.0,
            mce=0.0,
            overconfident=False,
            underconfident=False,
            bins=[],
            regime_calibration={},
            suggested_adjustment=0.0,
            sample_count=count,
            confidence="LOW",
        )


# Singleton
confidence_calibrator = ConfidenceCalibrator()
