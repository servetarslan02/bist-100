"""ALPHA BIST - News Data Provider"""

import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger()


class NewsProvider:
    """Fetches financial news from multiple sources."""

    def __init__(self, news_api_key: Optional[str] = None):
        self.news_api_key = news_api_key
        self.session = requests.Session()

    def fetch_newsapi(self, query: str = "BIST OR borsa istanbul OR hisse", language: str = "tr", page_size: int = 50) -> List[Dict[str, Any]]:
        """Fetch news from NewsAPI."""
        if not self.news_api_key:
            logger.warning("NewsAPI key not configured")
            return []

        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": self.news_api_key,
        }

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            articles = []
            for item in data.get("articles", []):
                article = {
                    "source": item.get("source", {}).get("name", "unknown"),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "url": item.get("url", ""),
                    "published_at": item.get("publishedAt", ""),
                    "language": language,
                }

                # Basic sentiment
                article["sentiment"] = self._basic_sentiment(f"{article['title']} {article['description']}")
                articles.append(article)

            logger.info("NewsAPI articles fetched", count=len(articles))
            return articles

        except Exception as e:
            logger.error("NewsAPI request failed", error=str(e))
            return []

    def fetch_financial_news_rss(self) -> List[Dict[str, Any]]:
        """Fetch financial news from Turkish RSS feeds."""
        import feedparser

        rss_feeds = [
            ("https://www.dunya.com/rss/ekonomi.xml", "Dünya"),
            ("https://www.paraanaliz.com/feed/", "ParaAnaliz"),
            ("https://www.borsagundem.com/rss", "Borsa Gündem"),
        ]

        articles = []
        for url, source_name in rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    article = {
                        "source": source_name,
                        "title": entry.get("title", ""),
                        "description": entry.get("summary", ""),
                        "url": entry.get("link", ""),
                        "published_at": entry.get("published", ""),
                        "language": "tr",
                    }
                    article["sentiment"] = self._basic_sentiment(f"{article['title']} {article['description']}")
                    articles.append(article)

            except Exception as e:
                logger.warning("RSS feed failed", source=source_name, error=str(e))

        logger.info("RSS articles fetched", count=len(articles))
        return articles

    def _basic_sentiment(self, text: str) -> float:
        """Basic Turkish sentiment analysis."""
        text = text.lower()

        positive = [
            "yükseliş", "artış", "kazanç", "rekor", "büyüme", "kar",
            "pozitif", "güçlü", "iyimser", "toparlanma", "çıkış",
        ]

        negative = [
            "düşüş", "kayıp", "zarar", "gerileme", "kriz", "risk",
            "negatif", "zayıf", "kötümser", "çöküş", "satış",
        ]

        pos = sum(1 for w in positive if w in text)
        neg = sum(1 for w in negative if w in text)
        total = pos + neg

        if not total or total == 0:
            return 0.0
        return (pos - neg) / total


# Singleton
news_provider = NewsProvider()
