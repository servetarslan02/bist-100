"""ALPHA BIST — FinGPT Sentiment (Türkçe finansal metin)."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

class FinGPTSentiment:
    """Türkçe finansal metin sentiment analizi."""
    POSITIVE_WORDS = ["yükseliş", "artış", "kâr", "büyüme", "olumlu", "rekor", "güçlü"]
    NEGATIVE_WORDS = ["düşüş", "kayıp", "zarar", "gerileme", "olumsuz", "kriz", "zayıf"]

    def analyze(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        pos = sum(1 for w in self.POSITIVE_WORDS if w in text_lower)
        neg = sum(1 for w in self.NEGATIVE_WORDS if w in text_lower)
        total = pos + neg
        if total == 0: return {"sentiment": "NEUTRAL", "score": 0.5}
        score = pos / total
        sentiment = "POSITIVE" if score > 0.6 else ("NEGATIVE" if score < 0.4 else "NEUTRAL")
        return {"sentiment": sentiment, "score": score}

fingpt_sentiment = FinGPTSentiment()
