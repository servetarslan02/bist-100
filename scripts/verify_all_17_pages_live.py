import urllib.request
import json
import sys

def verify_all():
    print("=" * 75)
    print("  ALPHA BIST — 17 SAYFA VE TÜM ARKA PLAN SERVİSLERİ DOĞRULAMA DENETİMİ")
    print("=" * 75)

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

    print("\n[A] FRONTEND SAYFA ERİŞİM KONTROLLERİ (Next.js 15 Standalone)")
    all_pages_ok = True
    for p in pages:
        url = f"http://localhost:3000{p}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.getcode()
                html = resp.read().decode("utf-8", errors="ignore")
                print(f"  [OK 200] {p:<25} -> {len(html):,} bytes HTML")
        except Exception as e:
            all_pages_ok = False
            print(f"  [FAIL]   {p:<25} -> {e}")

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

    print("\n[B] BACKEND DİNAMİK API VE MOTOR TESTLERİ (FastAPI / 8000)")
    all_apis_ok = True
    for ep, desc in api_endpoints:
        url = f"http://localhost:8000{ep}"
        try:
            req = urllib.request.Request(url, headers={"X-User-Id": "1"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.getcode()
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                item_count = len(data) if isinstance(data, list) else len(data.keys())
                print(f"  [OK 200] {ep:<40} | {desc:<32} | {item_count} alan/öğe")
        except Exception as e:
            all_apis_ok = False
            print(f"  [FAIL]   {ep:<40} | {desc:<32} | HATA: {e}")

    print("\n" + "=" * 75)
    if all_pages_ok and all_apis_ok:
        print("  DENETİM SONUCU: TÜM SAYFALAR VE UÇ NOKTALAR %100 CANLI VE AKTİF!")
    else:
        print("  DENETİM SONUCU: BAZI SERVİSLERDE EKSİKLER TESPİT EDİLDİ.")
    print("=" * 75)

if __name__ == "__main__":
    verify_all()
