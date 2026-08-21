"""
ALPHA BIST — News Provider v2.0 (Düzeltilmiş)

Duplicate pgsus map kaldırıldı.
RSS feed'leri config'den okunuyor.

FAZ 3: News & Sentiment
"""

import asyncio
import aiohttp
import feedparser
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

class NewsProvider:
    """Haber sağlayıcı."""

    # Şirket isimleri (duplicate KALDIRILDI)
    COMPANY_NAME_MAP = {
        "thyao": "Turk Hava Yollari",
        "garan": "Garanti BBVA",
        "isctr": "Is Bankasi",
        "akbnk": "Akbank",
        "ykbnk": "Yapi Kredi",
        "halkb": "Halkbank",
        "vakbn": "Vakifbank",
        "sahol": "Sabanci Holding",
        "kchol": "Koc Holding",
        "tuprs": "Tupras",
        "eregl": "Eregli Demir Celik",
        "krdmd": "Kardemir",
        "petkm": "Petkim",
        "sise": "Sisecam",
        "toaso": "Tofas",
        "froto": "Ford Otosan",
        "arclk": "Arcelik",
        "bimas": "BIM",
        "mgros": "Migros",
        "sokm": "Sok Marketler",
        "ttrak": "Turk Traktor",
        "asels": "Aselsan",
        "tcell": "Turkcell",
        "ttkom": "Turk Telekom",
        "pgsus": "Pegasus",  # Tek tanım
        "clebi": "Clebi Hava Servisi",
        "alark": "Alarko Holding",
        "enjsa": "Enerjisa",
        "odas": "Odas Elektrik",
        "akenr": "Akenerji",
        "aydem": "Aydem Enerji",
        "cimsa": "Cimsa",
        "nuhcm": "Nuh Cimento",
        "golts": "Goltas Cimento",
        "bucim": "Bursa Cimento",
        "konya": "Konya Cimento",
        "btcim": "Batı Cimento",
        "ecilc": "Eczacibasi",
        "hektas": "Hektas",
        "kmpur": "Kimpur",
        "soda": "Soda Sanayi",
        "kzbgy": "Koza Bagimsiz",
        "kozal": "Koza Altin",
        "kozaa": "Koza Anadolu",
        "ulker": "Ulker",
        "bizim": "Bizim Toptan",
        "mavi": "Mavi Giyim",
        "desa": "Desa Deri",
        "derim": "Derimod",
        "gents": "Gents",
        "rtalb": "Rotal Yatirim",
        "avhol": "Avrupa Yatirim",
        "gsdho": "Gsd Holding",
        "ieyho": "Istanbul Enternasyonel",
        "ktskr": "Kutahya Seramik",
        "merit": "Merit",
        "naten": "Naturel Enerji",
        "sayas": "Say Yenilenebilir",
        "smrtg": "Smart Güneş",
        "alfas": "Alfa Solar",
        "gesan": "Gesan",
        "eupwr": "Euro Power",
        "astor": "Astor Enerji",
        "yeotk": "Yeo Teknoloji",
        "conse": "Consus Enerji",
        "aksen": "Aksa Enerji",
        "zoren": "Zorlu Enerji",
        "magen": "Maren Maraş",
        "huner": "Hun Enerji",
        "aksue": "Aksu Enerji",
        "bmstl": "Bimtas",
        "dohol": "Dogan Holding",
        "dgklb": "Dogus Otomotiv",
        "brlsm": "Birlesim Motor",
        "parsn": "Parsan",
        "boyd": "Boyner",
        "quagr": "Qua Granite",
        "bryt": "Borusan Yatirim",
        "cante": "Can2 Termik",
        "ccola": "Coca Cola İçecek",
        "ditas": "Ditas",
        "durdo": "Durdur",
        "egeen": "Ege Endustri",
        "eggub": "Ege Gubre",
        "elite": "Elite Naturel",
        "ersu": "Ersu",
        "etilr": "Etiler",
        "gubrf": "Gubre Fabrikalari",
        "hlgyo": "Halil Ibrahim Yatirim",
        "ihgzt": "Ihlas Gazetecilik",
        "ihlas": "Ihlas Holding",
        "indes": "Indes",
        "ipeke": "Ipek Dogal",
        "karsn": "Karsan",
        "kervt": "Kervansaray",
        "klsyn": "Kaleseramik",
        "klsER": "Kaleseramik",
        "knfrt": "Konfrut",
        "kords": "Kordsa",
        "krpls": "Koroplast",
        "krstl": "Kristal Kola",
        "kutpo": "Kutpo",
        "lkmnh": "Lokman Hekim",
        "logo": "Logo Yazilim",
        "maavi": "Mavi Giyim",
        "maktk": "Makina Takim",
        "mndtr": "Menderes Tekstil",
        "mpark": "MLP Saglik",
        "nibas": "Nibas",
        "nugyo": "Nurol GYO",
        "otkar": "Otokar",
        "oyakc": "Oyak Cimento",
        "ozgyo": "Ozak GYO",
        "ozsub": "Ozsubasi",
        "pamel": "Pamel Yenilenebilir",
        "pcilt": "Pinar Et",
        "pekgy": "Peker GYO",
        "pengd": "Pengoda",
        "pkent": "Polisan Kimya",
        "polho": "Polisan Holding",
        "prkme": "Park Elektrik",
        "przma": "Prizma Pres",
        "psgyo": "Pasar GYO",
        "rbn": "Rubenis",
        "sanel": "Sanel",
        "snkrn": "Sanko Pazarlama",
        "srvgY": "Servet GYO",
        "tavhl": "TAV Havalimanlari",
        "tknsa": "Teknosa",
        "tmpol": "Tempo Plastik",
        "trcas": "Trakya Cam",
        "trgyo": "Torunlar GYO",
        "tskb": "Türkiye Sinai Kalkinma",
        "tuclk": "Tuclas",
        "ulkER": "Ulker",
        "ulufa": "Ulufan",
        "vangd": "Vanet Gida",
        "vertu": "Verusaturk",
        "vesbe": "Vestel Beyaz Esya",
        "vkgyo": "Vakif GYO",
        "yggyo": "Yeni Gimat GYO",
        "yylgd": "Yayla Gida",
    }

    def __init__(self):
        # RSS feed'leri config'den oku (hardcoded yerine)
        self._rss_feeds = self._load_rss_feeds()
        logger.info("NewsProvider initialized", feeds=len(self._rss_feeds))

    def _load_rss_feeds(self) -> List[str]:
        """RSS feed URL'lerini yükle."""
        # Önce config'den dene
        try:
            from services.core.observability import config_manager
            feeds = config_manager.get("news.rss_feeds")
            if feeds:
                return feeds
        except Exception as e:
            logger.warning("RSS feed load failed", error=str(e))

        # Fallback: güvenilir ve hızlı finansal RSS beslemeleri
        return [
            "https://www.bloomberght.com/rss",
            "https://bigpara.hurriyet.com.tr/rss/",
            "https://www.trthaber.com/ekonomi_articles.rss",
        ]

    async def fetch_financial_news_rss(self, max_items: int = 20) -> List[Dict]:
        """RSS haberleri çek."""
        all_news = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for feed_url in self._rss_feeds:
                try:
                    async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            feed = feedparser.parse(content)

                            for entry in feed.entries[:20]:
                                news_item = {
                                    "title": entry.get("title", ""),
                                    "summary": entry.get("summary", ""),
                                    "link": entry.get("link", ""),
                                    "published": entry.get("published", ""),
                                    "source": feed_url,
                                }
                                all_news.append(news_item)

                except Exception as e:
                    logger.debug(f"RSS fetch skipped: {feed_url}", error=str(e))

        logger.info(f"Fetched {len(all_news)} news items")
        return all_news

    def match_news_to_ticker(self, news: Dict, ticker: str) -> bool:
        """Haberi hisseyle eşleştir.

        Öncelik sırası:
        1. BIST ticker kodu (kelime sınırı ile — yanlış pozitif önleme)
        2. KAP şirket kimliği (news dict içinde kap_ticker varsa)
        3. Şirket adı (COMPANY_NAME_MAP — fallback)
        """
        import re
        text = f"{news.get('title', '')} {news.get('summary', '')}"
        text_lower = text.lower()
        ticker_lower = ticker.lower()

        # 1. KAP ticker doğrudan eşleşme (en güvenilir)
        news_ticker = news.get("ticker", "").strip().upper()
        if news_ticker and news_ticker == ticker.upper():
            return True

        # 2. BIST ticker kodu — kelime sınırı ile eşleşme
        #    "as" → "aselsan" ile eşleşmemeli, ama "AS" kelime olarak eşleşmeli
        ticker_pattern = re.compile(r'\b' + re.escape(ticker_lower) + r'\b', re.IGNORECASE)
        if ticker_pattern.search(text):
            return True

        # 3. Şirket adı (fallback)
        company_name = self.COMPANY_NAME_MAP.get(ticker_lower, "")
        if company_name and company_name.lower() in text_lower:
            return True

        return False

# Singleton
news_provider = NewsProvider()
