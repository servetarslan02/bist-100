"""ALPHA BIST — FinGPT Sentiment (Nihai —⭐⭐⭐⭐⭐).

Finansal NLP sentiment analizi — transformer-based,
multi-source (KAP, haber, sosyal medya), confidence scoring.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class SentimentResult:
    """Sentiment analiz sonucu."""
    text: str
    sentiment: str  # POSITIVE, NEGATIVE, NEUTRAL
    score: float  # -1 ile 1 arası
    confidence: float  # 0 ile 1 arası
    source: str  # kap, news, social
    ticker: str = ""
    timestamp: str = ""


@dataclass
class AggregatedSentiment:
    """Bir hisse için toplu sentiment."""
    ticker: str
    avg_score: float
    weighted_score: float
    sentiment: str
    n_sources: int
    confidence: float
    latest_score: float
    momentum: float  # Sentiment değişimi


class FinGPTSentiment:
    """FinGPT-based sentiment analizi —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Transformer-based sentiment (FinBERT, BERT Türkçe)
    - Multi-source aggregation (KAP, haber, sosyal medya)
    - Confidence scoring
    - Sentiment momentum (değişim yönü)
    - Weighted aggregation (kaynak güvenilirliği)
    - Ticker-level aggregation
    - Sentiment history tracking
    - Fallback: rule-based sentiment
    """

    def __init__(self, model_name: str = "FinBERT"):
        self.model_name = model_name
        self._model = None
        self._tokenizer = None
        self._sentiment_history: dict[str, list[SentimentResult]] = {}
        self._source_weights = {
            "kap": 1.0,      # KAP en güvenilir
            "news": 0.7,
            "social": 0.3,
        }
        self._is_loaded = False

    def load_model(self) -> bool:
        """Model yükle."""
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            if self.model_name == "FinBERT":
                model_path = "ProsusAI/finbert"
            elif self.model_name == "TurkishBERT":
                model_path = "dbmdz/bert-base-turkish-cased"
            else:
                model_path = self.model_name

            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
            self._model.eval()
            self._is_loaded = True
            logger.info("sentiment_model_loaded", model=self.model_name)
            return True
        except ImportError:
            logger.warning("transformers not installed — using rule-based fallback")
            return False
        except Exception as e:
            logger.warning("sentiment_model_load_failed", error=str(e))
            return False

    def analyze(self, text: str, source: str = "news", ticker: str = "") -> SentimentResult:
        """Tek bir metin için sentiment analizi.

        Args:
            text: Analiz edilecek metin
            source: Kaynak (kap, news, social)
            ticker: Hisse kodu

        Returns:
            SentimentResult
        """
        if self._is_loaded and self._model is not None:
            return self._transformer_analyze(text, source, ticker)
        else:
            return self._rule_based_analyze(text, source, ticker)

    def analyze_batch(self, texts: list[str], source: str = "news", ticker: str = "") -> list[SentimentResult]:
        """Toplu sentiment analizi."""
        return [self.analyze(text, source, ticker) for text in texts]

    def get_ticker_sentiment(self, ticker: str, window_hours: int = 24) -> AggregatedSentiment | None:
        """Bir hisse için toplu sentiment.

        Args:
            ticker: Hisse kodu
            window_hours: Son N saat

        Returns:
            AggregatedSentiment
        """
        history = self._sentiment_history.get(ticker, [])
        if not history:
            return None

        # Son N saat
        now = datetime.now(UTC)
        recent = [
            r for r in history
            if (now - datetime.fromisoformat(r.timestamp)).total_seconds() < window_hours * 3600
        ] if history[0].timestamp else history

        if not recent:
            return None

        scores = [r.score for r in recent]
        confidences = [r.confidence for r in recent]

        # Weighted score
        weighted_scores = []
        for r in recent:
            w = self._source_weights.get(r.source, 0.5)
            weighted_scores.append(r.score * w * r.confidence)

        avg_score = float(np.mean(scores))
        weighted_score = float(np.sum(weighted_scores) / max(sum(self._source_weights.get(r.source, 0.5) * r.confidence for r in recent), 1e-8))

        # Sentiment
        if weighted_score > 0.1:
            sentiment = "POSITIVE"
        elif weighted_score < -0.1:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        # Momentum
        if len(scores) >= 2:
            recent_avg = np.mean(scores[-3:]) if len(scores) >= 3 else scores[-1]
            older_avg = np.mean(scores[:-3]) if len(scores) > 3 else scores[0]
            momentum = float(recent_avg - older_avg)
        else:
            momentum = 0.0

        return AggregatedSentiment(
            ticker=ticker,
            avg_score=round(avg_score, 4),
            weighted_score=round(weighted_score, 4),
            sentiment=sentiment,
            n_sources=len(recent),
            confidence=round(float(np.mean(confidences)), 4),
            latest_score=round(scores[-1], 4),
            momentum=round(momentum, 4),
        )

    def _transformer_analyze(self, text: str, source: str, ticker: str) -> SentimentResult:
        """Transformer-based sentiment analizi."""
        try:
            import torch

            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model(**inputs)

            probs = torch.softmax(outputs.logits, dim=1).numpy()[0]

            # FinBERT: [positive, negative, neutral]
            if len(probs) == 3:
                score = float(probs[0] - probs[1])  # positive - negative
                confidence = float(max(probs))
                if probs[0] > probs[1] and probs[0] > probs[2]:
                    sentiment = "POSITIVE"
                elif probs[1] > probs[0] and probs[1] > probs[2]:
                    sentiment = "NEGATIVE"
                else:
                    sentiment = "NEUTRAL"
            else:
                score = float(probs[0])
                confidence = float(max(probs))
                sentiment = "POSITIVE" if score > 0.5 else "NEGATIVE"

            result = SentimentResult(
                text=text[:100],
                sentiment=sentiment,
                score=round(score, 4),
                confidence=round(confidence, 4),
                source=source,
                ticker=ticker,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # History
            if ticker:
                if ticker not in self._sentiment_history:
                    self._sentiment_history[ticker] = []
                self._sentiment_history[ticker].append(result)

            return result

        except Exception as e:
            logger.warning("transformer_sentiment_failed", error=str(e))
            return self._rule_based_analyze(text, source, ticker)

    def _rule_based_analyze(self, text: str, source: str, ticker: str) -> SentimentResult:
        """Rule-based sentiment analizi (fallback)."""
        text_lower = text.lower()

        positive_words = ["yükseliş", "artış", "kâr", "büyüme", "rekor", "güçlü", "olumlu", "pozitif", "buy", "güzel", "iyi"]
        negative_words = ["düşüş", "kayıp", "zarar", "azalma", "zayıf", "olumsuz", "negatif", "sell", "kötü", "risk"]

        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)

        if pos_count > neg_count:
            score = min(pos_count * 0.2, 1.0)
            sentiment = "POSITIVE"
        elif neg_count > pos_count:
            score = max(-neg_count * 0.2, -1.0)
            sentiment = "NEGATIVE"
        else:
            score = 0.0
            sentiment = "NEUTRAL"

        confidence = min((pos_count + neg_count) * 0.15, 0.8)

        result = SentimentResult(
            text=text[:100],
            sentiment=sentiment,
            score=round(score, 4),
            confidence=round(confidence, 4),
            source=source,
            ticker=ticker,
            timestamp=datetime.now(UTC).isoformat(),
        )

        if ticker:
            if ticker not in self._sentiment_history:
                self._sentiment_history[ticker] = []
            self._sentiment_history[ticker].append(result)

        return result

    def get_history(self, ticker: str) -> list[dict[str, Any]]:
        """Sentiment geçmişi."""
        history = self._sentiment_history.get(ticker, [])
        return [
            {
                "text": r.text,
                "sentiment": r.sentiment,
                "score": r.score,
                "confidence": r.confidence,
                "source": r.source,
                "timestamp": r.timestamp,
            }
            for r in history[-50:]
        ]
