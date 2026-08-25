"""
ALPHA BIST — LLM Sentiment Analyzer v1.0

Ollama ile Türkçe finansal metin sentiment analizi.

Kullanım alanları:
- KAP açıklaması yorumlama
- Haber etki analizi
- Sosyal medya manipülasyon tespiti
- Ekşi Sözlük derin sentiment

LLM: Ollama (gemma4:12b-q4_0 veya benzeri Türkçe model)
"""

import asyncio
import time
from typing import Dict, Any, List
import structlog

logger = structlog.get_logger()


# Sentiment analiz promptu
SENTIMENT_SYSTEM_PROMPT = """Sen Türkçe finansal metin sentiment analiz uzmanısın.

Görevin: Verilen metni analiz edip sentiment skoru ve nedenlerini JSON formatında döndür.

Kurallar:
- Sadece verilen metne dayan
- Türkçe finansal terminolojiyi bil
- Piyasa etkisini değerlendir
- Manipülasyon belirtilerini tespit et

JSON Formatı:
{{
  "sentiment_score": -1.0 ile 1.0 arası,
  "confidence": 0.0-1.0,
  "impact_level": "LOW|MEDIUM|HIGH|CRITICAL",
  "category": "POSITIVE|NEGATIVE|NEUTRAL|MIXED",
  "key_factors": ["faktör1", "faktör2"],
  "risks": ["risk1"],
  "reasoning": "Kısa gerekçe"
}}"""

SENTIMENT_USER_PROMPT = """Aşağıdaki Türkçe finansal metni analiz et:

Kaynak: {source}
Şirket: {ticker}
Metin:
{text}

Bu metin hisse fiyatını nasıl etkiler? JSON formatında yanıt ver."""


