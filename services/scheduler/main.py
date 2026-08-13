"""
ALPHA BIST — Scheduler Service v2.0

Alpha Engine ile entegre.
BIST saatlerinde otomatik çalışır.
"""

import asyncio
from datetime import datetime
import structlog

from ..scanner.alpha_engine import alpha_engine
from ..ingestion.bist_universe import BIST_STOCKS

logger = structlog.get_logger()


class AlphaScheduler:
    """Otonom scheduler — Alpha Engine ile entegre."""

    def __init__(self):
        self._running = False
        self._last_scan = None
        self._scan_count = 0

    async def start(self):
        """Scheduler'ı başlat."""
        self._running = True

        # 800 hisseyi yükle
        alpha_engine.load_universe(BIST_STOCKS)
        logger.info("ALPHA Scheduler started", universe=len(BIST_STOCKS))

        while self._running:
            try:
                now = datetime.now()
                hour = now.hour
                minute = now.minute
                weekday = now.weekday()

                # Hafta sonu
                if weekday >= 5:
                    await asyncio.sleep(60)
                    continue

                # BIST saatleri: 10:00-18:00
                if 10 <= hour < 18:
                    await self._market_hours()
                elif hour == 9 and minute >= 50:
                    await self._pre_market()
                elif hour == 18 and minute <= 30:
                    await self._post_market()
                elif hour == 23 and minute <= 10:
                    await self._daily_summary()
                else:
                    await asyncio.sleep(60)

            except Exception as e:
                logger.error("Scheduler error", error=str(e))
                await asyncio.sleep(30)

    async def stop(self):
        self._running = False

    async def _pre_market(self):
        """Piyasa öncesi hazırlık."""
        logger.info("=== PRE-MARKET ===")
        # İlk tarama
        summary = await alpha_engine.run_full_cycle()
        logger.info("Pre-market scan completed", **{k: v for k, v in summary.items() if not isinstance(v, list)})
        await asyncio.sleep(60)

    async def _market_hours(self):
        """Piyasa açıkken sürekli tarama."""
        logger.info("=== MARKET SCAN ===")

        # Alpha Engine tam döngü
        summary = await alpha_engine.run_full_cycle()

        # Sonuçları logla
        signals = summary.get("top_signals", [])
        anomalies = summary.get("anomalies", 0)

        if signals:
            logger.info("SIGNALS GENERATED", count=len(signals))
            for s in signals[:5]:
                logger.info(f"  {s['type']}: {s['ticker']} score={s['score']:.0f} {s['direction']}")

        if anomalies > 0:
            logger.warning("ANOMALIES DETECTED", count=anomalies)

        self._last_scan = datetime.now()
        self._scan_count += 1

        # 5 dakika bekle
        await asyncio.sleep(300)

    async def _post_market(self):
        """Piyasa sonrası rapor."""
        logger.info("=== POST-MARKET ===")
        summary = alpha_engine.get_last_summary()
        logger.info("Daily summary", **{k: v for k, v in summary.items() if not isinstance(v, list)})
        await asyncio.sleep(60)

    async def _daily_summary(self):
        """Günlük özet."""
        logger.info("=== DAILY SUMMARY ===")
        await asyncio.sleep(60)


async def main():
    scheduler = AlphaScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        await scheduler.stop()
    except Exception as e:
        logger.error("Scheduler crashed", error=str(e))
        await scheduler.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
