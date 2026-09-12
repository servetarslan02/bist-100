"""
ALPHA BIST — Forecasting & Ensemble v1.1

- Forecasting Engine (multi-horizon)
- Ensemble Forecasting
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_HORIZONS: list[int] = [1, 5, 20, 60, 120]
MOMENTUM_WEIGHT: float = 0.3
RSI_OVERBOUGHT: float = 70.0
RSI_OVERSOLD: float = 30.0
RSI_DEFAULT: float = 50.0
RSI_PENALTY: float = 1.0
HORIZON_BASE: float = 20.0
PROB_BASE: float = 0.5
PROB_SCALE: float = 20.0
PROB_CAP: float = 0.85
PROB_FLOOR: float = 0.15
CONFIDENCE_BASE: float = 0.8
CONFIDENCE_FLOOR: float = 0.3
CONFIDENCE_HORIZON_DIVISOR: float = 200.0
DEFAULT_VOL: float = 20.0

__all__ = [
    "Forecast",
    "ForecastingEngine",
    "EnsembleForecasting",
    "forecasting_engine",
    "ensemble_forecasting",
]


@dataclass
class Forecast:
    """Tahmin sonucu.

    Belirli bir zaman ufku için tahmini getiri, olasılık ve güven bilgisi.
    """

    ticker: str
    horizon_days: int
    predicted_return: float
    probability_positive: float
    confidence: float
    model_source: str
    timestamp: str = ""

    def __repr__(self) -> str:
        return (
            f"<Forecast ticker={self.ticker!r} horizon={self.horizon_days}d "
            f"ret={self.predicted_return:+.2f}% prob={self.probability_positive:.3f} "
            f"conf={self.confidence:.3f} src={self.model_source!r}>"
        )


class ForecastingEngine:
    """Çoklu ufuk tahmin motoru.

    Farklı zaman ufukları için momentum ve RSI bazlı heuristic tahmin üretir.
    """

    HORIZONS: list[int] = DEFAULT_HORIZONS

    def __repr__(self) -> str:
        return f"<ForecastingEngine horizons={self.HORIZONS}>"

    def compute_forecasts(
        self,
        ticker: str,
        features: dict[str, float],
        historical_returns: list[float],
    ) -> list[Forecast]:
        """Farklı zaman ufukları için tahmin üret.

        Args:
            ticker: Varlık kodu.
            features: Feature sözlüğü (momentum, RSI vb.).
            historical_returns: Geçmiş getiri serisi.

        Returns:
            Her ufuk için bir Forecast listesi.
        """
        forecasts: list[Forecast] = []
        for horizon in self.HORIZONS:
            forecast = self._forecast_horizon(ticker, features, historical_returns, horizon)
            forecasts.append(forecast)

        logger.info(
            "forecast_uretildi",
            ticker=ticker,
            horizons=len(forecasts),
            avg_return=round(np.mean([f.predicted_return for f in forecasts]), 2),
        )
        return forecasts

    def _forecast_horizon(
        self, ticker: str, features: dict[str, float], returns: list[float], horizon: int
    ) -> Forecast:
        """Tek ufuk için tahmin üret.

        Args:
            ticker: Varlık kodu.
            features: Feature sözlüğü.
            returns: Geçmiş getiri serisi.
            horizon: Tahmin ufku (gün).

        Returns:
            Forecast: Tahmin sonucu.
        """
        momentum = features.get("momentum_20d", 0.0)
        rsi = features.get("rsi_14", RSI_DEFAULT)

        # Base return estimate
        base_return = momentum * MOMENTUM_WEIGHT

        # RSI adjustment
        if rsi > RSI_OVERBOUGHT:
            base_return -= RSI_PENALTY
        elif rsi < RSI_OVERSOLD:
            base_return += RSI_PENALTY

        # Horizon scaling
        horizon_factor = np.sqrt(horizon / HORIZON_BASE)
        predicted_return = base_return * horizon_factor

        # Probability
        if predicted_return > 0:
            prob = min(PROB_BASE + abs(predicted_return) / PROB_SCALE, PROB_CAP)
        else:
            prob = max(PROB_BASE - abs(predicted_return) / PROB_SCALE, PROB_FLOOR)

        # Confidence (düşük ufuk = daha yüksek güven)
        confidence = max(CONFIDENCE_FLOOR, CONFIDENCE_BASE - horizon / CONFIDENCE_HORIZON_DIVISOR)

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
    """Ensemble tahmin — çoklu model birleştirme.

    Farklı modellerin tahminlerini ağırlıklı olarak birleştirir.
    """

    def __repr__(self) -> str:
        return "<EnsembleForecasting>"

    def combine_forecasts(
        self,
        forecasts: list[Forecast],
        weights: dict[str, float] | None = None,
    ) -> Forecast:
        """Çoklu tahminleri ağırlıklı olarak birleştir.

        Args:
            forecasts: Tahmin listesi.
            weights: Model adı → ağırlık sözlüğü (None = eşit ağırlık).

        Returns:
            Forecast: Birleştirilmiş tahmin.
        """
        if not forecasts:
            logger.warning("bos_forecast_listesi")
            return Forecast(
                ticker="",
                horizon_days=0,
                predicted_return=0.0,
                probability_positive=PROB_BASE,
                confidence=0.0,
                model_source="ensemble",
            )

        if weights is None:
            weights = {f.model_source: 1.0 for f in forecasts}

        total_weight = 0.0
        weighted_return = 0.0
        weighted_prob = 0.0
        weighted_confidence = 0.0

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
