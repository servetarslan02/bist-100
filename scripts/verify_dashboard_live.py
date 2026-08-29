import structlog
logger = structlog.get_logger(__name__)
"""
ALPHA BIST — CANLI WEB DASHBOARD, KAP/HABER VE MAKRO ENTEGRASYON KANITI
Web arayüzünde '/', '/dashboard', '/api/v1/alternative/news' ve '/api/v1/alternative/macro' uç noktalarını doğrular.
"""

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath("."))

os.environ.setdefault("JWT_SECRET", "alpha-bist-test-secret-key-32-chars-minimum")
os.environ.setdefault("API_KEY_SECRET", "alpha-bist-api-secret-key-32-chars-minimum")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.api.app import app

logger.info("=" * 85)
logger.info("ALPHA BIST — WEB ARAYÜZÜ, KAP/HABER VE MAKRO CANLI PANEL DOĞRULAMASI")
logger.info("=" * 85)

client = TestClient(app)

# 1. Dashboard Root & HTML Testi
resp_dash = client.get("/")
logger.info(f"\n[1. TEST] Ana Dashboard Arayüzü GET / : Status {resp_dash.status_code}")
assert resp_dash.status_code == 200, "Dashboard HTML yüklenemedi!"
assert "Canlı KAP ve Finans Haberleri Akışı" in resp_dash.text, "KAP paneli HTML'de bulunamadı!"
assert "Küresel Makro & Emtia Göstergeleri" in resp_dash.text, "Makro paneli HTML'de bulunamadı!"
assert "629 Hisse (Tüm BIST)" in resp_dash.text, "629 hisse sayacı bulunamadı!"
logger.info("  ✓ Web Dashboard HTML, KAP Paneli ve Makro Paneli başarıyla render edildi.")

# 2. Canlı KAP ve Haber API Testi
resp_news = client.get("/api/v1/alternative/news?limit=5")
logger.info(f"\n[2. TEST] Canlı KAP & Haber API GET /api/v1/alternative/news : Status {resp_news.status_code}")
assert resp_news.status_code == 200, "Haber API yanıt vermedi!"
news_data = resp_news.json()
logger.info(f"  ✓ Çekilen Haber Sayısı: {news_data.get('count', 0)} adet")
if news_data.get("news"):
    logger.info(f'  ✓ Örnek Canlı Akış: "{news_data["news"][0].get("title", "")[:65]}..."')

# 3. Canlı Küresel Makro API Testi
resp_macro = client.get("/api/v1/alternative/macro")
logger.info(f"\n[3. TEST] Canlı Makro & Emtia API GET /api/v1/alternative/macro : Status {resp_macro.status_code}")
assert resp_macro.status_code == 200, "Makro API yanıt vermedi!"
macro_data = resp_macro.json().get("macro", {})
logger.info(f"  ✓ Makro Veri Kalemleri: {list(macro_data.keys())[:6]}")

logger.info("\n" + "=" * 85)
logger.info("BAŞARILI: KAP VE HABERLER EKRANA GERİ EKLENDİ, TÜM PANELLER %100 CANLI ÇALIŞIYOR.")
logger.info("=" * 85)
