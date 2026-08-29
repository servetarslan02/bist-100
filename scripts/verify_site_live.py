import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Site ve Uç Nokta Canlı Veri Doğrulama Scripti
"""

import sys
import urllib.request

import orjson

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

endpoints = [
    ("http://localhost:8000/api/v1/market/state", "Canlı BIST Rejim & Piyasa Genişliği"),
    ("http://localhost:8000/api/v1/market/heatmap", "Canlı Sektör Isı Haritası & Hisse Fiyatları"),
    ("http://localhost:8000/api/v1/market/radar?limit=1000", "Canlı BIST TÜM Evren Radarı & RSI/Skor"),
    ("http://localhost:8000/api/v1/macro/world", "Canlı DXY, US10Y, Brent, Altın, USDTRY, VIX"),
    ("http://localhost:8000/api/v1/event-study/events", "Canlı KAP & Finans Haber Akışı"),
    ("http://localhost:8000/api/v1/system/status", "Canlı CPU, RAM, Latency & Servis Durumu"),
    ("http://localhost:8000/api/v1/system/databases", "Gerçek PostgreSQL, ClickHouse, Redis Boyutları"),
]


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("ALPHA BIST -- SİTE ÜZERİNDEKİ CANLI VERİ ENTEGRASYONU DETAYLI DOĞRULAMASI")
    logger.info("=" * 80)
    for url, name in endpoints:
        try:
            req = urllib.request.urlopen(url, timeout=30)
            data = orjson.loads(req.read().decode("utf-8"))
            sample = ""
            if "sectors" in data:
                sample = f"Sektörler: {len(data['sectors'])} adet | İlk hisse: {data['sectors'][0]['stocks'][0]['symbol']} = ₺{data['sectors'][0]['stocks'][0]['price']}"
            elif "dxy" in data:
                sample = f"DXY: {data['dxy']} | Brent: ${data['brent_crude']} | Altın: ${data['gold_ounce']} | USD/TRY: {data['usd_try']} | VIX: {data.get('vix_level', data.get('vix'))}"
            elif "data" in data and isinstance(data["data"], list):
                sample = f"Taranan: {len(data['data'])} hisse | Örnek: {data['data'][0]['symbol']} (₺{data['data'][0]['price']})"
            elif "events" in data:
                sample = f"Canlı Haber/KAP: {len(data['events'])} adet | Son Olay: {data['events'][0]['title'][:40]}..."
            elif "resources" in data:
                sample = f"CPU: %{data['resources']['cpu_pct']} | RAM: {data['resources']['memory_used_mb']} MB / {data['resources']['memory_total_mb']} MB"
            elif "databases" in data:
                sample = f"ClickHouse: {data['databases'][0]['size']} | PostgreSQL: {data['databases'][1]['size']} | Redis: {data['databases'][2]['size']}"
            elif "regime" in data:
                sample = f"Rejim: {data['regime']} | Yükselen: {data.get('advancing', 0)} | Düşen: {data.get('declining', 0)}"

            logger.info(f"[DOĞRULANDI] {name:<38} -> {sample}")
        except Exception as e:
            logger.info(f"[HATA] {name} -> {e}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
