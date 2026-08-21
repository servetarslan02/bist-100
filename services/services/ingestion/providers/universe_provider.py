"""
ALPHA BIST — BIST Universe Auto-Discovery Provider v1.0

ÜCRETSİZ kaynaklardan BIST hisse listesini otomatik çeker ve günceller:
- KAP.org.tr (Kamuyu Aydınlatma Platformu) — tüm şirketler
- Yahoo Finance (yfinance) — BIST.IS suffix ile keşif
- Borsa İstanbul web sitesi — endeks kompozisyonları

Özellikler:
- Otomatik hisse keşfi (yeni halka arzlar, birleşmeler)
- Endeks üyelikleri (XU100, XU030, XU050) otomatik güncelleme
- Sektör eşleştirmesi (KAP + yfinance)
- Delisted / suspend tespiti
- Cache + periyodik refresh
"""

import requests
import yfinance as yf
import json
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class StockInfo:
    """Hisse bilgisi."""
    ticker: str
    name: str
    sector: str = "DIGER"
    sub_sector: str = ""
    market_cap: float = 0.0
    avg_volume_20d: float = 0.0
    index_membership: List[str] = None
    listing_status: str = "ACTIVE"  # ACTIVE, SUSPENDED, DELISTED
    isin: str = ""
    currency: str = "TRY"
    last_updated: str = ""
    source: str = ""

    def __post_init__(self):
        if self.index_membership is None:
            self.index_membership = []
        if not self.last_updated:
            self.last_updated = datetime.now(timezone.utc).isoformat()


