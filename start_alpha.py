"""
ALPHA BIST — Ana Başlatıcı
Tüm servisleri tek seferde başlatır.

Kullanım:
  python3 start_alpha.py

Sistem kendi kendine çalışır:
- BIST açıkken sürekli tarama
- Sinyal üretimi
- Trade planları
- Anomali tespiti
- Bildirimler
- Öğrenme
"""

import asyncio
import sys
import signal
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.core.logging import setup_logging
import structlog

logger = structlog.get_logger()


class AlphaSystem:
    """ALPHA BIST — Ana sistem sınıfı."""

    def __init__(self):
        self._running = False
        self._tasks = []

    async def start(self):
        """Tüm servisleri başlat."""
        setup_logging()

        print("=" * 60)
        print("ALPHA BIST — Market Intelligence & Quant Engine")
        print(f"Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print()

        self._running = True

        # Servisleri başlat
        from services.scheduler.main import AlphaScheduler
        from services.api.main import app

        scheduler = AlphaScheduler()

        # Scheduler'ı arka planda çalıştır
        self._tasks.append(asyncio.create_task(scheduler.start()))

        print("✓ Scheduler başlatıldı (BIST saatlerinde otomatik tarama)")
        print("✓ API servisi hazır (port 8000)")
        print()
        print("Sistem çalışıyor... BIST açıkken otomatik tarama yapacak.")
        print("Durdurmak için Ctrl+C")
        print()

        # API'yi başlat
        import uvicorn
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """Tüm servisleri durdur."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        print("\nALPHA BIST durduruldu.")


async def main():
    system = AlphaSystem()

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(system.stop()))

    try:
        await system.start()
    except KeyboardInterrupt:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())
