"""ALPHA BIST — Cache Warming (Sıcak Veri Önyükleme)

Servis başlarken sık kullanılan verileri Redis'e önceden yükler.
İlk istek yavaşlamasını önler.

Kullanım:
    from services.core.cache_warmer import cache_warmer
    await cache_warmer.warm_all()
"""

import asyncio
import time

import structlog

logger = structlog.get_logger()


class CacheWarmer:
    """Redis cache warming — sıcak veriyi önceden yükle."""

    def __init__(self):
        self._warmed = False
        self._warm_tasks: list[asyncio.Task] = []

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
        logger.info("Cache warming completed", success=f"{success}/{total}", duration_ms=round(duration, 1))

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
        """BIST seans takvimini yükle + tatil takvimini senkronize et."""
        try:
            from ..core.market_calendar import get_market_calendar
            from ..core.redis_helper import set_cached
            from ..core.holiday_manager import holiday_manager
            from datetime import date

            # Tatil takvimini hesapla + BIST'ten çek
            today = date.today()
            holidays = holiday_manager.get_holidays(today.year)
            half_days = holiday_manager.get_half_days(today.year)
            synced = await holiday_manager.sync_from_bist()

            calendar = get_market_calendar()
            if calendar:
                set_cached("market:calendar", calendar, ttl=86400)
                logger.info(
                    "Market calendar warmed",
                    holidays=len(holidays),
                    half_days=len(half_days),
                    bist_synced=synced,
                )
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
        """Sıcak anahtarları periyodik olarak tazele (background task).

        v2.0: KAP anlık duyuru izleme eklendi.
        """
        from datetime import date

        while True:
            try:
                await self._warm_latest_prices()
                await self._warm_active_signals()

                today = date.today()
                if today.weekday() < 5:  # Hafta içi
                    from ..core.holiday_manager import holiday_manager
                    from ..core.market_calendar import get_market_calendar
                    from datetime import UTC, datetime, time as dtime

                    now = datetime.now(UTC)
                    market_open = dtime(10, 0)
                    market_close = dtime(18, 0)

                    # 1. KAP anlık duyuru izleme (her saat)
                    try:
                        kap_holidays = await holiday_manager.check_kap_for_holidays()
                        if kap_holidays:
                            logger.warning(
                                "KAP holiday announcement detected by cache warmer",
                                dates=[d.isoformat() for d in kap_holidays],
                            )
                    except Exception as e:
                        logger.debug("KAP check failed", error=str(e))

                    # 2. Radar verisi kontrolü (piyasa açık saatlerde)
                    if market_open <= now.time() <= market_close:
                        calendar = get_market_calendar()
                        if calendar.is_trading_day(today):
                            from ..core.redis_helper import get_cached
                            radar = get_cached("radar:data")
                            if not radar:
                                detected = holiday_manager.report_no_data(today)
                                if detected:
                                    logger.warning(
                                        "Sudden holiday detected by cache warmer",
                                        date=today.isoformat(),
                                    )

            except Exception as e:
                logger.debug("Hot key refresh failed", error=str(e))
            await asyncio.sleep(3600)  # 1 saatte bir tazele


# Singleton
cache_warmer = CacheWarmer()
