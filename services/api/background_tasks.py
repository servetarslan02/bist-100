"""Arka plan görevleri — lifespan'dan ayrılmış."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger(__name__)


async def radar_cache_refresher():
    """BIST hisselerini TradingView'den çeker ve cache'i günceller.
    
    Seans saatlerinde her 2 saniyede bir gerçek veri çeker.
    Seans kapalıyken daha seyrek kontrol eder.
    """
    await asyncio.sleep(2)
    while True:
        try:
            from services.core.market_session_fsm import bist_session_fsm, BISTMarketPhase
            current_phase = bist_session_fsm.get_phase()

            if current_phase != BISTMarketPhase.CLOSED:
                # Seans açık — gerçek veri çek
                from .v1.market import _fetch_radar_fresh
                await _fetch_radar_fresh(limit=1000)
            # else: Seans kapalı — cache'i koru, sahte veri üretme

        except Exception as e:
            logger.warning(f"radar_cache_refresher error: {e}")
        
        # Seans açıkken sık, kapalıyken seyrek güncelle
        try:
            if current_phase != BISTMarketPhase.CLOSED:
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(10)


async def ml_learning_scheduler():
    """PC kapalı kaldığında kaçırılan eğitimleri tamamlar ve 4 saatte bir otonom öğrenir."""
    await asyncio.sleep(15)

    try:
        from ..learning.learning_pipeline import LearningPipeline
        pipeline = LearningPipeline()
        loop = asyncio.get_event_loop()
        logger.info("ml_scheduler: Başlangıç eksik eğitim/veri telafi kontrolü yapılıyor...")
        await loop.run_in_executor(None, pipeline.check_and_catchup_if_needed)
        logger.info("ml_scheduler: Başlangıç telafi kontrolü tamamlandı.")
    except Exception as e:
        logger.warning(f"ml_scheduler startup catchup error: {e}")

    while True:
        await asyncio.sleep(4 * 3600)
        try:
            from ..learning.learning_pipeline import LearningPipeline
            pipeline = LearningPipeline()
            loop = asyncio.get_event_loop()
            logger.info("ml_scheduler: Periyodik öğrenme döngüsü başlatılıyor...")
            await loop.run_in_executor(None, pipeline.run_learning_cycle)
            logger.info("ml_scheduler: Periyodik öğrenme başarıyla tamamlandı.")
        except Exception as e:
            logger.warning(f"ml_scheduler periodic error: {e}")


async def auto_storage_optimizer():
    """Arka planda otomatik ClickHouse ZSTD sıkıştırma ve önbellek temizliği yapar."""
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            from ..core.database import ch_execute
            ch_execute("OPTIMIZE TABLE bist_ticks FINAL")
            logger.info("auto_storage_optimizer: Periyodik ZSTD disk sıkıştırması ve temizliği tamamlandı.")
        except Exception as e:
            logger.warning(f"auto_storage_optimizer: {e}")


async def paper_trading_scheduler():
    """BIST seans takvimine göre çalışır: 18:15 EOD sinyal üretimi & 09:55 sabah açılışı yürütme."""
    TR_TZ = timezone(timedelta(hours=3))

    await asyncio.sleep(5)
    try:
        from services.paper_trading.paper_orchestrator import paper_orchestrator
        from services.pipeline.run_unified_daily import run_morning_execution_cycle
        cur_pos = paper_orchestrator.portfolio.get_all_positions()
        pending = paper_orchestrator.store.load_pending_signals()
        now_tr = datetime.now(TR_TZ)
        if now_tr.weekday() < 5 and (len(cur_pos) == 0 or len(pending) > 0):
            logger.info("paper_trading_scheduler: Başlangıç otonom portföy başlatma/telafi döngüsü çalıştırılıyor...",
                       positions=len(cur_pos), pending=len(pending))
            await run_morning_execution_cycle()
    except Exception as e:
        logger.warning(f"paper_trading_scheduler startup catchup error: {e}")

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
        logger.info(f"paper_trading_scheduler: {sleep_seconds:.1f} sn sonra ({phase} - {target_time.strftime('%H:%M')} TR) tetiklenecek.")
        await asyncio.sleep(sleep_seconds)

        if datetime.now(TR_TZ).weekday() < 5:
            try:
                from services.pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle
                if phase == "MORNING":
                    logger.info("paper_trading_scheduler: Sabah açılışı yürütme döngüsü başlıyor...")
                    await run_morning_execution_cycle()
                else:
                    logger.info("paper_trading_scheduler: EOD sinyal üretim ve MTM döngüsü başlıyor...")
                    await run_eod_signal_cycle()
            except Exception as e:
                logger.error(f"paper_trading_scheduler error in {phase}: {e}")
            finally:
                await asyncio.sleep(60)
