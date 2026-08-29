"""
ALPHA BIST — BIST Universe Auto-Discovery Provider v2.0
TÜM BIST hisselerini (600+ hisse) ve endeks üyeliklerini dinamik olarak keşfeder ve günceller.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import orjson
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
    index_membership: list[str] = None
    listing_status: str = "ACTIVE"  # ACTIVE, SUSPENDED, DELISTED
    isin: str = ""
    currency: str = "TRY"
    last_updated: str = ""
    source: str = ""

    def __post_init__(self):
        """Otomatik eklendi."""
        if self.index_membership is None:
            self.index_membership = []
        if not self.last_updated:
            self.last_updated = datetime.now(UTC).isoformat()


class LiveUniverseScraper:
    """Canlı kamu ve finans kaynaklarından tüm BIST hisselerini çeker."""

    def __init__(self):
        """Otomatik eklendi."""
        self.session = httpx.Client(follow_redirects=True)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        self.timeout = 10

    def discover_all_bist_stocks(self) -> dict[str, StockInfo]:
        """Tüm kaynakları tarayarak eksiksiz BIST hisse evrenini keşfet."""
        discovered: dict[str, StockInfo] = {}

        # 1. Kaynak: Mynet Finans BIST Tam Liste
        try:
            url = "https://finans.mynet.com/borsa/hisseler/"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                # format: href="/borsa/hisseler/GARAN-garanti-bankasi/"
                matches = re.findall(r'/borsa/hisseler/([a-z0-9]{3,6})-([^/"]+)/', resp.text)
                for sym, slug in matches:
                    ticker = sym.upper().strip()
                    if 2 <= len(ticker) <= 6 and not ticker.isdigit():
                        name = slug.replace("-", " ").title()
                        discovered[ticker] = StockInfo(
                            ticker=ticker,
                            name=name,
                            sector=self._guess_sector(ticker, name),
                            source="mynet_live",
                        )
                logger.info("mynet_universe_discovery_done", count=len(discovered))
        except Exception as e:
            logger.debug("mynet_discovery_failed", error=str(e))

        # 2. Kaynak: Bigpara Canlı Borsa
        try:
            url = "https://bigpara.hurriyet.com.tr/borsa/canli-borsa/"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                matches = re.findall(r"/borsa/hisse-fiyatlari/([a-z0-9]+)-detay/", resp.text)
                for sym in matches:
                    ticker = sym.upper().strip()
                    if 2 <= len(ticker) <= 6 and not ticker.isdigit() and ticker not in discovered:
                        discovered[ticker] = StockInfo(
                            ticker=ticker,
                            name=ticker,
                            sector=self._guess_sector(ticker, ticker),
                            source="bigpara_live",
                        )
        except Exception as e:
            logger.debug("bigpara_discovery_failed", error=str(e))

        # 3. Kaynak: İş Yatırım
        try:
            url = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                matches = re.findall(r'value="([A-Z0-9]{3,6})"\s*data-title="([^"]*)"', resp.text)
                for ticker, name in matches:
                    ticker = ticker.upper().strip()
                    if 2 <= len(ticker) <= 6 and not ticker.isdigit():
                        if ticker not in discovered:
                            discovered[ticker] = StockInfo(
                                ticker=ticker,
                                name=name or ticker,
                                sector=self._guess_sector(ticker, name),
                                source="isyatirim_live",
                            )
                        elif name and discovered[ticker].name == ticker:
                            discovered[ticker].name = name
        except Exception as e:
            logger.debug("isyatirim_discovery_failed", error=str(e))

        return discovered

    def _guess_sector(self, ticker: str, name: str) -> str:
        """Hisse sembolü veya isminden sektörü tahmin et / eşle."""
        name_u = (name + " " + ticker).upper()
        if any(
            w in name_u
            for w in ["BANK", "BANKASI", "GARAN", "AKBNK", "ISCTR", "YKBNK", "HALKB", "VAKBN", "TSKB", "ALBRK", "QNB"]
        ):
            return "BANKACILIK"
        if any(w in name_u for w in ["GYO", "GAYRIMENKUL", "KONUT"]):
            return "GAYRIMENKUL"
        if any(w in name_u for w in ["HAVACILIK", "HAVAYOLLARI", "THYAO", "PGSUS", "TAVHL", "CLEBI"]):
            return "HAVACILIK"
        if any(w in name_u for w in ["SAVUNMA", "ASELS", "SDTTR"]):
            return "SAVUNMA"
        if any(
            w in name_u
            for w in ["YAZILIM", "TEKNOLOJI", "BILISIM", "KFEIN", "LOGO", "MIATK", "VBTYZ", "ARDYZ", "FONET"]
        ):
            return "TEKNOLOJI"
        if any(
            w in name_u
            for w in ["ENERJI", "ELEKTRIK", "SOLAR", "PETROL", "TUPRS", "ASTOR", "ENJSA", "AKSEN", "EUPWR", "KONTR"]
        ):
            return "ENERJI"
        if any(w in name_u for w in ["DEMIR", "CELIK", "SANAYI", "EREGL", "KRDMD", "SISE", "ARCLK", "VESTL", "CIMSA"]):
            return "SANAYI"
        if any(w in name_u for w in ["HOLDING", "YATIRIM", "KCHOL", "SAHOL", "ALARK", "ENKAI", "AGHOL", "DOHOL"]):
            return "HOLDING"
        if any(w in name_u for w in ["GIDA", "MARKET", "PERAKENDE", "BIMAS", "MGROS", "CCOLA", "ULKER", "SOKM"]):
            return "PERAKENDE"
        if any(w in name_u for w in ["OTOMOTIV", "OTO", "FROTO", "TOASO", "TTRAK", "DOAS", "OTKAR"]):
            return "OTOMOTIV"
        if any(w in name_u for w in ["SIGORTA", "EMEKLI"]):
            return "SIGORTA"
        if any(w in name_u for w in ["TELEKOM", "ILETISIM", "TCELL", "TTKOM"]):
            return "TELEKOM"
        if any(w in name_u for w in ["SAGLIK", "ILAC", "HASTANE"]):
            return "SAGLIK"
        if any(w in name_u for w in ["MADEN", "MADENCILIK", "ALTIN", "KOZAL", "KOZAA"]):
            return "MADENCILIK"
        return "DIGER"


class UniverseAutoUpdater:
    """BIST Universe otomatik güncelleme ve yönetim motoru."""

    CACHE_FILE = Path("data/universe_cache.json")
    CACHE_TTL_HOURS = 12

    def __init__(self):
        """Otomatik eklendi."""
        self.scraper = LiveUniverseScraper()
        self._universe: dict[str, StockInfo] = {}
        self._indices: dict[str, list[str]] = {
            "XU100": [],
            "XU030": [],
            "XU050": [],
        }

    def get_universe(self, force_refresh: bool = False) -> dict[str, StockInfo]:
        """Güncel hisse evrenini döndür."""
        if not force_refresh and self._is_cache_valid():
            self._load_from_cache()
            if len(self._universe) > 100:
                return self._universe

        return self.refresh_universe()

    def refresh_universe(self) -> dict[str, StockInfo]:
        """Hisse evrenini tüm canlı kaynaklardan sıfırdan çek ve güncelle."""
        logger.info("Starting complete live BIST universe auto-discovery...")

        # 1. Canlı kaynaklardan tüm BIST hisselerini çek
        live_stocks = self.scraper.discover_all_bist_stocks()
        if live_stocks:
            self._universe = live_stocks
            logger.info("live_universe_discovered", count=len(self._universe))
        elif not self._universe:
            self._load_from_cache()

        # 2. Endeks üyeliklerini oluştur
        self._refresh_index_compositions()

        # 3. Cache'e kaydet
        self._save_to_cache()

        return self._universe

    def _refresh_index_compositions(self) -> Any:
        """BIST 100, BIST 30, BIST 50 endeks üyeliklerini belirle."""
        BIST_100_BENCHMARK = [
            "AEFES",
            "AGHOL",
            "AHGAZ",
            "AKBNK",
            "AKCNS",
            "AKFGY",
            "AKFYE",
            "AKSA",
            "AKSEN",
            "ALARK",
            "ALBRK",
            "ALFAS",
            "ANHYT",
            "ANSGR",
            "ARCLK",
            "ARDYZ",
            "ASELS",
            "ASTOR",
            "BERA",
            "BIMAS",
            "BINHO",
            "BIOEN",
            "BOBET",
            "BRSAN",
            "BRYAT",
            "BTCIM",
            "CANTE",
            "CCOLA",
            "CIMSA",
            "CLEBI",
            "CWENE",
            "DOAS",
            "DOHOL",
            "ECILC",
            "ECZYT",
            "EGEEN",
            "EKGYO",
            "ENERY",
            "ENJSA",
            "ENKAI",
            "EREGL",
            "EUPWR",
            "EUREN",
            "FROTO",
            "GARAN",
            "GENIL",
            "GESAN",
            "GOLTS",
            "GUBRF",
            "GWIND",
            "HALKB",
            "HEKTS",
            "IPEKE",
            "ISCTR",
            "ISDMR",
            "ISGYO",
            "ISMEN",
            "IZENR",
            "KARSAN",
            "KCAER",
            "KCHOL",
            "KLSER",
            "KMPUR",
            "KONTR",
            "KONYA",
            "KORDS",
            "KOZAA",
            "KOZAL",
            "KRDMD",
            "KZBGY",
            "MAVI",
            "MGROS",
            "MIATK",
            "OBAMS",
            "ODAS",
            "OTKAR",
            "OYAKC",
            "PASEU",
            "PETKM",
            "PGSUS",
            "QUAGR",
            "REEDR",
            "SAHOL",
            "SASA",
            "SAYAS",
            "SDTTR",
            "SISE",
            "SKBNK",
            "SMRTG",
            "SOKM",
            "TABGD",
            "TAVHL",
            "TCELL",
            "THYAO",
            "TKFEN",
            "TOASO",
            "TSKB",
            "TTKOM",
            "TTRAK",
            "TUKAS",
            "TUPRS",
            "TURSG",
            "ULKER",
            "VAKBN",
            "VESBE",
            "VESTL",
            "YEOTK",
            "YKBNK",
            "YYLGD",
            "ZOREN",
        ]
        BIST_30_BENCHMARK = [
            "AKBNK",
            "ALARK",
            "ARCLK",
            "ASELS",
            "ASTOR",
            "BIMAS",
            "BRSAN",
            "DOAS",
            "EKGYO",
            "ENKAI",
            "EREGL",
            "FROTO",
            "GARAN",
            "GUBRF",
            "HALKB",
            "HEKTS",
            "ISCTR",
            "KCHOL",
            "KONTR",
            "KOZAL",
            "KRDMD",
            "OYAKC",
            "PETKM",
            "PGSUS",
            "SAHOL",
            "SASA",
            "SISE",
            "TAVHL",
            "TCELL",
            "THYAO",
            "TOASO",
            "TUPRS",
            "YKBNK",
        ]

        all_syms = set(self._universe.keys())
        xu100 = [s for s in BIST_100_BENCHMARK if s in all_syms]
        # Eğer benchmark'ta olmayan varsa kalanını evrenden ekle
        for s in self._universe:
            if len(xu100) >= 100:
                break
            if s not in xu100:
                xu100.append(s)

        self._indices["XU100"] = xu100
        self._indices["XU030"] = [s for s in BIST_30_BENCHMARK if s in all_syms]
        self._indices["XU050"] = xu100[:50]

        for ticker, info in self._universe.items():
            members = []
            if ticker in self._indices["XU100"]:
                members.append("XU100")
            if ticker in self._indices["XU030"]:
                members.append("XU030")
            if ticker in self._indices["XU050"]:
                members.append("XU050")
            info.index_membership = members

    def get_index_members(self, index: str = "XU100") -> list[str]:
        """Endeks üyelerini döndür."""
        if not self._universe:
            self.get_universe()
        return self._indices.get(index, [])

    def get_tickers_by_sector(self, sector: str) -> list[str]:
        """Sektöre göre hisseleri döndür."""
        if not self._universe:
            self.get_universe()
        return [t for t, info in self._universe.items() if info.sector == sector.upper()]

    def get_all_sectors(self) -> list[str]:
        """Tüm sektörleri döndür."""
        if not self._universe:
            self.get_universe()
        return sorted(list(set(info.sector for info in self._universe.values())))

    def get_sector_stats(self) -> dict[str, int]:
        """Sektör bazlı istatistikler."""
        if not self._universe:
            self.get_universe()
        stats = {}
        for info in self._universe.values():
            stats[info.sector] = stats.get(info.sector, 0) + 1
        return stats

    def is_active(self, ticker: str) -> bool:
        """Hisse aktif mi?"""
        if not self._universe:
            self.get_universe()
        return ticker in self._universe

    def _is_cache_valid(self) -> bool:
        """Cache geçerli mi?"""
        if not self.CACHE_FILE.exists():
            return False
        try:
            mtime = datetime.fromtimestamp(self.CACHE_FILE.stat().st_mtime, tz=UTC)
            return (datetime.now(UTC) - mtime) < timedelta(hours=self.CACHE_TTL_HOURS)
        except Exception:
            return False

    def _load_from_cache(self) -> Any:
        """Cache'den yükle."""
        try:
            with open(self.CACHE_FILE, encoding="utf-8") as f:
                data = orjson.loads(f.read())
            self._universe = {}
            for ticker, info_dict in data.get("universe", {}).items():
                self._universe[ticker] = StockInfo(**info_dict)
            self._indices = data.get("indices", self._indices)
        except Exception as e:
            logger.debug("Cache load failed", error=str(e))

    def _save_to_cache(self) -> Any:
        """Cache'e kaydet."""
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "universe": {t: asdict(info) for t, info in self._universe.items()},
                "indices": self._indices,
                "saved_at": datetime.now(UTC).isoformat(),
                "total_count": len(self._universe),
            }
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        except Exception as e:
            logger.debug("Cache save failed", error=str(e))


# Singleton
universe_updater = UniverseAutoUpdater()


def get_current_universe() -> dict[str, StockInfo]:
    """Otomatik eklendi."""
    return universe_updater.get_universe()


def get_bist_100() -> list[str]:
    """Otomatik eklendi."""
    return universe_updater.get_index_members("XU100")


def get_bist_30() -> list[str]:
    """Otomatik eklendi."""
    return universe_updater.get_index_members("XU030")


def get_bist_50() -> list[str]:
    """Otomatik eklendi."""
    return universe_updater.get_index_members("XU050")


def get_all_tickers() -> list[str]:
    """Otomatik eklendi."""
    return list(universe_updater.get_universe().keys())


def get_sector(ticker: str) -> str:
    """Otomatik eklendi."""
    universe = universe_updater.get_universe()
    info = universe.get(ticker)
    return info.sector if info else "DIGER"
