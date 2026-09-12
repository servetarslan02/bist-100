"""
ALPHA BIST — Forecasting Utils v1.1

Haber etki motoru, tekrar tespiti ve olay zaman çizelgesi.
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Any

import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
IMPACT_POSITIVE_THRESHOLD: float = 0.1
IMPACT_NEGATIVE_THRESHOLD: float = -0.1
IMPORTANCE_HIGH: float = 0.8
IMPORTANCE_MEDIUM: float = 0.5
DEFAULT_SENTIMENT: float = 0.0
DEFAULT_IMPORTANCE: float = 0.5
DEFAULT_NOVELTY: float = 0.5
DEFAULT_CREDIBILITY: float = 0.5
MAX_SOURCES_PER_HASH: int = 50
MAX_TIMELINE_EVENTS: int = 100
DEFAULT_TIMELINE_LIMIT: int = 20
CORRELATION_WINDOW: int = 10
HASH_TRUNCATE: int = 16

__all__ = [
    "NewsImpactEngine",
    "NewsDuplicationEngine",
    "EventTimelineEngine",
    "news_impact_engine",
    "news_duplication_engine",
    "event_timeline_engine",
]


class NewsImpactEngine:
    """Haber etki motoru.

    Her haber olayının yön, büyüklük ve zaman ufku etkisini hesaplar.
    """

    def __repr__(self) -> str:
        return "<NewsImpactEngine>"

    def compute_impact(self, news_event: dict[str, Any]) -> dict[str, Any]:
        """Haber etkisi hesapla.

        Args:
            news_event: Haber olayı sözlüğü (sentiment, importance, novelty, credibility).

        Returns:
            direction, magnitude, confidence, horizon ve raw_impact içeren sözlük.
        """
        sentiment = news_event.get("sentiment", DEFAULT_SENTIMENT)
        importance = news_event.get("importance", DEFAULT_IMPORTANCE)
        novelty = news_event.get("novelty", DEFAULT_NOVELTY)
        credibility = news_event.get("credibility", DEFAULT_CREDIBILITY)

        impact = sentiment * importance * novelty * credibility

        if impact > IMPACT_POSITIVE_THRESHOLD:
            direction = "POSITIVE"
        elif impact < IMPACT_NEGATIVE_THRESHOLD:
            direction = "NEGATIVE"
        else:
            direction = "NEUTRAL"

        magnitude = abs(impact)

        if importance > IMPORTANCE_HIGH:
            horizon = "SHORT"
        elif importance > IMPORTANCE_MEDIUM:
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
    """Haber tekrarı tespiti.

    Aynı haberin farklı kaynaklardan gelip gelmediğini tespit eder.
    """

    def __repr__(self) -> str:
        return f"<NewsDuplicationEngine tracked={len(self._seen_hashes)}>"

    def __init__(self) -> None:
        """Haber tekrar motorunu başlat."""
        self._seen_hashes: dict[str, deque[str]] = {}

    def is_duplicate(self, title: str, source: str) -> bool:
        """Aynı haber farklı kaynaktan mı geldi?

        Args:
            title: Haber başlığı.
            source: Kaynak adı.

        Returns:
            True ise duplicate, False ise yeni haber.
        """
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:HASH_TRUNCATE]

        if title_hash in self._seen_hashes:
            if source not in self._seen_hashes[title_hash]:
                self._seen_hashes[title_hash].append(source)
            return True
        else:
            self._seen_hashes[title_hash] = deque([source], maxlen=MAX_SOURCES_PER_HASH)
            return False

    def get_source_count(self, title: str) -> int:
        """Kaç farklı kaynak aynı haberi paylaştı?

        Args:
            title: Haber başlığı.

        Returns:
            Kaynak sayısı.
        """
        title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()[:HASH_TRUNCATE]
        return len(self._seen_hashes.get(title_hash, []))


class EventTimelineEngine:
    """Olay zaman çizelgesi.

    Her ticker için olay geçmişini tutar ve korelasyon analizi yapar.
    """

    def __repr__(self) -> str:
        tickers = list(self._timelines.keys())
        return f"<EventTimelineEngine tickers={tickers}>"

    def __init__(self) -> None:
        """Olay zaman çizelgesi motorunu başlat."""
        self._timelines: dict[str, deque[dict[str, Any]]] = {}

    def add_event(self, ticker: str, event_type: str, data: dict[str, Any], timestamp: str) -> None:
        """Olay ekle.

        Args:
            ticker: Varlık kodu.
            event_type: Olay türü.
            data: Olay verisi.
            timestamp: Zaman damgası.
        """
        if ticker not in self._timelines:
            self._timelines[ticker] = deque(maxlen=MAX_TIMELINE_EVENTS)

        self._timelines[ticker].append(
            {"type": event_type, "data": data, "timestamp": timestamp}
        )

    def get_timeline(self, ticker: str, limit: int = DEFAULT_TIMELINE_LIMIT) -> list[dict[str, Any]]:
        """Ticker olay zaman çizelgesi.

        Args:
            ticker: Varlık kodu.
            limit: Döndürülecek maksimum olay sayısı.

        Returns:
            Olay listesi (en yeniden en eskiye).
        """
        return list(self._timelines.get(ticker, []))[-limit:]

    def get_correlation(self, ticker: str) -> dict[str, Any]:
        """Olaylar arası korelasyon.

        Args:
            ticker: Varlık kodu.

        Returns:
            Toplam olay, son olay türleri ve frekans sözlüğü.
        """
        timeline = self._timelines.get(ticker, [])
        if len(timeline) < 2:
            return {"correlated_events": []}

        recent = list(timeline)[-CORRELATION_WINDOW:]
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
