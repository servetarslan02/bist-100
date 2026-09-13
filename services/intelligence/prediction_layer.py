"""
ALPHA BIST — Prediction Layer v2.0 (Enhanced)

Multi-horizon, multi-model prediction:
- 1d, 5d, 20d, 60d horizon'lar
- Ensemble integration
- Calibration integration
- Quality grading

v2.0: Multi-horizon + ensemble + calibration
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class Prediction:
    """Prediction çıktısı — canonical contract."""

    ticker: str
    direction: str  # UP / DOWN / NEUTRAL
    expected_return_pct: float  # Beklenen getiri %
    confidence: float  # 0-1
    uncertainty: float  # Tahmin belirsizliği
    time_horizon: int  # Gün
    risk_reward: float  # Risk/getiri oranı
    quality_grade: str  # A+/A/B/C/D
    model_source: str  # "ml" / "ensemble" / "rule_based" / "fallback"
    calibrated_confidence: float = 0.0
    model_agreement: float = 0.0

    def __repr__(self) -> str:
        """Sınıfın metinsel temsilini döndürür."""
        return (
            f"Prediction(ticker={self.ticker!r}, direction={self.direction!r}, "
            f"return={self.expected_return_pct:+.2f}%, conf={self.confidence:.2f}, grade={self.quality_grade!r})"
        )


@dataclass
class MultiHorizonPrediction:
    """Çoklu ufuk prediction."""

    ticker: str
    predictions: dict[int, Prediction]  # horizon → Prediction
    consensus_direction: str = "NEUTRAL"
    consensus_confidence: float = 0.0
    best_horizon: int = 5
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        """Sınıfın metinsel temsilini döndürür."""
        return (
            f"MultiHorizonPrediction(ticker={self.ticker!r}, consensus={self.consensus_direction!r}, "
            f"conf={self.consensus_confidence:.2f}, best_horizon={self.best_horizon}d)"
        )


def compute_prediction(
    ticker: str,
    ml_prediction: float,
    ml_confidence: float,
    features: dict[str, Any],
    horizon: int = 5,
    model_source: str = "ml",
    calibrated_confidence: float | None = None,
    model_agreement: float | None = None,
) -> Prediction:
    """Model prediction'dan structured prediction üret."""

    def _s(v) -> Any:
        """Sayısal değeri güvenli float'a dönüştürür; geçersiz veya sonsuzsa 0.0 döndürür."""
        return float(v) if isinstance(v, (int, float)) and np.isfinite(float(v)) else 0.0

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
    features: dict[str, Any],
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


def _rule_based_prediction(ticker: str, features: dict[str, Any], horizon: int) -> Prediction:
    """Kurumsal düzeyde çok faktörlü kural tabanlı tahmin motoru.

    Trend (EMA), Momentum, RSI ortalamaya dönüş, Hacim teyidi ve Volatilite ölçeklemesi kullanır.
    """
    # 1. Momentum ve Trend
    momentum_20d = float(features.get("momentum_20d", 0.0))
    momentum_5d = float(features.get("momentum_5d", 0.0))
    trend_momentum = 0.60 * momentum_20d + 0.40 * momentum_5d

    # EMA Trend Farkı
    ema_gap = 0.0
    ema_20 = features.get("ema_20")
    ema_50 = features.get("ema_50")
    if ema_20 is not None and ema_50 is not None and float(ema_50) > 0:
        ema_gap = (float(ema_20) - float(ema_50)) / float(ema_50) * 100.0

    # 2. RSI Ortalamaya Dönüş (Mean-Reversion) Düzeltmesi
    rsi = float(features.get("rsi_14", 50.0))
    # 50'den sapma: 70 üzerinde negatif düzeltme, 30 altında pozitif tepki beklentisi
    mean_reversion_adj = (50.0 - rsi) * 0.05

    # 3. Hacim Teyidi (Volume Confirmation)
    vol_ratio = float(features.get("volume_ratio_20d") or features.get("volume_surge", 1.0))
    vol_confirm = min(1.5, max(0.6, vol_ratio))

    # 4. Temel Ham Tahmin Sentezi
    raw_signal = (trend_momentum * 0.25) + (ema_gap * 0.35) + mean_reversion_adj

    # Hacim destekliyorsa sinyali güçlendir, zayıfsa sönümle
    confirmed_signal = raw_signal * vol_confirm

    # Ufuk (Horizon) zaman kökü ölçeklemesi: 20 günlük bazdan ufka genişlet
    predicted_return = confirmed_signal * np.sqrt(horizon / 20.0)

    # 5. Model Mutabakatı ve Güven Skoru
    signals_agree = sum([
        1 if trend_momentum > 0 else -1,
        1 if ema_gap > 0 else -1,
        1 if (rsi > 50) else -1,
    ])
    agreement_ratio = abs(signals_agree) / 3.0  # 0.33 ile 1.0 arası

    # Güven: Sinyal mutabakatı ve volatiliteye bağlı dinamik hesaplama
    vol_20d = float(features.get("volatility_20d", 25.0))
    vol_penalty = min(0.3, vol_20d / 100.0)
    base_conf = 0.40 + (agreement_ratio * 0.35) - vol_penalty
    calibrated_conf = float(np.clip(base_conf, 0.20, 0.85))

    return compute_prediction(
        ticker=ticker,
        ml_prediction=round(float(predicted_return), 4),
        ml_confidence=round(calibrated_conf, 4),
        features=features,
        horizon=horizon,
        model_source="rule_based_quant",
        calibrated_confidence=round(calibrated_conf, 4),
        model_agreement=round(agreement_ratio, 4),
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
