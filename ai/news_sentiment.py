"""
ALPHA BIST — News Sentiment Analyzer

KAP haber akışı ve piyasa haberleri için duygu analizi.
Türkçe finansal kelime dağarcığı.
"""

from typing import Dict, Any, Optional, List
import re
import structlog

logger = structlog.get_logger()


class NewsSentimentAnalyzer:
    """Haber duygu analizi — Türkçe finansal optimize."""

    POSITIVE_WORDS = {
        "artış", "yükseliş", "kâr", "kar", "büyüme", "rekor", "zirve",
        "güçlü", "olumlu", "başarı", "iyileşme", "toparlanma", "yükseldi",
        "arttı", "kazandı", "değerlendi", "pozitif", "temettü", "bedelsiz",
        "halka arz", "yatırım", "genişleme", "ihracat", "sipariş", "sözleşme",
    }

    NEGATIVE_WORDS = {
        "düşüş", "kayıp", "zarar", "gerileme", "çöküş", "dip", "kriz",
        "zayıf", "olumsuz", "başarısızlık", "kötüleşme", "düşürdü",
        "azaldı", "kaybetti", "negatif", "risk", "iflas", "borç",
        "yaptırım", "ceza", "soruşturma", "dava", "iptal", "erteleme",
    }

    def analyze(self, text: str, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Haber metnini analiz et."""
        if not text:
            return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.0}

        text_lower = text.lower()
        words = set(re.findall(r'\w+', text_lower))

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

    def analyze_batch(self, texts: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Toplu haber analizi."""
        return [self.analyze(item.get("text", ""), item.get("ticker")) for item in texts]

    def get_market_sentiment(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Genel piyasa duygusu."""
        if not analyses:
            return {"overall": "NEUTRAL", "score": 0.0}

        scores = [a["score"] for a in analyses]
        avg_score = sum(scores) / len(scores)

        pos_count = len([a for a in analyses if a["sentiment"] == "POSITIVE"])
        neg_count = len([a for a in analyses if a["sentiment"] == "NEGATIVE"])

        if avg_score > 0.2:
            overall = "POSITIVE"
        elif avg_score < -0.2:
            overall = "NEGATIVE"
        else:
            overall = "NEUTRAL"

        return {
            "overall": overall,
            "average_score": round(avg_score, 4),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "total_analyzed": len(analyses),
        }


news_sentiment = NewsSentimentAnalyzer()
