"""ALPHA BIST - News Data Provider v2.0

Haberleri çeker ve hisse bazlı atar:
- RSS feed'lerden haber çekme
- Haber başlığından ticker çıkarma
- Importance + credibility scoring
- Her haberi doğru hisseye atama
"""

import re
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger()

# BIST şirket adı → ticker eşleme
COMPANY_NAME_MAP = {
    "thyao": "THYAO", "thy": "THYAO", "türk hava yolları": "THYAO", "turkish airlines": "THYAO",
    "asels": "ASELS", "aselsan": "ASELS",
    "garan": "GARAN", "garanti": "GARAN", "garanti bankası": "GARAN",
    "akbnk": "AKBNK", "akbank": "AKBNK",
    "eregl": "EREGL", "ereğli": "EREGL", "erdemir": "EREGL",
    "tuprs": "TUPRS", "tüpraş": "TUPRS", "tupras": "TUPRS",
    "sasa": "SASA", "sasa polyester": "SASA",
    "bimas": "BİM", "bim": "BİM",
    "arclk": "ARCLK", "arçelik": "ARCLK",
    "kchol": "KCHOL", "koç holding": "KCHOL",
    "sahol": "SAHOL", "sabancı": "SAHOL", "sabancı holding": "SAHOL",
    "pgsus": "PGSUS", "pegasus": "PGSUS",
    "tavhl": "TAVHL", "tav": "TAVHL",
    "vestel": "VESTEL", "vestel": "VESTEL",
    "froto": "FROTO", "ford otosan": "FROTO",
    "toaso": "TOASO", "tofaş": "TOASO",
    "iş bankası": "ISCTR", "isctr": "ISCTR",
    "halkbank": "HALKB", "halbk": "HALKB",
    "vakıfbank": "VAKBN", "vakbn": "VAKBN",
    "tcell": "TCELL", "turkcell": "TCELL",
    "ttkom": "TTKOM", "türk telekom": "TTKOM",
    "enka": "ENKAI", "enkai": "ENKAI",
    "şok": "SOKM", "sokm": "SOKM",
    "migros": "MGROS", "mgros": "MGROS",
    "aefes": "AEFES", "efes": "AEFES",
    "tuprs": "TUPRS", "petkim": "PETKM", "petkm": "PETKM",
    "tocl": "TOCL", "uşak seramik": "USAK",
    "xu100": "BIST100", "bist 100": "BIST100", "bist100": "BIST100",
    "borsa istanbul": "BIST100", "borsa": "BIST100",
    "akbank": "AKBNK", "garanti bank": "GARAN", "yapi kredi": "YKBNK",
    "halkbank": "HALKB", "vakifbank": "VAKBN", "ziraat": "ZIRAAT",
    "turkcell": "TCELL", "turk telekom": "TTKOM",
    "aselsan": "ASELS", "havelsan": "HVLSN", "tai": "TAI",
    "ford otosan": "FROTO", "tofas": "TOASO", "arcelik": "ARCLK",
    "bim": "BIMAS", "migros": "MGROS", "sok market": "SOKM",
    "pegasus": "PGSUS", "sunexpress": "SXS",
    "emlak konut": "EKGYO", "torunlar": "TRGYO",
    "alarko": "ALARK", "enka": "ENKAI",
    "sisecam": "SISE", "borusan": "BRSA",
    "kardemir": "KRDMA", "tupras": "TUPRS", "petkim": "PETKM",
    "aygaz": "AYGAZ", "opet": "OPET",
    "sabanci": "SAHOL", "koc holding": "KCHOL",
    "turkiye is bankasi": "ISCTR", "is bankasi": "ISCTR",
}


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
            ("https://www.borsagundem.com/rss", "Borsa Gündem"),
            ("https://www.bloomberght.com/rss", "Bloomberg HT"),
            ("https://www.aa.com.tr/tr/ekonomi/rss", "Anadolu Ajansı"),
        ]

        articles = []
        for url, source_name in rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    desc = entry.get("summary", "")
                    full_text = f"{title} {desc}"

                    article = {
                        "source": source_name,
                        "title": title,
                        "description": desc,
                        "url": entry.get("link", ""),
                        "published_at": entry.get("published", ""),
                        "language": "tr",
                        "tickers": self.extract_tickers(full_text),
                        "sentiment": self._basic_sentiment(full_text),
                        "importance": self.compute_importance(full_text),
                        "credibility": self.compute_credibility(source_name),
                    }
                    articles.append(article)

            except Exception as e:
                logger.warning("RSS feed failed", source=source_name, error=str(e))

        logger.info("RSS articles fetched", count=len(articles))
        return articles

    def extract_tickers(self, text: str) -> List[str]:
        """Haber başlığından BIST ticker'larını çıkar."""
        text_lower = text.lower()
        found = set()

        for name, ticker in COMPANY_NAME_MAP.items():
            if name in text_lower:
                found.add(ticker)

        # Regex: BIST ticker formatı (4-5 harf, büyük harf)
        ticker_pattern = re.findall(r'\b([A-Z]{4,5})\b', text)
        for t in ticker_pattern:
            if t in COMPANY_NAME_MAP.values():
                found.add(t)

        return list(found)

    def compute_importance(self, text: str) -> float:
        """Haber önem skoru (0-1)."""
        text_lower = text.lower()
        importance = 0.3  # Varsayılan

        # Yüksek önem
        high_importance = ["bilanço", "finansal sonuç", "temettü", "kar payı", "birleşme",
                          "devralma", "sözleşme", "ihale", "yatırım", "dava", "ceza",
                          "rekor", "iflas", "kriz", "merkez bankası", "faiz"]
        for word in high_importance:
            if word in text_lower:
                importance += 0.15

        # Orta önem
        mid_importance = ["açıklama", "duyuru", "toplantı", "genel kurul", "yönetim"]
        for word in mid_importance:
            if word in text_lower:
                importance += 0.05

        return min(1.0, importance)

    def compute_credibility(self, source: str) -> float:
        """Kaynak güvenilirlik skoru (0-1)."""
        credibility_map = {
            "Dünya": 0.9, "Bloomberg": 0.95, "Reuters": 0.95,
            "Anadolu Ajansı": 0.85, "AA": 0.85,
            "Borsa Gündem": 0.7, "ParaAnaliz": 0.75,
            "Investing.com": 0.8, "Ekonomim": 0.8,
            "Sözcü": 0.6, "Hürriyet": 0.65, "Milliyet": 0.65,
        }
        return credibility_map.get(source, 0.5)

    def _basic_sentiment(self, text: str) -> float:
        """Basic Turkish sentiment analysis."""
        text = text.lower()

        positive = [
            "yükseliş", "artış", "kazanç", "rekor", "büyüme", "kar",
            "pozitif", "güçlü", "iyimser", "toparlanma", "çıkış",
            "sözleşme", "ihale", "yatırım", "temettü", "bedelsiz",
        ]

        negative = [
            "düşüş", "kayıp", "zarar", "gerileme", "kriz", "risk",
            "negatif", "zayıf", "kötümser", "çöküş", "satış",
            "dava", "ceza", "iptal", "iflas", "borç",
        ]

        pos = sum(1 for w in positive if w in text)
        neg = sum(1 for w in negative if w in text)
        total = pos + neg

        if not total or total == 0:
            return 0.0
        return (pos - neg) / total


# Singleton
news_provider = NewsProvider()
