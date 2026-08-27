"""
ALPHA BIST — Social Media Data Provider v2.0 (Async + Ekşi + Reddit)

Kaynaklar: X/Twitter, StockTwits, Ekşi Sözlük, Reddit
Kullanım: Sentiment analizi, sosyal medya takibi

v2.0: Async refactor + Ekşi Sözlük scraper + Reddit + gelişmiş sentiment
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()


# Türkçe sentiment sözlüğü
TURKISH_POSITIVE = [
    "yükseliş",
    "artış",
    "kazanç",
    "rekor",
    "büyüme",
    "kar",
    "kâr",
    "pozitif",
    "güçlü",
    "iyimser",
    "toparlanma",
    "al",
    "alım",
    "alın",
    "patlama",
    "fırlama",
    "uçma",
    "coşku",
    "mutlu",
    "güzel",
    "harika",
    "süper",
    "mükemmel",
    "devam",
    "destek",
    "güven",
    "umut",
    "bullish",
    "moon",
    "pump",
    "buy",
    "long",
    "gain",
    "rocket",
    "breakout",
    "rally",
    "surge",
    "soar",
    "boom",
]

TURKISH_NEGATIVE = [
    "düşüş",
    "kayıp",
    "zarar",
    "gerileme",
    "kriz",
    "risk",
    "negatif",
    "zayıf",
    "kötümser",
    "sat",
    "satış",
    "satın",
    "çöküş",
    "panik",
    "korku",
    "endişe",
    "tehlike",
    "alarm",
    "felaket",
    "berbat",
    "korkunç",
    "kötü",
    "çarpı",
    "batış",
    "bearish",
    "dump",
    "sell",
    "short",
    "crash",
    "loss",
    "collapse",
    "plunge",
    "tank",
    "nosedive",
    "freefall",
]


class SocialProvider:
    """Sosyal medya veri sağlayıcısı (async)."""

    def __init__(self):
        self._client = get_client("social", timeout=15.0, max_retries=2)
        self._x_api_key: str | None = None

    def set_x_api_key(self, key: str):
        """X API key ayarla."""
        self._x_api_key = key

    # =====================================================
    # X (Twitter)
    # =====================================================

    async def fetch_x_mentions(
        self,
        query: str = "$BIST OR $BIST100 OR borsa istanbul",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """X (Twitter) mentions çek (async)."""
        if not self._x_api_key:
            logger.debug("X API key not configured")
            return []

        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": query,
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,public_metrics,lang",
            "expansions": "author_id",
        }

        try:
            data = await self._client.get_json(url, params=params)
            if not data:
                return []

            tweets = []
            for item in data.get("data", []):
                metrics = item.get("public_metrics", {})
                tweet = {
                    "social_id": item.get("id", ""),
                    "platform": "X",
                    "author": item.get("author_id", ""),
                    "content": item.get("text", ""),
                    "created_at": item.get("created_at", ""),
                    "language": item.get("lang", "tr"),
                    "retweet_count": metrics.get("retweet_count", 0),
                    "like_count": metrics.get("like_count", 0),
                    "reply_count": metrics.get("reply_count", 0),
                    "engagement_score": (
                        metrics.get("retweet_count", 0) * 3
                        + metrics.get("like_count", 0) * 1
                        + metrics.get("reply_count", 0) * 2
                    ),
                    "sentiment": self._analyze_sentiment(item.get("text", "")),
                }
                tweets.append(tweet)

            logger.info("X mentions fetched", count=len(tweets))
            return tweets

        except Exception as e:
            logger.error("X API request failed", error=str(e))
            return []

    # =====================================================
    # StockTwits
    # =====================================================

    async def fetch_stocktwits(self, ticker: str) -> list[dict[str, Any]]:
        """StockTwits mesajları çek (async)."""
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

        try:
            data = await self._client.get_json(url)
            if not data:
                return []

            messages = []
            for item in data.get("messages", []):
                sentiment_raw = item.get("entities", {}).get("sentiment", {})
                sentiment_basic = sentiment_raw.get("basic")

                sentiment = 0.0
                if sentiment_basic == "Bullish":
                    sentiment = 1.0
                elif sentiment_basic == "Bearish":
                    sentiment = -1.0

                msg = {
                    "social_id": str(item.get("id", "")),
                    "platform": "StockTwits",
                    "ticker": ticker,
                    "author": item.get("user", {}).get("username", ""),
                    "content": item.get("body", ""),
                    "created_at": item.get("created_at", ""),
                    "sentiment": sentiment,
                    "sentiment_label": sentiment_basic or "Neutral",
                    "engagement_score": item.get("likes", {}).get("total", 0),
                }
                messages.append(msg)

            logger.info("StockTwits fetched", ticker=ticker, count=len(messages))
            return messages

        except Exception as e:
            logger.warning("StockTwits request failed", ticker=ticker, error=str(e))
            return []

    # =====================================================
    # Ekşi Sözlük
    # =====================================================

    async def fetch_eksi_topic(
        self,
        query: str,
        max_entries: int = 20,
    ) -> list[dict[str, Any]]:
        """Ekşi Sözlük başlığı çek (async).

        Args:
            query: Arama terimi (ör: "thyao", "borsa")
            max_entries: Maksimum entry sayısı
        """
        try:
            # Ekşi Sözlük arama API'si

            # Doğrudan başlık URL'si
            topic_url = f"https://eksisozluk.com/{query}--1"
            client = get_client("eksi", timeout=15.0, max_retries=2)

            try:
                text = await client.get_text(topic_url, params=None)
            except Exception:
                return []

            if not text:
                return []

            # Basit HTML parse (BeautifulSoup gerektirmez)
            entries = self._parse_eksi_html(text, max_entries)

            # Sentiment analizi
            for entry in entries:
                entry["sentiment"] = self._analyze_sentiment(entry.get("content", ""))
                entry["platform"] = "Ekşi Sözlük"
                entry["query"] = query

            logger.info("Ekşi Sözlük fetched", query=query, count=len(entries))
            return entries

        except Exception as e:
            logger.warning("Ekşi Sözlük fetch failed", query=query, error=str(e))
            return []

    def _parse_eksi_html(self, html: str, max_entries: int) -> list[dict[str, Any]]:
        """Ekşi Sözlük HTML'den entry'leri çıkar."""
        entries = []

        # Entry content pattern
        content_pattern = re.compile(
            r'<div class="content"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )

        # Entry date pattern
        date_pattern = re.compile(
            r'<div class="entry-date"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )

        # Author pattern
        author_pattern = re.compile(
            r'<a class="entry-author"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )

        contents = content_pattern.findall(html)
        dates = date_pattern.findall(html)
        authors = author_pattern.findall(html)

        for i, content in enumerate(contents[:max_entries]):
            # HTML tag'lerini temizle
            clean_content = re.sub(r"<[^>]+>", "", content).strip()
            clean_content = clean_content.replace("&amp;", "&")
            clean_content = clean_content.replace("&lt;", "<")
            clean_content = clean_content.replace("&gt;", ">")
            clean_content = clean_content.replace("&quot;", '"')
            clean_content = clean_content.replace("&#39;", "'")

            if not clean_content:
                continue

            entry = {
                "content": clean_content,
                "date": dates[i].strip() if i < len(dates) else "",
                "author": authors[i].strip() if i < len(authors) else "",
                "social_id": f"eksi_{i}",
            }
            entries.append(entry)

        return entries

    async def fetch_eksi_stock_mentions(
        self,
        ticker: str,
        company_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hisse ile ilgili Ekşi Sözlük entry'leri (async)."""
        all_entries = []

        # Ticker ile ara
        entries = await self.fetch_eksi_topic(ticker.lower())
        all_entries.extend(entries)

        # Şirket adı ile ara
        if company_name:
            entries = await self.fetch_eksi_topic(company_name.lower().replace(" ", "-"))
            all_entries.extend(entries)

        # "borsa" genel başlığı
        if not all_entries:
            entries = await self.fetch_eksi_topic("borsa-istanbul")
            all_entries.extend(entries)

        return all_entries

    # =====================================================
    # Reddit
    # =====================================================

    async def fetch_reddit_mentions(
        self,
        subreddit: str = "yatirim",
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Reddit Türkiye subreddit'inden gönderileri çek (async).

        Args:
            subreddit: Alt reddit (varsayılan: yatirim)
            query: Arama terimi (opsiyonel)
            limit: Maksimum gönderi sayısı
        """
        try:
            if query:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {"q": query, "limit": limit, "sort": "new", "t": "week"}
            else:
                url = f"https://www.reddit.com/r/{subreddit}/new.json"
                params = {"limit": limit}

            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ALPHABIST/1.0)",
            }

            client = get_client("reddit", timeout=15.0, max_retries=2, headers=headers)
            data = await client.get_json(url, params=params)

            if not data:
                return []

            posts = []
            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                if not post_data:
                    continue

                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                content = f"{title} {selftext}".strip()

                post = {
                    "social_id": post_data.get("id", ""),
                    "platform": "Reddit",
                    "subreddit": subreddit,
                    "author": post_data.get("author", ""),
                    "title": title,
                    "content": content[:500],  # İlk 500 karakter
                    "url": f"https://reddit.com{post_data.get('permalink', '')}",
                    "score": post_data.get("score", 0),
                    "num_comments": post_data.get("num_comments", 0),
                    "created_at": datetime.fromtimestamp(post_data.get("created_utc", 0), tz=UTC).isoformat(),
                    "sentiment": self._analyze_sentiment(content),
                    "engagement_score": (post_data.get("score", 0) * 2 + post_data.get("num_comments", 0) * 3),
                }
                posts.append(post)

            logger.info("Reddit fetched", subreddit=subreddit, count=len(posts))
            return posts

        except Exception as e:
            logger.warning("Reddit fetch failed", subreddit=subreddit, error=str(e))
            return []

    async def fetch_reddit_stock_mentions(
        self,
        ticker: str,
        subreddits: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hisse ile ilgili Reddit gönderileri (async)."""
        if subreddits is None:
            subreddits = ["yatirim", "borsa", "turkey", "KucukYatirimci"]

        all_posts = []
        for sub in subreddits:
            posts = await self.fetch_reddit_mentions(subreddit=sub, query=ticker)
            all_posts.extend(posts)

        logger.info("Reddit stock mentions", ticker=ticker, count=len(all_posts))
        return all_posts

    # =====================================================
    # Sentiment Analysis
    # =====================================================

    def _analyze_sentiment(self, text: str) -> float:
        """Gelişmiş Türkçe/İngilizce sentiment analizi (-1.0 ile +1.0 arası).
        Negation handling ile: 'iyi değil' → negative, 'kötü değil' → positive.
        """
        if not text:
            return 0.0

        text_lower = text.lower()
        words = text_lower.split()

        pos_count = 0
        neg_count = 0
        negation_words = {"değil", "yok", "olmayan", "değildir", "olmaz", "hiç", "asla", "ne", "olmadı"}
        negate = False
        for word in words:
            if word in negation_words:
                negate = True
                continue
            if word in TURKISH_POSITIVE:
                if negate:
                    neg_count += 1
                else:
                    pos_count += 1
                negate = False
            elif word in TURKISH_NEGATIVE:
                if negate:
                    pos_count += 1
                else:
                    neg_count += 1
                negate = False

        total = pos_count + neg_count
        if total == 0:
            return 0.0

        # Normalize edilmiş sentiment
        sentiment = (pos_count - neg_count) / total

        # Emoji kontrolü
        emoji_pos = text.count("🚀") + text.count("📈") + text.count("💰") + text.count("🟢")
        emoji_neg = text.count("📉") + text.count("💀") + text.count("🔴") + text.count("😱")

        if emoji_pos + emoji_neg > 0:
            emoji_sentiment = (emoji_pos - emoji_neg) / (emoji_pos + emoji_neg)
            sentiment = (sentiment + emoji_sentiment) / 2

        return round(max(-1.0, min(1.0, sentiment)), 3)

    def _analyze_sentiment_batch(self, texts: list[str]) -> dict[str, Any]:
        """Toplu sentiment analizi."""
        if not texts:
            return {"avg_sentiment": 0.0, "positive_ratio": 0.0, "count": 0}

        sentiments = [self._analyze_sentiment(t) for t in texts]
        positive = sum(1 for s in sentiments if s > 0.1)
        negative = sum(1 for s in sentiments if s < -0.1)
        neutral = len(sentiments) - positive - negative

        return {
            "avg_sentiment": round(sum(sentiments) / len(sentiments), 3),
            "positive_ratio": round(positive / len(sentiments), 3),
            "negative_ratio": round(negative / len(sentiments), 3),
            "neutral_ratio": round(neutral / len(sentiments), 3),
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "count": len(sentiments),
        }

    # =====================================================
    # Aggregate
    # =====================================================

    async def fetch_all_social(
        self,
        ticker: str,
        company_name: str | None = None,
    ) -> dict[str, Any]:
        """Tüm sosyal medya kaynaklarından veri çek (async, paralel)."""
        tasks = [
            self.fetch_stocktwits(ticker),
            self.fetch_eksi_stock_mentions(ticker, company_name),
            self.fetch_reddit_stock_mentions(ticker),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Social fetch task failed", error=str(result))
                continue
            if isinstance(result, list):
                all_items.extend(result)

        # Aggregate sentiment
        [item.get("sentiment", 0) for item in all_items if item.get("sentiment") is not None]

        return {
            "ticker": ticker,
            "items": all_items,
            "total_count": len(all_items),
            "sentiment": self._analyze_sentiment_batch([item.get("content", "") for item in all_items]),
            "by_platform": {
                "stocktwits": len([i for i in all_items if i.get("platform") == "StockTwits"]),
                "eksi": len([i for i in all_items if i.get("platform") == "Ekşi Sözlük"]),
                "reddit": len([i for i in all_items if i.get("platform") == "Reddit"]),
                "x": len([i for i in all_items if i.get("platform") == "X"]),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Singleton
social_provider = SocialProvider()
