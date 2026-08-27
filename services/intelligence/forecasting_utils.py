"""
ALPHA BIST - Forecasting Utils

Contains helper logic previously in forecasting.py to adhere to Single Responsibility Principle.
- News Impact
- News Duplication
- Event Timeline
"""

import hashlib
from collections import deque
from typing import Any

import structlog

logger = structlog.get_logger()


class NewsImpactEngine:
    """Haber etki motoru."""

    def compute_impact(self, news_event: dict) -> dict[str, Any]:
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
        self._seen_hashes: dict[str, deque] = {}  # hash → deque of sources

    def is_duplicate(self, title: str, source: str) -> bool:
        """Aynı haber farklı kaynaktan mı geldi?"""
        # Basit hash
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:16]

        if title_hash in self._seen_hashes:
            if source not in self._seen_hashes[title_hash]:
                self._seen_hashes[title_hash].append(source)
            return True  # Duplicate
        else:
            self._seen_hashes[title_hash] = deque([source], maxlen=50)
            return False

    def get_source_count(self, title: str) -> int:
        """Kaç farklı kaynak aynı haberi paylaştı?"""
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:16]
        return len(self._seen_hashes.get(title_hash, []))


class EventTimelineEngine:
    """Olay zaman çizelgesi."""

    def __init__(self):
        self._timelines: dict[str, deque] = {}  # ticker → deque of events

    def add_event(self, ticker: str, event_type: str, data: dict, timestamp: str):
        """Olay ekle."""
        if ticker not in self._timelines:
            self._timelines[ticker] = deque(maxlen=100)

        self._timelines[ticker].append(
            {
                "type": event_type,
                "data": data,
                "timestamp": timestamp,
            }
        )

    def get_timeline(self, ticker: str, limit: int = 20) -> list[dict]:
        """Ticker olay zaman çizelgesi."""
        return self._timelines.get(ticker, [])[-limit:]

    def get_correlation(self, ticker: str) -> dict[str, Any]:
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


# Singletons
news_impact_engine = NewsImpactEngine()
news_duplication_engine = NewsDuplicationEngine()
event_timeline_engine = EventTimelineEngine()
