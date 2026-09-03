"""
ALPHA BIST — Investing.com TR Adapter v1.0

Investing.com Türkiye hisse yorumları ve sentiment.
Web scraping ile veri toplama.

Features:
- investing_sentiment: Yorum sentiment skoru
- investing_volume: Yorum sayısı
- investing_positive_ratio: Pozitif yorum oranı
- investing_analyst_consensus: Analist görüş birliği
- investing_technical_rating: Teknik rating
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class InvestingAdapter(BaseAdapter):
    """Investing.com TR adapter'ı."""

    source_name = "investing"
    rate_limit = 5

    # BIST ticker → Investing.com URL mapping
    TICKER_URLS: dict[str, str] = {
        "THYAO": "thyao",
        "GARAN": "garan",
        "AKBNK": "akbnk",
        "ASELS": "asels",
        "BIMAS": "bimas",
        "EREGL": "eregl",
        "KCHOL": "kchol",
        "SAHOL": "sahol",
        "SISE": "sise",
        "TUPRS": "tuprs",
        "PETKM": "petkm",
        "TOASO": "toaso",
        "FROTO": "froto",
        "TCELL": "tcell",
        "TTKOM": "ttkom",
        "HALKB": "halkb",
        "VAKBN": "vakbn",
        "ISCTR": "isctr",
    }

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Investing.com verisi çek.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek parametreler.

        Returns:
            Yorum listesi ve metadata içeren sözlük veya None.
        """
        slug = self.TICKER_URLS.get(ticker.upper())
        if not slug:
            return None

        try:
            data = await self._scrape_comments(slug, ticker)
            return data
        except Exception as e:
            logger.warning("Investing.com scrape failed", ticker=ticker, error=str(e))
            return None

    async def _scrape_comments(self, slug: str, ticker: str) -> dict[str, Any]:
        """Investing.com yorumlarını scrape et.

        Args:
            slug: Investing.com URL slug'ı.
            ticker: Hisse sembolü.

        Returns:
            Yorum listesi ve metadata içeren sözlük.
        """
        try:
            import aiohttp
            from bs4 import BeautifulSoup

            url = f"https://tr.investing.com/equities/{slug}-comment"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {}

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    comments = []
                    # Yorum kutularını bul
                    comment_items = soup.select('.comment, .user-comment, [data-test="comment"]')

                    for item in comment_items[:20]:
                        text = item.get_text(strip=True)
                        if len(text) < 10:
                            continue
                        comments.append({"text": text[:500]})

                    # Teknik rating
                    tech_rating = soup.select_one('.techRating, .overall-rating, [data-test="rating"]')
                    rating_text = tech_rating.text.strip() if tech_rating else ""

                    return {
                        "comments": comments,
                        "total_count": len(comments),
                        "technical_rating": rating_text,
                        "ticker": ticker,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

        except ImportError as e:
            logger.warning("Missing dependency for Investing scraping", missing=str(e))
            return {}
        except Exception as e:
            logger.debug("Investing.com scrape error", error=str(e))
            return {}

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Investing.com feature'larını hesapla.

        Args:
            data: collect() ile döndürülen ham veri.
            ticker: Hisse sembolü.

        Returns:
            Feature sözlüğü.
        """
        if not data or not data.get("comments"):
            return {}

        comments = data["comments"]
        total = len(comments)
        if total == 0:
            return {}

        # Basit sentiment
        sentiments = [self._basic_sentiment(c["text"]) for c in comments]
        positive = sum(1 for s in sentiments if s > 0.1)
        negative = sum(1 for s in sentiments if s < -0.1)

        features = {
            "investing_sentiment": float(np.mean(sentiments)),
            "investing_volume": float(total),
            "investing_positive_ratio": positive / total,
            "investing_negative_ratio": negative / total,
            "investing_sentiment_std": float(np.std(sentiments)),
        }

        # Teknik rating
        rating = data.get("technical_rating", "")
        if rating:
            rating_map = {"strong_buy": 1.0, "buy": 0.5, "neutral": 0, "sell": -0.5, "strong_sell": -1.0}
            for key, val in rating_map.items():
                if key in rating.lower():
                    features["investing_technical_rating"] = val
                    break

        return features

    def _basic_sentiment(self, text: str) -> float:
        """Keyword tabanlı basit sentiment analizi (-1 ile +1 arası).

        Olumsuzluk ekleri (değil, yok, asla) ile birlikte çalışır.

        Args:
            text: Analiz edilecek metin.

        Returns:
            -1 (negatif) ile +1 (pozitif) arası sentiment skoru.
        """
        text_lower = text.lower()
        words = text_lower.split()
        positive_words = [
            "yükseliş",
            "artış",
            "güçlü",
            "olumlu",
            "al",
            "hedef",
            "potansiyel",
            "kâr",
            "büyüme",
            "rekor",
            "başarı",
            "destek",
            "teşvik",
            "ihracat",
            "yatırım",
            "genişleme",
            "iyileşme",
            "toparlanma",
            "temettü",
            "sipariş",
            "sözleşme",
        ]
        negative_words = [
            "düşüş",
            "zarar",
            "zayıf",
            "sat",
            "risk",
            "tehlike",
            "kısa",
            "short",
            "kayıp",
            "azalma",
            "gerileme",
            "iptal",
            "iflas",
            "borç",
            "dava",
            "ceza",
            "soruşturma",
            "kriz",
            "olumsuz",
            "daralma",
            "temerrüt",
        ]
        positive_count = 0
        negative_count = 0
        negation_words = {"değil", "yok", "olmayan", "değildir", "olmaz", "hiç", "asla", "ne", "olmadı"}
        negate = False
        for word in words:
            if word in negation_words:
                negate = True
                continue
            if word in positive_words:
                if negate:
                    negative_count += 1
                else:
                    positive_count += 1
                negate = False
            elif word in negative_words:
                if negate:
                    positive_count += 1
                else:
                    negative_count += 1
                negate = False
        total = positive_count + negative_count
        return (positive_count - negative_count) / total if total > 0 else 0.0


# Singleton
investing_adapter = InvestingAdapter()
