"""ALPHA BIST — Cache Warming (Sıcak Veri Önyükleme)

Servis başlarken sık kullanılan verileri Redis'e önceden yükler.
İlk istek yavaşlamasını önler.

Kullanım:
    from services.core.cache_warmer import cache_warmer
    await cache_warmer.warm_all()
"""

import asyncio
import time
from typing import List
import structlog

logger = structlog.get_logger()


class CacheWarmer:
    """Redis cache warming — sıcak veriyi önceden yükle."""

    def __init__(self):
        self._warmed = False
        self._warm_tasks: List[asyncio.Task] = []

    async def warm_all(self):
        """Tüm sıcak verileri paralel olarak yükle."""
        if self._warmed:
            logger.debug("Cache already warmed, skipping")
            return

        start = time.monotonic()
        logger.info("Cache warming started")

        tasks = [
            self._warm_bist_universe(),
            self._warm_market_calendar(),
            self._warm_latest_prices(),
            self._warm_active_signals(),
            self._warm_portfolio_state(),
            self._warm_risk_metrics(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if r is True)
        total = len(tasks)

        duration = (time.monotonic() - start) * 1000
        self._warmed = True
        logger.info("Cache warming completed",
                    success=f"{success}/{total}", duration_ms=round(duration, 1))

    async def _warm_bist_universe(self) -> bool:
        """BIST hisse listesini yükle."""
        try:
            from ..core.redis_helper import set_cached
            from ..ingestion.bist_universe import get_bist_universe
            universe = get_bist_universe()
            if universe:
                set_cached("bist:universe", universe, ttl=86400)  # 24 saat
                logger.debug("Warmed BIST universe", count=len(universe))
                return True
        except Exception as e:
            logger.debug("BIST universe warm failed", error=str(e))
        return False

    async def _warm_market_calendar(self) -> bool:
        """BIST seans takvimini yükle."""
        try:
            from ..core.redis_helper import set_cached
            from ..core.market_calendar import get_market_calendar
            calendar = get_market_calendar()
            if calendar:
                set_cached("market:calendar", calendar, ttl=86400)
                logger.debug("Warmed market calendar")
                return True
        except Exception as e:
            logger.debug("Market calendar warm failed", error=str(e))
        return False

    async def _warm_latest_prices(self) -> bool:
        """Son fiyatları yükle (radar cache)."""
        try:
            from ..core.redis_helper import get_cached
            # Mevcut radar verisi varsa tazele
            radar = get_cached("radar:data")
            if radar:
                logger.debug("Radar cache already warm", count=len(radar))
                return True
            # Yoksa TradingView'den çek
            from ..api.v1.market import _fetch_radar_fresh
            await _fetch_radar_fresh(limit=500)
            logger.debug("Warmed latest prices from TradingView")
            return True
        except Exception as e:
            logger.debug("Latest prices warm failed", error=str(e))
        return False

    async def _warm_active_signals(self) -> bool:
        """Aktif sinyalleri yükle."""
        try:
            from ..core.redis_helper import get_cached
            signals = get_cached("signals:latest")
            if signals:
                logger.debug("Signals cache already warm", count=len(signals))
                return True
        except Exception as e:
            logger.debug("Signals warm failed", error=str(e))
        return False

    async def _warm_portfolio_state(self) -> bool:
        """Portföy durumunu yükle."""
        try:
            from ..core.redis_helper import get_cached
            pf = get_cached("portfolio:state")
            if pf:
                logger.debug("Portfolio cache already warm")
                return True
        except Exception as e:
            logger.debug("Portfolio warm failed", error=str(e))
        return False

    async def _warm_risk_metrics(self) -> bool:
        """Risk metriklerini yükle."""
        try:
            from ..core.redis_helper import get_cached
            risk = get_cached("risk:metrics")
            if risk:
                logger.debug("Risk cache already warm")
                return True
        except Exception as e:
            logger.debug("Risk warm failed", error=str(e))
        return False

    async def refresh_hot_keys(self):
        """Sıcak anahtarları periyodik olarak tazele (background task)."""
        while True:
            try:
                await self._warm_latest_prices()
                await self._warm_active_signals()
            except Exception as e:
                logger.debug("Hot key refresh failed", error=str(e))
            await asyncio.sleep(30)  # 30 saniyede bir tazele


# Singleton
cache_warmer = CacheWarmer()
