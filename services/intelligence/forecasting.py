"""
ALPHA BIST — Forecasting & Ensemble v1.0

- Forecasting Engine (multi-horizon)
- Ensemble Forecasting
- News Impact Engine
- News Duplication Engine
- Event Timeline Engine
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
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
        features: Dict[str, float],
        historical_returns: List[float],
    ) -> List[Forecast]:
        """Farklı zaman ufukları için tahmin üret."""
        forecasts = []

        for horizon in self.HORIZONS:
            forecast = self._forecast_horizon(ticker, features, historical_returns, horizon)
            forecasts.append(forecast)

        return forecasts

    def _forecast_horizon(self, ticker: str, features: Dict, returns: List[float], horizon: int) -> Forecast:
        """Tek ufuk için tahmin."""
        # Feature-based heuristic prediction
        momentum = features.get("momentum_20d", 0)
        vol = features.get("realized_vol_20d", 20)
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
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class EnsembleForecasting:
    """Ensemble tahmin — çoklu model birleştirme."""

    def combine_forecasts(
        self,
        forecasts: List[Forecast],
        weights: Optional[Dict[str, float]] = None,
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
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class NewsImpactEngine:
    """Haber etki motoru."""

    def compute_impact(self, news_event: Dict) -> Dict[str, Any]:
        """Her haber için etki hesapla."""
        sentiment = news_event.get("sentiment", 0)
        importance = news_event.get("importance", 0.5)
        novelty = news_event.get("novelty", 0.5)
        credibility = news_event.get("credibility", 0.5)

        # Impact = sentiment × importance × novelty × credibility
        impact = sentiment * importance * novelty * credibility

        # Direction
        if impact > 0.1:
            direction = "POSITIVE"
        elif impact < -0.1:
            direction = "NEGATIVE"
        else:
            direction = "NEUTRAL"

        # Magnitude
        magnitude = abs(impact)

        # Time horizon
        if importance > 0.8:
            horizon = "SHORT"  # Yüksek önem = kısa vadede etki
        elif importance > 0.5:
            horizon = "MEDIUM"
        else:
            horizon = "LONG"

        return {
            "direction": direction,
            "magnitude": round(magnitude, 4),
            "confidence": round(credibility, 4),
            "horizon": horizon,
            "raw_impact": round(impact, 4),
        }


class NewsDuplicationEngine:
    """Haber tekrarı tespiti."""

    def __init__(self):
        self._seen_hashes: Dict[str, List[str]] = {}

    def is_duplicate(self, title: str, source: str) -> bool:
        """Aynı haber farklı kaynaktan mı geldi?"""
        # Basit hash
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:16]

        if title_hash in self._seen_hashes:
            if source not in self._seen_hashes[title_hash]:
                self._seen_hashes[title_hash].append(source)
            return True  # Duplicate
        else:
            self._seen_hashes[title_hash] = [source]
            return False

    def get_source_count(self, title: str) -> int:
        """Kaç farklı kaynak aynı haberi paylaştı?"""
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:16]
        return len(self._seen_hashes.get(title_hash, []))


class EventTimelineEngine:
    """Olay zaman çizelgesi."""

    def __init__(self):
        self._timelines: Dict[str, List[Dict]] = {}

    def add_event(self, ticker: str, event_type: str, data: Dict, timestamp: str):
        """Olay ekle."""
        if ticker not in self._timelines:
            self._timelines[ticker] = []

        self._timelines[ticker].append({
            "type": event_type,
            "data": data,
            "timestamp": timestamp,
        })

        # Son 100 olay tut
        self._timelines[ticker] = self._timelines[ticker][-100:]

    def get_timeline(self, ticker: str, limit: int = 20) -> List[Dict]:
        """Ticker olay zaman çizelgesi."""
        return self._timelines.get(ticker, [])[-limit:]

    def get_correlation(self, ticker: str) -> Dict[str, Any]:
        """Olaylar arası korelasyon."""
        timeline = self._timelines.get(ticker, [])
        if len(timeline) < 2:
            return {"correlated_events": []}

        # Son olaylar arasındaki ilişki
        recent = timeline[-10:]
        event_types = [e["type"] for e in recent]
        unique_types = set(event_types)

        return {
            "total_events": len(timeline),
            "recent_event_types": list(unique_types),
            "event_frequency": {t: event_types.count(t) for t in unique_types},
        }


import hashlib

# Singletons
forecasting_engine = ForecastingEngine()
ensemble_forecasting = EnsembleForecasting()
news_impact_engine = NewsImpactEngine()
news_duplication_engine = NewsDuplicationEngine()
event_timeline_engine = EventTimelineEngine()
