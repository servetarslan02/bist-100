import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import urllib.request

import orjson


def verify_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 75)
    logger.info("  ALPHA BIST — 17 SAYFA VE TÜM ARKA PLAN SERVİSLERİ DOĞRULAMA DENETİMİ")
    logger.info("=" * 75)

    # 1. FRONTEND SAYFALARI (17 Sayfa)
    pages = [
        "/",
        "/opportunities",
        "/portfolio",
        "/strategy",
        "/learning",
        "/models",
        "/alerts",
        "/asset?ticker=THYAO",
        "/world",
        "/scenario",
        "/radar",
        "/map",
        "/data",
        "/events",
        "/research",
        "/system",
    ]

    logger.info("\n[A] FRONTEND SAYFA ERİŞİM KONTROLLERİ (Next.js 15 Standalone)")
    all_pages_ok = True
    for p in pages:
        url = f"http://localhost:3000{p}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.getcode()
                html = resp.read().decode("utf-8", errors="ignore")
                logger.info(f"  [OK 200] {p:<25} -> {len(html):,} bytes HTML")
        except Exception as e:
            all_pages_ok = False
            logger.info(f"  [FAIL]   {p:<25} -> {e}")

    # 2. BACKEND DINAMIK UÇ NOKTALARI
    api_endpoints = [
        ("/api/v1/market/heatmap", "Canlı Sektör Isı Haritası"),
        ("/api/v1/risk/stress-test?horizon_days=30", "Dinamik Monte Carlo Stres Testi"),
        ("/api/v1/models/list", "ML Model Kayıt Defteri"),
        ("/api/v1/scanner/opportunities", "30Y ML Fırsat Tarayıcısı"),
        ("/api/v1/macro/overview", "Canlı Küresel Makro & CDS"),
        ("/api/v1/portfolio/state", "Risk Parity Portföy Durumu"),
        ("/api/v1/learning/performance-matrix", "Öğrenme Matrisi"),
        ("/api/v1/system/status", "Mikroservis Sağlık Telemetrisi"),
        ("/api/v1/event-study/events", "Canlı Haber & KAP Akışı"),
    ]

    logger.info("\n[B] BACKEND DİNAMİK API VE MOTOR TESTLERİ (FastAPI / 8000)")
    all_apis_ok = True
    for ep, desc in api_endpoints:
        url = f"http://localhost:8000{ep}"
        try:
            req = urllib.request.Request(url, headers={"X-User-Id": "1"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.getcode()
                raw = resp.read().decode("utf-8")
                data = orjson.loads(raw)
                item_count = len(data) if isinstance(data, list) else len(data.keys())
                logger.info(f"  [OK 200] {ep:<40} | {desc:<32} | {item_count} alan/öğe")
        except Exception as e:
            all_apis_ok = False
            logger.info(f"  [FAIL]   {ep:<40} | {desc:<32} | HATA: {e}")

    logger.info("\n" + "=" * 75)
    if all_pages_ok and all_apis_ok:
        logger.info("  DENETİM SONUCU: TÜM SAYFALAR VE UÇ NOKTALAR %100 CANLI VE AKTİF!")
    else:
        logger.info("  DENETİM SONUCU: BAZI SERVİSLERDE EKSİKLER TESPİT EDİLDİ.")
    logger.info("=" * 75)


if __name__ == "__main__":
    verify_all()
