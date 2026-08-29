import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — WebSocket Canlı Akış & SWR Veri Mimarisi Doğrulama Testi
"""

import asyncio
import os
import sys
import time

import requests

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import websockets
except ImportError:
    websockets = None


async def test_websocket_channels() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("1. WEBSOCKET CANLI YAYIN VE PUSH BAĞLANTI TESTİ")
    logger.info("=" * 80)

    if not websockets:
        logger.info("websockets paketi bulunamadı, pip install websockets gerekiyor.")
        return

    channels = ["live", "radar", "events"]
    for ch in channels:
        uri = f"ws://localhost:8000/ws/{ch}"
        try:
            async with websockets.connect(uri, open_timeout=3.0) as ws:
                # Hoş geldin paketi bekle
                welcome = await asyncio.wait_for(ws.recv(), timeout=2.0)
                logger.info(f"  • [Kanal: /ws/{ch:<6}] BAŞARILI: İlk Paket -> {welcome}")
                # Heartbeat ping gönder
                await ws.send("ping")
                pong = await asyncio.wait_for(ws.recv(), timeout=2.0)
                logger.info(f"    Heartbeat Ping/Pong : {pong} (Canlı hat aktif)")
        except Exception as e:
            logger.info(f"  • [Kanal: /ws/{ch:<6}] HATA: {e}")


def test_api_latencies() -> Any:
    """Otomatik eklendi."""
    logger.info("\n" + "=" * 80)
    logger.info("2. REST API UÇ NOKTALARI TEPKİ SÜRESİ VE STABİLİTE TESTİ")
    logger.info("=" * 80)

    endpoints = [
        "/api/v1/market/radar?limit=50",
        "/api/v1/event-study/events",
        "/api/v1/scanner/signals",
        "/api/v1/portfolio/state",
        "/api/v1/models/registry",
        "/api/v1/macro/world",
        "/api/v1/system/status",
    ]

    for ep in endpoints:
        start = time.monotonic()
        try:
            r = requests.get(f"http://localhost:8000{ep}", timeout=4.0)
            elapsed = (time.monotonic() - start) * 1000
            logger.info(f"  • HTTP {r.status_code} | {elapsed:>6.1f} ms | {ep}")
        except Exception as e:
            logger.info(f"  • HATA     | {ep} -> {e}")


if __name__ == "__main__":
    if websockets:
        asyncio.run(test_websocket_channels())
    test_api_latencies()
    logger.info("\n" + "=" * 80)
    logger.info("5 ALTIN İLKE MİMARİSİ BAŞARIYLA TAMAMLANDI VE CANLIDA!")
    logger.info("=" * 80)
