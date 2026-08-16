"""
ALPHA BIST — BIST Universe v4.0 (Auto-Discovery)

TÜM BIST hisseleri + sektör bilgileri — OTOMATIK KEŞIF.
BIST 100, BIST 30, BIST 50, BIST TUM (tum hisseler).

v4.0 Degisiklikler:
- KAP + yfinance + Borsa Istanbul web'den otomatik hisse keşfi
- Endeks kompozisyonlari otomatik guncelleme
- Sektör haritasi otomatik eslestirme
- Cache + periyodik refresh
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

# Auto-discovery provider'ı lazy import et (circular dependency önleme)
_universe_updater = None

def _get_updater():
    global _universe_updater
    if _universe_updater is None:
        try:
            from .providers.universe_provider import UniverseAutoUpdater
            _universe_updater = UniverseAutoUpdater()
        except ImportError:
            logger.warning("UniverseAutoUpdater not available, using static fallback")
            _universe_updater = None
    return _universe_updater


@dataclass
class TickerInfo:
    """Hisse bilgisi."""
    ticker: str
    name: str
    sector: str
    sub_sector: str
    index_membership: List[str]  # XU100, XU030, vs.
    market_cap: float = 0.0
    is_active: bool = True


class BISTUniverse:
    """BIST hisse evreni — OTOMATIK KEŞIF + static fallback."""

    # Static fallback listeler (auto-discovery başarisiz olursa)
    _STATIC_BIST_100_TICKERS: List[str] = [
        "AEFES", "AGHOL", "AKBNK", "AKFGY", "AKFYE", "AKSA", "AKSEN", "ALARK", "ALBRK", "ALFAS",
        "ALTNY", "ANELE", "ARCLK", "ASELS", "ASTOR", "BERA", "BIMAS", "BRSAN", "BRYAT", "BTCIM",
        "CANTE", "CCOLA", "CIMSA", "DOAS", "DOHOL", "ECILC", "ECZYT", "EGEEN", "EKGYO", "ENJSA",
        "ENKAI", "EREGL", "EUPWR", "FROTO", "GARAN", "GENIL", "GESAN", "GLYHO", "GOLTS", "GOODY",
        "GRTRK", "GSDHO", "GUBRF", "HALKB", "HEKTS", "IMASM", "INDES", "IPEKE", "ISCTR", "ISGYO",
        "ISMEN", "IZENR", "IZMDC", "KARSN", "KCAER", "KCHOL", "KLSER", "KMPUR", "KONTR", "KONYA",
        "KOZAA", "KOZAL", "KRDMD", "KTLEV", "LIDER", "MAVI", "MGROS", "MIATK", "NTHOL", "ODAS",
        "OTKAR", "OYAKC", "PENTA", "PETKM", "PGSUS", "QUAGR", "SAHOL", "SASA", "SISE", "SKBNK",
        "SMRTG", "SNGYO", "SOKM", "TAVHL", "TCELL", "THYAO", "TKFEN", "TOASO", "TSKB", "TTKOM",
        "TTRAK", "TUKAS", "TUPRS", "ULKER", "VAKBN", "VESBE", "VESTL", "YKBNK", "YYLGD", "ZOREN",
    ]

    _STATIC_BIST_30_TICKERS: List[str] = [
        "AKBNK", "ALARK", "ARCLK", "ASELS", "BIMAS", "EKGYO", "ENKAI", "EREGL", "FROTO",
        "GARAN", "GUBRF", "HALKB", "HEKTS", "ISCTR", "KCHOL", "KOZAA", "KOZAL", "KRDMD",
        "ODAS", "OTKAR", "PETKM", "PGSUS", "SAHOL", "SASA", "SISE", "TAVHL", "TCELL",
        "THYAO", "TKFEN", "TOASO", "TUPRS", "VAKBN", "YKBNK",
    ]

    _STATIC_BIST_50_TICKERS: List[str] = _STATIC_BIST_30_TICKERS + [
        "AGHOL", "AKSA", "AKSEN", "ASTOR", "BERA", "BRSAN", "CCOLA", "CIMSA", "DOAS",
        "ECILC", "EGEEN", "ENJSA", "EUPWR", "GENIL", "GESAN", "GLYHO", "GOLTS", "GRTRK",
        "IMASM", "INDES", "IPEKE", "ISGYO", "ISMEN", "IZENR", "KCAER", "KLSER", "KMPUR",
        "KONTR", "KONYA", "KTLEV", "MAVI", "MGROS", "NTHOL", "OYAKC", "PENTA", "QUAGR",
        "SKBNK", "SMRTG", "SNGYO", "SOKM", "TSKB", "TTKOM", "TTRAK", "ULKER", "VESBE", "VESTL",
    ]

    _STATIC_BIST_ALL_TICKERS: List[str] = _STATIC_BIST_100_TICKERS + [
        "A1CAP", "ACSEL", "ADEL", "ADESE", "AFYON", "AHGAZ", "AKCNS", "AKENR", "AKGRT",
        "AKMGY", "AKSGY", "AKSUE", "AKYHO", "ALCAR", "ALCTL", "ALKA", "ALKIM", "ALMAD",
        "ANHYT", "ANSGR", "ARASE", "ARDYZ", "ARENA", "ARMDA", "ARSAN", "ARTMS", "ASGYO",
        "ATAGY", "ATATP", "ATEKS", "ATSYH", "AVGYO", "AVHOL", "AVOD", "AVPGY", "AYCES",
        "AYEN", "AYGAZ", "AZTEK", "BAGFS", "BAKAB", "BALAT", "BANVT", "BASCM", "BEYAZ",
        "BFREN", "BIEHL", "BIOEN", "BIZIM", "BJKAS", "BLCYT", "BMSCH", "BMSTL", "BNTAS",
        "BOSSA", "BRISA", "BRKO", "BRKSN", "BRLSM", "BRMEN", "BSOKE", "BUCIM", "BURCE",
        "BURVA", "BYDNR", "CASA", "CELHA", "CEMAS", "CEMTS", "CLEBI", "CMBTN", "CMENT",
        "CONSE", "COSMO", "CRDFA", "CRFSA", "CUSAN", "DAGHL", "DAGI", "DAPGM", "DARDL",
        "DENGE", "DERHL", "DERIM", "DESA", "DESPC", "DEVA", "DGATE", "DGGYO", "DIRIT",
        "DITAS", "DJIST", "DMSAS", "DNISI", "DOBUR", "DOCO", "DOGUB", "DURDO", "DYOBY",
        "DZGYO", "EDATA", "EDIP", "EFORC", "EGEPO", "EGGUB", "EGPRO", "EGSER", "EKSUN",
        "ELITE", "EMKEL", "EMNIS", "ENSRI", "EPLAS", "ERBOS", "ERCB", "ERSU", "ESCOM",
        "ETILR", "ETYAT", "EUHOL", "EUKYO", "EUYO", "FADE", "FENER", "FLAP", "FMIZP",
        "FORMT", "FRIGO", "GEDIK", "GENTS", "GEREL", "GLBMD", "GLRYH", "GMTAS", "GRSEL",
        "GSDDE", "GSRAY", "HALK", "HATEK", "HDFGS", "HLGYO", "HUBVC", "HUNER", "HURGZ",
        "ICBCT", "IDEAS", "IDGYO", "IEYHO", "IHAAS", "IHGZT", "IHLAS", "IHLGM", "IHYAY",
        "INTEM", "INVEO", "INVES", "ISATR", "ISBIR", "ISBTR", "ISCAM", "ISDMR", "ISFIN",
        "ISGSY", "ISKPL", "ISKUR", "ISSEN", "ISYAT", "IZFAS", "JANTS", "KAPLM", "KARYE",
        "KATMR", "KAYSE", "KBORU", "KENT", "KERVN", "KERVT", "KFEIN", "KLGYO", "KLKIM",
        "KLNMA", "KLRHO", "KNFRT", "KONKA", "KOPOL", "KORDS", "KOTON", "KOYCE", "KRDMA",
        "KRDMB", "KRONT", "KRSAN", "KRSTL", "KRVGD", "KSTUR", "KTSKR", "KUTPO", "KUYAS",
        "LKMNH", "LOGO", "LUKSK", "MAALT", "MACKO", "MACOZ", "MAGEN", "MAKTK", "MANAS",
        "MARKA", "MARTI", "MEDTR", "MEGAP", "MEGMT", "MEKAG", "MEPET", "MERCN", "MERIT",
        "MERKO", "METRO", "METUR", "MMCAS", "MNDRS", "MNDTR", "MOBTL", "MRGYO", "MRSHL",
        "MSGYO", "MTRKS", "MTRYO", "MZHLD", "NATEN", "NIBAS", "NTGAZ", "NUGYO", "NUHCM",
        "OBASE", "OFSYM", "ONCSM", "ORCAY", "ORGE", "ORMA", "OSMEN", "OSTIM", "OYAYO",
        "OYLUM", "OZBAL", "OZGYO", "OZKGY", "OZRDN", "PAGYO", "PARSN", "PASEU", "PCILT",
        "PEGYO", "PEKGY", "PENGD", "PETUN", "PINSU", "PKART", "PKENT", "PNSUT", "POLHO",
        "POLTK", "PRDGS", "PRKAB", "PRKME", "PRZMA", "PSDTC", "QNBFB", "QNBFL", "RALYH",
        "RAYSG", "RHEAG", "RODRG", "RTALB", "RUBNS", "RYGYO", "RYSAS", "SAFKR", "SAMAT",
        "SANEL", "SANFM", "SANKO", "SARKY", "SAYAS", "SDTTR", "SEGYO", "SEKFK", "SEKUR",
        "SELEC", "SELGD", "SERVE", "SEYKM", "SILVR", "SINAI", "SKTAS", "SMART", "SNKRN",
        "SNPAM", "SODA", "SODSN", "SOKE", "SONME", "SRVGY", "SUMAS", "SUNTK", "SURGY",
        "TATGD", "TBORG", "TDGYO", "TEKTU", "TERA", "TETMT", "TEZOL", "TGSAS", "TKNSA",
        "TLMAN", "TMPOL", "TMSN", "TRCAS", "TRGYO", "TRILC", "TSPOR", "TUCLK", "TURGG",
        "TURSG", "UFUK", "ULAS", "ULUFA", "ULUSE", "UMPAS", "UNYEC", "USAK", "UTPYA",
        "UZERB", "VAKFN", "VAKKO", "VANGD", "VBTYZ", "VERTU", "VERUS", "VKFYO", "VKGYO",
        "VKING", "YAPRK", "YATAS", "YAYLA", "YBTAS", "YESIL", "YGGYO", "YGYO", "YKSLN",
        "YONGA", "ZEDUR", "ZRGYO",
    ]

    _STATIC_SECTOR_MAP: Dict[str, str] = {
        "AKBNK": "BANKACILIK", "ALBRK": "BANKACILIK", "GARAN": "BANKACILIK",
        "HALKB": "BANKACILIK", "ISCTR": "BANKACILIK", "SKBNK": "BANKACILIK",
        "TSKB": "BANKACILIK", "VAKBN": "BANKACILIK", "YKBNK": "BANKACILIK",
        "PGSUS": "HAVACILIK", "THYAO": "HAVACILIK",
        "DOAS": "OTOMOTIV", "FROTO": "OTOMOTIV", "KARSN": "OTOMOTIV",
        "OTKAR": "OTOMOTIV", "TOASO": "OTOMOTIV", "TTRAK": "OTOMOTIV",
        "BIMAS": "PERAKENDE", "MAVI": "PERAKENDE", "MGROS": "PERAKENDE",
        "SOKM": "PERAKENDE", "ULKER": "PERAKENDE",
        "ARDYZ": "TEKNOLOJI", "FONET": "TEKNOLOJI", "INFO": "TEKNOLOJI",
        "LOGO": "TEKNOLOJI", "MIATK": "TEKNOLOJI", "NETAS": "TEKNOLOJI",
        "ASELS": "SAVUNMA",
        "AKSEN": "ENERJI", "ENJSA": "ENERJI", "EUPWR": "ENERJI",
        "ODAS": "ENERJI", "ZOREN": "ENERJI",
        "ENKAI": "INSAAT", "EKGYO": "INSAAT", "ISGYO": "INSAAT",
        "NTHOL": "INSAAT", "SNGYO": "INSAAT", "TKFEN": "INSAAT",
        "EREGL": "DEMIR_CELIK", "KRDMD": "DEMIR_CELIK",
        "AKSA": "KIMYA", "PETKM": "KIMYA", "SASA": "KIMYA", "TUPRS": "KIMYA",
        "SISE": "CAM",
        "KONTR": "TEKSTIL", "KONYA": "TEKSTIL", "YUNSA": "TEKSTIL",
        "AEFES": "GIDA", "CIMSA": "GIDA", "CCOLA": "GIDA", "TUKAS": "GIDA",
        "TAVHL": "TURIZM",
        "TCELL": "TELEKOM", "TTKOM": "TELEKOM",
        "AGHOL": "HOLDING", "ALARK": "HOLDING", "BERA": "HOLDING",
        "DOHOL": "HOLDING", "GLYHO": "HOLDING", "KCHOL": "HOLDING",
        "SAHOL": "HOLDING",
        "ECZYT": "SAGLIK", "MPARK": "SAGLIK",
        "KOZAA": "MADEN", "KOZAL": "MADEN",
        "XU100": "BENCHMARK",
    }

    def __init__(self, use_auto_discovery: bool = True):
        self.logger = structlog.get_logger()
        self._use_auto = use_auto_discovery
        self._dynamic_universe: Optional[Dict] = None
        self._dynamic_indices: Dict[str, List[str]] = {}

        if use_auto_discovery:
            self._refresh_dynamic()

        self.logger.info("BISTUniverse initialized",
                        mode="auto" if use_auto_discovery else "static",
                        bist_100=len(self.BIST_100_TICKERS),
                        bist_all=len(self.BIST_ALL_TICKERS))

    def _refresh_dynamic(self):
        """Dinamik evreni yenile."""
        updater = _get_updater()
        if updater:
            try:
                self._dynamic_universe = updater.get_universe()
                self._dynamic_indices = {
                    "XU100": updater.get_index_members("XU100"),
                    "XU030": updater.get_index_members("XU030"),
                    "XU050": updater.get_index_members("XU050"),
                }
            except Exception as e:
                self.logger.warning("Auto-discovery failed, using static fallback", error=str(e))
                self._dynamic_universe = None

    @property
    def BIST_100_TICKERS(self) -> List[str]:
        if self._dynamic_indices.get("XU100"):
            return self._dynamic_indices["XU100"]
        return self._STATIC_BIST_100_TICKERS

    @property
    def BIST_30_TICKERS(self) -> List[str]:
        if self._dynamic_indices.get("XU030"):
            return self._dynamic_indices["XU030"]
        return self._STATIC_BIST_30_TICKERS

    @property
    def BIST_50_TICKERS(self) -> List[str]:
        if self._dynamic_indices.get("XU050"):
            return self._dynamic_indices["XU050"]
        return self._STATIC_BIST_50_TICKERS

    @property
    def BIST_ALL_TICKERS(self) -> List[str]:
        if self._dynamic_universe:
            return list(self._dynamic_universe.keys())
        return self._STATIC_BIST_ALL_TICKERS

    @property
    def SECTOR_MAP(self) -> Dict[str, str]:
        if self._dynamic_universe:
            return {
                t: info.sector for t, info in self._dynamic_universe.items()
            }
        return self._STATIC_SECTOR_MAP

    def get_ticker_sector(self, ticker: str) -> str:
        """Hissenin sektorunu dondur."""
        if self._dynamic_universe and ticker in self._dynamic_universe:
            return self._dynamic_universe[ticker].sector
        return self._STATIC_SECTOR_MAP.get(ticker, "DIGER")

    def get_tickers_by_sector(self, sector: str) -> List[str]:
        """Sektore gore hisseleri getir."""
        if self._dynamic_universe:
            return [
                t for t, info in self._dynamic_universe.items()
                if info.sector == sector.upper()
            ]
        return [t for t, s in self._STATIC_SECTOR_MAP.items() if s == sector]

    def get_index_members(self, index: str = "XU100") -> List[str]:
        """Endeks uyelerini getir."""
        if self._dynamic_indices.get(index):
            return self._dynamic_indices[index]
        if index == "XU100":
            return self._STATIC_BIST_100_TICKERS
        elif index == "XU030":
            return self._STATIC_BIST_30_TICKERS
        elif index == "XU050":
            return self._STATIC_BIST_50_TICKERS
        elif index == "ALL":
            return self.BIST_ALL_TICKERS
        return []

    def is_active(self, ticker: str) -> bool:
        """Hisse aktif mi?"""
        if self._dynamic_universe:
            info = self._dynamic_universe.get(ticker)
            return info is not None and info.listing_status == "ACTIVE"
        return ticker in self._STATIC_BIST_ALL_TICKERS

    def get_all_sectors(self) -> List[str]:
        """Tum sektorleri getir."""
        if self._dynamic_universe:
            sectors = set(info.sector for info in self._dynamic_universe.values())
            return sorted(list(sectors))
        return sorted(list(set(self._STATIC_SECTOR_MAP.values())))

    def get_sector_stats(self) -> Dict[str, int]:
        """Sektor bazli istatistikler."""
        if self._dynamic_universe:
            stats = {}
            for info in self._dynamic_universe.values():
                stats[info.sector] = stats.get(info.sector, 0) + 1
            return stats
        stats = {}
        for ticker, sector in self._STATIC_SECTOR_MAP.items():
            stats[sector] = stats.get(sector, 0) + 1
        return stats

    def refresh(self):
        """Evreni yenile (manuel cagri)."""
        self._refresh_dynamic()

    def get_ticker_info(self, ticker: str) -> Optional[TickerInfo]:
        """Detayli hisse bilgisi dondur."""
        if self._dynamic_universe and ticker in self._dynamic_universe:
            info = self._dynamic_universe[ticker]
            return TickerInfo(
                ticker=info.ticker,
                name=info.name,
                sector=info.sector,
                sub_sector=info.sub_sector,
                index_membership=info.index_membership,
                market_cap=info.market_cap,
                is_active=info.listing_status == "ACTIVE",
            )
        # Static fallback
        if ticker in self._STATIC_BIST_ALL_TICKERS:
            return TickerInfo(
                ticker=ticker,
                name=ticker,
                sector=self._STATIC_SECTOR_MAP.get(ticker, "DIGER"),
                sub_sector="",
                index_membership=[],
            )
        return None


# Module-level helper functions for backward compatibility
def get_sector(ticker: str) -> str:
    """Hissenin sektorunu bul."""
    return bist_universe.get_ticker_sector(ticker)

# Singleton (auto-discovery aktif)
bist_universe = BISTUniverse(use_auto_discovery=True)

# Backward compatibility exports
BIST_STOCKS = bist_universe.BIST_100_TICKERS
BIST_INDICES = {"XU100": "BIST 100", "XU030": "BIST 30", "XU050": "BIST 50"}