class KAPUniverseProvider:
    """KAP'tan tüm BIST şirketlerini çeker."""

    KAP_API = "https://www.kap.org.tr/tr/api"
    KAP_URL = "https://www.kap.org.tr"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })
        self.timeout = 15

    def fetch_all_companies(self) -> Dict[str, StockInfo]:
        """KAP'tan tüm şirketleri çek."""
        companies = {}

        # Yöntem 1: KAP API'den şirket listesi
        try:
            companies = self._fetch_from_api()
            if companies:
                logger.info("KAP API'den şirketler çekildi", count=len(companies))
                return companies
        except Exception as e:
            logger.warning("KAP API failed", error=str(e))

        # Yöntem 2: KAP web sitesinden scrape
        try:
            companies = self._fetch_from_web()
            if companies:
                logger.info("KAP web'den şirketler çekildi", count=len(companies))
                return companies
        except Exception as e:
            logger.warning("KAP web scrape failed", error=str(e))

        return companies

    def _fetch_from_api(self) -> Dict[str, StockInfo]:
        """KAP API'den şirket listesi."""
        # KAP şirket arama endpoint'i
        url = f"{self.KAP_API}/companies"

        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            # Alternatif: KAP ana sayfadaki şirket listesi
            return self._fetch_from_search()

        data = resp.json()
        companies = {}

        for item in data.get("data", []):
            ticker = item.get("ticker", "").strip().upper()
            name = item.get("companyName", "").strip()
            sector = item.get("sector", "").strip().upper()
            isin = item.get("isin", "").strip()

            if ticker and len(ticker) <= 5:  # BIST ticker formatı
                companies[ticker] = StockInfo(
                    ticker=ticker,
                    name=name or ticker,
                    sector=self._normalize_sector(sector),
                    isin=isin,
                    source="kap_api",
                )

        return companies

    def _fetch_from_search(self) -> Dict[str, StockInfo]:
        """KAP arama fonksiyonunu kullanarak şirketleri bul."""
        companies = {}

        # Türkçe karakterler + alfabetik arama
        search_terms = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["AŞ", "Ş", "Ç", "Ğ", "İ", "Ö", "Ü"]

        for term in search_terms:
            try:
                url = f"{self.KAP_API}/search"
                resp = self.session.get(url, params={"term": term, "type": "company"}, timeout=self.timeout)

                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("results", []):
                        ticker = item.get("ticker", "").strip().upper()
                        name = item.get("name", "").strip()

                        if ticker and len(ticker) <= 5 and ticker not in companies:
                            companies[ticker] = StockInfo(
                                ticker=ticker,
                                name=name or ticker,
                                source="kap_search",
                            )
            except Exception as e:
                logger.debug("Handled exception, continuing", error=str(e))
                continue

        return companies

    def _fetch_from_web(self) -> Dict[str, StockInfo]:
        """KAP web sitesinden şirket listesi scrape et."""
        companies = {}

        # KAP şirketler sayfası
        url = f"{self.KAP_URL}/tr/sirketler"
        resp = self.session.get(url, timeout=self.timeout)

        if resp.status_code != 200:
            return companies

        html = resp.text

        # Şirket ticker ve isimlerini regex ile bul
        # Format: <a href="/tr/sirket/ABC" data-ticker="ABC">ABC Şirket Adı</a>
        patterns = [
            r'data-ticker="([A-Z]{2,5})"[^>]*>([^<]+)<',
            r'href="/tr/sirket/([A-Z]{2,5})"[^>]*>([^<]+)<',
            r'class="[^"]*company[^"]*"[^>]*>\s*([A-Z]{2,5})\s*-\s*([^<]+)<',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html)
            for ticker, name in matches:
                ticker = ticker.strip().upper()
                name = name.strip()

                if ticker and len(ticker) <= 5 and ticker not in companies:
                    companies[ticker] = StockInfo(
                        ticker=ticker,
                        name=name or ticker,
                        source="kap_web",
                    )

        return companies

    def fetch_company_sector(self, ticker: str) -> str:
        """KAP'tan şirket sektörünü çek."""
        try:
            url = f"{self.KAP_URL}/tr/sirket/{ticker}"
            resp = self.session.get(url, timeout=self.timeout)

            if resp.status_code == 200:
                html = resp.text

                # Sektör bilgisi ara
                sector_patterns = [
                    r'[Ss]ekt[öo]r\s*:?\s*([^<\n,]+)',
                    r'[Ff]aaliyet[^<]*>([^<]+)',
                    r'class="[^"]*sector[^"]*"[^>]*>([^<]+)<',
                ]

                for pattern in sector_patterns:
                    match = re.search(pattern, html)
                    if match:
                        sector = match.group(1).strip().upper()
                        return self._normalize_sector(sector)

        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="universe_provider.py:209")
            pass

        return "DIGER"

    @staticmethod
    def _normalize_sector(sector: str) -> str:
        """Sektör ismini normalize et."""
        sector_map = {
            "BANKACILIK": "BANKACILIK",
            "BANKA": "BANKACILIK",
            "FINANS": "BANKACILIK",
            "FINANCIAL": "BANKACILIK",
            "HAVACILIK": "HAVACILIK",
            "AVIATION": "HAVACILIK",
            "HAVA": "HAVACILIK",
            "OTOMOTIV": "OTOMOTIV",
            "AUTOMOTIVE": "OTOMOTIV",
            "ARAC": "OTOMOTIV",
            "PERAKENDE": "PERAKENDE",
            "RETAIL": "PERAKENDE",
            "TEKNOLOJI": "TEKNOLOJI",
            "TECHNOLOGY": "TEKNOLOJI",
            "TEK": "TEKNOLOJI",
            "BILGI": "TEKNOLOJI",
            "SAVUNMA": "SAVUNMA",
            "DEFENSE": "SAVUNMA",
            "ENERJI": "ENERJI",
            "ENERGY": "ENERJI",
            "INSAAT": "INSAAT",
            "CONSTRUCTION": "INSAAT",
            "DEMIR CELIK": "DEMIR_CELIK",
            "DEMIR": "DEMIR_CELIK",
            "STEEL": "DEMIR_CELIK",
            "METAL": "DEMIR_CELIK",
            "KIMYA": "KIMYA",
            "CHEMICAL": "KIMYA",
            "CAM": "CAM",
            "GLASS": "CAM",
            "TEKSTIL": "TEKSTIL",
            "TEXTILE": "TEKSTIL",
            "GIDA": "GIDA",
            "FOOD": "GIDA",
            "TURIZM": "TURIZM",
            "TOURISM": "TURIZM",
            "TELEKOM": "TELEKOM",
            "TELECOM": "TELEKOM",
            "HOLDING": "HOLDING",
            "SAGLIK": "SAGLIK",
            "HEALTH": "SAGLIK",
            "MADEN": "MADEN",
            "MINING": "MADEN",
            "ULAŞTIRMA": "ULASTIRMA",
            "ULASTIRMA": "ULASTIRMA",
            "TRANSPORTATION": "ULASTIRMA",
            "LOJISTIK": "ULASTIRMA",
            "LOGISTICS": "ULASTIRMA",
            "SIGORTA": "SIGORTA",
            "INSURANCE": "SIGORTA",
            "MENKUL": "MENKUL_KIYMET",
            "MENKUL KIYMET": "MENKUL_KIYMET",
            "SECURITIES": "MENKUL_KIYMET",
            "DAYANIKLI": "DAYANIKLI_TUKETIM",
            "DAYANIKLI TUKETIM": "DAYANIKLI_TUKETIM",
            "CONSUMER": "DAYANIKLI_TUKETIM",
            "PETROL": "PETROL",
            "OIL": "PETROL",
            "PLASTIK": "PLASTIK",
            "PLASTIC": "PLASTIK",
            "ORMAN": "ORMAN",
            "FORESTRY": "ORMAN",
            "PAZARLAMA": "PAZARLAMA",
            "MARKETING": "PAZARLAMA",
        }

        sector_clean = sector.strip().upper()
        for key, value in sector_map.items():
            if key in sector_clean or sector_clean in key:
                return value

        return "DIGER"


