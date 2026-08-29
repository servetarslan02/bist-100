from typing import Any
"""
ALPHA BIST — News Provider v2.0 (Düzeltilmiş)

Duplicate pgsus map kaldırıldı.
RSS feed'leri config'den okunuyor.

FAZ 3: News & Sentiment
"""

import asyncio
import time
import urllib.parse
from datetime import UTC, datetime, timedelta, timezone

import aiohttp
import feedparser
import structlog

logger = structlog.get_logger()


def compute_financial_sentiment(title: str, summary: str = "") -> float:
    """Metin üzerinden gerçek, deterministik Türkçe ve İngilizce finansal NLP duygu skoru üretir (-1.0 ile +1.0 arası)."""
    text = f"{title} {summary}".lower()

    pos_weights = {
        "rekor": 0.8,
        "tavan": 0.9,
        "kâr": 0.6,
        "karını artırdı": 0.75,
        "katladı": 0.8,
        "anlaşma": 0.6,
        "ihale": 0.65,
        "sipariş": 0.6,
        "büyüme": 0.5,
        "yükseliş": 0.55,
        "temettü": 0.6,
        "bedelsiz": 0.6,
        "onay": 0.45,
        "tahminleri aştı": 0.7,
        "yeşil ışık": 0.5,
        "güçlü": 0.4,
        "zirve": 0.5,
        "artış": 0.4,
        "alım": 0.35,
        "fırsat": 0.4,
        "ralli": 0.75,
        "ortaklık": 0.5,
        "yatırım": 0.55,
        "kapasite artışı": 0.6,
        "hedef yükseltti": 0.7,
        "outperform": 0.6,
        "buy": 0.5,
        "upgrade": 0.65,
        "kazandı": 0.6,
        "lider": 0.4,
        "faiz indirimi": 0.55,
        "enflasyon düştü": 0.65,
        "cari fazla": 0.6,
        "ihracat rekoru": 0.7,
    }

    neg_weights = {
        "taban": -0.9,
        "zarar": -0.7,
        "düşüş": -0.5,
        "çöküş": -0.85,
        "kayıp": -0.6,
        "dava": -0.6,
        "ceza": -0.75,
        "soruşturma": -0.65,
        "iptal": -0.7,
        "iflas": -0.95,
        "konkordato": -0.9,
        "zayıf": -0.45,
        "risk": -0.4,
        "satış": -0.3,
        "şahin": -0.4,
        "kriz": -0.75,
        "siber saldırı": -0.6,
        "maliyet": -0.35,
        "kesinti": -0.5,
        "hedef düşürdü": -0.65,
        "downscale": -0.6,
        "sell": -0.5,
        "uyarı": -0.45,
        "geriledi": -0.45,
        "enflasyon": -0.50,
        "zam": -0.40,
        "faiz artışı": -0.50,
        "borç": -0.45,
        "yaptırım": -0.55,
        "cari açık": -0.50,
        "bütçe açığı": -0.55,
        "işsizlik": -0.45,
        "pahallılık": -0.50,
    }

    score = 0.0
    matches = 0
    for phrase, w in pos_weights.items():
        if phrase in text:
            score += w
            matches += 1

    for phrase, w in neg_weights.items():
        if phrase in text:
            score += w
            matches += 1

    if matches == 0:
        return 0.0  # Kesin ve net Nötr (%0)

    final_score = max(-1.0, min(1.0, score / max(1, matches)))
    return round(final_score, 2)


