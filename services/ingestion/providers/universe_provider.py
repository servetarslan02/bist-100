"""
ALPHA BIST — BIST Universe Auto-Discovery Provider v2.0
TÜM BIST hisselerini (600+ hisse) ve endeks üyeliklerini dinamik olarak keşfeder ve günceller.
"""

import re
from dataclasses import asdict, dataclass, field
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
    index_membership: list[str] = field(default_factory=list)
    listing_status: str = "ACTIVE"  # ACTIVE, SUSPENDED, DELISTED
    isin: str = ""
    currency: str = "TRY"
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str = ""


class LiveUniverseScraper:
    """Canlı kamu ve finans kaynaklarından tüm BIST hisselerini çeker."""

    def __init__(self, timeout_seconds: float = 15.0):
        """BIST hisse evreni tarayıcısını yapılandır."""
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _get_client(self) -> httpx.Client:
        """Yeni veya havuzlu HTTP client döndür."""
        return httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=True)

    def __repr__(self) -> str:
        return f"<LiveUniverseScraper(primary='tradingview', backups=['mynet', 'bigpara', 'isyatirim'], timeout={self.timeout.read})>"

    def _discover_tradingview(self, client: httpx.Client) -> dict[str, StockInfo]:
        """TradingView Scanner API üzerinden birincil BIST hisse listesini keşfet.

        Args:
            client: Yapılandırılmış httpx.Client bağlantısı.

        Returns:
            dict[str, StockInfo]: TradingView üzerinden çekilen BIST hisseleri.
        """
        discovered: dict[str, StockInfo] = {}
        try:
            url = "https://scanner.tradingview.com/turkey/scan"
            payload = {
                "filter": [],
                "options": {"lang": "tr"},
                "symbols": {"query": {"types": []}},
                "columns": ["name", "description", "close", "market_cap_basic", "sector", "industry"],
                "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
                "range": [0, 1000],
            }
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                rows = data.get("data", [])
                for row in rows:
                    d = row.get("d", [])
                    if len(d) < 2:
                        continue
                    ticker = str(d[0]).split(":")[-1].strip().upper()
                    if not (2 <= len(ticker) <= 6) or ticker.isdigit():
                        continue
                    name = str(d[1]).strip() if d[1] else ticker
                    mcap = float(d[3]) if len(d) > 3 and d[3] is not None else 0.0
                    tv_sector = str(d[4]) if len(d) > 4 and d[4] else ""
                    tv_industry = str(d[5]) if len(d) > 5 and d[5] else ""

                    discovered[ticker] = StockInfo(
                        ticker=ticker,
                        name=name,
                        sector=self._guess_sector(ticker, name, tv_sector, tv_industry),
                        sub_sector=tv_industry,
                        market_cap=mcap,
                        source="tradingview_primary",
                    )
                logger.info("tradingview_primary_universe_discovery_done", count=len(discovered))
        except Exception as e:
            logger.warning("tradingview_discovery_failed", error=str(e))
        return discovered

    def discover_all_bist_stocks(self) -> dict[str, StockInfo]:
        """Tüm kaynakları tarayarak eksiksiz BIST hisse evrenini keşfet.

        ÖNCELİK SIRASI:
        1. BİRİNCİL LİSTE: TradingView Scanner API (Tüm BIST hisseleri tek pakette)
        2. YEDEK LİSTE: Mynet Finans, Bigpara, İş Yatırım (Eksik veya alternatif hisseler için)
        """
        discovered: dict[str, StockInfo] = {}

        with self._get_client() as client:
            # 1. BİRİNCİL KAYNAK: TradingView Scanner API
            tv_stocks = self._discover_tradingview(client)
            if tv_stocks:
                discovered.update(tv_stocks)
                logger.info("tradingview_master_universe_set", count=len(discovered))

            # 2. YEDEK LİSTE 1: Mynet Finans BIST Tam Liste
            try:
                url = "https://finans.mynet.com/borsa/hisseler/"
                resp = client.get(url)
                if resp.status_code == 200:
                    matches = re.findall(r'/borsa/hisseler/([a-z0-9]{3,6})-([^/"]+)/', resp.text)
                    added_count = 0
                    for sym, slug in matches:
                        ticker = sym.upper().strip()
                        if 2 <= len(ticker) <= 6 and not ticker.isdigit() and ticker not in discovered:
                            name = slug.replace("-", " ").title()
                            discovered[ticker] = StockInfo(
                                ticker=ticker,
                                name=name,
                                sector=self._guess_sector(ticker, name),
                                source="mynet_backup",
                            )
                            added_count += 1
                    logger.info("mynet_backup_universe_done", total_discovered=len(discovered), newly_added=added_count)
            except Exception as e:
                logger.debug("mynet_backup_discovery_failed", error=str(e))

            # 3. YEDEK LİSTE 2: Bigpara Canlı Borsa
            try:
                url = "https://bigpara.hurriyet.com.tr/borsa/canli-borsa/"
                resp = client.get(url)
                if resp.status_code == 200:
                    matches = re.findall(r"/borsa/hisse-fiyatlari/([a-z0-9]+)-detay/", resp.text)
                    added_count = 0
                    for sym in matches:
                        ticker = sym.upper().strip()
                        if 2 <= len(ticker) <= 6 and not ticker.isdigit() and ticker not in discovered:
                            discovered[ticker] = StockInfo(
                                ticker=ticker,
                                name=ticker,
                                sector=self._guess_sector(ticker, ticker),
                                source="bigpara_backup",
                            )
                            added_count += 1
                    logger.info("bigpara_backup_universe_done", total_discovered=len(discovered), newly_added=added_count)
            except Exception as e:
                logger.debug("bigpara_backup_discovery_failed", error=str(e))

            # 4. YEDEK LİSTE 3: İş Yatırım
            try:
                url = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx"
                resp = client.get(url)
                if resp.status_code == 200:
                    matches = re.findall(r'value="([A-Z0-9]{3,6})"\s*data-title="([^"]*)"', resp.text)
                    added_count = 0
                    for ticker, name in matches:
                        ticker = ticker.upper().strip()
                        if 2 <= len(ticker) <= 6 and not ticker.isdigit():
                            if ticker not in discovered:
                                discovered[ticker] = StockInfo(
                                    ticker=ticker,
                                    name=name or ticker,
                                    sector=self._guess_sector(ticker, name),
                                    source="isyatirim_backup",
                                )
                                added_count += 1
                            elif name and (discovered[ticker].name == ticker or not discovered[ticker].name):
                                discovered[ticker].name = name
                    logger.info("isyatirim_backup_universe_done", total_discovered=len(discovered), newly_added=added_count)
            except Exception as e:
                logger.debug("isyatirim_backup_discovery_failed", error=str(e))

        return discovered

    def _guess_sector(
        self,
        ticker: str,
        name: str,
        tv_sector: str = "",
        tv_industry: str = "",
    ) -> str:
        """Hisse sembolü, şirket adı veya TradingView sektöründen BIST sektörünü eşle."""
        # 1. TradingView sektör eşlemesi
        if tv_sector:
            sec_map = {
                "Commercial Services": "HIZMET",
                "Communications": "TELEKOM",
                "Consumer Durables": "SANAYI",
                "Consumer Non-Durables": "PERAKENDE",
                "Consumer Services": "HIZMET",
                "Distribution Services": "TICARET",
                "Electronic Technology": "TEKNOLOJI",
                "Energy Minerals": "ENERJI",
                "Finance": "BANKACILIK" if any(w in ticker for w in ["BNK", "ISCTR", "GARAN", "AKBNK", "YKBNK", "HALKB", "VAKBN", "TSKB", "ALBRK"]) else "FINANS",
                "Health Services": "SAGLIK",
                "Health Technology": "SAGLIK",
                "Industrial Services": "SANAYI",
                "Non-Energy Minerals": "MADENCILIK",
                "Process Industries": "KIMYA",
                "Producer Manufacturing": "SANAYI",
                "Retail Trade": "PERAKENDE",
                "Technology Services": "TEKNOLOJI",
                "Transportation": "HAVACILIK" if any(w in ticker for w in ["THYAO", "PGSUS", "TAVHL", "CLEBI"]) else "ULASTIRMA",
                "Utilities": "ENERJI",
            }
            if tv_sector in sec_map:
                return sec_map[tv_sector]

        # 2. Anahtar kelime eşlemesi
        name_u = (name + " " + ticker).upper()
        if any(w in name_u for w in ["BANK", "BANKASI", "GARAN", "AKBNK", "ISCTR", "YKBNK", "HALKB", "VAKBN", "TSKB", "ALBRK", "QNB"]):
            return "BANKACILIK"
        if any(w in name_u for w in ["GYO", "GAYRIMENKUL", "KONUT"]):
            return "GAYRIMENKUL"
        if any(w in name_u for w in ["HAVACILIK", "HAVAYOLLARI", "THYAO", "PGSUS", "TAVHL", "CLEBI"]):
            return "HAVACILIK"
        if any(w in name_u for w in ["SAVUNMA", "ASELS", "SDTTR"]):
            return "SAVUNMA"
        if any(w in name_u for w in ["YAZILIM", "TEKNOLOJI", "BILISIM", "KFEIN", "LOGO", "MIATK", "VBTYZ", "ARDYZ", "FONET", "REEDR", "BINHO"]):
            return "TEKNOLOJI"
        if any(w in name_u for w in ["ENERJI", "ELEKTRIK", "SOLAR", "PETROL", "TUPRS", "ASTOR", "ENJSA", "AKSEN", "EUPWR", "KONTR", "CWENE", "YEOTK"]):
            return "ENERJI"
        if any(w in name_u for w in ["DEMIR", "CELIK", "SANAYI", "EREGL", "KRDMD", "SISE", "ARCLK", "VESTL", "CIMSA", "AKCNS", "BOBET", "KCAER"]):
            return "SANAYI"
        if any(w in name_u for w in ["HOLDING", "YATIRIM", "KCHOL", "SAHOL", "ALARK", "ENKAI", "AGHOL", "DOHOL", "BERA", "TKFEN"]):
            return "HOLDING"
        if any(w in name_u for w in ["GIDA", "MARKET", "PERAKENDE", "BIMAS", "MGROS", "CCOLA", "ULKER", "SOKM", "AEFES", "TATGD"]):
            return "PERAKENDE"
        if any(w in name_u for w in ["OTOMOTIV", "OTO", "FROTO", "TOASO", "TTRAK", "DOAS", "OTKAR", "KARSAN"]):
            return "OTOMOTIV"
        if any(w in name_u for w in ["SIGORTA", "EMEKLI", "ANSGR", "ANHYT", "TURSG", "AGESA"]):
            return "SIGORTA"
        if any(w in name_u for w in ["TELEKOM", "ILETISIM", "TCELL", "TTKOM"]):
            return "TELEKOM"
        if any(w in name_u for w in ["SAGLIK", "ILAC", "HASTANE", "GENIL", "ECILC", "MPARK"]):
            return "SAGLIK"
        if any(w in name_u for w in ["MADEN", "MADENCILIK", "ALTIN", "KOZAL", "KOZAA", "IPEKE"]):
            return "MADENCILIK"
        if any(w in name_u for w in ["KIMYA", "PETKIM", "PETKM", "AKSA", "SASA", "HEKTS", "GUBRF"]):
            return "KIMYA"
        return "DIGER"


