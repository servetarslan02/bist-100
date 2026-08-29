"""
ALPHA BIST — News Sentiment Analyzer

KAP haber akışı için duygu analizi.
Türkçe finansal kelime dağarcığı.
"""

import re
from typing import Any

import structlog

logger = structlog.get_logger()


class NewsSentimentAnalyzer:
    """Haber duygu analizi."""

    POSITIVE_WORDS = {
        "artış",
        "yükseliş",
        "kâr",
        "kar",
        "büyüme",
        "rekor",
        "zirve",
        "güçlü",
        "olumlu",
        "başarı",
        "iyileşme",
        "toparlanma",
        "yükseldi",
        "arttı",
        "kazandı",
        "değerlendi",
        "pozitif",
        "temettü",
        "bedelsiz",
    }

    NEGATIVE_WORDS = {
        "düşüş",
        "kayıp",
        "zarar",
        "gerileme",
        "çöküş",
        "dip",
        "kriz",
        "zayıf",
        "olumsuz",
        "başarısızlık",
        "kötüleşme",
        "düşürdü",
        "azaldı",
        "kaybetti",
        "negatif",
        "risk",
        "iflas",
        "borç",
    }

    def analyze(self, text: str, ticker: str | None = None) -> dict[str, Any]:
        """Haber metnini analiz et."""
        if not text:
            return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.0}

        text_lower = text.lower()
        words = set(re.findall(r"\w+", text_lower))

        pos_matches = words & self.POSITIVE_WORDS
        neg_matches = words & self.NEGATIVE_WORDS

        pos_count = len(pos_matches)
        neg_count = len(neg_matches)
        total = pos_count + neg_count

        if total == 0:
            score = 0.0
            sentiment = "NEUTRAL"
        else:
            score = (pos_count - neg_count) / total
            score = max(-1.0, min(1.0, score))
            if score > 0.2:
                sentiment = "POSITIVE"
            elif score < -0.2:
                sentiment = "NEGATIVE"
            else:
                sentiment = "NEUTRAL"

        confidence = min(total / 5.0, 1.0) if total > 0 else 0.0

        result = {
            "sentiment": sentiment,
            "score": round(score, 4),
            "confidence": round(confidence, 2),
            "positive_words": list(pos_matches),
            "negative_words": list(neg_matches),
        }
        if ticker:
            result["ticker"] = ticker
        return result

    def analyze_batch(self, texts: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return [self.analyze(item.get("text", ""), item.get("ticker")) for item in texts]

    def get_market_sentiment(self, analyses: list[dict[str, Any]]) -> dict[str, Any]:
        """Otomatik eklendi."""
        if not analyses:
            return {"overall": "NEUTRAL", "score": 0.0}

        scores = [a["score"] for a in analyses]
        avg_score = sum(scores) / len(scores)

        if avg_score > 0.2:
            overall = "POSITIVE"
        elif avg_score < -0.2:
            overall = "NEGATIVE"
        else:
            overall = "NEUTRAL"

        return {
            "overall": overall,
            "average_score": round(avg_score, 4),
            "total_analyzed": len(analyses),
        }


news_sentiment = NewsSentimentAnalyzer()
