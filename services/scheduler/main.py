"""
ALPHA BIST — Scheduler v2.0

3 katmanlı tarama zamanlaması:
- Layer 1: Live Scanner → sürekli (tick bazlı)
- Layer 2: Batch Scanner → günde 5 kez (09:50, 12:00, 15:00, 17:50)
- Layer 3: Event Scanner → event geldiğinde immediate
"""

import asyncio
from datetime import datetime
import structlog

from ..scanner.alpha_engine import alpha_engine
from ..ingestion.bist_universe import bist_universe

logger = structlog.get_logger()


class AlphaScheduler:
    """Otonom scheduler — 3 katmanlı tarama."""

    def __init__(self):
        self._running = False
        self._last_batch_scan = None
        self._batch_scan_times = [9, 12, 15, 17]  # Saat başları

    async def start(self):
        """Scheduler'ı başlat."""
        self._running = True

        # Universe yükle
        tickers = bist_universe.get_tickers()
        alpha_engine.load_universe(tickers)
        logger.info("ALPHA Scheduler started", universe=len(tickers))

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
                    # Layer 2: Batch scan zamanı mı?
                    if hour in self._batch_scan_times and minute < 5:
                        await self._batch_scan()
                    else:
                        # Normal saatler — bekle
                        await asyncio.sleep(60)

                elif hour == 9 and minute >= 50:
                    # Piyasa öncesi
                    await self._pre_market()

                elif hour == 18 and minute <= 30:
                    # Piyasa sonrası
                    await self._post_market()

                elif hour == 23 and minute <= 10:
                    # Günlük özet
                    await self._daily_summary()

                else:
                    await asyncio.sleep(60)

            except Exception as e:
                logger.error("Scheduler error", error=str(e))
                await asyncio.sleep(30)

    async def stop(self):
        self._running = False

    async def _pre_market(self):
        """Piyasa öncesi hazırlık — ilk batch scan."""
        logger.info("=== PRE-MARKET ===")
        summary = await alpha_engine.run_batch_scan()
        self._last_batch_scan = datetime.now()
        logger.info("Pre-market scan completed",
                    signals=summary.get("signals_generated", 0))
        await asyncio.sleep(60)

    async def _batch_scan(self):
        """Batch tarama — günde 5 kez."""
        logger.info("=== BATCH SCAN ===")
        summary = await alpha_engine.run_batch_scan()
        self._last_batch_scan = datetime.now()

        signals = summary.get("top_signals", [])
        anomalies = summary.get("anomalies", 0)

        if signals:
            logger.info("SIGNALS", count=len(signals))
            for s in signals[:5]:
                logger.info(f"  {s['type']}: {s['ticker']} score={s['score']:.0f}")

        if anomalies > 0:
            logger.warning("ANOMALIES", count=anomalies)

        # Sonraki batch'e kadar bekle
        await asyncio.sleep(300)

    async def _post_market(self):
        """Piyasa sonrası rapor."""
        logger.info("=== POST-MARKET ===")
        summary = alpha_engine.get_last_summary()
        logger.info("Daily summary",
                    scanned=summary.get("total_scanned", 0),
                    signals=summary.get("signals_generated", 0))
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
