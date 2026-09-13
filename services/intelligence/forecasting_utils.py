"""
ALPHA BIST — Tahmin Yardımcıları & Olay Etki Analiz Motoru v3.0 (Forecasting Utilities)

BIST pay piyasalarında haber akışı tekilleştirme, zaman çizelgesi korelasyonu ve haber etki analitiği sağlar.

Bileşenler:
  - NewsImpactEngine: Duygu, önem, yenilik ve kaynak güvenilirliğini birleştiren çok boyutlu etki skoru.
  - NewsDuplicationEngine: N-gram Jaccard benzerliği ve MD5 karma tabanlı gelişmiş haber tekilleştirme.
  - EventTimelineEngine: Varlık bazlı olay zaman serisi, olay kümeleme ve gecikmeli piyasa tepkisi analitiği.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_IMPORTANCE_WEIGHT: float = 0.35
DEFAULT_NOVELTY_WEIGHT: float = 0.25
DEFAULT_CREDIBILITY_WEIGHT: float = 0.40
DEFAULT_IMPACT_THRESHOLD_POS: float = 0.08
DEFAULT_IMPACT_THRESHOLD_NEG: float = -0.08
DEFAULT_JACCARD_SIMILARITY_THRESHOLD: float = 0.65
DEFAULT_MAX_SEEN_HASHES: int = 1000
DEFAULT_MAX_TIMELINE_EVENTS: int = 200


class NewsImpactEngine:
    """Haber duygu, önem ve güvenilirlik metriklerini birleştiren kuantitatif etki motoru."""

    def __repr__(self) -> str:
        return "<NewsImpactEngine>"

    def compute_impact(self, news_event: dict[str, Any]) -> dict[str, Any]:
        """Gelen haber veya KAP bildiriminin piyasa etki derecesini ve ufkunu hesaplar.

        Args:
            news_event: Haber içeriği (sentiment, importance, novelty, credibility, sector).

        Returns:
            dict[str, Any]: Yön, büyüklük, güven, zaman ufku ve ham etki skoru içeren sözlük.
        """
        sentiment = float(news_event.get("sentiment", 0.0))
        importance = float(news_event.get("importance", 0.5))
        novelty = float(news_event.get("novelty", 0.5))
        credibility = float(news_event.get("credibility", 0.5))

        # Ağırlıklı çarpan analizi
        weight_factor = (
            importance * DEFAULT_IMPORTANCE_WEIGHT
            + novelty * DEFAULT_NOVELTY_WEIGHT
            + credibility * DEFAULT_CREDIBILITY_WEIGHT
        )
        impact = sentiment * weight_factor

        # Yön tespiti
        if impact > DEFAULT_IMPACT_THRESHOLD_POS:
            direction = "POSITIVE"
        elif impact < DEFAULT_IMPACT_THRESHOLD_NEG:
            direction = "NEGATIVE"
        else:
            direction = "NEUTRAL"

        # Etki büyüklüğü ve zaman ufku
        magnitude = abs(impact)
        if importance >= 0.8:
            horizon = "SHORT"  # Yüksek önem ve şok etki anlık fiyatlanır
        elif importance >= 0.45:
            horizon = "MEDIUM"
        else:
            horizon = "LONG"

        return {
            "direction": direction,
            "magnitude": round(magnitude, 4),
            "confidence": round(credibility, 4),
            "horizon": horizon,
            "raw_impact": round(impact, 4),
            "calculated_at": datetime.now(tz=UTC).isoformat(),
        }


class NewsDuplicationEngine:
    """Haber tekrarlarını ve farklı ajanslardan gelen benzer içerikleri yakalayan tekilleştirme motoru."""

    def __init__(self, similarity_threshold: float = DEFAULT_JACCARD_SIMILARITY_THRESHOLD) -> None:
        """Motoru ilklendirir ve n-gram havuzunu oluşturur."""
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: dict[str, deque[str]] = {}  # hash -> sources
        self._title_tokens: dict[str, set[str]] = {}  # hash -> word token set

    def __repr__(self) -> str:
        return f"<NewsDuplicationEngine seen_hashes={len(self._seen_hashes)}>"

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Metni küçük harfli kelime token'larına ayırır."""
        clean_text = re.sub(r"[^\w\s]", " ", text.lower())
        return {word for word in clean_text.split() if len(word) > 2}

    def _jaccard_similarity(self, tokens_a: set[str], tokens_b: set[str]) -> float:
        """İki kelime kümesi arasındaki Jaccard Benzerlik katsayısını hesaplar."""
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a.intersection(tokens_b))
        union = len(tokens_a.union(tokens_b))
        return intersection / union if union > 0 else 0.0

    def is_duplicate(self, title: str, source: str) -> bool:
        """Haberin daha önce başka bir kaynak veya aynı kaynak tarafından geçilip geçilmediğini kontrol eder.

        Args:
            title: Haber başlığı.
            source: Haber kaynağı (KAP, Matriks, Bloomberg HT, Foreks vb.).

        Returns:
            bool: Tekrar eden haber ise True, özgün ise False.
        """
        if not title:
            return False

        title_hash = hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:16]
        current_tokens = self._tokenize(title)

        # 1. Birebir MD5/SHA256 eşleşmesi
        if title_hash in self._seen_hashes:
            if source not in self._seen_hashes[title_hash]:
                self._seen_hashes[title_hash].append(source)
            return True

        # 2. Benzer başlıkların Jaccard benzerliği ile tespiti (Farklı ajans aynı haberi farklı başlıkla verebilir)
        for existing_hash, existing_tokens in list(self._title_tokens.items())[-200:]:
            sim = self._jaccard_similarity(current_tokens, existing_tokens)
            if sim >= self.similarity_threshold:
                # Benzer haber bulundu
                if source not in self._seen_hashes[existing_hash]:
                    self._seen_hashes[existing_hash].append(source)
                return True

        # Yeni özgün haber kaydı
        if len(self._seen_hashes) >= DEFAULT_MAX_SEEN_HASHES:
            # En eski anahtarları temizle
            oldest_key = next(iter(self._seen_hashes))
            del self._seen_hashes[oldest_key]
            self._title_tokens.pop(oldest_key, None)

        self._seen_hashes[title_hash] = deque([source], maxlen=20)
        self._title_tokens[title_hash] = current_tokens
        return False

    def get_source_count(self, title: str) -> int:
        """Belirtilen haberin kaç farklı bağımsız kaynak tarafından teyit edildiğini döner."""
        title_hash = hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:16]
        return len(self._seen_hashes.get(title_hash, []))


