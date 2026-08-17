"""
ALPHA BIST — Sentiment Feature Engine v1.0

Haber, KAP ve sosyal medya verilerinden feature üretir:
- News sentiment (aggregated, momentum, credibility-weighted)
- KAP sentiment (category-based, importance-weighted)
- Social sentiment (volume, engagement, manipulation detection)
- Sentiment momentum (trend, acceleration)

FAZ 2.4: Sentiment Features
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
import structlog

logger = structlog.get_logger()


class SentimentFeatureEngine:
    """Haber/KAP/sosyal medya sentiment feature'ları üretir."""

    def __init__(self):
        self._news_history: Dict[str, List[Dict]] = {}  # ticker -> news events
        self._kap_history: Dict[str, List[Dict]] = {}   # ticker -> KAP events
        self._social_history: Dict[str, List[Dict]] = {}  # ticker -> social events

    def add_news_event(self, ticker: str, event: Dict[str, Any]):
        """Haber olayı ekle."""
        if ticker not in self._news_history:
            self._news_history[ticker] = []
        self._news_history[ticker].append({
            "sentiment": event.get("sentiment", 0),
            "importance": event.get("importance", 0.5),
            "credibility": event.get("credibility", 0.5),
            "novelty": event.get("novelty", 0.5),
            "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        })
        # Son 100 haber tut
        self._news_history[ticker] = self._news_history[ticker][-100:]

    def add_kap_event(self, ticker: str, event: Dict[str, Any]):
        """KAP olayı ekle."""
        if ticker not in self._kap_history:
            self._kap_history[ticker] = []
        self._kap_history[ticker].append({
            "sentiment": event.get("sentiment", 0),
            "importance": event.get("importance", 0.5),
            "is_price_sensitive": event.get("is_price_sensitive", False),
            "category": event.get("category", ""),
            "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        })
        self._kap_history[ticker] = self._kap_history[ticker][-50:]

    def add_social_event(self, ticker: str, event: Dict[str, Any]):
        """Sosyal medya olayı ekle."""
        if ticker not in self._social_history:
            self._social_history[ticker] = []
        self._social_history[ticker].append({
            "sentiment": event.get("sentiment", 0),
            "engagement_score": event.get("engagement_score", 0),
            "platform": event.get("platform", ""),
            "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        })
        self._social_history[ticker] = self._social_history[ticker][-200:]

    def compute_news_features(self, ticker: str) -> Dict[str, float]:
        """Haber sentiment feature'ları."""
        features = {}
        events = self._news_history.get(ticker, [])

        if not events:
            features["news_sentiment"] = 0.0
            features["news_count_24h"] = 0.0
            features["news_importance_avg"] = 0.0
            features["news_credibility_avg"] = 0.0
            return features

        # Son 24 saat
        now = datetime.now(timezone.utc)
        recent = [e for e in events if self._is_recent(e.get("timestamp"), hours=24)]

        if recent:
            # Ağırlıklı sentiment (credibility × importance × sentiment)
            weighted_sum = 0
            total_weight = 0
            for e in recent:
                weight = e.get("credibility", 0.5) * e.get("importance", 0.5)
                weighted_sum += e.get("sentiment", 0) * weight
                total_weight += weight

            features["news_sentiment"] = round(weighted_sum / total_weight, 4) if total_weight > 0 else 0
            features["news_count_24h"] = float(len(recent))
            features["news_importance_avg"] = round(np.mean([e.get("importance", 0) for e in recent]), 4)
            features["news_credibility_avg"] = round(np.mean([e.get("credibility", 0) for e in recent]), 4)
        else:
            features["news_sentiment"] = 0.0
            features["news_count_24h"] = 0.0
            features["news_importance_avg"] = 0.0
            features["news_credibility_avg"] = 0.0

        # Sentiment momentum (son 3 gün vs önceki 3 gün)
        recent_3d = [e for e in events if self._is_recent(e.get("timestamp"), hours=72)]
        older_3d = [e for e in events if self._is_recent(e.get("timestamp"), hours=168) and not self._is_recent(e.get("timestamp"), hours=72)]

        if recent_3d and older_3d:
            recent_avg = np.mean([e.get("sentiment", 0) for e in recent_3d])
            older_avg = np.mean([e.get("sentiment", 0) for e in older_3d])
            features["news_sentiment_momentum"] = round(recent_avg - older_avg, 4)
        else:
            features["news_sentiment_momentum"] = 0.0

        return features

    def compute_kap_features(self, ticker: str) -> Dict[str, float]:
        """KAP sentiment feature'ları."""
        features = {}
        events = self._kap_history.get(ticker, [])

        if not events:
            features["kap_sentiment"] = 0.0
            features["kap_count_7d"] = 0.0
            features["kap_price_sensitive_count"] = 0.0
            features["kap_importance_avg"] = 0.0
            return features

        # Son 7 gün
        recent = [e for e in events if self._is_recent(e.get("timestamp"), hours=168)]

        if recent:
            # Ağırlıklı sentiment
            weighted_sum = 0
            total_weight = 0
            for e in recent:
                weight = e.get("importance", 0.5)
                if e.get("is_price_sensitive"):
                    weight *= 2.0  # Price sensitive olaylar daha ağırlıklı
                weighted_sum += e.get("sentiment", 0) * weight
                total_weight += weight

            features["kap_sentiment"] = round(weighted_sum / total_weight, 4) if total_weight > 0 else 0
            features["kap_count_7d"] = float(len(recent))
            features["kap_price_sensitive_count"] = float(sum(1 for e in recent if e.get("is_price_sensitive")))
            features["kap_importance_avg"] = round(np.mean([e.get("importance", 0) for e in recent]), 4)

            # KAP EMA (exponential moving average)
            alpha = 0.3
            ema = recent[0].get("sentiment", 0)
            for e in recent[1:]:
                ema = alpha * e.get("sentiment", 0) + (1 - alpha) * ema
            features["kap_sentiment_ema"] = round(ema, 4)
        else:
            features["kap_sentiment"] = 0.0
            features["kap_count_7d"] = 0.0
            features["kap_price_sensitive_count"] = 0.0
            features["kap_importance_avg"] = 0.0
            features["kap_sentiment_ema"] = 0.0

        return features

    def compute_social_features(self, ticker: str) -> Dict[str, float]:
        """Sosyal medya sentiment feature'ları."""
        features = {}
        events = self._social_history.get(ticker, [])

        if not events:
            features["social_sentiment"] = 0.0
            features["social_volume_24h"] = 0.0
            features["social_engagement_avg"] = 0.0
            features["social_manipulation_score"] = 0.0
            return features

        # Son 24 saat
        recent = [e for e in events if self._is_recent(e.get("timestamp"), hours=24)]

        if recent:
            sentiments = [e.get("sentiment", 0) for e in recent]
            features["social_sentiment"] = round(np.mean(sentiments), 4)
            features["social_volume_24h"] = float(len(recent))
            features["social_engagement_avg"] = round(np.mean([e.get("engagement_score", 0) for e in recent]), 2)

            # Manipulation detection
            features["social_manipulation_score"] = self._detect_manipulation(recent)
        else:
            features["social_sentiment"] = 0.0
            features["social_volume_24h"] = 0.0
            features["social_engagement_avg"] = 0.0
            features["social_manipulation_score"] = 0.0

        return features

    def _detect_manipulation(self, events: List[Dict]) -> float:
        """Sosyal medya manipülasyon tespiti.

        Returns: 0-1 arası manipulation skoru (0 = güvenli, 1 = şüpheli)
        """
        if len(events) < 5:
            return 0.0

        score = 0.0

        # 1. Ani hacim artışı (son 1 saat vs önceki 23 saat)
        recent_1h = sum(1 for e in events if self._is_recent(e.get("timestamp"), hours=1))
        if len(events) > 0:
            expected_hourly = len(events) / 24
            if expected_hourly > 0 and recent_1h > expected_hourly * 5:
                score += 0.3  # Ani hacim artışı

        # 2. Tekrarlayan içerik (benzer sentiment)
        sentiments = [e.get("sentiment", 0) for e in events]
        unique_sentiments = len(set(round(s, 1) for s in sentiments))
        if unique_sentiments < len(sentiments) * 0.3:
            score += 0.2  # Çok benzer içerikler

        # 3. Düşük kaliteli hesaplar (düşük engagement)
        avg_engagement = np.mean([e.get("engagement_score", 0) for e in events])
        if avg_engagement < 2:
            score += 0.2  # Düşük kaliteli hesaplar

        # 4. Aşırı tek yönlü sentiment
        positive_ratio = sum(1 for s in sentiments if s > 0.5) / len(sentiments)
        if positive_ratio > 0.9 or positive_ratio < 0.1:
            score += 0.3  # Aşırı tek yönlü

        return min(1.0, score)

    def compute_all_sentiment_features(self, ticker: str) -> Dict[str, float]:
        """Tüm sentiment feature'ları hesapla."""
        features = {}
        features.update(self.compute_news_features(ticker))
        features.update(self.compute_kap_features(ticker))
        features.update(self.compute_social_features(ticker))

        # Composite sentiment
        news = features.get("news_sentiment", 0)
        kap = features.get("kap_sentiment", 0)
        social = features.get("social_sentiment", 0)

        # Ağırlıklı ortalama (KAP en güvenilir)
        features["composite_sentiment"] = round(
            kap * 0.5 + news * 0.3 + social * 0.2, 4
        )

        # NaN/Inf temizle
        cleaned = {}
        for k, v in features.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                cleaned[k] = 0.0
            else:
                cleaned[k] = v

        return cleaned

    def _is_recent(self, timestamp_str: str, hours: int = 24) -> bool:
        """Timestamp son N saat içinde mi?"""
        try:
            if isinstance(timestamp_str, str):
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            else:
                ts = timestamp_str
            if ts.tzinfo is None:
                from datetime import timezone
                ts = ts.replace(tzinfo=timezone.utc)
            return (datetime.now(ts.tzinfo) - ts) < timedelta(hours=hours)
        except Exception:
            return False


# Singleton
sentiment_feature_engine = SentimentFeatureEngine()


# =====================================================
# Alternative Data Entegrasyonu (B26)
# =====================================================
def compute_alternative_features(alt_data: Dict = None) -> Dict[str, float]:
    """Tüm alternatif veri kaynaklarını birleştir."""
    if alt_data is None: alt_data = {}
    features = {}
    try:
        from services.alternative.web_scraping import compute_web_features
        if alt_data.get("web"):
            features.update({f"web_{k}": v for k, v in compute_web_features(alt_data["web"], "").items()})
    except: pass
    try:
        from services.alternative.social import compute_social_features
        if alt_data.get("social"):
            features.update({f"social_{k}": v for k, v in compute_social_features(alt_data["social"], "").items()})
    except: pass
    try:
        from services.alternative.jobs import compute_job_features
        if alt_data.get("jobs"):
            features.update({f"job_{k}": v for k, v in compute_job_features(alt_data["jobs"], "").items()})
    except: pass
    try:
        from services.alternative.credit_card import compute_cc_features
        if alt_data.get("cc"):
            features.update({f"cc_{k}": v for k, v in compute_cc_features(alt_data["cc"], "").items()})
    except: pass
    try:
        from services.alternative.satellite import compute_satellite_features
        if alt_data.get("satellite"):
            features.update({f"sat_{k}": v for k, v in compute_satellite_features(alt_data["satellite"], "").items()})
    except: pass
    return features
