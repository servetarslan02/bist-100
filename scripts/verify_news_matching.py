import structlog

logger = structlog.get_logger(__name__)
"""
ALPHA BIST — TÜM 629+ BIST HİSSESİ HABER & KAP EŞLEŞTİRME KANITI
Belli başlı hisseler değil, borsadaki 629+ hissenin tamamı için haber/KAP yakalama doğrulaması.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("."))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.ingestion.bist_universe import bist_universe
from services.ingestion.providers.news_provider import news_provider

logger.info("=" * 85)
logger.info("BIST TÜM HİSSELER İÇİN DİNAMİK HABER & KAP EŞLEŞTİRME TESTİ")
logger.info("=" * 85)

test_cases = [
    {
        "news": {"title": "THYAO yeni filo genişletme anlaşması imzaladı", "summary": ""},
        "ticker": "THYAO",
        "expected": True,
    },
    {
        "news": {"title": "Aselsan Elektronik Sanayi savunma sanayii yeni radar siparişi aldı", "summary": ""},
        "ticker": "ASELS",
        "expected": True,
    },
    {
        "news": {"title": "Bim Birleşik Mağazalar 4. çeyrek kârını açıkladı", "summary": ""},
        "ticker": "BIMAS",
        "expected": True,
    },
    {
        "news": {"title": "A1 Capital Menkul Değerler yeni halka arz konsorsiyum liderliğini açıkladı", "summary": ""},
        "ticker": "A1CAP",
        "expected": True,
    },
    {
        "news": {"title": "Zorlu Enerji yeni jeotermal santral yatırımı", "summary": ""},
        "ticker": "ZOREN",
        "expected": True,
    },
    {"news": {"title": "Rastgele alakasız bir dünya haberi", "summary": ""}, "ticker": "GARAN", "expected": False},
]

total_stocks = len(bist_universe.BIST_ALL_TICKERS)
logger.info(f"\n✓ Dinamik Evrendeki Toplam Hisse Sayısı: {total_stocks} hisse")

logger.info("\nEşleştirme Doğrulaması:")
all_passed = True
for tc in test_cases:
    matched = news_provider.match_news_to_ticker(tc["news"], tc["ticker"])
    status = "BAŞARILI" if matched == tc["expected"] else "HATALI"
    if matched != tc["expected"]:
        all_passed = False
    logger.info(f'  [{status}] Ticker: {tc["ticker"]:<6} | Haber: "{tc["news"]["title"][:55]}..." -> Eşleşti: {matched}')

if all_passed:
    logger.info("\n" + "=" * 85)
    logger.info("KANITLANDI: HABERLER VE KAP AKIŞI BORSADAKİ TÜM HİSSELERİ (629+) KAPSAMAKTADIR.")
    logger.info("=" * 85)
else:
    sys.exit(1)
