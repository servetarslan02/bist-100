"""ALPHA BIST — Prediction Layer v1.0

MultiHorizonModel → direction, expected return, confidence, quality grade.
Canonical contract ile uyumlu.
"""

import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
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
    model_source: str           # "ml" / "rule_based" / "fallback"


def compute_prediction(
    ticker: str,
    ml_prediction: float,
    ml_confidence: float,
    features: Dict[str, Any],
    horizon: int = 5,
    model_source: str = "ml",
) -> Prediction:
    """Model prediction'dan structured prediction üret.

    Args:
        ticker: Hisse kodu
        ml_prediction: Model çıktısı (forward return %)
        ml_confidence: Model güven skoru (0-1)
        features: Feature dict
        horizon: Tahmin ufku (gün)
        model_source: Model kaynağı
    """
    _s = lambda v: float(v) if isinstance(v, (int, float)) and np.isfinite(float(v)) else 0.0

    # Direction belirle
    if ml_prediction > 1.0:
        direction = "UP"
    elif ml_prediction < -1.0:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    # Uncertainty (prediction std'den)
    vol = _s(features.get("volatility_20d", 20))
    vol_norm = vol / 100 if vol > 1 else vol
    uncertainty = vol_norm * np.sqrt(horizon / 252) * 100

    # Risk/reward
    atr_pct = _s(features.get("atr_pct", 2))
    risk = atr_pct * 1.5  # Stop mesafesi
    reward = abs(ml_prediction)
    risk_reward = reward / risk if risk > 0 else 0

    # Quality grade
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
    )


def _compute_quality_grade(
    confidence: float,
    expected_return: float,
    risk_reward: float,
    volatility: float,
) -> str:
    """A+/A/B/C/D kalite sınıfı."""
    score = 0

    # Confidence katkısı
    if confidence > 0.8:
        score += 3
    elif confidence > 0.6:
        score += 2
    elif confidence > 0.4:
        score += 1

    # Expected return katkısı
    if abs(expected_return) > 5:
        score += 2
    elif abs(expected_return) > 2:
        score += 1

    # Risk/reward katkısı
    if risk_reward > 2:
        score += 2
    elif risk_reward > 1:
        score += 1

    # Volatilite cezası
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


def compute_multi_horizon_predictions(
    ticker: str,
    multi_model,  # MultiHorizonModel
    features: Dict[str, Any],
) -> Dict[int, Prediction]:
    """Tüm horizon'lar için prediction üret."""
    predictions = {}

    if multi_model is None:
        # Rule-based fallback
        for h in [1, 5, 20, 60]:
            pred = compute_prediction(
                ticker=ticker, ml_prediction=0.0, ml_confidence=0.1,
                features=features, horizon=h, model_source="fallback",
            )
            predictions[h] = pred
        return predictions

    for horizon, model in multi_model.horizon_models.items():
        try:
            ml_pred = model.predict(features)
            ml_conf = model.confidence_score
        except Exception:
            ml_pred = 0.0
            ml_conf = 0.0

        pred = compute_prediction(
            ticker=ticker,
            ml_prediction=ml_pred,
            ml_confidence=ml_conf,
            features=features,
            horizon=horizon,
            model_source="ml",
        )
        predictions[horizon] = pred

    return predictions
