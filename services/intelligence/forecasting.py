"""
ALPHA BIST — Forecasting & Ensemble v1.0

- Forecasting Engine (multi-horizon)
- Ensemble Forecasting
- News Impact Engine
- News Duplication Engine
- Event Timeline Engine
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class Forecast:
    """Tahmin sonucu."""
    ticker: str
    horizon_days: int
    predicted_return: float
    probability_positive: float
    confidence: float
    model_source: str
    timestamp: str = ""


class ForecastingEngine:
    """Çoklu ufuk tahmin motoru."""

    HORIZONS = [1, 5, 20, 60, 120]

    def compute_forecasts(
        self,
        ticker: str,
        features: dict[str, float],
        historical_returns: list[float],
    ) -> list[Forecast]:
        """Farklı zaman ufukları için tahmin üret."""
        forecasts = []

        for horizon in self.HORIZONS:
            forecast = self._forecast_horizon(ticker, features, historical_returns, horizon)
            forecasts.append(forecast)

        return forecasts

    def _forecast_horizon(self, ticker: str, features: dict, returns: list[float], horizon: int) -> Forecast:
        """Tek ufuk için tahmin."""
        # Feature-based heuristic prediction
        momentum = features.get("momentum_20d", 0)
        features.get("realized_vol_20d", 20)
        rsi = features.get("rsi_14", 50)

        # Base return estimate
        base_return = momentum * 0.3  # Momentum devam varsayımı

        # RSI adjustment
        if rsi > 70:
            base_return -= 1.0  # Aşırı alım
        elif rsi < 30:
            base_return += 1.0  # Aşırı satım

        # Horizon scaling
        horizon_factor = np.sqrt(horizon / 20)  # Square root of time
        predicted_return = base_return * horizon_factor

        # Probability
        if predicted_return > 0:
            prob = min(0.5 + abs(predicted_return) / 20, 0.85)
        else:
            prob = max(0.5 - abs(predicted_return) / 20, 0.15)

        # Confidence (düşük ufuk = daha yüksek güven)
        confidence = max(0.3, 0.8 - horizon / 200)

        return Forecast(
            ticker=ticker,
            horizon_days=horizon,
            predicted_return=round(predicted_return, 2),
            probability_positive=round(prob, 4),
            confidence=round(confidence, 4),
            model_source="heuristic",
            timestamp=datetime.now(UTC).isoformat(),
        )


class EnsembleForecasting:
    """Ensemble tahmin — çoklu model birleştirme."""

    def combine_forecasts(
        self,
        forecasts: list[Forecast],
        weights: dict[str, float] | None = None,
    ) -> Forecast:
        """Çoklu tahminleri birleştir."""
        if not forecasts:
            return Forecast(ticker="", horizon_days=0, predicted_return=0, probability_positive=0.5, confidence=0, model_source="ensemble")

        if weights is None:
            weights = {f.model_source: 1.0 for f in forecasts}

        total_weight = 0
        weighted_return = 0
        weighted_prob = 0
        weighted_confidence = 0

        for f in forecasts:
            w = weights.get(f.model_source, 1.0) * f.confidence
            weighted_return += f.predicted_return * w
            weighted_prob += f.probability_positive * w
            weighted_confidence += f.confidence * w
            total_weight += w

        if total_weight > 0:
            weighted_return /= total_weight
            weighted_prob /= total_weight
            weighted_confidence /= total_weight

        return Forecast(
            ticker=forecasts[0].ticker,
            horizon_days=forecasts[0].horizon_days,
            predicted_return=round(weighted_return, 2),
            probability_positive=round(weighted_prob, 4),
            confidence=round(weighted_confidence, 4),
            model_source="ensemble",
            timestamp=datetime.now(UTC).isoformat(),
        )



# Singletons
forecasting_engine = ForecastingEngine()
ensemble_forecasting = EnsembleForecasting()

