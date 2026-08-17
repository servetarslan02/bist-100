"""ALPHA BIST — Production Scheduler v3.0

Market session-aware job scheduling.
Uses: MarketSessionManager + JobWorker + system_jobs DB table.
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable
import structlog

from services.core.market_session import market_session, MarketPhase
from services.core.worker import job_worker, JobType

logger = structlog.get_logger()


class ProductionScheduler:
    """Production-grade scheduler.

    Market session aware: trading job'ları sadece piyasa açıkken çalışır.
    DB-backed job tracking: system_jobs tablosu.
    Config-driven intervals.
    """

    # Varsayılan job interval'ları (saniye)
    DEFAULT_INTERVALS = {
        "feature_calculation": 300,    # 5 dakika
        "live_inference": 300,         # 5 dakika
        "health_check": 60,            # 1 dakika
        "market_data_update": 120,     # 2 dakika
        "ranking": 600,                # 10 dakika
        "signal_generation": 600,      # 10 dakika
        "persistence": 900,            # 15 dakika
        "daily_report": 86400,         # 1 gün
    }

    def __init__(self, intervals: Optional[Dict[str, int]] = None):
        self._intervals = {**self.DEFAULT_INTERVALS, **(intervals or {})}
        self._running = False
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._last_run: Dict[str, float] = {}

    def register_handler(self, job_type: str, handler: Callable[..., Awaitable[Any]]):
        """Job handler kaydet."""
        self._handlers[job_type] = handler
        logger.info("Handler registered", job_type=job_type)

    async def start(self):
        """Scheduler'ı başlat."""
        self._running = True
        logger.info("Production scheduler starting", phase=market_session.current_phase().value)

        # Startup sequence
        await self._startup_sequence()

        # Main loop
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler tick error", error=str(e))
                await asyncio.sleep(10)

        logger.info("Scheduler stopped")

    async def stop(self):
        """Scheduler'ı durdur."""
        self._running = False
        await job_worker.shutdown(timeout=30)
        logger.info("Scheduler stop requested")

    async def _startup_sequence(self):
        """Startup'ta çalışacak kontroller."""
        from .config import settings
        from .database import check_db_health

        logger.info("=== STARTUP SEQUENCE ===")

        # 1. Config validation
        env = settings.app_env
        logger.info(f"Config loaded: env={env}")

        # 2. DB health
        health = await check_db_health()
        for svc, status in health.items():
            level = "info" if status == "healthy" else "warning"
            getattr(logger, level)(f"DB: {svc} = {status}")

        # 3. Market session
        session_status = market_session.get_status()
        logger.info("Market session", **session_status)

        logger.info("=== STARTUP COMPLETE ===")

    async def _tick(self):
        """Tek scheduler döngüsü."""
        phase = market_session.current_phase()

        if phase == MarketPhase.CLOSED:
            # Piyasa kapalı — sadece health check
            await self._maybe_run("health_check", trading_only=False)
            sleep_time = min(market_session.seconds_until_next_phase(), 300)
            await asyncio.sleep(max(sleep_time, 30))
            return

        if phase == MarketPhase.PRE_MARKET:
            await self._maybe_run("market_data_update", trading_only=False)
            await self._maybe_run("feature_calculation", trading_only=False)
            await asyncio.sleep(30)
            return

        if phase == MarketPhase.ACTIVE:
            # Aktif trading — tüm job'lar çalışabilir
            for job_type in ["market_data_update", "feature_calculation",
                             "live_inference", "ranking", "signal_generation",
                             "health_check"]:
                await self._maybe_run(job_type, trading_only=True)
            await asyncio.sleep(30)
            return

        if phase == MarketPhase.POST_MARKET:
            await self._maybe_run("persistence", trading_only=False)
            await self._maybe_run("daily_report", trading_only=False)
            await asyncio.sleep(30)
            return

        if phase == MarketPhase.AFTER_HOURS:
            await self._maybe_run("health_check", trading_only=False)
            await asyncio.sleep(300)
            return

    async def _maybe_run(self, job_type: str, trading_only: bool = True):
        """Job çalıştırılmalı mı? Interval kontrolü yap."""
        now = time.time()
        interval = self._intervals.get(job_type, 300)
        last = self._last_run.get(job_type, 0)

        if now - last < interval:
            return

        handler = self._handlers.get(job_type)
        if handler is None:
            return

        # Trading-only job'lar sadece piyasa açıkken
        if trading_only and not market_session.should_run_trading_job():
            return

        self._last_run[job_type] = now

        # Job'ı worker'a gönder
        try:
            job_id = await job_worker.submit_job(
                job_type=job_type,
                handler=handler,
                payload={"phase": market_session.current_phase().value},
                timeout=self._intervals.get(job_type, 300),
            )
            if job_id:
                logger.info("Job scheduled", job_type=job_type, job_id=job_id)
        except Exception as e:
            logger.error("Failed to schedule job", job_type=job_type, error=str(e))


# Singleton
production_scheduler = ProductionScheduler()
