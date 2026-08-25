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

import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class InvestingAdapter(BaseAdapter):
    """Investing.com TR adapter'ı."""

    source_name = "investing"
    rate_limit = 5

    # BIST ticker → Investing.com URL mapping
    TICKER_URLS: Dict[str, str] = {
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

    async def collect(self, ticker: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Investing.com verisi çek."""
        slug = self.TICKER_URLS.get(ticker.upper())
        if not slug:
            return None

        try:
            data = await self._scrape_comments(slug, ticker)
            return data
        except Exception as e:
            logger.warning("Investing.com scrape failed", ticker=ticker, error=str(e))
            return None

    async def _scrape_comments(self, slug: str, ticker: str) -> Dict[str, Any]:
        """Yorumları scrape et."""
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
                    soup = BeautifulSoup(html, 'html.parser')

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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

        except ImportError:
            logger.warning("beautifulsoup4 not installed")
            return {}
        except Exception as e:
            logger.debug("Investing.com scrape error", error=str(e))
            return {}

    def compute_features(self, data: Dict[str, Any], ticker: str) -> Dict[str, float]:
        """Investing.com feature'ları hesapla."""
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
        """Keyword-based sentiment with negation handling."""
        text_lower = text.lower()
        words = text_lower.split()
        pos = [
            "yükseliş", "artış", "güçlü", "olumlu", "al", "hedef", "potansiyel", "kâr",
            "büyüme", "rekor", "başarı", "destek", "teşvik", "ihracat", "yatırım",
            "genişleme", "iyileşme", "toparlanma", "temettü", "sipariş", "sözleşme",
        ]
        neg = [
            "düşüş", "zarar", "zayıf", "sat", "risk", "tehlike", "kısa", "short",
            "kayıp", "azalma", "gerileme", "iptal", "iflas", "borç", "dava",
            "ceza", "soruşturma", "kriz", "olumsuz", "daralma", "temerrüt",
        ]
        p = 0
        n = 0
        negation_words = {"değil", "yok", "olmayan", "değildir", "olmaz", "hiç", "asla", "ne", "olmadı"}
        negate = False
        for word in words:
            if word in negation_words:
                negate = True
                continue
            if word in pos:
                if negate:
                    n += 1
                else:
                    p += 1
                negate = False
            elif word in neg:
                if negate:
                    p += 1
                else:
                    n += 1
                negate = False
        t = p + n
        return (p - n) / t if t > 0 else 0


# Singleton
investing_adapter = InvestingAdapter()