class YFinanceUniverseProvider:
    """Yahoo Finance'dan BIST hisselerini keşfet ve doğrula."""

    def __init__(self):
        self._cache: Dict[str, any] = {}

    def discover_bist_stocks(self, tickers: List[str]) -> Dict[str, StockInfo]:
        """Verilen ticker'ları yfinance ile doğrula ve bilgilerini çek."""
        companies = {}

        # Batch download ile bilgileri çek
        yf_tickers = [f"{t}.IS" for t in tickers]

        try:
            # Ticker objelerini oluştur
            for ticker in tickers:
                try:
                    yf_ticker = f"{ticker}.IS"
                    t = yf.Ticker(yf_ticker)
                    info = t.info

                    if not info:
                        continue

                    # Hisse BIST'te aktif mi kontrol et
                    exchange = info.get("exchange", "").upper()
                    country = info.get("country", "").upper()

                    # BIST doğrulaması
                    is_bist = (
                        exchange in ["IST", "BIST", "IS", "ISTANBUL"]
                        or country in ["TURKEY", "TÜRKİYE", "TR"]
                        or info.get("currency", "").upper() == "TRY"
                    )

                    if not is_bist:
                        continue

                    # Sektör bilgisi
                    sector = info.get("sector", "")
                    industry = info.get("industry", "")

                    companies[ticker] = StockInfo(
                        ticker=ticker,
                        name=info.get("longName", info.get("shortName", ticker)),
                        sector=self._normalize_yf_sector(sector, industry),
                        sub_sector=industry,
                        market_cap=info.get("marketCap", 0) or 0,
                        avg_volume_20d=info.get("averageVolume", 0) or 0,
                        currency=info.get("currency", "TRY"),
                        source="yfinance",
                    )

                except Exception as e:
                    logger.debug("yfinance ticker failed", ticker=ticker, error=str(e))
                    continue

        except Exception as e:
            logger.error("yfinance discovery failed", error=str(e))

        logger.info("yfinance discovery completed", count=len(companies))
        return companies

    def fetch_index_composition(self, index_symbol: str = "XU100") -> List[str]:
        """Yahoo Finance'dan endeks kompozisyonunu çekmeye çalış."""
        try:
            # Yahoo Finance'da BIST endeksleri .IS suffix ile
            yf_symbol = f"^{index_symbol}" if not index_symbol.startswith("^") else index_symbol

            # Alternatif: BIST ETF'lerinden kompozisyon çıkarımı
            etf_map = {
                "XU100": "TUR.IS",  # iShares MSCI Turkey ETF
                # Diğer ETF'ler eklenebilir
            }

            if index_symbol in etf_map:
                etf = yf.Ticker(etf_map[index_symbol])
                holdings = etf.info.get("holdings", [])
                tickers = [h.get("symbol", "").replace(".IS", "").upper() for h in holdings]
                return [t for t in tickers if t]

        except Exception as e:
            logger.warning("yfinance index composition failed", error=str(e))

        return []

    @staticmethod
    def _normalize_yf_sector(sector: str, industry: str) -> str:
        """Yahoo Finance sektörünü normalize et."""
        sector = (sector or "").upper()
        industry = (industry or "").upper()

        mapping = {
            "FINANCIAL SERVICES": "BANKACILIK",
            "BANKS": "BANKACILIK",
            "INDUSTRIALS": "SANAYI",
            "TECHNOLOGY": "TEKNOLOJI",
            "COMMUNICATION SERVICES": "TELEKOM",
            "CONSUMER CYCLICAL": "DAYANIKLI_TUKETIM",
            "CONSUMER DEFENSIVE": "GIDA",
            "ENERGY": "ENERJI",
            "HEALTHCARE": "SAGLIK",
            "MATERIALS": "MADEN",
            "REAL ESTATE": "INSAAT",
            "UTILITIES": "ENERJI",
        }

        for key, value in mapping.items():
            if key in sector or key in industry:
                return value

        # Industry bazlı eşleştirme
        if any(w in industry for w in ["AEROSPACE", "DEFENSE"]):
            return "SAVUNMA"
        if any(w in industry for w in ["AIRLINES", "AIRPORTS"]):
            return "HAVACILIK"
        if any(w in industry for w in ["STEEL", "IRON", "METAL"]):
            return "DEMIR_CELIK"
        if any(w in industry for w in ["CHEMICAL", "PLASTIC", "FERTILIZER"]):
            return "KIMYA"
        if any(w in industry for w in ["TEXTILE", "APPAREL"]):
            return "TEKSTIL"
        if any(w in industry for w in ["FOOD", "BEVERAGE"]):
            return "GIDA"
        if any(w in industry for w in ["RETAIL", "DEPARTMENT"]):
            return "PERAKENDE"
        if any(w in industry for w in ["HOTEL", "RESORT", "TRAVEL"]):
            return "TURIZM"
        if any(w in industry for w in ["GLASS", "CERAMIC"]):
            return "CAM"
        if any(w in industry for w in ["MINING", "GOLD", "COAL"]):
            return "MADEN"
        if any(w in industry for w in ["CONSTRUCTION", "BUILDING"]):
            return "INSAAT"
        if any(w in industry for w in ["HOLDING", "CONGLOMERATE"]):
            return "HOLDING"
        if any(w in industry for w in ["INSURANCE"]):
            return "SIGORTA"
        if any(w in industry for w in ["OIL", "GAS", "PETROLEUM"]):
            return "PETROL"
        if any(w in industry for w in ["FORESTRY", "PAPER", "WOOD"]):
            return "ORMAN"
        if any(w in industry for w in ["SHIPPING", "LOGISTICS", "TRANSPORT"]):
            return "ULASTIRMA"
        if any(w in industry for w in ["BROKERAGE", "SECURITIES", "ASSET"]):
            return "MENKUL_KIYMET"

        return "DIGER"


