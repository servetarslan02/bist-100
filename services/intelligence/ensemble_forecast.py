"""
ALPHA BIST — Ensemble Forecast Engine v1.1

Çoklu model ensemble forecasting:
- LightGBM, XGBoost, Heuristic, Statistical models
- Regime-based model weighting
- Model agreement scoring
- Confidence calibration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_HORIZON: int = 5
DEFAULT_FALLBACK_CONFIDENCE: float = 0.3
DEFAULT_SINGLE_MODEL_AGREEMENT: float = 0.5
MIN_MODEL_COUNT_FOR_AGREEMENT: int = 2
AGREEMENT_MEAN_EPSILON: float = 0.001
FULL_MODEL_FACTOR_COUNT: int = 4
OVERCONFIDENCE_CEILING: float = 0.9
OVERCONFIDENCE_PENALTY: float = 0.5
HEURISTIC_RSI_OVERBOUGHT: float = 70.0
HEURISTIC_RSI_OVERSOLD: float = 30.0
HEURISTIC_RSI_DEFAULT: float = 50.0
HEURISTIC_BASE_WEIGHT: float = 0.3
HEURISTIC_RSI_PENALTY: float = 1.0
HEURISTIC_CONF_BASE: float = 0.6
MOMENTUM_5D_WEIGHT: float = 0.6
MOMENTUM_20D_WEIGHT: float = 0.4
MOMENTUM_CONF_BASE: float = 0.7
STAT_REVERSION_BB_WEIGHT: float = 5.0
STAT_REVERSION_RSI_WEIGHT: float = 0.1
STAT_REVERSION_SCALE: float = 0.5
STAT_CONF_BASE: float = 0.5
CONF_NORMALIZER: float = 20.0
MOMENTUM_CONF_NORMALIZER: float = 15.0

__all__ = [
    "ModelForecast",
    "EnsembleResult",
    "EnsembleForecaster",
    "heuristic_model",
    "momentum_model",
    "statistical_model",
    "ensemble_forecaster",
]


@dataclass
class ModelForecast:
    """Tek model tahmini.

    Bir modelin tahmin sonucu ve güven bilgisini temsil eder.
    """

    model_name: str
    predicted_return: float
    confidence: float
    horizon_days: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"<ModelForecast model={self.model_name!r} "
            f"pred={self.predicted_return:.4f} conf={self.confidence:.3f}>"
        )


@dataclass
class EnsembleResult:
    """Ensemble sonucu.

    Tüm modellerin birleşik tahmini, güven ve anlaşma metrikleri.
    """

    ticker: str
    horizon_days: int
    ensemble_prediction: float
    ensemble_confidence: float
    model_agreement: float
    model_predictions: dict[str, float]
    model_confidences: dict[str, float]
    regime: str
    weights_used: dict[str, float]
    calibrated_confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<EnsembleResult ticker={self.ticker!r} "
            f"pred={self.ensemble_prediction:.4f} conf={self.calibrated_confidence:.3f} "
            f"agree={self.model_agreement:.3f} regime={self.regime!r}>"
        )


class EnsembleForecaster:
    """Çoklu model ensemble forecaster.

    Rejime göre model ağırlıklarını değiştirir.
    Model agreement = confidence proxy.
    """

    REGIME_WEIGHTS: dict[str, dict[str, float]] = {
        "BULL": {"lightgbm": 0.30, "xgboost": 0.25, "heuristic": 0.20, "statistical": 0.15, "momentum": 0.10},
        "BEAR": {"lightgbm": 0.20, "xgboost": 0.20, "heuristic": 0.25, "statistical": 0.25, "momentum": 0.10},
        "HIGH_VOLATILITY": {"lightgbm": 0.20, "xgboost": 0.20, "heuristic": 0.30, "statistical": 0.20, "momentum": 0.10},
        "LOW_VOLATILITY": {"lightgbm": 0.30, "xgboost": 0.25, "heuristic": 0.15, "statistical": 0.20, "momentum": 0.10},
        "SIDEWAYS": {"lightgbm": 0.25, "xgboost": 0.25, "heuristic": 0.20, "statistical": 0.20, "momentum": 0.10},
        "RISK_ON": {"lightgbm": 0.25, "xgboost": 0.25, "heuristic": 0.20, "statistical": 0.15, "momentum": 0.15},
        "RISK_OFF": {"lightgbm": 0.20, "xgboost": 0.20, "heuristic": 0.30, "statistical": 0.25, "momentum": 0.05},
        "CRISIS": {"lightgbm": 0.15, "xgboost": 0.15, "heuristic": 0.35, "statistical": 0.30, "momentum": 0.05},
        "RECOVERY": {"lightgbm": 0.25, "xgboost": 0.25, "heuristic": 0.20, "statistical": 0.20, "momentum": 0.10},
        "UNKNOWN": {"lightgbm": 0.25, "xgboost": 0.25, "heuristic": 0.20, "statistical": 0.20, "momentum": 0.10},
    }

    def __repr__(self) -> str:
        return f"<EnsembleForecaster models={list(self._models.keys())}>"

    def __init__(self) -> None:
        """Ensemble forecaster'ı başlat."""
        self._models: dict[str, Callable[..., Any]] = {}
        self._performance: dict[str, dict[str, Any]] = {}

    def register_model(self, name: str, predict_fn: Callable[..., Any]) -> None:
        """Model kaydet.

        Args:
            name: Model adı.
            predict_fn: Tahmin fonksiyonu (features, horizon) → (pred, conf) veya dict.
        """
        self._models[name] = predict_fn
        logger.info("forecast_model_kaydedildi", name=name)

    def forecast(
        self,
        features: dict[str, Any],
        horizon: int = DEFAULT_HORIZON,
        regime: str = "UNKNOWN",
        ticker: str = "",
    ) -> EnsembleResult:
        """Ensemble forecast üret.

        Args:
            features: Feature sözlüğü.
            horizon: Tahmin ufku (gün).
            regime: Mevcut piyasa rejimi.
            ticker: Hisse kodu.

        Returns:
            EnsembleResult: Birleşik tahmin, güven ve model detayları.
        """
        forecasts: dict[str, float] = {}
        confidences: dict[str, float] = {}

        for name, model_fn in self._models.items():
            try:
                result = model_fn(features, horizon)
                if isinstance(result, tuple):
                    pred, conf = result
                elif isinstance(result, dict):
                    pred = result.get("prediction", 0.0)
                    conf = result.get("confidence", DEFAULT_FALLBACK_CONFIDENCE)
                else:
                    pred = float(result)
                    conf = DEFAULT_FALLBACK_CONFIDENCE

                forecasts[name] = pred
                confidences[name] = conf

            except Exception as e:
                logger.warning("model_hatasi", model=name, error=str(e))

        # Heuristic fallback
        if not forecasts:
            logger.warning("hic_model_basarisi_yok", regime=regime)
            forecasts["heuristic"] = self._heuristic_predict(features, horizon)
            confidences["heuristic"] = DEFAULT_FALLBACK_CONFIDENCE

        # Rejime göre ağırlıklar
        weights = self.REGIME_WEIGHTS.get(regime, self.REGIME_WEIGHTS["UNKNOWN"])
        active_weights = {name: weights.get(name, 1.0 / len(forecasts)) for name in forecasts}
        total_w = sum(active_weights.values())
        if total_w > 0:
            active_weights = {k: v / total_w for k, v in active_weights.items()}
        else:
            # Eşit ağırlık fallback
            active_weights = {k: 1.0 / len(forecasts) for k in forecasts}

        # Ağırlıklı ensemble
        ensemble_pred = sum(forecasts[name] * active_weights.get(name, 0) for name in forecasts)
        ensemble_conf = sum(confidences[name] * active_weights.get(name, 0) for name in forecasts)

        # Model agreement
        preds = list(forecasts.values())
        if len(preds) >= MIN_MODEL_COUNT_FOR_AGREEMENT:
            pred_std = float(np.std(preds))
            pred_mean = float(np.mean(np.abs(preds)))
            agreement = max(0.0, 1.0 - pred_std / max(pred_mean, AGREEMENT_MEAN_EPSILON))
        else:
            agreement = DEFAULT_SINGLE_MODEL_AGREEMENT

        calibrated = self._calibrate_confidence(ensemble_conf, agreement, len(forecasts))

        logger.info(
            "ensemble_forecast",
            ticker=ticker,
            regime=regime,
            models=len(forecasts),
            agreement=round(agreement, 3),
            calibrated=round(calibrated, 3),
        )

        return EnsembleResult(
            ticker=ticker,
            horizon_days=horizon,
            ensemble_prediction=round(ensemble_pred, 4),
            ensemble_confidence=round(ensemble_conf, 4),
            model_agreement=round(agreement, 4),
            model_predictions={k: round(v, 4) for k, v in forecasts.items()},
            model_confidences={k: round(v, 4) for k, v in confidences.items()},
            regime=regime,
            weights_used={k: round(v, 4) for k, v in active_weights.items()},
            calibrated_confidence=round(calibrated, 4),
        )

    def _heuristic_predict(self, features: dict[str, Any], horizon: int) -> float:
        """Heuristic tahmin (fallback).

        Args:
            features: Feature sözlüğü.
            horizon: Tahmin ufku.

        Returns:
            Heuristic tahmini (float).
        """
        momentum = features.get("momentum_20d", 0)
        rsi = features.get("rsi_14", HEURISTIC_RSI_DEFAULT)

        base = momentum * HEURISTIC_BASE_WEIGHT
        if rsi > HEURISTIC_RSI_OVERBOUGHT:
            base -= HEURISTIC_RSI_PENALTY
        elif rsi < HEURISTIC_RSI_OVERSOLD:
            base += HEURISTIC_RSI_PENALTY

        return base * np.sqrt(horizon / 20)

    def _calibrate_confidence(
        self, raw_confidence: float, agreement: float, n_models: int
    ) -> float:
        """Confidence kalibrasyonu.

        Args:
            raw_confidence: Ham güven skoru.
            agreement: Model anlaşma oranı.
            n_models: Katılan model sayısı.

        Returns:
            Kalibre edilmiş güven skoru (0-1).
        """
        model_factor = min(1.0, n_models / FULL_MODEL_FACTOR_COUNT)
        calibrated = raw_confidence * agreement * model_factor

        if calibrated > OVERCONFIDENCE_CEILING:
            calibrated = OVERCONFIDENCE_CEILING - (calibrated - OVERCONFIDENCE_CEILING) * OVERCONFIDENCE_PENALTY

        return max(0.0, min(1.0, calibrated))

    def update_performance(self, model_name: str, accuracy: float, sharpe: float = 0.0) -> None:
        """Model performansını güncelle.

        Args:
            model_name: Model adı.
            accuracy: Doğruluk oranı.
            sharpe: Sharpe oranı.
        """
        self._performance[model_name] = {
            "accuracy": accuracy,
            "sharpe": sharpe,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def get_model_performance(self) -> dict[str, dict[str, Any]]:
        """Model performanslarını döndür.

        Returns:
            Model adı → performans metrikleri sözlüğü.
        """
        return self._performance


# ─── Built-in Models ─────────────────────────────────────────────────


def heuristic_model(features: dict[str, Any], horizon: int) -> tuple[float, float]:
    """Heuristic model (momentum + RSI).

    Args:
        features: Feature sözlüğü.
        horizon: Tahmin ufku.

    Returns:
        (tahmin, güven) çifti.
    """
    momentum = features.get("momentum_20d", 0)
    rsi = features.get("rsi_14", HEURISTIC_RSI_DEFAULT)
    pred = momentum * HEURISTIC_BASE_WEIGHT
    if rsi > HEURISTIC_RSI_OVERBOUGHT:
        pred -= HEURISTIC_RSI_PENALTY
    elif rsi < HEURISTIC_RSI_OVERSOLD:
        pred += HEURISTIC_RSI_PENALTY
    pred *= np.sqrt(horizon / 20)
    conf = max(DEFAULT_FALLBACK_CONFIDENCE, HEURISTIC_CONF_BASE - abs(pred) / CONF_NORMALIZER)
    return pred, conf


def momentum_model(features: dict[str, Any], horizon: int) -> tuple[float, float]:
    """Momentum model.

    Args:
        features: Feature sözlüğü.
        horizon: Tahmin ufku.

    Returns:
        (tahmin, güven) çifti.
    """
    mom_5d = features.get("momentum_5d", 0)
    mom_20d = features.get("momentum_20d", 0)
    pred = (mom_5d * MOMENTUM_5D_WEIGHT + mom_20d * MOMENTUM_20D_WEIGHT) * np.sqrt(horizon / 20)
    conf = max(DEFAULT_FALLBACK_CONFIDENCE, MOMENTUM_CONF_BASE - abs(pred) / MOMENTUM_CONF_NORMALIZER)
    return pred, conf


def statistical_model(features: dict[str, Any], horizon: int) -> tuple[float, float]:
    """Statistical model (mean reversion).

    Args:
        features: Feature sözlüğü.
        horizon: Tahmin ufku.

    Returns:
        (tahmin, güven) çifti.
    """
    rsi = features.get("rsi_14", HEURISTIC_RSI_DEFAULT)
    bb_position = features.get("bb_position", 0.5)
    reversion = (0.5 - bb_position) * STAT_REVERSION_BB_WEIGHT + (50 - rsi) * STAT_REVERSION_RSI_WEIGHT
    pred = reversion * np.sqrt(horizon / 20) * STAT_REVERSION_SCALE
    conf = max(DEFAULT_FALLBACK_CONFIDENCE, STAT_CONF_BASE - abs(pred) / CONF_NORMALIZER)
    return pred, conf


# Singleton
ensemble_forecaster = EnsembleForecaster()

# Kayıtlı modeller
ensemble_forecaster.register_model("heuristic", heuristic_model)
ensemble_forecaster.register_model("momentum", momentum_model)
ensemble_forecaster.register_model("statistical", statistical_model)
