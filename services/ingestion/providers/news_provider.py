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

# BIST şirket adı → ticker eşleme (tekil, tekrarsız)
# Key'ler küçük harf, value'lar BIST ticker formatı
COMPANY_NAME_MAP = {
    # Ulaşım
    "thy": "THYAO", "thyao": "THYAO", "türk hava yolları": "THYAO", "turkish airlines": "THYAO",
    "pgsus": "PGSUS", "pegasus": "PGSUS",
    "tavhl": "TAVHL", "tav": "TAVHL",
    "sunexpress": "SXS",
    # Savunma
    "asels": "ASELS", "aselsan": "ASELS",
    "havelsan": "HVLSN",
    "tai": "TAI", "tusaş": "TAI",
    "roketsan": "ROKETSAN",
    "pgsus": "PGSUS",
    # Bankacılık
    "garan": "GARAN", "garanti": "GARAN", "garanti bankası": "GARAN", "garanti bank": "GARAN",
    "akbnk": "AKBNK", "akbank": "AKBNK",
    "isctr": "ISCTR", "iş bankası": "ISCTR", "is bankası": "ISCTR", "turkiye is bankasi": "ISCTR",
    "halbk": "HALKB", "halkbank": "HALKB",
    "vakbn": "VAKBN", "vakıfbank": "VAKBN", "vakifbank": "VAKBN",
    "ykbnk": "YKBNK", "yapı kredi": "YKBNK", "yapi kredi": "YKBNK",
    "qnbfb": "QNBFB", "finansbank": "QNBFB",
    "tskb": "TSKB", "turkiye sinai kalkinma": "TSKB",
    # Holding
    "kchol": "KCHOL", "koç holding": "KCHOL", "koc holding": "KCHOL",
    "sahol": "SAHOL", "sabancı": "SAHOL", "sabancı holding": "SAHOL", "sabanci": "SAHOL",
    "toaso": "TOASO", "tofaş": "TOASO", "tofas": "TOASO",
    "tuprs": "TUPRS", "tüpraş": "TUPRS", "tupras": "TUPRS",
    # Enerji
    "petkm": "PETKM", "petkim": "PETKM",
    "aygaz": "AYGAZ",
    "opet": "OPET",
    "ayen": "AYEN", "ayen enerji": "AYEN",
    "odas": "ODAS", "odaş": "ODAS",
    "akener": "AKENR", "akenerji": "AKENR",
    # Perakende
    "bimas": "BIMAS", "bim": "BIMAS", "bim market": "BIMAS",
    "mgros": "MGROS", "migros": "MGROS",
    "sokm": "SOKM", "şok": "SOKM", "sok market": "SOKM",
    "aefes": "AEFES", "efes": "AEFES",
    # Sanayi
    "eregl": "EREGL", "ereğli": "EREGL", "erdemir": "EREGL",
    "arclk": "ARCLK", "arçelik": "ARCLK", "arcelik": "ARCLK",
    "froto": "FROTO", "ford otosan": "FROTO",
    "vestel": "VESTEL",
    "sise": "SISE", "şişecam": "SISE", "sisecam": "SISE",
    "brsa": "BRSA", "borusan": "BRSA",
    "krdma": "KRDMA", "kardemir": "KRDMA",
    "tcell": "TCELL", "turkcell": "TCELL",
    "ttkom": "TTKOM", "türk telekom": "TTKOM", "turk telekom": "TTKOM",
    "enka": "ENKAI", "enkai": "ENKAI",
    "alark": "ALARK", "alarko": "ALARK",
    # Gayrimenkul
    "ekgyo": "EKGYO", "emlak konut": "EKGYO",
    "trgyo": "TRGYO", "torunlar": "TRGYO",
    # Gıda
    "tukaş": "TUKAS", "tukas": "TUKAS",
    "konfr": "KONFR", "konfrüt": "KONFR",
    # Teknoloji
    "logo": "LOGO", "yazılım": "LOGO",
    # İndeksler
    "xu100": "BIST100", "bist 100": "BIST100", "bist100": "BIST100",
    "borsa istanbul": "BIST100", "borsa": "BIST100",
    "xu030": "BIST30", "bist 30": "BIST30", "bist30": "BIST30",
    # Sektör isimleri (haber eşleştirme için)
    "havacılık": "SECTOR_AVIATION",
    "bankacılık": "SECTOR_BANKING",
    "enerji": "SECTOR_ENERGY",
    "perakende": "SECTOR_RETAIL",
    "teknoloji": "SECTOR_TECH",
    "savunma": "SECTOR_DEFENSE",
    "otomotiv": "SECTOR_AUTOMOTIVE",
    "gıda": "SECTOR_FOOD",
    "gayrimenkul": "SECTOR_REALESTATE",
    "sigorta": "SECTOR_INSURANCE",
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

        # 1. COMPANY_NAME_MAP ile eşleştir (uzun isimler önce)
        # Uzun isimlerin önce eşleşmesi için sırala ("garanti bankası" > "garanti")
        sorted_names = sorted(COMPANY_NAME_MAP.keys(), key=len, reverse=True)
        for name in sorted_names:
            if name in text_lower:
                ticker = COMPANY_NAME_MAP[name]
                # Sektör eşleme ise atla (sadece ticker olanları al)
                if not ticker.startswith("SECTOR_"):
                    found.add(ticker)
                # Eşleşen metni işaretle (çift eşleşmeyi önle)
                text_lower = text_lower.replace(name, " " * len(name))

        # 2. Regex: Doğrudan ticker yazımı (büyük harf, 4-6 karakter)
        # "THYAO hisseleri" gibi
        ticker_pattern = re.findall(r'\b([A-Z]{4,6})\b', text)
        for t in ticker_pattern:
            t_upper = t.upper()
            # Sadece bilinen ticker'ları kabul et
            if t_upper in set(COMPANY_NAME_MAP.values()) and not t_upper.startswith("SECTOR_"):
                found.add(t_upper)

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
