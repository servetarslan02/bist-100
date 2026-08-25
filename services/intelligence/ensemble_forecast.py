"""
ALPHA BIST — Ensemble Forecast Engine v1.0

Çoklu model ensemble forecasting:
- LightGBM, XGBoost, Heuristic, Statistical models
- Regime-based model weighting
- Model agreement scoring
- Confidence calibration

Kullanım:
    engine = EnsembleForecaster()
    engine.register_model("lightgbm", lgbm_predict)
    result = engine.forecast(features, horizon=5, regime="BULL")
"""

import numpy as np
from typing import Dict, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class ModelForecast:
    """Tek model tahmini."""
    model_name: str
    predicted_return: float
    confidence: float
    horizon_days: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleResult:
    """Ensemble sonucu."""
    ticker: str
    horizon_days: int
    ensemble_prediction: float
    ensemble_confidence: float
    model_agreement: float        # 0-1, yüksek = modeller hemfikir
    model_predictions: Dict[str, float]
    model_confidences: Dict[str, float]
    regime: str
    weights_used: Dict[str, float]
    calibrated_confidence: float  # Kalibre edilmiş güven
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EnsembleForecaster:
    """
    Çoklu model ensemble forecaster.

    Rejime göre model ağırlıklarını değiştirir.
    Model agreement = confidence proxy.
    """

    # Rejime göre varsayılan model ağırlıkları
    REGIME_WEIGHTS = {
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

    def __init__(self):
        self._models: Dict[str, Callable] = {}
        self._performance: Dict[str, Dict] = {}  # model → {accuracy, sharpe, ic}

    def register_model(self, name: str, predict_fn: Callable):
        """Model kaydet."""
        self._models[name] = predict_fn
        logger.info("Forecast model registered", name=name)

    def forecast(
        self,
        features: Dict[str, Any],
        horizon: int = 5,
        regime: str = "UNKNOWN",
        ticker: str = "",
    ) -> EnsembleResult:
        """
        Ensemble forecast.

        Args:
            features: Feature dict
            horizon: Tahmin ufku (gün)
            regime: Mevcut rejim
            ticker: Hisse kodu

        Returns:
            EnsembleResult
        """
        # Her modelden tahmin al
        forecasts: Dict[str, float] = {}
        confidences: Dict[str, float] = {}

        for name, model_fn in self._models.items():
            try:
                result = model_fn(features, horizon)
                if isinstance(result, tuple):
                    pred, conf = result
                elif isinstance(result, dict):
                    pred = result.get("prediction", 0.0)
                    conf = result.get("confidence", 0.5)
                else:
                    pred = float(result)
                    conf = 0.5

                forecasts[name] = pred
                confidences[name] = conf

            except Exception as e:
                logger.debug("Model failed", model=name, error=str(e))

        # Heuristic fallback
        if not forecasts:
            forecasts["heuristic"] = self._heuristic_predict(features, horizon)
            confidences["heuristic"] = 0.3

        # Rejime göre ağırlıklar
        weights = self.REGIME_WEIGHTS.get(regime, self.REGIME_WEIGHTS["UNKNOWN"])
        active_weights = {
            name: weights.get(name, 1.0 / len(forecasts))
            for name in forecasts
        }
        # Normalize
        total_w = sum(active_weights.values())
        active_weights = {k: v / total_w for k, v in active_weights.items()}

        # Ağırlıklı ensemble
        ensemble_pred = sum(
            forecasts[name] * active_weights.get(name, 0)
            for name in forecasts
        )

        # Ağırlıklı confidence
        ensemble_conf = sum(
            confidences[name] * active_weights.get(name, 0)
            for name in forecasts
        )

        # Model agreement
        preds = list(forecasts.values())
        if len(preds) >= 2:
            pred_std = np.std(preds)
            pred_mean = np.mean(np.abs(preds))
            agreement = max(0, 1.0 - pred_std / max(pred_mean, 0.001))
        else:
            agreement = 0.5

        # Kalibre edilmiş confidence
        calibrated = self._calibrate_confidence(ensemble_conf, agreement, len(forecasts))

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

    def _heuristic_predict(self, features: Dict, horizon: int) -> float:
        """Heuristic tahmin (fallback)."""
        momentum = features.get("momentum_20d", 0)
        rsi = features.get("rsi_14", 50)

        base = momentum * 0.3
        if rsi > 70:
            base -= 1.0
        elif rsi < 30:
            base += 1.0

        return base * np.sqrt(horizon / 20)

    def _calibrate_confidence(
        self,
        raw_confidence: float,
        agreement: float,
        n_models: int,
    ) -> float:
        """Confidence kalibrasyonu."""
        # Model sayısına göre ayarla
        model_factor = min(1.0, n_models / 4)  # 4+ model = tam güven

        # Agreement ile çarparak kalibre et
        calibrated = raw_confidence * agreement * model_factor

        # Overconfidence cezası
        if calibrated > 0.9:
            calibrated = 0.9 - (calibrated - 0.9) * 0.5

        return max(0.0, min(1.0, calibrated))

    def update_performance(self, model_name: str, accuracy: float, sharpe: float = 0):
        """Model performansını güncelle."""
        self._performance[model_name] = {
            "accuracy": accuracy,
            "sharpe": sharpe,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_model_performance(self) -> Dict[str, Dict]:
        """Model performansları."""
        return self._performance


# Built-in models
def heuristic_model(features: Dict, horizon: int) -> tuple:
    """Heuristic model."""
    momentum = features.get("momentum_20d", 0)
    rsi = features.get("rsi_14", 50)
    pred = momentum * 0.3
    if rsi > 70:
        pred -= 1.0
    elif rsi < 30:
        pred += 1.0
    pred *= np.sqrt(horizon / 20)
    conf = max(0.3, 0.6 - abs(pred) / 20)
    return pred, conf


def momentum_model(features: Dict, horizon: int) -> tuple:
    """Momentum model."""
    mom_5d = features.get("momentum_5d", 0)
    mom_20d = features.get("momentum_20d", 0)
    pred = (mom_5d * 0.6 + mom_20d * 0.4) * np.sqrt(horizon / 20)
    conf = max(0.3, 0.7 - abs(pred) / 15)
    return pred, conf


def statistical_model(features: Dict, horizon: int) -> tuple:
    """Statistical model (mean reversion)."""
    rsi = features.get("rsi_14", 50)
    bb_position = features.get("bb_position", 0.5)
    # Mean reversion signal
    reversion = (0.5 - bb_position) * 5 + (50 - rsi) * 0.1
    pred = reversion * np.sqrt(horizon / 20) * 0.5
    conf = max(0.3, 0.5 - abs(pred) / 20)
    return pred, conf


# Singleton
ensemble_forecaster = EnsembleForecaster()

# Kayıtlı modeller
ensemble_forecaster.register_model("heuristic", heuristic_model)
ensemble_forecaster.register_model("momentum", momentum_model)
ensemble_forecaster.register_model("statistical", statistical_model)
