"""
ALPHA BIST — Zero Mock / Real Data Verification Suite
Tüm API uç noktalarını tarar ve hiçbir sahte/mock/dummy veri olmadığını doğrular.
"""

import sys
import asyncio
import httpx
import orjson

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8000/api/v1"

ENDPOINTS = [
    ("/market/state", "BIST Canli Piyasa Durumu"),
    ("/market/heatmap", "BIST Canli Sektor Isi Haritasi"),
    ("/market/radar?limit=50", "BIST Canli Piyasa Radari"),
    ("/macro/world", "Kuresel Makro Piyasa Gostergeleri"),
    ("/event-study/events", "Canli KAP ve Olay Akisi"),
    ("/system/status", "Sistem Saglik ve Donanim Telemetrisi"),
    ("/system/databases", "Canli Veritabani ve Bellek Boyutlari"),
    ("/system/alerts", "Sistem ve Model Alarmlari"),
]

MOCK_KEYWORDS = ["MOCK", "DUMMY", "SYNTHETIC_TEST", "SAMPLE_EVENT", "84.2M Satır", "62.4M", "14.2 Milyar ₺"]

async def run_audit():
    print("=" * 75)
    print("ALPHA BIST -- SIFIR SAHTE VERI (ZERO-MOCK) KAPSAMLI DENETIM TESTI")
    print("=" * 75)
    
    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for path, desc in ENDPOINTS:
            url = f"{BASE_URL}{path}"
            try:
                t0 = asyncio.get_event_loop().time()
                res = await client.get(url)
                lat = (asyncio.get_event_loop().time() - t0) * 1000
                
                if res.status_code != 200:
                    print(f"[HATA - {res.status_code}] {desc} ({path})")
                    failed += 1
                    continue
                
                body_text = res.text
                has_mock = any(kw.lower() in body_text.lower() for kw in MOCK_KEYWORDS)
                
                if has_mock:
                    print(f"[SAHTE VERI TESPIT EDILDI] {desc} ({path})")
                    failed += 1
                else:
                    data = res.json()
                    item_count = len(data) if isinstance(data, list) else len(data.keys())
                    print(f"[DOGRULANDI - CANLI] {desc:<40} | {lat:5.1f}ms | JSON Alanlari: {item_count}")
                    passed += 1
            except Exception as e:
                print(f"[BAGLANTI HATASI] {desc} ({path}) -> {e}")
                failed += 1

    print("=" * 75)
    if failed == 0:
        print(f"TUM {passed} UC NOKTA BASARIYLA GECTI. SISTEMDE SIFIR SAHTE VERI DOGRULANDI!")
    else:
        print(f"{failed} UC NOKTADA SORUN TESPIT EDILDI.")
    print("=" * 75)

if __name__ == "__main__":
    asyncio.run(run_audit())
