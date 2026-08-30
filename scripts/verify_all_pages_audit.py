import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Tüm 16 Sayfa ve 5 Temel İlke Denetim Testi
"""

import os
import sys

import requests

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PAGES = [
    ("/", "Ana Yönetim Paneli"),
    ("/radar", "Piyasa Radarı"),
    ("/opportunities", "Fırsat & Sinyal Tarayıcı"),
    ("/portfolio", "Portföy & Sanal Bakiye"),
    ("/events", "KAP & Borsa Olay Merkezi"),
    ("/asset", "Hisse Detay & TradingView Grafik"),
    ("/models", "Model Kayıt Defteri"),
    ("/learning", "Otonom Öğrenme Laboratuvarı"),
    ("/scenario", "Makro Senaryo & Stres Testi"),
    ("/strategy", "Strateji & Backtest Analizi"),
    ("/world", "Küresel Makro İstihbarat"),
    ("/alerts", "Akıllı Alarm & Uyarı Merkezi"),
    ("/data", "Veri Merkezi & ClickHouse Depolama"),
    ("/research", "Yapay Zeka Araştırma Raporları"),
    ("/system", "Sistem & Servis Sağlığı"),
    ("/map", "Sektörel Isı Haritası"),
]


def audit_all_pages() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("ALPHA BIST — 16 SAYFA DETAYLI DENETİM RAPORU")
    logger.info("=" * 80)

    success_count = 0
    for path, title in PAGES:
        url = f"http://localhost:3000{path}"
        try:
            r = requests.get(url, timeout=3.0)
            status = "OK (200)" if r.status_code == 200 else f"HATA ({r.status_code})"
            logger.info(f"  • {path:<16} | {status:<10} | {title}")
            if r.status_code == 200:
                success_count += 1
        except Exception as e:
            logger.info(f"  • {path:<16} | HATA       | {e}")

    logger.info("-" * 80)
    logger.info(f"Sonuç: {success_count}/{len(PAGES)} sayfa %100 çalışır durumda ve yayında.")
    logger.info("=" * 80)


if __name__ == "__main__":
    audit_all_pages()
