"""
ALPHA BIST — Probability Engine v1.0

Olasılıksal tahminler:
- Return distribution (getiri dağılımı)
- Hit rate (tahmin doğruluğu)
- Calibration (confidence vs actual frequency)
- Brier score

FAZ 5.3: Probability Engine
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ReturnDistribution:
    """Getiri dağılımı."""
    ticker: str
    horizon_days: int
    mean_return: float
    std_return: float
    skewness: float
    kurtosis: float
    percentiles: Dict[int, float]  # {10: -5.2, 25: -1.3, 50: 2.1, 75: 5.8, 90: 10.2}


@dataclass
class CalibrationResult:
    """Kalibrasyon sonucu."""
    mean_predicted: float
    mean_actual: float
    brier_score: float
    calibration_error: float
    bins: List[Dict[str, float]]  # [{predicted: 0.7, actual: 0.65, count: 50}, ...]


@dataclass
class PredictionOutcome:
    """Tahmin ve sonuç çifti."""
    predicted_probability: float
    actual_outcome: bool  # True = pozitif getiri
    ticker: str
    prediction_date: str
    horizon_days: int


class ProbabilityEngine:
    """Olasılıksal tahmin motoru."""

    def compute_return_distribution(
        self,
        ticker: str,
        historical_returns: List[float],
        horizon_days: int = 20,
    ) -> ReturnDistribution:
        """Geçmiş getirilerden getiri dağılımı çıkar.

        Args:
            historical_returns: Günlük getiri serisi (%)
        """
        if not historical_returns or len(historical_returns) < 10:
            return ReturnDistribution(
                ticker=ticker, horizon_days=horizon_days,
                mean_return=0, std_return=0, skewness=0, kurtosis=0,
                percentiles={10: 0, 25: 0, 50: 0, 75: 0, 90: 0},
            )

        returns = np.array(historical_returns)

        # Horizon getirisi (kümülatif)
        if horizon_days > 1 and len(returns) >= horizon_days:
            # Rolling horizon returns
            horizon_returns = []
            for i in range(len(returns) - horizon_days + 1):
                cum_return = np.prod(1 + returns[i:i + horizon_days] / 100) - 1
                horizon_returns.append(cum_return * 100)
            returns = np.array(horizon_returns)

        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))

        # Skewness
        if std_ret > 0:
            skew = float(np.mean(((returns - mean_ret) / std_ret) ** 3))
        else:
            skew = 0.0

        # Kurtosis
        if std_ret > 0:
            kurt = float(np.mean(((returns - mean_ret) / std_ret) ** 4)) - 3
        else:
            kurt = 0.0

        # Percentiles
        percentiles = {
            10: round(float(np.percentile(returns, 10)), 2),
            25: round(float(np.percentile(returns, 25)), 2),
            50: round(float(np.percentile(returns, 50)), 2),
            75: round(float(np.percentile(returns, 75)), 2),
            90: round(float(np.percentile(returns, 90)), 2),
        }

        return ReturnDistribution(
            ticker=ticker,
            horizon_days=horizon_days,
            mean_return=round(mean_ret, 4),
            std_return=round(std_ret, 4),
            skewness=round(skew, 4),
            kurtosis=round(kurt, 4),
            percentiles=percentiles,
        )

    def compute_hit_rate(self, predictions: List[PredictionOutcome]) -> float:
        """Tahmin doğruluğu (hit rate).

        predicted > 0.5 ve actual = True → doğru
        predicted <= 0.5 ve actual = False → doğru
        """
        if not predictions:
            return 0.0

        correct = 0
        for p in predictions:
            predicted_positive = p.predicted_probability > 0.5
            if predicted_positive == p.actual_outcome:
                correct += 1

        return round(correct / len(predictions), 4)

    def compute_calibration(
        self,
        predictions: List[PredictionOutcome],
        num_bins: int = 10,
    ) -> CalibrationResult:
        """Kalibrasyon analizi.

        %70 confidence verilen tahminlerin gerçekten %70'i doğru mu?
        """
        if not predictions:
            return CalibrationResult(
                mean_predicted=0, mean_actual=0,
                brier_score=0, calibration_error=0, bins=[],
            )

        # Bin'le
        bins = []
        for i in range(num_bins):
            lower = i / num_bins
            upper = (i + 1) / num_bins

            bin_predictions = [
                p for p in predictions
                if lower <= p.predicted_probability < upper
            ]

            if bin_predictions:
                mean_predicted = np.mean([p.predicted_probability for p in bin_predictions])
                mean_actual = np.mean([1.0 if p.actual_outcome else 0.0 for p in bin_predictions])
                bins.append({
                    "lower": round(lower, 2),
                    "upper": round(upper, 2),
                    "predicted": round(float(mean_predicted), 4),
                    "actual": round(float(mean_actual), 4),
                    "count": len(bin_predictions),
                })

        # Genel metrikler
        all_predicted = [p.predicted_probability for p in predictions]
        all_actual = [1.0 if p.actual_outcome else 0.0 for p in predictions]

        mean_predicted = float(np.mean(all_predicted))
        mean_actual = float(np.mean(all_actual))

        # Brier Score (düşük = iyi)
        brier = float(np.mean([(p - a) ** 2 for p, a in zip(all_predicted, all_actual)]))

        # Calibration error (Expected Calibration Error)
        cal_error = 0.0
        total_count = len(predictions)
        for b in bins:
            weight = b["count"] / total_count
            cal_error += weight * abs(b["predicted"] - b["actual"])

        return CalibrationResult(
            mean_predicted=round(mean_predicted, 4),
            mean_actual=round(mean_actual, 4),
            brier_score=round(brier, 4),
            calibration_error=round(cal_error, 4),
            bins=bins,
        )

    def compute_probability_from_features(
        self,
        features: Dict[str, float],
        model_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Feature'lardan olasılık tahmini (heuristic).

        Gerçek ML modeli yokken kullanılır.
        """
        if model_weights is None:
            model_weights = {
                "momentum": 0.25,
                "volume": 0.20,
                "volatility": 0.15,
                "trend": 0.20,
                "rsi": 0.20,
            }

        score = 0.0
        total_weight = 0.0

        # Momentum
        roc_5d = features.get("roc_5d", 0)
        roc_20d = features.get("roc_20d", 0) or features.get("momentum_20d", 0)
        momentum_score = 50 + min(roc_5d * 3, 20) + min(roc_20d * 1, 15)
        momentum_score = max(0, min(100, momentum_score))
        score += momentum_score * model_weights.get("momentum", 0.25)
        total_weight += model_weights.get("momentum", 0.25)

        # Volume
        vol_z = features.get("volume_zscore", 0)
        volume_score = 50 + min(vol_z * 10, 30) if vol_z > 0 else 50 + max(vol_z * 10, -30)
        volume_score = max(0, min(100, volume_score))
        score += volume_score * model_weights.get("volume", 0.20)
        total_weight += model_weights.get("volume", 0.20)

        # Volatility
        vol_20d = features.get("realized_vol_20d", 20)
        vol_score = max(0, min(100, 70 - vol_20d))  # Düşük vol = yüksek skor
        score += vol_score * model_weights.get("volatility", 0.15)
        total_weight += model_weights.get("volatility", 0.15)

        # Trend
        trend = features.get("trend_slope_20d", 0)
        trend_score = 50 + min(trend * 5, 30) if trend > 0 else 50 + max(trend * 5, -30)
        trend_score = max(0, min(100, trend_score))
        score += trend_score * model_weights.get("trend", 0.20)
        total_weight += model_weights.get("trend", 0.20)

        # RSI
        rsi = features.get("rsi_14", 50)
        if rsi > 70:
            rsi_score = max(0, 100 - (rsi - 70) * 2)  # Aşırı alım
        elif rsi < 30:
            rsi_score = min(100, 50 + (30 - rsi) * 2)  # Aşırı satım → fırsat
        else:
            rsi_score = 50
        score += rsi_score * model_weights.get("rsi", 0.20)
        total_weight += model_weights.get("rsi", 0.20)

        # Normalize
        final_score = score / total_weight if total_weight > 0 else 50

        # Olasılığa çevir (sigmoid-like)
        probability = 1 / (1 + np.exp(-(final_score - 50) / 15))

        return {
            "score": round(final_score, 2),
            "probability_positive": round(float(probability), 4),
            "confidence": round(abs(probability - 0.5) * 2, 4),  # 0-1 arası
        }


# Singleton
probability_engine = ProbabilityEngine()
