"""
ALPHA BIST — Prediction Layer v2.0 (Enhanced)

Multi-horizon, multi-model prediction:
- 1d, 5d, 20d, 60d horizon'lar
- Ensemble integration
- Calibration integration
- Quality grading

v2.0: Multi-horizon + ensemble + calibration
"""

import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class Prediction:
    """Prediction çıktısı — canonical contract."""
    ticker: str
    direction: str              # UP / DOWN / NEUTRAL
    expected_return_pct: float  # Beklenen getiri %
    confidence: float           # 0-1
    uncertainty: float          # Tahmin belirsizliği
    time_horizon: int           # Gün
    risk_reward: float          # Risk/getiri oranı
    quality_grade: str          # A+/A/B/C/D
    model_source: str           # "ml" / "ensemble" / "rule_based" / "fallback"
    calibrated_confidence: float = 0.0
    model_agreement: float = 0.0


@dataclass
class MultiHorizonPrediction:
    """Çoklu ufuk prediction."""
    ticker: str
    predictions: Dict[int, Prediction]  # horizon → Prediction
    consensus_direction: str = "NEUTRAL"
    consensus_confidence: float = 0.0
    best_horizon: int = 5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def compute_prediction(
    ticker: str,
    ml_prediction: float,
    ml_confidence: float,
    features: Dict[str, Any],
    horizon: int = 5,
    model_source: str = "ml",
    calibrated_confidence: Optional[float] = None,
    model_agreement: Optional[float] = None,
) -> Prediction:
    """Model prediction'dan structured prediction üret."""
    _s = lambda v: float(v) if isinstance(v, (int, float)) and np.isfinite(float(v)) else 0.0

    if ml_prediction > 1.0:
        direction = "UP"
    elif ml_prediction < -1.0:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    vol = _s(features.get("volatility_20d", 20))
    vol_norm = vol / 100 if vol > 1 else vol
    uncertainty = vol_norm * np.sqrt(horizon / 252) * 100

    atr_pct = _s(features.get("atr_pct", 2))
    risk = atr_pct * 1.5
    reward = abs(ml_prediction)
    risk_reward = reward / risk if risk > 0 else 0

    quality_grade = _compute_quality_grade(ml_confidence, ml_prediction, risk_reward, vol_norm)

    return Prediction(
        ticker=ticker,
        direction=direction,
        expected_return_pct=round(ml_prediction, 4),
        confidence=round(ml_confidence, 4),
        uncertainty=round(uncertainty, 4),
        time_horizon=horizon,
        risk_reward=round(risk_reward, 4),
        quality_grade=quality_grade,
        model_source=model_source,
        calibrated_confidence=round(calibrated_confidence or ml_confidence, 4),
        model_agreement=round(model_agreement or 0.0, 4),
    )


def compute_multi_horizon_predictions(
    ticker: str,
    features: Dict[str, Any],
    ensemble_forecaster=None,
    calibrator=None,
    regime: str = "UNKNOWN",
) -> MultiHorizonPrediction:
    """Tüm horizon'lar için prediction üret.

    Args:
        ticker: Hisse kodu
        features: Feature dict
        ensemble_forecaster: EnsembleForecaster instance (opsiyonel)
        calibrator: ConfidenceCalibrator instance (opsiyonel)
        regime: Mevcut rejim
    """
    horizons = [1, 5, 20, 60]
    predictions = {}

    for h in horizons:
        if ensemble_forecaster:
            # Ensemble forecast kullan
            result = ensemble_forecaster.forecast(features, horizon=h, regime=regime, ticker=ticker)
            pred = compute_prediction(
                ticker=ticker,
                ml_prediction=result.ensemble_prediction,
                ml_confidence=result.ensemble_confidence,
                features=features,
                horizon=h,
                model_source="ensemble",
                calibrated_confidence=result.calibrated_confidence,
                model_agreement=result.model_agreement,
            )
        else:
            # Rule-based fallback
            pred = _rule_based_prediction(ticker, features, h)

        # Kalibrasyon
        if calibrator:
            pred.calibrated_confidence = calibrator.adjust_confidence(pred.calibrated_confidence, regime)

        predictions[h] = pred

    # Consensus
    directions = [p.direction for p in predictions.values()]
    up_count = directions.count("UP")
    down_count = directions.count("DOWN")

    if up_count > down_count:
        consensus = "UP"
    elif down_count > up_count:
        consensus = "DOWN"
    else:
        consensus = "NEUTRAL"

    avg_conf = np.mean([p.calibrated_confidence for p in predictions.values()])

    # En iyi horizon (en yüksek confidence)
    best_h = max(predictions.keys(), key=lambda h: predictions[h].calibrated_confidence)

    return MultiHorizonPrediction(
        ticker=ticker,
        predictions=predictions,
        consensus_direction=consensus,
        consensus_confidence=round(float(avg_conf), 4),
        best_horizon=best_h,
    )


def _rule_based_prediction(ticker: str, features: Dict, horizon: int) -> Prediction:
    """Rule-based fallback prediction."""
    momentum = features.get("momentum_20d", 0)
    rsi = features.get("rsi_14", 50)

    base = momentum * 0.3
    if rsi > 70:
        base -= 1.0
    elif rsi < 30:
        base += 1.0

    predicted = base * np.sqrt(horizon / 20)
    conf = max(0.2, 0.5 - abs(predicted) / 20)

    return compute_prediction(
        ticker=ticker,
        ml_prediction=predicted,
        ml_confidence=conf,
        features=features,
        horizon=horizon,
        model_source="rule_based",
    )


def _compute_quality_grade(
    confidence: float,
    expected_return: float,
    risk_reward: float,
    volatility: float,
) -> str:
    """A+/A/B/C/D kalite sınıfı."""
    score = 0

    if confidence > 0.8:
        score += 3
    elif confidence > 0.6:
        score += 2
    elif confidence > 0.4:
        score += 1

    if abs(expected_return) > 5:
        score += 2
    elif abs(expected_return) > 2:
        score += 1

    if risk_reward > 2:
        score += 2
    elif risk_reward > 1:
        score += 1

    if volatility > 0.4:
        score -= 1

    if score >= 7:
        return "A+"
    elif score >= 5:
        return "A"
    elif score >= 3:
        return "B"
    elif score >= 1:
        return "C"
    else:
        return "D"
