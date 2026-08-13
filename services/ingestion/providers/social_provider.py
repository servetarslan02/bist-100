"""ALPHA BIST - Social Media Data Provider"""

import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger()


class SocialProvider:
    """Fetches social media data for sentiment analysis."""

    def __init__(self, x_api_key: Optional[str] = None):
        self.x_api_key = x_api_key
        self.session = requests.Session()

    def fetch_x_mentions(self, query: str = "$BIST OR $BIST100 OR borsa istanbul",
                         max_results: int = 50) -> List[Dict[str, Any]]:
        """Fetch mentions from X (Twitter) API v2."""
        if not self.x_api_key:
            logger.warning("X API key not configured")
            return []

        url = "https://api.twitter.com/2/tweets/search/recent"
        headers = {"Authorization": f"Bearer {self.x_api_key}"}
        params = {
            "query": query,
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,public_metrics,lang",
            "expansions": "author_id",
        }

        try:
            resp = self.session.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            tweets = []
            for item in data.get("data", []):
                tweet = {
                    "social_id": item.get("id", ""),
                    "platform": "X",
                    "author": item.get("author_id", ""),
                    "content": item.get("text", ""),
                    "created_at": item.get("created_at", ""),
                    "language": item.get("lang", "tr"),
                    "retweet_count": item.get("public_metrics", {}).get("retweet_count", 0),
                    "like_count": item.get("public_metrics", {}).get("like_count", 0),
                    "reply_count": item.get("public_metrics", {}).get("reply_count", 0),
                }

                # Engagement score
                metrics = item.get("public_metrics", {})
                tweet["engagement_score"] = (
                    metrics.get("retweet_count", 0) * 3 +
                    metrics.get("like_count", 0) * 1 +
                    metrics.get("reply_count", 0) * 2
                )

                # Basic sentiment
                tweet["sentiment"] = self._basic_sentiment(tweet["content"])

                tweets.append(tweet)

            logger.info("X mentions fetched", count=len(tweets))
            return tweets

        except Exception as e:
            logger.error("X API request failed", error=str(e))
            return []

    def fetch_stocktwits(self, ticker: str) -> List[Dict[str, Any]]:
        """Fetch mentions from StockTwits API."""
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            messages = []
            for item in data.get("messages", []):
                msg = {
                    "social_id": str(item.get("id", "")),
                    "platform": "StockTwits",
                    "author": item.get("user", {}).get("username", ""),
                    "content": item.get("body", ""),
                    "created_at": item.get("created_at", ""),
                    "sentiment": 1.0 if item.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish" else
                                -1.0 if item.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish" else 0.0,
                    "engagement_score": item.get("likes", {}).get("total", 0),
                }
                messages.append(msg)

            logger.info("StockTwits fetched", ticker=ticker, count=len(messages))
            return messages

        except Exception as e:
            logger.warning("StockTwits request failed", ticker=ticker, error=str(e))
            return []

    def _basic_sentiment(self, text: str) -> float:
        """Basic Turkish/English sentiment analysis."""
        text = text.lower()

        positive = [
            "yükseliş", "artış", "kazanç", "rekor", "büyüme", "kar",
            "pozitif", "güçlü", "iyimser", "toparlanma", "al", "alım",
            "bullish", "moon", "pump", "buy", "long", "gain",
        ]

        negative = [
            "düşüş", "kayıp", "zarar", "gerileme", "kriz", "risk",
            "negatif", "zayıf", "kötümser", "sat", "satış",
            "bearish", "dump", "sell", "short", "crash", "loss",
        ]

        pos = sum(1 for w in positive if w in text)
        neg = sum(1 for w in negative if w in text)
        total = pos + neg

        if total == 0:
            return 0.0
        return (pos - neg) / total


# Singleton
social_provider = SocialProvider()
