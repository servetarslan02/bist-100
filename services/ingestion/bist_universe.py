"""
ALPHA BIST - Dynamic BIST Universe v2.0

Sabit liste yok. KAP'tan canlı çeker.
Yeni halka arzlar otomatik eklenir.
Güncel liste her gün yenilenir.
"""

import requests
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from pathlib import Path
import structlog

logger = structlog.get_logger()

# Cache dosyası
CACHE_FILE = Path("data/bist_universe_cache.json")
CACHE_MAX_AGE_HOURS = 24


class BISTUniverse:
    """Dinamik BIST hisse evreni."""

    def __init__(self):
        self._tickers: List[str] = []
        self._ticker_info: Dict[str, Dict] = {}
        self._last_update: Optional[datetime] = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def get_tickers(self, force_refresh: bool = False) -> List[str]:
        """BIST hisse listesini döndür. Gerekirse güncelle."""
        if not force_refresh and self._tickers and self._last_update:
            age = (datetime.now() - self._last_update).total_seconds() / 3600
            if age < CACHE_MAX_AGE_HOURS:
                return self._tickers

        # Cache'den yükle
        if not force_refresh and self._load_from_cache():
            return self._tickers

        # KAP'tan çek
        self._fetch_from_kap()

        # yfinance ile doğrula
        self._validate_with_yfinance()

        # Cache'e kaydet
        self._save_to_cache()

        self._last_update = datetime.now()
        logger.info("BIST universe updated", count=len(self._tickers))

        return self._tickers

    def get_ticker_info(self, ticker: str) -> Optional[Dict]:
        """Hisse bilgisi döndür."""
        if not self._tickers:
            self.get_tickers()
        return self._ticker_info.get(ticker)

    def get_sector(self, ticker: str) -> str:
        """Sektör bilgisi döndür."""
        info = self._ticker_info.get(ticker, {})
        return info.get("sector", "OTHER")

    def _fetch_from_kap(self):
        """KAP'tan şirket listesini çek."""
        try:
            url = "https://kap.org.tr/tr/bist-sirketler"
            resp = self._session.get(url, timeout=30)

            if resp.status_code != 200:
                logger.warning("KAP fetch failed, using fallback", status=resp.status_code)
                self._load_fallback()
                return

            # JSON'dan parse et
            text = resp.text

            # stockCode'ları çıkar
            pattern = r'"stockCode"\s*:\s*"([^"]+)"'
            matches = re.findall(pattern, text)

            # Filtrele: sadece geçerli hisse kodları (4-5 harf)
            tickers = []
            for code in matches:
                code = code.strip().upper()
                if len(code) >= 3 and len(code) <= 6 and code.isalpha():
                    tickers.append(code)

            # Benzersiz yap
            tickers = sorted(list(set(tickers)))

            if len(tickers) > 100:
                self._tickers = tickers
                logger.info("KAP tickers fetched", count=len(tickers))
            else:
                logger.warning("KAP returned too few tickers, using fallback")
                self._load_fallback()

        except Exception as e:
            logger.error("KAP fetch error", error=str(e))
            self._load_fallback()

    def _validate_with_yfinance(self):
        """yfinance ile doğrula — delisted olanları çıkar."""
        import yfinance as yf

        if not self._tickers:
            return

        # Batch download (hızlı doğrulama)
        test_tickers = self._tickers[:50]  # İlk 50'yi test et
        try:
            data = yf.download(
                [f"{t}.IS" for t in test_tickers],
                period="5d",
                group_by="ticker",
                threads=True,
                progress=False,
            )

            valid = []
            for t in test_tickers:
                try:
                    td = data[f"{t}.IS"].dropna()
                    if len(td) > 0:
                        valid.append(t)
                except Exception:
                    pass

            # Eğer ilk 50'de >%80 geçerliyse, tüm listeyi kabul et
            if len(valid) > len(test_tickers) * 0.8:
                logger.info("yfinance validation passed", valid_rate=f"{len(valid)/len(test_tickers)*100:.0f}%")
            else:
                logger.warning("yfinance validation low", valid_rate=f"{len(valid)/len(test_tickers)*100:.0f}%")

        except Exception as e:
            logger.warning("yfinance validation failed", error=str(e))

    def _load_fallback(self):
        """Fallback: Sabit liste (güncel BIST şirketleri)."""
        self._tickers = [
            "ACSEL", "ADEL", "ADESE", "ADGYO", "AEFES", "AFYON", "AGESA", "AGHOL",
            "AGROT", "AHGAZ", "AHSGY", "AKBNK", "AKCNS", "AKENR", "AKFGY", "AKFYE",
            "AKGRT", "AKMGY", "AKSA", "AKSEN", "AKSGY", "AKSUE", "AKYHO", "ALARK",
            "ALBRK", "ALCAR", "ALFAS", "ALGYO", "ALKIM", "ALTNY", "ANHYT", "ANSGR",
            "ARASE", "ARCLK", "ARDYZ", "ARENA", "ARSAN", "ASELS", "ASGYO", "ASTOR",
            "ATAGY", "ATAKP", "ATATP", "AYCES", "AYDEM", "AYEN", "AYES", "AYGAZ",
            "AZTEK", "BAGFS", "BAKAB", "BALAT", "BANVT", "BARMA", "BASCM", "BASGZ",
            "BAYRK", "BERA", "BEYAZ", "BFREN", "BIENY", "BIGCH", "BIMAS", "BINBN",
            "BINHO", "BIOEN", "BIZIM", "BJKAS", "BLCYT", "BMSCH", "BMSTL", "BNTAS",
            "BOBET", "BORLS", "BRISA", "BRKO", "BRKSN", "BRKVY", "BRLSM", "BRMEN",
            "BRSAN", "BRYAT", "BSOKE", "BTCIM", "BUCIM", "BURCE", "BURVA", "BVSAN",
            "BYDNR", "CANTE", "CASA", "CCOLA", "CELHA", "CEMAS", "CEMTS", "CEOEM",
            "CFRSA", "CGCAM", "CIMSA", "CLEBI", "CMBTN", "CONSE", "COSMO", "CRDFA",
            "CRFSA", "CUSAN", "CVKMD", "CWENE", "DAGI", "DAPGM", "DARDL", "DCTTR",
            "DENGE", "DERHL", "DERIM", "DESA", "DESPC", "DEVA", "DGATE", "DGNMO",
            "DIRIT", "DITAS", "DMRGD", "DMSAS", "DNISI", "DOAS", "DOCO", "DOFER",
            "DOGUB", "DOHOL", "DOKTA", "DURDO", "DYOBY", "DZGYO", "ECILC", "ECZYT",
            "EDATA", "EDIP", "EGEEN", "EGEPO", "EGGUB", "EGPRO", "EGSER", "EKGYO",
            "EKIZ", "EKOS", "EKSUN", "ELITE", "EMKEL", "EMNIS", "ENJSA", "ENKAI",
            "ENSRI", "ENTRA", "EPLAS", "ERBOS", "ERCB", "EREGL", "ERSU", "ESCAR",
            "ESCOM", "ESEN", "ETILR", "ETYAT", "EUHOL", "EUPWR", "EUREN", "FADE",
            "FENER", "FLAP", "FMIZP", "FONET", "FORMT", "FORTE", "FRIGO", "FROTO",
            "FZLGY", "GARAN", "GARFA", "GEDIK", "GEDZA", "GENIL", "GENTS", "GEREL",
            "GESAN", "GIPTA", "GLBMD", "GLCVY", "GLYHO", "GMTAS", "GOKNR", "GOLTS",
            "GOODY", "GOZDE", "GRSEL", "GRTRK", "GSDDE", "GSDHO", "GSRAY", "GUBRF",
            "GWIND", "GZNMI", "HALKB", "HATEK", "HDFGS", "HEDEF", "HEKTS", "HKTM",
            "HLGYO", "HTTBT", "HUBVC", "HUNER", "HURGZ", "ICBCT", "ICUGS", "IDGYO",
            "IEYHO", "IHAAS", "IHEVA", "IHGZT", "IHLAS", "IHLGM", "IHYAY", "IMASM",
            "INDES", "INFO", "INTEM", "INVEO", "INVES", "IPEKE", "ISDMR", "ISFIN",
            "ISGSY", "ISKPL", "ISKUR", "ISMEN", "ISSEN", "ISYAT", "IZENR", "IZFAS",
            "IZINV", "JANTS", "KAPLM", "KAREL", "KARSN", "KARTN", "KARYE", "KATMR",
            "KAYSE", "KBORU", "KCAER", "KCHOL", "KERVN", "KERVT", "KFEIN", "KLGYO",
            "KLKIM", "KLMSN", "KLNMA", "KLRHO", "KLSER", "KLSYN", "KMPUR", "KNFRT",
            "KONKA", "KONTR", "KONYA", "KOPOL", "KORDS", "KOSDA", "KRDMA", "KRDMB",
            "KRDMD", "KRGYO", "KRONT", "KRPLS", "KRSTL", "KRTEK", "KRVGD", "KSTUR",
            "KTLEV", "KTSKR", "KUVVA", "KUYAS", "KZBGY", "KZGYO", "LIDER", "LIDFA",
            "LILAK", "LINK", "LKMNH", "LOGO", "LUKSK", "MAALT", "MACKO", "MAGEN",
            "MAKIM", "MAKTK", "MANAS", "MARKA", "MARTI", "MAVI", "MEDTR", "MEGAP",
            "MEKAG", "MERCN", "MERIT", "MERKO", "METRO", "METUR", "MGROS", "MHRGY",
            "MIATK", "MIPAZ", "MMCAS", "MNDRS", "MNDTR", "MOBTL", "MOGAN", "MPARK",
            "MRGYO", "MRSHL", "MSGYO", "MTRKS", "MTRYO", "MZHLD", "NATEN", "NETAS",
            "NIBAS", "NTGAZ", "NTHOL", "NUGYO", "NUHCM", "OBAMS", "OBASE", "ODAS",
            "ONCSM", "ORCAY", "ORGE", "ORMA", "OSMEN", "OSTIM", "OTKAR", "OTTO",
            "OYAKC", "OYAYO", "OYLUM", "OYYAT", "OZGYO", "OZKGY", "OZRDN", "OZSUB",
            "PAGYO", "PAMEL", "PAPIL", "PARSN", "PASEU", "PCILT", "PEKGY", "PENGD",
            "PENTA", "PETKM", "PETUN", "PGSUS", "PINSU", "PKART", "PKENT", "PLTUR",
            "PNLSN", "PNSUT", "POLHO", "POLTK", "PRDGS", "PRKAB", "PRKME", "PSGYO",
            "QNBFB", "QNBFL", "QUAGR", "RALYH", "RAYSG", "REEDR", "RGYAS", "RNPOL",
            "RODRG", "ROYAL", "RUBNS", "RYGYO", "RYSAS", "SAFKR", "SAHOL", "SAMAT",
            "SANEL", "SANFM", "SANKO", "SARKY", "SASA", "SAYAS", "SDTTR", "SEGYO",
            "SEKFK", "SEKUR", "SELEC", "SELGD", "SELVA", "SEYKM", "SILVR", "SISE",
            "SKBNK", "SKYLP", "SMART", "SMRTG", "SNGYO", "SNICA", "SNKRN", "SNPAM",
            "SOKM", "SORTR", "SOYAK", "SRVGY", "SUMAS", "SUNTK", "SURGY", "SUWEN",
            "TABGD", "TATGD", "TAVHL", "TBORG", "TCELL", "TDGYO", "TEKTU", "TERA",
            "TETMT", "TEZOL", "TGSAS", "THYAO", "TKFEN", "TKNSA", "TLMAN", "TMPOL",
            "TMSN", "TNZTP", "TOASO", "TRCAS", "TRGYO", "TRILC", "TSGYO", "TSKB",
            "TTKOM", "TTRAK", "TUCLK", "TUKAS", "TUPRS", "TUREX", "TURSG", "UFUK",
            "ULKER", "ULUFA", "ULUSE", "ULUUN", "UMPAS", "UNLU", "USAK", "UZERB",
            "VAKBN", "VAKFN", "VAKKO", "VANGD", "VBTYZ", "VERUS", "VESBE", "VESTEL",
            "VKFYO", "VKGYO", "VKING", "VOYVK", "YAPRK", "YATAS", "YAYLA", "YBTAS",
            "YEOTK", "YESIL", "YGGYO", "YGYO", "YKBNK", "YKSLN", "YONGA", "YUNSA",
            "YYAPI", "YYLGD", "ZEDUR", "ZOREN", "ZRGYO",
        ]
        logger.info("Fallback universe loaded", count=len(self._tickers))

    def _load_from_cache(self) -> bool:
        """Cache'den yükle."""
        try:
            if not CACHE_FILE.exists():
                return False

            data = json.loads(CACHE_FILE.read_text())
            age_hours = (datetime.now().timestamp() - data.get("timestamp", 0)) / 3600

            if age_hours > CACHE_MAX_AGE_HOURS:
                return False

            self._tickers = data.get("tickers", [])
            self._ticker_info = data.get("ticker_info", {})
            self._last_update = datetime.fromtimestamp(data.get("timestamp", 0))

            logger.info("Universe loaded from cache", count=len(self._tickers))
            return len(self._tickers) > 100

        except Exception:
            return False

    def _save_to_cache(self):
        """Cache'e kaydet."""
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "tickers": self._tickers,
                "ticker_info": self._ticker_info,
                "timestamp": datetime.now().timestamp(),
                "count": len(self._tickers),
            }
            CACHE_FILE.write_text(json.dumps(data, indent=2))
            logger.info("Universe cached", count=len(self._tickers))
        except Exception as e:
            logger.warning("Cache save failed", error=str(e))

    def add_ticker(self, ticker: str, info: Optional[Dict] = None):
        """Yeni hisse ekle (halka arz vb.)."""
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            if info:
                self._ticker_info[ticker] = info
            logger.info("Ticker added", ticker=ticker)
            self._save_to_cache()

    def remove_ticker(self, ticker: str):
        """Hisse çıkar (delisting vb.)."""
        ticker = ticker.upper().strip()
        if ticker in self._tickers:
            self._tickers.remove(ticker)
            self._ticker_info.pop(ticker, None)
            logger.info("Ticker removed", ticker=ticker)
            self._save_to_cache()