def is_relevant_to_bist_and_macro(title: str, summary: str = "") -> bool:
    """Borsa İstanbul ve Türkiye makroekonomisi ile ilgili olmayan haberleri eler.

    Pozitif kontrol: Başlıkta/özette Türkiye, BIST, TCMB veya bilinen bir
    Türk şirket/marka referansı olmalı. Sadece 'yasaklı kelime yok' kontrolü
    yeterli değil — 'dolar', 'şirket', 'tahmin' gibi genel kelimeler yanlış
    pozitif üretiyordu.
    """
    import re

    text = f"{title} {summary}".lower()

    irrelevant_geos = [
        "venezuela",
        "sri lanka",
        "somali",
        "nijerya",
        "peru",
        "kongo",
        "zimbabve",
        "haiti",
        "patriot hareketliliği",
        "yunanistan'da patriot",
        "starlink cihazı",
    ]
    if any(geo in text for geo in irrelevant_geos):
        return False

    # Pozitif alaka kontrolü: Kelime sınırı ile (substring değil)
    turkey_bist_keywords = [
        r"türkiye",
        r"turkiye",
        r"türk\b",
        r"turk\b",
        r"bist\b",
        r"borsa istanbul",
        r"tcmb",
        r"merkez bankası",
        r"kap\b",
        r"tüik",
        r"tuik",
        r"hazine",
        r"istanbul",
        r"ankara",
        r"izmir",
        r"lira\b",
        r"try\b",
    ]
    if any(re.search(kw, text) for kw in turkey_bist_keywords):
        return True

    # Bilinen Türk şirket/marka isimleri (tam kelime eşleşmesi)
    for alias in NewsProvider.COMPANY_NAME_MAP.values():
        first_word = alias.split()[0].lower()
        if len(first_word) >= 4 and re.search(r"\b" + re.escape(first_word) + r"\b", text):
            return True

    # Global makro terimler yalnızca TCMB/faiz/BIST konteğiyle birlikte anılıyorsa kabul et
    global_macro_context = ["fed", "ecb", "powell", "jackson hole"]
    tr_context = ["tcmb", "faiz", "enflasyon", "lira", "bist", "türkiye", "turkiye"]
    if any(g in text for g in global_macro_context) and any(t in text for t in tr_context):
        return True

    return False


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
        """Otomatik eklendi."""
        # RSS feed'leri config'den oku (hardcoded yerine)
        self._rss_feeds = self._load_rss_feeds()
        logger.info("NewsProvider initialized", feeds=len(self._rss_feeds))

    def _load_rss_feeds(self) -> list[str]:
        """RSS feed URL'lerini yükle."""
        # Önce config'den dene
        try:
            from services.core.observability import config_manager

            feeds = config_manager.get("news.rss_feeds")
            if feeds:
                return feeds
        except Exception as e:
            logger.warning("RSS feed load failed", error=str(e))

        # Fallback: Türkiye'nin en popüler ve geniş finansal/KAP RSS beslemeleri
        return [
            "https://www.bloomberght.com/rss",
            "https://bigpara.hurriyet.com.tr/rss/",
            "https://www.trthaber.com/ekonomi_articles.rss",
            "https://tr.investing.com/rss/news_25.rss",
            "https://tr.investing.com/rss/news_14.rss",
            "https://www.dunya.com/rss?kategori=finans",
            "https://www.dunya.com/rss?kategori=sirketler",
        ]

    async def fetch_financial_news_rss(self, max_items: int = 50) -> list[dict]:
        """Tüm RSS beslemelerini paralel (eşzamanlı) olarak anında çeker."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        async def _fetch_single_feed(session, feed_url) -> Any:
            """Otomatik eklendi."""
            items = []
            try:
                async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=3.0, connect=1.5)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries[:15]:
                            t = entry.get("title", "")
                            s = entry.get("summary", "")

                            # Finans dışı genel gürültü filtresi
                            noise_keywords = [
                                "sakatlık",
                                "futbol",
                                "maç",
                                "süper lig",
                                "dizi",
                                "ünlü",
                                "magazin",
                                "şampiyonlar ligi",
                                "kandil",
                                "hava durumu",
                                "sıcaklıklar",
                                "ösym",
                                "ags sonuçları",
                                "şans oyunları",
                                "milli piyango",
                                "deprem",
                                "namaz",
                            ]
                            if any(k in f"{t} {s}".lower() for k in noise_keywords):
                                continue

                            # Gerçek yayınlanma zamanını ayıkla
                            pub_str = ""
                            epoch = time.time()
                            if hasattr(entry, "published_parsed") and entry.published_parsed:
                                try:
                                    import calendar

                                    epoch = float(calendar.timegm(entry.published_parsed))
                                    tr_tz = timezone(timedelta(hours=3))
                                    dt = datetime.fromtimestamp(epoch, tz=UTC).astimezone(tr_tz)
                                    pub_str = dt.strftime("%d.%m %H:%M")
                                except Exception:
                                    logger.warning("Caught Exception in _fetch_single_feed", exc_info=True)
                            if not pub_str:
                                pub_str = entry.get("published", "") or entry.get("updated", "")

                            items.append(
                                {
                                    "title": t,
                                    "summary": s,
                                    "link": entry.get("link", ""),
                                    "published": pub_str,
                                    "published_epoch": epoch,
                                    "source": feed_url,
                                    "sentiment_score": compute_financial_sentiment(t, s),
                                }
                            )
            except Exception as e:
                logger.debug(f"RSS fetch note: {feed_url} - {e}")
            return items

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            tasks = [_fetch_single_feed(session, url) for url in self._rss_feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_news = []
        for res in results:
            if isinstance(res, list):
                all_news.extend(res)

        logger.info(f"Fetched {len(all_news)} news items across {len(self._rss_feeds)} sources in parallel")
        return all_news

    async def fetch_official_kap_disclosures(self, max_items: int = 25) -> list[dict]:
        """Doğrudan KAP (Kamuyu Aydınlatma Platformu) resmi şirket bildirimlerini çeker."""
        url = "https://news.google.com/rss/search?q=%22KAP%22+hisse+bildirimi+borsa&hl=tr&gl=TR&ceid=TR:tr"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        items = []
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3.5)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries[:max_items]:
                            t = entry.get("title", "")
                            s = entry.get("summary", "")

                            pub_str = ""
                            epoch = time.time()
                            if hasattr(entry, "published_parsed") and entry.published_parsed:
                                try:
                                    import calendar

                                    epoch = float(calendar.timegm(entry.published_parsed))
                                    tr_tz = timezone(timedelta(hours=3))
                                    dt = datetime.fromtimestamp(epoch, tz=UTC).astimezone(tr_tz)
                                    pub_str = dt.strftime("%d.%m %H:%M")
                                except Exception:
                                    logger.warning("Caught Exception in fetch_official_kap_disclosures", exc_info=True)
                            if not pub_str:
                                pub_str = entry.get("published", "") or entry.get("updated", "")

                            items.append(
                                {
                                    "title": t,
                                    "summary": s,
                                    "link": entry.get("link", ""),
                                    "published": pub_str,
                                    "published_epoch": epoch,
                                    "source": "KAP (Kamuyu Aydınlatma Platformu)",
                                    "type": "KAP",
                                    "sentiment_score": compute_financial_sentiment(t, s),
                                }
                            )
        except Exception as e:
            logger.debug(f"Official KAP fetch note: {e}")
        return items

    async def fetch_official_tcmb_news(self, max_items: int = 25) -> list[dict]:
        """Doğrudan TCMB (Merkez Bankası) ve Makroekonomi duyuru ve kararlarını çeker."""
        url = "https://news.google.com/rss/search?q=%22TCMB%22+OR+%22Merkez+Bankas%C4%B1%22+faiz+OR+enflasyon+OR+rezerv&hl=tr&gl=TR&ceid=TR:tr"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        items = []
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3.5)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries[:max_items]:
                            t = entry.get("title", "")
                            s = entry.get("summary", "")

                            pub_str = ""
                            epoch = time.time()
                            if hasattr(entry, "published_parsed") and entry.published_parsed:
                                try:
                                    import calendar

                                    epoch = float(calendar.timegm(entry.published_parsed))
                                    tr_tz = timezone(timedelta(hours=3))
                                    dt = datetime.fromtimestamp(epoch, tz=UTC).astimezone(tr_tz)
                                    pub_str = dt.strftime("%d.%m %H:%M")
                                except Exception:
                                    logger.warning("Caught Exception in fetch_official_tcmb_news", exc_info=True)
                            if not pub_str:
                                pub_str = entry.get("published", "") or entry.get("updated", "")

                            items.append(
                                {
                                    "title": t,
                                    "summary": s,
                                    "link": entry.get("link", ""),
                                    "published": pub_str,
                                    "published_epoch": epoch,
                                    "source": "TCMB / Merkez Bankası",
                                    "type": "MACRO",
                                    "sentiment_score": compute_financial_sentiment(t, s),
                                }
                            )
        except Exception as e:
            logger.debug(f"Official TCMB fetch note: {e}")
        return items

    async def fetch_news_for_ticker(self, ticker: str, max_items: int = 15) -> list[dict]:
        """629 BIST hissesinin her biri için dinamik, özel canlı haber ve KAP taraması yapar."""
        ticker_clean = ticker.replace(".IS", "").upper().strip()
        all_news = []

        # Google News RSS / Canlı Finans & KAP Arama Beslemesi
        query = urllib.parse.quote(f"{ticker_clean} hisse OR kap OR borsa")
        url = f"https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries[:max_items]:
                            t = entry.get("title", "")
                            s = entry.get("summary", "")
                            all_news.append(
                                {
                                    "title": t,
                                    "summary": s,
                                    "link": entry.get("link", ""),
                                    "published": entry.get("published", ""),
                                    "source": "Google News / KAP",
                                    "ticker": ticker_clean,
                                    "sentiment_score": compute_financial_sentiment(t, s),
                                }
                            )
        except Exception as e:
            logger.debug(f"Dynamic ticker news note for {ticker_clean}: {e}")

        return all_news

    def match_news_to_ticker(self, news: dict, ticker: str) -> bool:
        """Haberi hisseyle eşleştir — TÜM BIST HİSSELERİ İÇİN DİNAMİK.

        Öncelik sırası:
        1. KAP ticker doğrudan eşleşme (en güvenilir)
        2. BIST ticker kodu (kelime sınırı ile — yanlış pozitif önleme, ör: THYAO, EREGL)
        3. Şirket adı & Unvanı (bist_universe dinamik 629+ hisse listesi)
        4. COMPANY_NAME_MAP takma isimleri
        """
        import re

        text = f"{news.get('title', '')} {news.get('summary', '')}"
        text_lower = text.lower()
        ticker_upper = ticker.strip().upper()
        ticker_lower = ticker.strip().lower()

        # 1. KAP ticker doğrudan eşleşme
        news_ticker = news.get("ticker", "").strip().upper()
        if news_ticker and news_ticker == ticker_upper:
            return True

        # 2. BIST ticker kodu (tam kelime olarak eşleşmeli)
        ticker_pattern = re.compile(r"\b" + re.escape(ticker_lower) + r"\b", re.IGNORECASE)
        if ticker_pattern.search(text):
            return True

        # 3. Dinamik Universe üzerinden Şirket Resmi Adı ve Marka Kelimeleri (629+ hisse)
        try:
            from ..bist_universe import bist_universe

            stock_info = bist_universe._updater.get_universe().get(ticker_upper)
            if stock_info and stock_info.name:
                raw_name = stock_info.name.lower()
                clean_name = re.sub(
                    r"\b(a\.ş\.|as|sanayi|ticaret|anonim|şirketi|holding|yatırım|yatirim|menkul|değerler|degerler|üretim|uretim)\b",
                    "",
                    raw_name,
                ).strip()
                tokens = [t.strip() for t in clean_name.split() if len(t.strip()) >= 3]
                if tokens:
                    # Ana marka kelimesi (ör: "zorlu", "a1 capital", "garanti", "aselsan")
                    first_two = " ".join(tokens[:2])
                    if len(first_two) >= 4 and first_two in text_lower:
                        return True
                    if len(tokens[0]) >= 4 and tokens[0] in text_lower:
                        return True
        except Exception:
            logger.warning("Caught Exception in match_news_to_ticker", exc_info=True)

        # 4. COMPANY_NAME_MAP eşleşmesi
        company_alias = self.COMPANY_NAME_MAP.get(ticker_lower, "")
        return bool(company_alias and company_alias.lower() in text_lower)


# Singleton
news_provider = NewsProvider()
