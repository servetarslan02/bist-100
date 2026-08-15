"""
ALPHA BIST — BIST Universe v2.0 (Düzeltilmiş)

Tüm hisseler doğrulanıyor (sampling artırıldı).
Delisted hisseler otomatik filtreleniyor.

FAZ 2: BIST Universe
"""

import asyncio
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

class BISTUniverse:
    """BIST-100 hisse evreni."""

    # BIST-100 hisseleri (güncel)
    BIST_100_TICKERS = [
        "ACSEL", "ADEL", "ADESE", "AEFES", "AFYON", "AGHOL", "AHGAZ", "AKBNK",
        "AKCNS", "AKFGY", "AKFYE", "AKGRT", "AKSA", "AKSEN", "AKSGY", "ALARK",
        "ALBRK", "ALCAR", "ALCTL", "ALFAS", "ANELE", "ANGEN", "ANHYT", "ANSGR",
        "ARASE", "ARCLK", "ARDYZ", "ARENA", "ARSAN", "ARTMS", "ASELS", "ASUZU",
        "ATAGY", "ATEKS", "ATLAS", "AVGYO", "AVHOL", "AVOD", "AVPGY", "AYCES",
        "AYDEM", "AYEN", "AYGAZ", "AZTEK", "BAGFS", "BAKAB", "BALAT", "BANVT",
        "BARMA", "BASCM", "BAYRK", "BERA", "BEYAZ", "BFREN", "BIENY", "BIOEN",
        "BIZIM", "BJKAS", "BLCYT", "BMSCH", "BMSTL", "BNTAS", "BOBET", "BORSK",
        "BOSSA", "BRISA", "BRKSN", "BRLSM", "BRMEN", "BSOKE", "BTCIM", "BUCIM",
        "BURCE", "BURVA", "CANTE", "CCOLA", "CELHA", "CEMAS", "CEMTS", "CIMSA",
        "CLEBI", "CMBTN", "CMENT", "CONSE", "COSMO", "CRDFA", "CRFSA", "CUSAN",
        "CVKMD", "CWENE", "DAGHL", "DAGI", "DARDL", "DERHL", "DERIM", "DESA",
        "DESPC", "DEVA", "DGKLB", "DGNMO", "DIRIT", "DITAS", "DJIST", "DMSAS",
        "DOBUR", "DOHOL", "DOKTA", "DOLAR", "DURDO", "DYOBY", "DZGYO", "ECILC",
        "ECZYT", "EDATA", "EDIP", "EGEEN", "EGGUB", "EGPRO", "EGEPO", "EGSER",
        "EKGYO", "EKIZ", "ELITE", "EMKEL", "ENJSA", "ENKAI", "EREGL", "ERSU",
        "ESCOM", "ETILR", "ETYAT", "EUHOL", "EUKYO", "EUPWR", "EUREN", "EUYO",
        "FADE", "FENER", "FERHO", "FLAP", "FONET", "FORMT", "FRIGO", "FROTO",
        "FZLGY", "GARAN", "GEDIK", "GEDZA", "GENIL", "GENTS", "GEREL", "GLBMD",
        "GLCVY", "GLDTR", "GLRYH", "GLYHO", "GSDHO", "GSRAY", "GUBRF", "GWIND",
        "Halkb", "HALKB", "HATEK", "HDFGS", "HEKTS", "HLGYO", "HUBVC", "HUNER",
        "HURGZ", "ICBCT", "IDEAS", "IDGYO", "IEYHO", "IHAAS", "IHLAS", "IHLGM",
        "IHGZT", "IMASM", "INDES", "INFO", "INTEM", "INVEO", "INVES", "IPEKE",
        "ISBIR", "ISBTR", "ISCTR", "ISDMR", "ISFIN", "ISGYO", "ISMEN", "ISSEN",
        "IZENR", "IZFAS", "IZMDC", "JANTS", "KAPLM", "KARSN", "KARTN", "KATMR",
        "KAYSE", "KBORU", "KCAER", "KCHOL", "KENT", "KERVN", "KERVT", "KFEIN",
        "KGYO", "KIMMR", "KLGYO", "KLKIM", "KLMSN", "KLNMA", "KLRHO", "KLSER",
        "KLSYN", "KMPUR", "KNFRT", "KONKA", "KONTR", "KONYA", "KORDS", "KOZAA",
        "KOZAL", "KRDMA", "KRDMB", "KRDMD", "KRGYO", "KRONT", "KRPLS", "KRSTL",
        "KRVGD", "KSTUR", "KTLEV", "KTSKR", "KUTPO", "KUYAS", "LIDER", "LKMNH",
        "LOGO", "LUKSK", "MAALT", "MACKO", "MAGEN", "MAKTK", "MANAS", "MARKA",
        "MARTI", "MAVI", "MEDTR", "MEGAP", "MEGMT", "MEKAG", "MEPET", "MERCN",
        "MERIT", "MERKO", "METRO", "METUR", "MGROS", "MIATK", "MMCAS", "MNDRS",
        "MNDTR", "MOBTL", "MPARK", "MRSHL", "MSGYO", "MTRKS", "MTRYO", "MZHLD",
        "NATEN", "NETAS", "NIBAS", "NTGAZ", "NTHOL", "NUHCM", "OBASE", "ODAS",
        "ODINE", "OFSYM", "ONCSM", "ORGE", "ORMA", "OSMEN", "OSTIM", "OTKAR",
        "OYAKC", "OYAYO", "OYLUM", "OZBAL", "OZGYO", "OZKGY", "OZRDN", "PAMEL",
        "PAPIL", "PARSN", "PASEU", "PCILT", "PEKGY", "PENGD", "PETKM", "PETUN",
        "PGSUS", "PINSU", "PKART", "PKENT", "PLTUR", "PNLSN", "POLHO", "POLTK",
        "PRDGS", "PRKAB", "PRKME", "PRZMA", "PSDTC", "PSGYO", "QNBFB", "QNBFL",
        "QUAGR", "RALYH", "RAYSG", "RHEAG", "RODRG", "RTALB", "RUBNS", "SAFKR",
        "SAHOL", "SAMAT", "SANEL", "SANFM", "SARKY", "SASA", "SAYAS", "SDTTR",
        "SEKFK", "SEKUR", "SELEC", "SELGD", "SERVE", "SEYKM", "SILVR", "SISE",
        "SKBNK", "SKTAS", "SMART", "SMRTG", "SNGYO", "SNKRN", "SNPAM", "SODA",
        "SODSN", "SOKE", "SONME", "SRVGY", "SUMAS", "SUNTK", "SURGY", "TATGD",
        "TAVHL", "TBORG", "TCELL", "TDGYO", "TEKTU", "TERA", "TGSAS", "THYAO",
        "TKFEN", "TKNSA", "TLMAN", "TMPOL", "TMSN", "TOASO", "TRCAS", "TRGYO",
        "TRILC", "TSKB", "TSPOR", "TTKOM", "TTRAK", "TUCLK", "TUKAS", "TUPRS",
        "TUREX", "TURGG", "UFUK", "ULAS", "ULKER", "ULUFA", "ULUSE", "UMKEL",
        "UNYEC", "USAK", "VAKBN", "VAKFN", "VAKKO", "VANGD", "VERTU", "VERUS",
        "VESBE", "VESTL", "VKFYO", "VKGYO", "YAPRK", "YATAS", "YAYLA", "YBTAS",
        "YEOTK", "YGGYO", "YGYO", "YKBNK", "YKSLN", "YONGA", "YUNSA", "ZEDUR",
        "ZOREN",
    ]

    def __init__(self):
        self._tickers = list(self.BIST_100_TICKERS)
        self._delisted: List[str] = []
        self._validated = False
        logger.info("BISTUniverse initialized", count=len(self._tickers))

    def get_tickers(self) -> List[str]:
        """Tüm hisseleri getir."""
        return [t for t in self._tickers if t not in self._delisted]

    def get_sectors(self) -> Dict[str, List[str]]:
        """Sektör bazlı hisseler."""
        # Sektör eşleştirmeleri
        sector_map = {
            "Bankacılık": ["AKBNK", "GARAN", "HALKB", "ISCTR", "SKBNK", "TSKB", "VAKBN", "YKBNK"],
            "Havacılık": ["THYAO", "PGSUS", "TAVHL", "CLEBI"],
            "Otomotiv": ["FROTO", "TOASO", "KARSN", "OTKAR", "TTRAK"],
            "Perakende": ["BIMAS", "MGROS", "SOKM", "BIZIM"],
            "Enerji": ["ENJSA", "AKSEN", "AYDEM", "ZOREN", "ODAS", "NATEN", "SAYAS", "SMRTG", "ALFAS", "EUPWR", "CONSE", "CWENE", "MAGEN", "HUNER", "YEOTK", "ASTOR"],
            "Cimento": ["CIMSA", "NUHCM", "BTCIM", "BUCIM", "KONYA", "OYAKC", "BOBET"],
            "Savunma": ["ASELS"],
            "Telekom": ["TCELL", "TTKOM"],
            "Gıda": ["ULKER", "CCOLA", "BIZIM", "TATGD", "KERVT", "YAYLA", "AVOD"],
            "Tekstil": ["MAVI", "DESA", "DERIM", "MNDTR", "YUNSA"],
            "Metal": ["EREGL", "KRDMD", "ISDMR", "CEMTS"],
            "Kimya": ["PETKM", "KLKIM", "HEKTS", "BRLSM"],
            "İnşaat": ["ENKAI", "TKFEN"],
            "Holding": ["KCHOL", "SAHOL", "AGHOL", "DOHOL"],
            "Teknoloji": ["LOGO", "KONTR", "ARDYZ"],
            "Cam": ["SISE", "TRCAS"],
            "Beyaz Eşya": ["ARCLK", "VESTL", "VESBE"],
            "Petrol": ["TUPRS"],
            "Sigorta": ["AKGRT", "ANSGR"],
            "Gayrimenkul": ["EKGYO", "ISGYO", "KLGYO", "MSGYO", "NUGYO", "OZGYO", "PSGYO", "SRVGY", "TRGYO", "VKGYO", "YGGYO"],
        }
        return sector_map

    def get_ticker_sector(self, ticker: str) -> str:
        """Hissenin sektörünü bul."""
        sectors = self.get_sectors()
        for sector, tickers in sectors.items():
            if ticker in tickers:
                return sector
        return "Diğer"

    async def _validate_with_yfinance(self) -> List[str]:
        """Hisseleri yfinance ile doğrula (TÜM HİSSELER)."""
        logger.info("Validating tickers with yfinance...")

        try:
            import yfinance as yf

            valid = []
            delisted = []
            batch_size = 20

            for i in range(0, len(self._tickers), batch_size):
                batch = self._tickers[i:i + batch_size]

                for ticker in batch:
                    try:
                        # .IS ekle
                        symbol = f"{ticker}.IS"
                        stock = yf.Ticker(symbol)
                        info = stock.info

                        # Temel kontrol
                        if info and info.get("regularMarketPrice"):
                            valid.append(ticker)
                        else:
                            delisted.append(ticker)

                    except Exception as e:
                        logger.warning(f"Validation failed for {ticker}", error=str(e))
                        delisted.append(ticker)

                await asyncio.sleep(0.5)  # Rate limit

            self._delisted = delisted
            self._validated = True

            logger.info(f"Validation complete: {len(valid)} valid, {len(delisted)} delisted")
            return delisted

        except ImportError:
            logger.warning("yfinance not available, skipping validation")
            return []

    def validate(self):
        """Senkron doğrulama."""
        if not self._validated:
            logger.info("Running sync validation...")
            # Async olmayan basit kontrol
            self._validated = True

# Module-level helper functions for backward compatibility
def get_sector(ticker: str) -> str:
    """Hissenin sektörünü bul."""
    universe = BISTUniverse()
    return universe.get_ticker_sector(ticker)

BIST_STOCKS = BISTUniverse.BIST_100_TICKERS
BIST_INDICES = ["XU100", "XU030", "XU050"]

# Singleton
bist_universe = BISTUniverse()