class EventTimelineEngine:
    """Hisse ve sektör bazlı olayların zaman çizelgesini takip eden ve olay yoğunluğunu ölçen motor."""

    def __init__(self, max_events_per_ticker: int = DEFAULT_MAX_TIMELINE_EVENTS) -> None:
        """Zaman çizelgesi motorunu ilklendirir."""
        self.max_events = max_events_per_ticker
        self._timelines: dict[str, deque[dict[str, Any]]] = {}

    def __repr__(self) -> str:
        return f"<EventTimelineEngine tracked_tickers={len(self._timelines)}>"

    def add_event(self, ticker: str, event_type: str, data: dict[str, Any], timestamp: str | None = None) -> None:
        """Hisse zaman çizelgesine yeni bir kurumsal veya teknik olay kaydeder.

        Args:
            ticker: BIST hisse sembolü.
            event_type: Olay tipi ("KAP_DIVIDEND", "EARNINGS_ANNOUNCEMENT", "TECH_BREAKOUT", vb.).
            data: Olaya ait detay verileri.
            timestamp: İsteğe bağlı ISO zaman damgası.
        """
        sym = ticker.upper()
        if sym not in self._timelines:
            self._timelines[sym] = deque(maxlen=self.max_events)

        ts = timestamp or datetime.now(tz=UTC).isoformat()
        self._timelines[sym].append(
            {
                "type": event_type,
                "data": data,
                "timestamp": ts,
            }
        )

    def get_timeline(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        """Hisseye ait en son gerçekleşen olayları zaman sırasına göre döner."""
        sym = ticker.upper()
        timeline = list(self._timelines.get(sym, []))
        return timeline[-limit:]

    def get_correlation(self, ticker: str) -> dict[str, Any]:
        """Hisse için olaylar arası frekans ve tür çeşitliliği analizini hesaplar."""
        sym = ticker.upper()
        timeline = list(self._timelines.get(sym, []))
        if len(timeline) < 2:
            return {"total_events": len(timeline), "correlated_events": [], "event_frequency": {}}

        recent = timeline[-15:]
        event_types = [str(e.get("type", "")) for e in recent]
        unique_types = sorted(set(event_types))

        freq = {t: event_types.count(t) for t in unique_types}
        return {
            "total_events": len(timeline),
            "recent_event_types": unique_types,
            "event_frequency": freq,
            "event_clustering_score": round(len(event_types) / max(len(unique_types), 1), 2),
        }


# Singleton Örnekleri
news_impact_engine = NewsImpactEngine()
news_duplication_engine = NewsDuplicationEngine()
event_timeline_engine = EventTimelineEngine()

__all__ = [
    "EventTimelineEngine",
    "NewsDuplicationEngine",
    "NewsImpactEngine",
    "event_timeline_engine",
    "news_duplication_engine",
    "news_impact_engine",
]