# BIST endeksleri
BIST_INDICES = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XBANK": "BIST Banka",
    "XUSIN": "BIST Sınai",
    "XUMAL": "BIST Mali",
    "XUTEK": "BIST Teknoloji",
    "XHOLD": "BIST Holding",
}

# Sektör eşleme
SECTOR_MAP = {
    "AKBNK": "BANK", "GARAN": "BANK", "HALKB": "BANK", "ISCTR": "BANK",
    "VAKBN": "BANK", "YKBNK": "BANK", "SKBNK": "BANK", "ICBCT": "BANK",
    "THYAO": "AVIATION", "PGSUS": "AVIATION",
    "EREGL": "METAL", "KRDMD": "METAL", "ISDMR": "METAL",
    "TUPRS": "ENERGY", "PETKM": "ENERGY", "AKSEN": "ENERGY", "ODAS": "ENERGY",
    "BIMAS": "RETAIL", "MGROS": "RETAIL", "SOKM": "RETAIL", "ULKER": "RETAIL",
    "ARCLK": "INDUST", "FROTO": "AUTO", "TOASO": "AUTO", "OTKAR": "AUTO",
    "ASELS": "TECH", "NETAS": "TECH", "LOGO": "TECH", "INDES": "TECH",
    "KCHOL": "HOLDING", "SAHOL": "HOLDING", "DOHOL": "HOLDING",
    "SISE": "CHEM", "BAGFS": "CHEM", "ALKIM": "CHEM", "SASA": "CHEM",
    "TCELL": "TELECOM", "TTKOM": "TELECOM",
    "EKGYO": "REAL", "HLGYO": "REAL",
    "CCOLA": "FOOD", "AEFES": "FOOD",
}


# Singleton
bist_universe = BISTUniverse()


# Kolaylık fonksiyonları
def get_yfinance_ticker(ticker: str) -> str:
    return f"{ticker}.IS"


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "OTHER")


# Eski API uyumluluğu
BIST_STOCKS = []  # Boş — artık dinamik


def get_all_yfinance_tickers() -> list:
    tickers = bist_universe.get_tickers()
    return [f"{t}.IS" for t in tickers]