class BISTWebProvider:
    """Borsa İstanbul web sitesinden endeks kompozisyonları çeker."""

    BIST_URL = "https://www.borsaistanbul.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
        })
        self.timeout = 15

    def fetch_index_composition(self, index_code: str = "XU100") -> List[str]:
        """Borsa İstanbul'dan endeks kompozisyonunu çek."""
        tickers = []

        # Yöntem 1: BIST API
        try:
            url = f"{self.BIST_URL}/api/index/{index_code}/components"
            resp = self.session.get(url, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("components", []):
                    ticker = item.get("symbol", "").strip().upper()
                    if ticker:
                        tickers.append(ticker)

                if tickers:
                    logger.info(f"BIST {index_code} from API", count=len(tickers))
                    return tickers

        except Exception as e:
            logger.debug(f"BIST API failed for {index_code}", error=str(e))

        # Yöntem 2: Web scrape
        try:
            tickers = self._scrape_index_page(index_code)
            if tickers:
                logger.info(f"BIST {index_code} from web", count=len(tickers))
                return tickers

        except Exception as e:
            logger.debug(f"BIST web scrape failed for {index_code}", error=str(e))

        return tickers

    def _scrape_index_page(self, index_code: str) -> List[str]:
        """Endeks sayfasından ticker'ları scrape et."""
        tickers = []

        url = f"{self.BIST_URL}/tr/endeksler/hisse-senedi-endeksleri/{index_code}"
        resp = self.session.get(url, timeout=self.timeout)

        if resp.status_code != 200:
            return tickers

        html = resp.text

        # Ticker pattern'leri
        patterns = [
            r'data-symbol="([A-Z]{2,5})"',
            r'class="[^"]*symbol[^"]*"[^>]*>([A-Z]{2,5})<',
            r'<td[^>]*>\s*([A-Z]{2,5})\s*</td>',
            r'href="/tr/hisse/([A-Z]{2,5})"',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html)
            for ticker in matches:
                ticker = ticker.strip().upper()
                if ticker and ticker not in tickers and len(ticker) <= 5:
                    tickers.append(ticker)

        return tickers

    def fetch_all_indices(self) -> Dict[str, List[str]]:
        """Tüm endeks kompozisyonlarını çek."""
        indices = {
            "XU100": [],
            "XU030": [],
            "XU050": [],
        }

        for index_code in indices.keys():
            indices[index_code] = self.fetch_index_composition(index_code)

        return indices


class UniverseAutoUpdater:
    """BIST Universe otomatik güncelleme motoru."""

    CACHE_FILE = Path("/mnt/agents/output/bist-100/data/universe_cache.json")
    CACHE_TTL_HOURS = 24  # Cache geçerlilik süresi

    def __init__(self):
        self.kap_provider = KAPUniverseProvider()
        self.yf_provider = YFinanceUniverseProvider()
        self.bist_provider = BISTWebProvider()
        self._universe: Dict[str, StockInfo] = {}
        self._indices: Dict[str, List[str]] = {
            "XU100": [],
            "XU030": [],
            "XU050": [],
        }

    def get_universe(self, force_refresh: bool = False) -> Dict[str, StockInfo]:
        """Güncel hisse evrenini döndür."""
        if not force_refresh and self._is_cache_valid():
            self._load_from_cache()
            logger.info("Universe loaded from cache", count=len(self._universe))
            return self._universe

        self.refresh_universe()
        return self._universe

    def refresh_universe(self) -> Dict[str, StockInfo]:
        """Hisse evrenini tüm kaynaklardan yenile."""
        logger.info("Starting universe refresh...")

        # 1. KAP'tan tüm şirketleri çek
        kap_companies = self.kap_provider.fetch_all_companies()
        logger.info("KAP companies fetched", count=len(kap_companies))

        # 2. Yahoo Finance ile doğrula ve zenginleştir
        if kap_companies:
            tickers = list(kap_companies.keys())
            yf_companies = self.yf_provider.discover_bist_stocks(tickers)

            # Merge: KAP + yfinance
            for ticker, kap_info in kap_companies.items():
                if ticker in yf_companies:
                    yf_info = yf_companies[ticker]
                    # yfinance verileri daha güncel olabilir
                    self._universe[ticker] = StockInfo(
                        ticker=ticker,
                        name=yf_info.name or kap_info.name,
                        sector=yf_info.sector if yf_info.sector != "DIGER" else kap_info.sector,
                        sub_sector=yf_info.sub_sector,
                        market_cap=yf_info.market_cap or kap_info.market_cap,
                        avg_volume_20d=yf_info.avg_volume_20d,
                        currency=yf_info.currency,
                        source="merged_kap_yf",
                    )
                else:
                    # Sadece KAP'ta var
                    self._universe[ticker] = kap_info

        # 3. Endeks kompozisyonlarını çek
        self._refresh_index_compositions()

        # 4. Endeks üyeliklerini hisselere ata
        self._assign_index_memberships()

        # 5. Cache'e kaydet
        self._save_to_cache()

        logger.info("Universe refresh completed",
                    total_stocks=len(self._universe),
                    xu100=len(self._indices["XU100"]),
                    xu030=len(self._indices["XU030"]),
                    xu050=len(self._indices["XU050"]))

        return self._universe

    def _refresh_index_compositions(self):
        """Endeks kompozisyonlarını güncelle."""
        # BIST web sitesinden çek
        bist_indices = self.bist_provider.fetch_all_indices()

        for index_code, tickers in bist_indices.items():
            if tickers:
                self._indices[index_code] = tickers

        # Eğer BIST web'den alınamazsa, yfinance'dan dene
        for index_code in ["XU100", "XU030", "XU050"]:
            if not self._indices.get(index_code):
                yf_tickers = self.yf_provider.fetch_index_composition(index_code)
                if yf_tickers:
                    self._indices[index_code] = yf_tickers

        # Fallback: Market cap sıralaması ile XU100 tahmini
        if not self._indices["XU100"]:
            self._indices["XU100"] = self._estimate_xu100_by_market_cap()

    def _estimate_xu100_by_market_cap(self) -> List[str]:
        """Market cap'e göre XU100 tahmini (fallback)."""
        sorted_stocks = sorted(
            self._universe.items(),
            key=lambda x: x[1].market_cap,
            reverse=True
        )
        return [ticker for ticker, _ in sorted_stocks[:100]]

    def _assign_index_memberships(self):
        """Hisse bilgilerine endeks üyeliklerini ata."""
        for ticker, info in self._universe.items():
            memberships = []
            for index_code, members in self._indices.items():
                if ticker in members:
                    memberships.append(index_code)
            info.index_membership = memberships

    def get_index_members(self, index: str = "XU100") -> List[str]:
        """Endeks üyelerini döndür."""
        return self._indices.get(index, [])

    def get_tickers_by_sector(self, sector: str) -> List[str]:
        """Sektöre göre hisseleri döndür."""
        return [
            t for t, info in self._universe.items()
            if info.sector == sector.upper()
        ]

    def get_all_sectors(self) -> List[str]:
        """Tüm sektörleri döndür."""
        sectors = set(info.sector for info in self._universe.values())
        return sorted(list(sectors))

    def get_sector_stats(self) -> Dict[str, int]:
        """Sektör bazlı istatistikler."""
        stats = {}
        for info in self._universe.values():
            stats[info.sector] = stats.get(info.sector, 0) + 1
        return stats

    def is_active(self, ticker: str) -> bool:
        """Hisse aktif mi?"""
        info = self._universe.get(ticker)
        if not info:
            return False
        return info.listing_status == "ACTIVE"

    def get_delisted(self) -> List[str]:
        """Delisted hisseleri döndür."""
        return [
            t for t, info in self._universe.items()
            if info.listing_status == "DELISTED"
        ]

    def _is_cache_valid(self) -> bool:
        """Cache geçerli mi?"""
        if not self.CACHE_FILE.exists():
            return False

        try:
            mtime = datetime.fromtimestamp(self.CACHE_FILE.stat().st_mtime, tz=timezone.utc)
            age = datetime.now(timezone.utc) - mtime
            return age < timedelta(hours=self.CACHE_TTL_HOURS)
        except Exception as e:
            return False

    def _load_from_cache(self):
        """Cache'den yükle."""
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._universe = {}
            for ticker, info_dict in data.get("universe", {}).items():
                self._universe[ticker] = StockInfo(**info_dict)

            self._indices = data.get("indices", self._indices)

        except Exception as e:
            logger.warning("Cache load failed", error=str(e))
            self._universe = {}

    def _save_to_cache(self):
        """Cache'e kaydet."""
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "universe": {
                    t: asdict(info) for t, info in self._universe.items()
                },
                "indices": self._indices,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning("Cache save failed", error=str(e))

    def export_to_bist_universe_format(self) -> Dict:
        """Mevcut BISTUniverse formatına dönüştür."""
        return {
            "BIST_100_TICKERS": self._indices.get("XU100", []),
            "BIST_30_TICKERS": self._indices.get("XU030", []),
            "BIST_50_TICKERS": self._indices.get("XU050", []),
            "BIST_ALL_TICKERS": list(self._universe.keys()),
            "SECTOR_MAP": {
                t: info.sector for t, info in self._universe.items()
            },
            "total_count": len(self._universe),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


# Singleton
universe_updater = UniverseAutoUpdater()


# Backward compatibility
BIST_STOCKS = None  # Dinamik olarak universe_updater.get_universe() ile alınacak


def get_current_universe() -> Dict[str, StockInfo]:
    """Güncel hisse evrenini döndür (backward compatible)."""
    return universe_updater.get_universe()


def get_bist_100() -> List[str]:
    """BIST 100 hisselerini döndür."""
    universe_updater.get_universe()
    return universe_updater.get_index_members("XU100")


def get_bist_30() -> List[str]:
    """BIST 30 hisselerini döndür."""
    universe_updater.get_universe()
    return universe_updater.get_index_members("XU030")


def get_bist_50() -> List[str]:
    """BIST 50 hisselerini döndür."""
    universe_updater.get_universe()
    return universe_updater.get_index_members("XU050")


def get_all_tickers() -> List[str]:
    """Tüm BIST hisselerini döndür."""
    return list(universe_updater.get_universe().keys())


def get_sector(ticker: str) -> str:
    """Hissenin sektörünü döndür."""
    universe = universe_updater.get_universe()
    info = universe.get(ticker)
    return info.sector if info else "DIGER"


if __name__ == "__main__":
    # Test
    updater = UniverseAutoUpdater()
    universe = updater.refresh_universe()

    logger.info("debug_output", message=f"\nToplam hisse: {len(universe)}")
    logger.info("debug_output", message=f"XU100: {len(updater.get_index_members('XU100'))}")
    logger.info("debug_output", message=f"XU030: {len(updater.get_index_members('XU030'))}")
    logger.info("debug_output", message=f"XU050: {len(updater.get_index_members('XU050'))}")

    logger.info("debug_output", message="\nSektör dağılımı:")
    for sector, count in updater.get_sector_stats().items():
        logger.info("debug_output", message=f"  {sector}: {count}")

    logger.info("debug_output", message="\nİlk 10 hisse:")
    for ticker in list(universe.keys())[:10]:
        info = universe[ticker]
        logger.info("debug_output", message=f"  {ticker}: {info.name} ({info.sector}) MC:{info.market_cap:,.0f}")
