"""
ALPHA BIST — BIST Universe v3.0

TÜM BIST hisseleri + sektör bilgileri.
BIST 100, BIST 30, BIST 50, BIST TÜM (tüm hisseler).
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


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
    """BIST hisse evreni — TÜM hisseler."""

    # BIST 100 (BIST TÜM'den en likit 100 hisse)
    BIST_100_TICKERS: List[str] = [
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

    # BIST 30 (en likit 30 hisse)
    BIST_30_TICKERS: List[str] = [
        "AKBNK", "ALARK", "ARCLK", "ASELS", "BIMAS", "EKGYO", "ENKAI", "EREGL", "FROTO",
        "GARAN", "GUBRF", "HALKB", "HEKTS", "ISCTR", "KCHOL", "KOZAA", "KOZAL", "KRDMD",
        "ODAS", "OTKAR", "PETKM", "PGSUS", "SAHOL", "SASA", "SISE", "TAVHL", "TCELL",
        "THYAO", "TKFEN", "TOASO", "TUPRS", "VAKBN", "YKBNK",
    ]

    # BIST 50
    BIST_50_TICKERS: List[str] = BIST_30_TICKERS + [
        "AGHOL", "AKSA", "AKSEN", "ASTOR", "BERA", "BRSAN", "CCOLA", "CIMSA", "DOAS",
        "ECILC", "EGEEN", "ENJSA", "EUPWR", "GENIL", "GESAN", "GLYHO", "GOLTS", "GRTRK",
        "IMASM", "INDES", "IPEKE", "ISGYO", "ISMEN", "IZENR", "KCAER", "KLSER", "KMPUR",
        "KONTR", "KONYA", "KTLEV", "MAVI", "MGROS", "NTHOL", "OYAKC", "PENTA", "QUAGR",
        "SKBNK", "SMRTG", "SNGYO", "SOKM", "TSKB", "TTKOM", "TTRAK", "ULKER", "VESBE", "VESTL",
    ]

    # BIST TÜM — TÜM BIST hisseleri (yaklaşık 450+ hisse)
    # Bu liste periyodik olarak güncellenmeli
    BIST_ALL_TICKERS: List[str] = BIST_100_TICKERS + [
        # BIST 100 dışı kalan diğer hisseler (örnek liste, gerçek veri ile güncellenmeli)
        "A1CAP", "ACSEL", "ADEL", "ADESE", "AFYON", "AHGAZ", "AKCNS", "AKENR", "AKFGY", "AKGRT",
        "AKMGY", "AKSGY", "AKSUE", "AKYHO", "ALCAR", "ALCTL", "ALKA", "ALKIM", "ALMAD", "ANELE",
        "ANHYT", "ANSGR", "ARASE", "ARDYZ", "ARENA", "ARMDA", "ARSAN", "ARTMS", "ASGYO", "ATAGY",
        "ATATP", "ATEKS", "ATSYH", "AVGYO", "AVHOL", "AVOD", "AVPGY", "AYCES", "AYEN", "AYGAZ",
        "AZTEK", "BAGFS", "BAKAB", "BALAT", "BANVT", "BASCM", "BEYAZ", "BFREN", "BIEHL", "BIOEN",
        "BIZIM", "BJKAS", "BLCYT", "BMSCH", "BMSTL", "BNTAS", "BOSSA", "BRISA", "BRKO", "BRKSN",
        "BRLSM", "BRMEN", "BSOKE", "BUCIM", "BURCE", "BURVA", "BYDNR", "CASA", "CCOLA", "CELHA",
        "CEMAS", "CEMTS", "CLEBI", "CMBTN", "CMENT", "CONSE", "COSMO", "CRDFA", "CRFSA", "CUSAN",
        "DAGHL", "DAGI", "DAPGM", "DARDL", "DENGE", "DERHL", "DERIM", "DESA", "DESPC", "DEVA",
        "DGATE", "DGGYO", "DIRIT", "DITAS", "DJIST", "DMSAS", "DNISI", "DOBUR", "DOCO", "DOGUB",
        "DOHOL", "DURDO", "DYOBY", "DZGYO", "ECZYT", "EDATA", "EDIP", "EFORC", "EGEPO", "EGGUB",
        "EGPRO", "EGSER", "EKSUN", "ELITE", "EMKEL", "EMNIS", "ENJSA", "ENSRI", "EPLAS", "ERBOS",
        "ERCB", "EREGL", "ERSU", "ESCOM", "ETILR", "ETYAT", "EUHOL", "EUKYO", "EUYO", "FADE",
        "FENER", "FLAP", "FMIZP", "FONET", "FORMT", "FRIGO", "FROTO", "GARAN", "GEDIK", "GENTS",
        "GEREL", "GLBMD", "GLRYH", "GMTAS", "GOLTS", "GOODY", "GRSEL", "GSDDE", "GSDHO", "GSRAY",
        "GUBRF", "HALK", "HATEK", "HDFGS", "HEKTS", "HLGYO", "HUBVC", "HUNER", "HURGZ", "ICBCT",
        "IDEAS", "IDGYO", "IEYHO", "IHAAS", "IHGZT", "IHLAS", "IHLGM", "IHYAY", "INDES", "INFO",
        "INTEM", "INVEO", "INVES", "IPEKE", "ISATR", "ISBIR", "ISBTR", "ISCAM", "ISDMR", "ISFIN",
        "ISGSY", "ISGYO", "ISCTR", "ISKPL", "ISKUR", "ISMEN", "ISSEN", "ISYAT", "IZFAS", "IZMDC",
        "JANTS", "KAPLM", "KARYE", "KATMR", "KAYSE", "KBORU", "KCAER", "KCHOL", "KENT", "KERVN",
        "KERVT", "KFEIN", "KLGYO", "KLKIM", "KLNMA", "KLRHO", "KLSER", "KMPUR", "KNFRT", "KONKA",
        "KONTR", "KONYA", "KOPOL", "KORDS", "KOTON", "KOYCE", "KRDMA", "KRDMB", "KRDMD", "KRONT",
        "KRSAN", "KRSTL", "KRVGD", "KSTUR", "KTLEV", "KTSKR", "KUTPO", "KUYAS", "LIDER", "LKMNH",
        "LOGO", "LUKSK", "MAALT", "MACKO", "MACOZ", "MAGEN", "MAKTK", "MANAS", "MARKA", "MARTI",
        "MAVI", "MEDTR", "MEGAP", "MEGMT", "MEKAG", "MEPET", "MERCN", "MERIT", "MERKO", "METRO",
        "METUR", "MGROS", "MIATK", "MMCAS", "MNDRS", "MNDTR", "MOBTL", "MPARK", "MRGYO", "MRSHL",
        "MSGYO", "MTRKS", "MTRYO", "MZHLD", "NATEN", "NETAS", "NIBAS", "NTGAZ", "NTHOL", "NUGYO",
        "NUHCM", "OBASE", "ODAS", "OFSYM", "ONCSM", "ORCAY", "ORGE", "ORMA", "OSMEN", "OSTIM",
        "OTKAR", "OYAKC", "OYAYO", "OYLUM", "OZBAL", "OZGYO", "OZKGY", "OZRDN", "PAGYO", "PARSN",
        "PASEU", "PCILT", "PEGYO", "PEKGY", "PENGD", "PENTA", "PETKM", "PETUN", "PGSUS", "PINSU",
        "PKART", "PKENT", "PNSUT", "POLHO", "POLTK", "PRDGS", "PRKAB", "PRKME", "PRZMA", "PSDTC",
        "QNBFB", "QNBFL", "QUAGR", "RALYH", "RAYSG", "RHEAG", "RODRG", "RTALB", "RUBNS", "RYGYO",
        "RYSAS", "SAFKR", "SAHOL", "SAMAT", "SANEL", "SANFM", "SANKO", "SARKY", "SASA", "SAYAS",
        "SDTTR", "SEGYO", "SEKFK", "SEKUR", "SELEC", "SELGD", "SERVE", "SEYKM", "SILVR", "SINAI",
        "SISE", "SKBNK", "SKTAS", "SMART", "SMRTG", "SNGYO", "SNKRN", "SNPAM", "SODA", "SODSN",
        "SOKE", "SOKM", "SONME", "SRVGY", "SUMAS", "SUNTK", "SURGY", "TATGD", "TAVHL", "TBORG",
        "TCELL", "TDGYO", "TEKTU", "TERA", "TETMT", "TEZOL", "TGSAS", "THYAO", "TKFEN", "TKNSA",
        "TLMAN", "TMPOL", "TMSN", "TOASO", "TRCAS", "TRGYO", "TRILC", "TSKB", "TSPOR", "TTKOM",
        "TTRAK", "TUCLK", "TUKAS", "TUPRS", "TURGG", "TURSG", "UFUK", "ULAS", "ULKER", "ULUFA",
        "ULUSE", "UMPAS", "UNYEC", "USAK", "UTPYA", "UZERB", "VAKBN", "VAKFN", "VAKKO", "VANGD",
        "VBTYZ", "VERTU", "VERUS", "VESBE", "VESTL", "VKFYO", "VKGYO", "VKING", "YAPRK", "YATAS",
        "YAYLA", "YBTAS", "YESIL", "YGGYO", "YGYO", "YKBNK", "YKSLN", "YONGA", "YUNSA", "YYLGD",
        "ZEDUR", "ZOREN", "ZRGYO",
    ]

    # Tekrarları kaldır
    BIST_ALL_TICKERS = list(dict.fromkeys(BIST_ALL_TICKERS))

    # Sektör haritası (100+ hisse için)
    SECTOR_MAP: Dict[str, str] = {
        # Bankacılık
        "AKBNK": "BANKACILIK", "ALBRK": "BANKACILIK", "GARAN": "BANKACILIK",
        "HALKB": "BANKACILIK", "ISCTR": "BANKACILIK", "SKBNK": "BANKACILIK",
        "TSKB": "BANKACILIK", "VAKBN": "BANKACILIK", "YKBNK": "BANKACILIK",
        # Havacılık
        "PGSUS": "HAVACILIK", "THYAO": "HAVACILIK",
        # Otomotiv
        "DOAS": "OTOMOTIV", "FROTO": "OTOMOTIV", "KARSN": "OTOMOTIV",
        "OTKAR": "OTOMOTIV", "TOASO": "OTOMOTIV", "TTRAK": "OTOMOTIV",
        # Perakende
        "BIMAS": "PERAKENDE", "MAVI": "PERAKENDE", "MGROS": "PERAKENDE",
        "SOKM": "PERAKENDE", "ULKER": "PERAKENDE",
        # Teknoloji
        "ARDYZ": "TEKNOLOJI", "FONET": "TEKNOLOJI", "INFO": "TEKNOLOJI",
        "LOGO": "TEKNOLOJI", "MIATK": "TEKNOLOJI", "NETAS": "TEKNOLOJI",
        # Savunma
        "ASELS": "SAVUNMA",
        # Enerji
        "AKSEN": "ENERJI", "ENJSA": "ENERJI", "EUPWR": "ENERJI",
        "ODAS": "ENERJI", "ZOREN": "ENERJI",
        # İnşaat
        "ENKAI": "INSAAT", "EKGYO": "INSAAT", "ISGYO": "INSAAT",
        "NTHOL": "INSAAT", "SNGYO": "INSAAT", "TKFEN": "INSAAT",
        # Demir-Çelik
        "EREGL": "DEMIR_CELIK", "KRDMD": "DEMIR_CELIK",
        # Kimya
        "AKSA": "KIMYA", "PETKM": "KIMYA", "SASA": "KIMYA", "TUPRS": "KIMYA",
        # Cam
        "SISE": "CAM",
        # Tekstil
        "KONTR": "TEKSTIL", "KONYA": "TEKSTIL", "YUNSA": "TEKSTIL",
        # Gıda
        "AEFES": "GIDA", "CIMSA": "GIDA", "CCOLA": "GIDA", "TUKAS": "GIDA",
        # Turizm
        "TAVHL": "TURIZM",
        # Telekom
        "TCELL": "TELEKOM", "TTKOM": "TELEKOM",
        # Holding
        "AGHOL": "HOLDING", "ALARK": "HOLDING", "BERA": "HOLDING",
        "DOHOL": "HOLDING", "GLYHO": "HOLDING", "KCHOL": "HOLDING",
        "SAHOL": "HOLDING",
        # Sağlık
        "ECZYT": "SAGLIK", "MPARK": "SAGLIK",
        # Maden
        "KOZAA": "MADEN", "KOZAL": "MADEN",
        # Diğer
        "XU100": "BENCHMARK",
    }

    def __init__(self):
        self.logger = structlog.get_logger()
        self.logger.info("BISTUniverse initialized",
                        bist_100=len(self.BIST_100_TICKERS),
                        bist_all=len(self.BIST_ALL_TICKERS))

    def get_ticker_sector(self, ticker: str) -> str:
        """Hissenin sektörünü döndür."""
        return self.SECTOR_MAP.get(ticker, "DIGER")

    def get_tickers_by_sector(self, sector: str) -> List[str]:
        """Sektöre göre hisseleri getir."""
        return [t for t, s in self.SECTOR_MAP.items() if s == sector]

    def get_index_members(self, index: str = "XU100") -> List[str]:
        """Endeks üyelerini getir."""
        if index == "XU100":
            return self.BIST_100_TICKERS
        elif index == "XU030":
            return self.BIST_30_TICKERS
        elif index == "XU050":
            return self.BIST_50_TICKERS
        elif index == "ALL":
            return self.BIST_ALL_TICKERS
        return []

    def is_active(self, ticker: str) -> bool:
        """Hisse aktif mi?"""
        return ticker in self.BIST_ALL_TICKERS

    def get_all_sectors(self) -> List[str]:
        """Tüm sektörleri getir."""
        return sorted(list(set(self.SECTOR_MAP.values())))

    def get_sector_stats(self) -> Dict[str, int]:
        """Sektör bazlı istatistikler."""
        stats = {}
        for ticker, sector in self.SECTOR_MAP.items():
            stats[sector] = stats.get(sector, 0) + 1
        return stats


# Module-level helper functions for backward compatibility
def get_sector(ticker: str) -> str:
    """Hissenin sektörünü bul."""
    universe = BISTUniverse()
    return universe.get_ticker_sector(ticker)

BIST_STOCKS = BISTUniverse.BIST_100_TICKERS
BIST_INDICES = ["XU100", "XU030", "XU050"]

# Singleton
bist_universe = BISTUniverse()