class LLMSentimentAnalyzer:
    """LLM tabanlı Türkçe sentiment analizi."""

    def __init__(self, llm_client=None):
        self._llm_client = llm_client
        self._cache: Dict[str, tuple] = {}  # key → (result, cached_at)

    def set_llm_client(self, client):
        """LLM client ayarla."""
        self._llm_client = client

    async def analyze(
        self,
        text: str,
        ticker: str = "",
        source: str = "unknown",
    ) -> Dict[str, Any]:
        """Metin sentiment analizi yap.

        Args:
            text: Analiz edilecek metin
            ticker: Hisse kodu
            source: Kaynak (kap, news, social, eksi)

        Returns:
            Sentiment sonucu
        """
        if not text or len(text.strip()) < 20:
            return self._neutral_result()

        # Cache kontrolü (TTL-based)
        cache_key = f"{ticker}:{hash(text[:200])}"
        if cache_key in self._cache:
            result, cached_at = self._cache[cache_key]
            if time.time() - cached_at < 3600:
                return result

        # LLM varsa kullan
        if self._llm_client:
            result = await self._llm_analyze(text, ticker, source)
        else:
            # Fallback: keyword-based
            result = self._keyword_analyze(text)

        # Cache'e yaz (TTL-based)
        self._cache[cache_key] = (result, time.time())
        # Cleanup: remove expired entries
        if len(self._cache) > 1000:
            now = time.time()
            self._cache = {k: v for k, v in self._cache.items() if now - v[1] < 3600}

        return result

    async def _llm_analyze(self, text: str, ticker: str, source: str) -> Dict[str, Any]:
        """LLM ile sentiment analizi."""
        try:
            user_prompt = SENTIMENT_USER_PROMPT.format(
                source=source,
                ticker=ticker,
                text=text[:1500],  # LLM context limit
            )

            response = await self._llm_client.generate_with_retry(
                system_prompt=SENTIMENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )

            if response.success:
                from services.agents.llm_client import parse_llm_json
                parsed = parse_llm_json(response.content)
                if parsed and "sentiment_score" in parsed:
                    return {
                        "sentiment_score": max(-1, min(1, parsed["sentiment_score"])),
                        "confidence": max(0, min(1, parsed.get("confidence", 0.5))),
                        "impact_level": parsed.get("impact_level", "MEDIUM"),
                        "category": parsed.get("category", "NEUTRAL"),
                        "key_factors": parsed.get("key_factors", []),
                        "risks": parsed.get("risks", []),
                        "reasoning": parsed.get("reasoning", ""),
                        "source": "llm",
                    }

            # LLM başarısız → fallback
            return self._keyword_analyze(text)

        except Exception as e:
            logger.warning("LLM sentiment failed", error=str(e))
            return self._keyword_analyze(text)

    def _keyword_analyze(self, text: str) -> Dict[str, Any]:
        """Keyword-based sentiment with negation handling (fallback)."""
        text_lower = text.lower()
        words = text_lower.split()

        # Finansal pozitif kelimeler
        positive = [
            "artış", "yükseliş", "büyüme", "kâr", "rekor", "başarı",
            "arttı", "yükseldi", "güçlü", "olumlu", "destek", "teşvik",
            "ihracat", "yatırım", "genişleme", "iyileşme", "toparlanma",
            "temettü", "bedelsiz", "sermaye artışı", "satın alma",
            "işbirliği", "anlaşma", "sözleşme", "ihale", "sipariş",
        ]

        negative = [
            "düşüş", "kayıp", "zarar", "azalma", "gerileme", "kriz",
            "düştü", "azaldı", "zayıf", "olumsuz", "risk", "tehlike",
            "iflas", "batık", "restrüktür", "borç", "yükümlülük",
            "dava", "ceza", "soruşturma", "skandal", "yanlış",
            "iptal", "ertelemme", "askıya", "durdurma", "kapatma",
            "işten çıkarma", "tasfiye", "kayıp", "zarar",
        ]

        pos_count = 0
        neg_count = 0
        negation_words = {"değil", "yok", "olmayan", "değildir", "olmaz", "hiç", "asla", "ne", "olmadı"}
        negate = False
        for word in words:
            if word in negation_words:
                negate = True
                continue
            if word in positive:
                if negate:
                    neg_count += 1
                else:
                    pos_count += 1
                negate = False
            elif word in negative:
                if negate:
                    pos_count += 1
                else:
                    neg_count += 1
                negate = False

        total = pos_count + neg_count
        if total == 0:
            return self._neutral_result()

        score = (pos_count - neg_count) / total
        confidence = min(0.7, total / 10)  # Daha fazla kelime = daha güvenilir

        category = "NEUTRAL"
        if score > 0.2:
            category = "POSITIVE"
        elif score < -0.2:
            category = "NEGATIVE"
        elif pos_count > 0 and neg_count > 0:
            category = "MIXED"

        impact = "LOW"
        if abs(score) > 0.5:
            impact = "HIGH"
        elif abs(score) > 0.3:
            impact = "MEDIUM"

        return {
            "sentiment_score": round(score, 4),
            "confidence": round(confidence, 4),
            "impact_level": impact,
            "category": category,
            "key_factors": [],
            "risks": [],
            "reasoning": f"Keyword-based: {pos_count} positive, {neg_count} negative",
            "source": "keyword_fallback",
        }

    def _neutral_result(self) -> Dict[str, Any]:
        """Nötr sonuç."""
        return {
            "sentiment_score": 0.0,
            "confidence": 0.0,
            "impact_level": "LOW",
            "category": "NEUTRAL",
            "key_factors": [],
            "risks": [],
            "reasoning": "Insufficient data",
            "source": "default",
        }

    async def analyze_batch(
        self,
        texts: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Toplu sentiment analizi.

        Args:
            texts: [{"text": "...", "ticker": "...", "source": "..."}]
        """
        tasks = [
            self.analyze(
                text=item["text"],
                ticker=item.get("ticker", ""),
                source=item.get("source", "unknown"),
            )
            for item in texts
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Cache istatistikleri."""
        return {
            "cache_size": len(self._cache),
            "has_llm": self._llm_client is not None,
        }


# Singleton
llm_sentiment = LLMSentimentAnalyzer()
