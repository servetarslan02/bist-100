"""ALPHA BIST - BIST Universe (All listed instruments)"""

# Complete BIST stock universe as of August 2026
# Ticker format: yfinance uses .IS suffix for BIST

BIST_STOCKS = [
    "ACSEL", "ADEL", "ADESE", "AEFES", "AFYON", "AGESA", "AGHOL", "AGROT", "AHGAZ",
    "AKBNK", "AKCNS", "AKENR", "AKFGY", "AKFYE", "AKGRT", "AKMGY", "AKSA", "AKSEN",
    "AKSGY", "AKSUE", "AKYHO", "ALARK", "ALBRK", "ALCAR", "ALFAS", "ALGYO", "ALKIM",
    "ALTNY", "ANHYT", "ANSGR", "ARASE", "ARCLK", "ARDYZ", "ARENA", "ARSAN", "ASELS",
    "ASGYO", "ASTOR", "ATAGY", "ATAKP", "ATATP", "AYCES", "AYDEM", "AYEN", "AYES",
    "AYGAZ", "AZTEK", "BAGFS", "BAKAB", "BALAT", "BANVT", "BARMA", "BASCM", "BASGZ",
    "BAYRK", "BERA", "BEYAZ", "BFREN", "BIENY", "BIGCH", "BIMAS", "BINBN", "BINHO",
    "BIOEN", "BIZIM", "BJKAS", "BLCYT", "BMSCH", "BMSTL", "BNTAS", "BOBET", "BORLS",
    "BORSA", "BRISA", "BRKO", "BRKSN", "BRKVY", "BRLSM", "BRMEN", "BRSAN", "BRYAT",
    "BSOKE", "BTCIM", "BUCIM", "BURCE", "BURVA", "BVSAN", "BYDNR", "CANTE", "CASA",
    "CCOLA", "CELHA", "CEMAS", "CEMTS", "CEOEM", "CFRSA", "CGCAM", "CIMSA", "CLEBI",
    "CMBTN", "CMSGZ", "CONSE", "COSMO", "CRDFA", "CRFSA", "CUSAN", "CVKMD", "CWENE",
    "DAGHL", "DAGI", "DAPGM", "DARDL", "DCTTR", "DENGE", "DERHL", "DERIM", "DESA",
    "DESPC", "DEVA", "DGATE", "DGNMO", "DIRIT", "DITAS", "DMRGD", "DMSAS", "DNISI",
    "DOAS", "DOBUR", "DOCO", "DOFER", "DOGUB", "DOHOL", "DOKTA", "DURDO", "DYOBY",
    "DZGYO", "ECILC", "ECZYT", "EDATA", "EDIP", "EGEEN", "EGEPO", "EGGUB", "EGPRO",
    "EGSER", "EKGYO", "EKIZ", "EKOS", "EKSUN", "ELITE", "EMKEL", "EMNIS", "ENJSA",
    "ENKAI", "ENSRI", "ENTRA", "EPLAS", "ERBOS", "ERCB", "EREGL", "ERSU", "ESCAR",
    "ESCOM", "ESEN", "ETILR", "ETYAT", "EUHOL", "EUPWR", "EUREN", "EVREN", "EXLAZ",
    "FADE", "FENER", "FLAP", "FMIZP", "FONET", "FORMT", "FORTE", "FRIGO", "FROTO",
    "FZLGY", "GARAN", "GARFA", "GEDIK", "GEDZA", "GENIL", "GENTS", "GEREL", "GESAN",
    "GIPTA", "GLBMD", "GLCVY", "GLYHO", "GMTAS", "GOKNR", "GOLTS", "GOODY", "GOZDE",
    "GRSEL", "GRTRK", "GSDDE", "GSDHO", "GSRAY", "GUBRF", "GWIND", "GZNMI", "HALKB",
    "HATEK", "HDFGS", "HEDEF", "HEKTS", "HKTM", "HLGYO", "HTTBT", "HUBVC", "HUNER",
    "HURGZ", "ICBCT", "ICUGS", "IDGYO", "IEYHO", "IHAAS", "IHEVA", "IHGZT", "IHLAS",
    "IHLGM", "IHYAY", "IMASM", "INDES", "INFO", "INTEM", "INVEO", "INVES", "IPEKE",
    "ISDMR", "ISFIN", "ISGSY", "ISIST", "ISKPL", "ISKUR", "ISMEN", "ISSEN", "ISYAT",
    "IZENR", "IZFAS", "IZINV", "JANTS", "KAPLM", "KAREL", "KARSN", "KARTN", "KARYE",
    "KATMR", "KAYSE", "KBORU", "KCAER", "KCHOL", "KERVN", "KERVT", "KFEIN", "KLGYO",
    "KLKIM", "KLMSN", "KLNMA", "KLRHO", "KLSER", "KLSYN", "KMPUR", "KNFRT", "KONKA",
    "KONTR", "KONYA", "KOPOL", "KORDS", "KOSDA", "KRDMA", "KRDMB", "KRDMD", "KRGYO",
    "KRONT", "KRPLS", "KRSTL", "KRTEK", "KRVGD", "KSTUR", "KTLEV", "KTSKR", "KUVVA",
    "KUYAS", "KZBGY", "KZGYO", "LIDER", "LIDFA", "LILAK", "LINK", "LKMNH", "LOGO",
    "LUKSK", "MAALT", "MACKO", "MAGEN", "MAKIM", "MAKTK", "MANAS", "MARKA", "MARTI",
    "MAVI", "MEDTR", "MEGAP", "MEKAG", "MERCN", "MERIT", "MERKO", "METRO", "METUR",
    "MGROS", "MHRGY", "MIATK", "MIPAZ", "MMCAS", "MNDRS", "MNDTR", "MOBTL", "MOGAN",
    "MPARK", "MRGYO", "MRSHL", "MSGYO", "MTRKS", "MTRYO", "MZHLD", "NATEN", "NETAS",
    "NIBAS", "NTGAZ", "NTHOL", "NUGYO", "NUHCM", "OBAMS", "OBASE", "ODAS", "ONCSM",
    "ORCAY", "ORGE", "ORMA", "OSMEN", "OSTIM", "OTKAR", "OTTO", "OYAKC", "OYAYO",
    "OYLUM", "OYYAT", "OZGYO", "OZKGY", "OZRDN", "OZSUB", "PAGYO", "PAMEL", "PAPIL",
    "PARSN", "PASEU", "PCILT", "PEKGY", "PENGD", "PENTA", "PETKM", "PETUN", "PGSUS",
    "PINSU", "PKART", "PKENT", "PLTUR", "PNLSN", "PNSUT", "POLHO", "POLTK", "PRDGS",
    "PRKAB", "PRKME", "PSGYO", "QNBFB", "QNBFL", "QUAGR", "RALYH", "RAYSG", "REEDR",
    "RGYAS", "RNPOL", "RODRG", "ROYAL", "RUBNS", "RYGYO", "RYSAS", "SAFKR", "SAHOL",
    "SAMAT", "SANEL", "SANFM", "SANKO", "SARKY", "SASA", "SAYAS", "SDTTR", "SEGYO",
    "SEKFK", "SEKUR", "SELEC", "SELGD", "SELVA", "SEYKM", "SILVR", "SISE", "SKBNK",
    "SKYLP", "SMART", "SMRTG", "SNGYO", "SNICA", "SNKRN", "SNPAM", "SOKM", "SORTR",
    "SOYAK", "SRVGY", "SUMAS", "SUNTK", "SURGY", "SUWEN", "TABGD", "TATGD", "TAVHL",
    "TBORG", "TCELL", "TDGYO", "TEKTU", "TERA", "TETMT", "TEZOL", "TGSAS", "THYAO",
    "TKFEN", "TKNSA", "TLMAN", "TMPOL", "TMSN", "TNZTP", "TOASO", "TRCAS", "TRGYO",
    "TRILC", "TSGYO", "TSKB", "TTKOM", "TTRAK", "TUCLK", "TUKAS", "TUPRS", "TUREX",
    "TURSG", "UFUK", "UFUK", "ULKER", "ULUFA", "ULUSE", "ULUUN", "UMPAS", "UNLU",
    "USAK", "UZERB", "VAKBN", "VAKFN", "VAKKO", "VANGD", "VBTYZ", "VERUS", "VESBE",
    "VESTEL", "VKFYO", "VKGYO", "VKING", "VOYVK", "YAPRK", "YATAS", "YAYLA", "YBTAS",
    "YEOTK", "YESIL", "YGGYO", "YGYO", "YKBNK", "YKSLN", "YONGA", "YUNSA", "YYAPI",
    "YYLGD", "ZEDUR", "ZOREN", "ZRGYO",
]