class UniverseAutoUpdater:
    """BIST Universe otomatik güncelleme ve yönetim motoru."""

    CACHE_FILE = Path("data/universe_cache.json")
    CACHE_TTL_HOURS = 12

    def __init__(self):
        """BIST hisse evreni otomatik güncelleme motorunu başlat."""
        self.scraper = LiveUniverseScraper()
        self._universe: dict[str, StockInfo] = {}
        self._indices: dict[str, list[str]] = {
            "XU100": [],
            "XU030": [],
            "XU050": [],
        }

    def __repr__(self) -> str:
        return f"<UniverseAutoUpdater(total_stocks={len(self._universe)}, indices={list(self._indices.keys())})>"

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

        # 2. Delisted / erişilemeyen hisseleri filtrele
        self._filter_delisted_tickers()

        # 3. Endeks üyeliklerini oluştur
        self._refresh_index_compositions()

        # 4. Cache'e kaydet
        self._save_to_cache()

        return self._universe

    def _filter_delisted_tickers(self) -> None:
        """TradingView Scanner üzerinden aktif olmayan hisseleri evrenden temizle.

        Mantık:
        - TradingView Scanner tüm aktif BIST hisselerini döndürür (birincil kaynak).
        - TradingView'de görünmeyen ama backup kaynaklardan (Mynet/Bigpara/İsYatirim)
          gelen ticker'lar devre dışı/delisted kabul edilip evrenden çıkarılır.
        - Bu yöntem yfinance'e hiç dokunmaz; tamamen TradingView ekosistemi içinde kalır.
        """
        # Eğer TradingView birincil keşfinden hiç ticker gelmediyse filtre yapma
        tv_tickers: set[str] = {
            t for t, info in self._universe.items()
            if info.source == "tradingview_primary"
        }

        if not tv_tickers:
            logger.info("delisted_filter_skip: TradingView verisi yok, filtre atlanıyor")
            return

        # Backup kaynaklardan gelen ama TradingView'de KESİNLİKLE görünmeyen ticker'lar
        # TradingView, tüm aktif BIST hisselerini döndürür.
        # Burada bulunmayanlar büyük ihtimalle delisted/suspend.
        backup_only: list[str] = [
            t for t, info in self._universe.items()
            if info.source != "tradingview_primary"
        ]

        if not backup_only:
            logger.info("delisted_filter_done: tüm hisseler TradingView doğrulamalı")
            return

        logger.info("delisted_filter_check", backup_only_count=len(backup_only))

        # TradingView Scanner'a tekrar kısa sorgu — backup ticker'ları gerçekten biliyor mu?
        removed: list[str] = []
        try:
            url = "https://scanner.tradingview.com/turkey/scan"
            payload = {
                "filter": [],
                "options": {"lang": "tr"},
                "symbols": {"query": {"types": []}},
                "columns": ["name"],
                "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
                "range": [0, 1500],  # Tüm BIST evrenini al
            }
            with self._get_client() as client:
                resp = client.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                tv_all: set[str] = set()
                for row in data.get("data", []):
                    d = row.get("d", [])
                    if d:
                        raw_sym = str(d[0]).split(":")[-1].strip().upper()
                        tv_all.add(raw_sym)

                # Backup'tan gelen, TradingView'de hiç görünmeyen ticker'lar → sil
                for ticker in backup_only:
                    if ticker not in tv_all:
                        removed.append(ticker)

                logger.info(
                    "tradingview_recheck_done",
                    tv_active_count=len(tv_all),
                    backup_checked=len(backup_only),
                    to_remove=len(removed),
                )
            else:
                logger.warning("delisted_filter_tv_api_error", status=resp.status_code)
        except Exception as e:
            logger.warning("delisted_filter_tv_error", error=str(e))
            return

        for ticker in removed:
            self._universe.pop(ticker, None)

        if removed:
            logger.info("delisted_tickers_removed", count=len(removed), tickers=removed[:20])
        else:
            logger.info("delisted_filter_done_no_removals")



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

    def _save_to_cache(self, force: bool = False) -> Any:
        """Cache'e kaydet (debounced — SSD dostu, zorunlu veya ilk kayıtta anında yazar)."""
        from services.core.debounce import should_save

        if not self._universe:
            return

        # Cache dosyası yoksa veya içi boşsa debounce bekleme, direkt kaydet
        cache_empty = not self.CACHE_FILE.exists() or self.CACHE_FILE.stat().st_size < 100
        if not force and not cache_empty and not should_save("universe_cache", 300):
            return

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
            logger.info("universe_cache_saved", count=len(self._universe), path=str(self.CACHE_FILE))
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
