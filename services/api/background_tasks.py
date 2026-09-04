"""Arka plan görevleri — lifespan'dan ayrılmış."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import logging
from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("alpha-bist.background_tasks")


async def radar_cache_refresher() -> Any:
    """BIST hisselerini TradingView'den çeker ve cache'i günceller.

    Seans saatlerinde 60 saniyede bir gerçek veri çeker.
    Seans kapalıyken 300 saniyede bir kontrol eder.
    """
    await asyncio.sleep(10)
    while True:
        current_phase = None
        try:
            from ..core.market_session_fsm import BISTMarketPhase, bist_session_fsm

            current_phase = bist_session_fsm.get_phase()

            if current_phase != BISTMarketPhase.CLOSED:
                from .v1.market import _fetch_radar_fresh

                with tracer.start_as_current_span("background.radar_cache_refresher.fetch"):
                    await _fetch_radar_fresh(limit=1000)

        except Exception as e:
            logger.warning("radar_cache_refresher_hatasi: hata=%s", e)

        try:
            if current_phase is not None and current_phase != BISTMarketPhase.CLOSED:
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(300)
        except Exception:
            await asyncio.sleep(60)


async def ml_learning_scheduler() -> Any:
    """ML eğitimleri müstakil alpha-learning konteynerinde yürütülür; API hafif kalır.

    Bu fonksiyon bir yer tutucudur. ML eğitimleri ayrı bir servise delege edilmiştir.
    Gelecekte bu fonksiyon, eğitim durumunu izlemek veya sonuçları toplamak için genişletilebilir.
    """
    logger.info("ml_scheduler: ML eğitimleri müstakil alpha-learning servisine delege edildi.")
    while True:
        await asyncio.sleep(86400)


async def auto_storage_optimizer() -> Any:
    """Arka planda otomatik ClickHouse ZSTD sıkıştırma ve önbellek temizliği yapar."""
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            from ..core.database import ch_execute

            with tracer.start_as_current_span("background.auto_storage_optimizer"):
                ch_execute("OPTIMIZE TABLE bist_ticks FINAL")
            logger.info("auto_storage_optimizer: Periyodik ZSTD disk sıkıştırması ve temizliği tamamlandı.")
        except Exception as e:
            logger.warning("auto_storage_optimizer_hatasi: hata=%s", e)


async def paper_trading_scheduler() -> Any:
    """BIST seans takvimine göre çalışır: 18:15 EOD sinyal üretimi & 09:55 sabah açılışı yürütme."""
    TR_TZ = timezone(timedelta(hours=3))

    await asyncio.sleep(5)
    try:
        from ...pipeline.startup_catchup import master_catchup

        logger.info("paper_trading_scheduler: Başlangıç Master Catch-up (Tüm eksik seanslar ve eğitimler) başlatılıyor...")
        with tracer.start_as_current_span("background.paper_trading_scheduler.master_catchup"):
            await master_catchup.execute_full_catchup()
    except Exception as e:
        logger.warning("paper_trading_scheduler_master_catchup_hatasi: hata=%s", e)

    while True:
        now = datetime.now(TR_TZ)
        t_morning = now.replace(hour=9, minute=55, second=0, microsecond=0)
        t_eod = now.replace(hour=18, minute=15, second=0, microsecond=0)

        upcoming = []
        if now < t_morning:
            upcoming.append((t_morning, "MORNING"))
        if now < t_eod:
            upcoming.append((t_eod, "EOD"))
        if not upcoming:
            upcoming.append((t_morning + timedelta(days=1), "MORNING"))

        target_time, phase = min(upcoming, key=lambda x: x[0])
        sleep_seconds = (target_time - now).total_seconds()
        logger.info(
            "paper_trading_scheduler: %s sn sonra (%s - %s TR) tetiklenecek.",
            f"{sleep_seconds:.1f}", phase, target_time.strftime('%H:%M')
        )
        await asyncio.sleep(sleep_seconds)

        if datetime.now(TR_TZ).weekday() < 5:
            try:
                from ...pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle

                if phase == "MORNING":
                    logger.info("paper_trading_scheduler: Sabah açılışı yürütme döngüsü başlıyor...")
                    with tracer.start_as_current_span("background.paper_trading_scheduler.morning"):
                        await run_morning_execution_cycle()
                else:
                    logger.info("paper_trading_scheduler: EOD sinyal üretim ve MTM döngüsü başlıyor...")
                    with tracer.start_as_current_span("background.paper_trading_scheduler.eod"):
                        await run_eod_signal_cycle()
            except Exception as e:
                logger.error("paper_trading_scheduler_hatasi: phase=%s hata=%s", phase, e)
            finally:
                await asyncio.sleep(60)