# BIST indices
BIST_INDICES = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XBANK": "BIST Banka",
    "XUSIN": "BIST Sınai",
    "XUMAL": "BIST Mali",
    "XUTEK": "BIST Teknoloji",
    "XHOLD": "BIST Holding",
    "XTRALM": "BIST Tüm",
}

# Sector mapping (ticker -> sector_code)
SECTOR_MAP = {
    "AKBNK": "BANK", "GARAN": "BANK", "HALKB": "BANK", "ISCTR": "BANK",
    "VAKBN": "BANK", "YKBNK": "BANK", "SKBNK": "BANK", "ICBCT": "BANK",
    "QNBFB": "BANK", "QNBFL": "BANK",

    "THYAO": "AVIATION", "PGSUS": "AVIATION",

    "EREGL": "METAL", "KRDMD": "METAL", "KRDMA": "METAL", "KRDMB": "METAL",
    "ISDMR": "METAL", "CMSGZ": "METAL",

    "TUPRS": "ENERGY", "PETKM": "ENERGY", "AYEN": "ENERGY", "AKSEN": "ENERGY",
    "ODAS": "ENERGY", "AYDEM": "ENERGY", "GWIND": "ENERGY", "CONSE": "ENERGY",
    "NATEN": "ENERGY", "AKENR": "ENERGY", "AYES": "ENERGY",

    "BIMAS": "RETAIL", "MGROS": "RETAIL", "SOKM": "RETAIL", "ULKER": "RETAIL",
    "TATGD": "RETAIL", "SELVA": "RETAIL",

    "ARCLK": "INDUST", "FROTO": "AUTO", "TOASO": "AUTO", "OTKAR": "AUTO",
    "TTRAK": "AUTO", "DOAS": "AUTO", "BRISA": "AUTO",

    "ASELS": "TECH", "NETAS": "TECH", "LOGO": "TECH", "INDES": "TECH",
    "AZTEK": "TECH", "KAREL": "TECH", "SMART": "TECH", "EDATA": "TECH",

    "KCHOL": "HOLDING", "SAHOL": "HOLDING", "DOHOL": "HOLDING", "TAVHL": "HOLDING",
    "ENKAI": "HOLDING", "TKFEN": "HOLDING", "VESTEL": "HOLDING",

    "SISE": "CHEM", "BAGFS": "CHEM", "KOPOL": "CHEM", "ALKIM": "CHEM",
    "SASA": "CHEM", "EGGUB": "CHEM",

    "TCELL": "TELECOM", "TTKOM": "TELECOM",

    "EKGYO": "REAL", "HLGYO": "REAL", "GYGYO": "REAL",

    "CCOLA": "FOOD", "AEFES": "FOOD", "TBORG": "FOOD",
}


def get_yfinance_ticker(ticker: str) -> str:
    """Convert BIST ticker to yfinance format."""
    return f"{ticker}.IS"


def get_all_yfinance_tickers() -> list:
    """Get all BIST tickers in yfinance format."""
    return [f"{t}.IS" for t in BIST_STOCKS]


def get_sector(ticker: str) -> str:
    """Get sector code for a ticker."""
    return SECTOR_MAP.get(ticker, "OTHER")
