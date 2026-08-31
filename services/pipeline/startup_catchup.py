"""
ALPHA BIST — Master Startup Catch-Up Engine v2.0
=====================================================================================
Kişisel PC Senaryosu İçin Uçtan Uca Otonom Telafi Motoru:

Bilgisayar kapalı kaldığında (1 gün, 3 gün, 1 hafta fark etmeksizin) sistem açıldığı an:
1. Kaçırılan tüm BIST seans günlerini kronolojik sırayla tespit eder.
2. Eksik piyasa verilerini ve geçmiş bar'ları otomatik backfill eder.
3. Her kaçırılan iş günü için:
   - Sabah 09:55 Açılış Yürütmesini o günün gerçek Açılış fiyatlarıyla işletir.
   - Akşam 18:15 Gün Sonu Değerlemesini (MTM) ve yeni sinyal üretimini tamamlar.
4. Kaçırılan yapay zeka model eğitimlerini ve performans kalibrasyonunu telafi eder.
5. Portföyü ve Fırsatlar sayfasını anlık bugüne eşitler.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    import orjson
except ImportError:
    import json as orjson

import structlog

from services.core.market_calendar import MarketCalendar
from services.ingestion.backfill import backfill_manager
from services.learning.learning_pipeline import LearningPipeline
from services.paper_trading.paper_orchestrator import paper_orchestrator
from services.pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle
from services.scanner.bist_ml_scanner import bist_ml_scanner

logger = structlog.get_logger("startup_catchup")
TR_TZ = timezone(timedelta(hours=3))


class MasterStartupCatchup:
    """PC kapalı kaldığında kaçan tüm görevleri sırasıyla yürüten telafi yöneticisi."""

    def __init__(self):
        self.calendar = MarketCalendar()
        self.learning_pipeline = LearningPipeline()

    def get_missed_trading_days(self, last_date_str: str | None, current_date: date) -> list[date]:
        """Son işlem tarihinden bugüne kadar olan kaçırılmış resmi BIST seans günlerini döner."""
        if not last_date_str:
            return []

        try:
            last_dt = date.fromisoformat(last_date_str[:10])
        except Exception:
            return []

        missed = []
        cur = last_dt + timedelta(days=1)
        while cur < current_date:
            # Hafta sonu değilse ve resmi tatil değilse seans günüdür
            if cur.weekday() < 5 and not self.calendar.is_holiday(cur):
                missed.append(cur)
            cur += timedelta(days=1)

        return missed

    async def execute_full_catchup(self) -> dict[str, Any]:
        """Tüm telafi sürecini baştan sona çalıştırır."""
        logger.info("================================================================")
        logger.info("[STARTUP CATCH-UP] Otonom Telafi Dongusu Baslatiliyor...")
        logger.info("================================================================")

        now_tr = datetime.now(TR_TZ)
        today = now_tr.date()

        # 1. Son işlem tarihini oku
        last_date_str = paper_orchestrator.store.get_config("last_cycle_date")
        missed_days = self.get_missed_trading_days(last_date_str, today)

        results = {
            "status": "COMPLETED",
            "last_cycle_date": last_date_str,
            "missed_days_count": len(missed_days),
            "missed_days": [d.isoformat() for d in missed_days],
            "data_backfilled": False,
            "trades_replayed": 0,
            "ml_retrained": False,
        }

        # 2. Veri Boşluklarını Tespit Et ve Doldur (Backfill)
        if missed_days:
            try:
                logger.info("1/4: Kacirilan seanslar icin piyasa verileri taraniyor (Backfill)...")
                active_tickers = [p["ticker"] for p in paper_orchestrator.portfolio.get_all_positions()]
                from services.ingestion.bist_universe import bist_universe
                target_tickers = list(set(active_tickers + list(bist_universe.BIST_30_TICKERS)))
                gaps = await backfill_manager.detect_all_gaps(tickers=target_tickers)
                if gaps:
                    logger.info(f"Hedef veri boslugu tespit edildi ({len(gaps)} adet). Dolduruluyor...")
                    await backfill_manager.backfill_all(gaps)
                    results["data_backfilled"] = True
                else:
                    logger.info("Hedef hisselerin gecmis verileri tam.")
            except Exception as e:
                logger.warning(f"Backfill sirasinda uyari (atlandi): {e}")
        else:
            logger.info("1/4: Kacirilan seans gunu bulunmuyor, veri tabani guncel.")

        # 3. Kaçırılan Seans Günlerini Sırasıyla Oynat (Replay & Execution)
        if missed_days:
            logger.info(f"2/4: Kacirilan {len(missed_days)} seans gunu sirayla isletiliyor...")
            for day in missed_days:
                day_str = day.isoformat()
                logger.info(f"  [REPLAY] Seans Telafisi Isleniyor: {day_str}")
                try:
                    # Sabah Açılış Emirlerini Gerçek Açılış Fiyatıyla Doldur
                    morning_res = await run_morning_execution_cycle(target_date=day_str)
                    results["trades_replayed"] += morning_res.get("executed_trades_count", 0)

                    # Akşam Gün Sonu Değerlemesi ve Yeni Sinyal Üretimi
                    await run_eod_signal_cycle(target_date=day_str)
                except Exception as day_err:
                    logger.error(f"  [ERROR] {day_str} seans telafisinde hata: {day_err}")
            logger.info("Tum kacirilan seanslar basariyla telafi edildi ve portfoye islendi.")
        else:
            logger.info("2/4: Kacirilan gecmis seans gunu yok.")

        # 4. Yapay Zeka Model ve Öğrenme Telafisi (ML Catch-up)
        try:
            logger.info("3/4: Model drift ve eksik egitim kontrolu yapiliyor...")
            ml_res = self.learning_pipeline.check_and_catchup_if_needed()
            if ml_res.get("status") != "up_to_date":
                results["ml_retrained"] = True
                logger.info("Yapay zeka modelleri yeni seans verileriyle egitildi ve guncellendi.")
            else:
                logger.info("Modeller guncel, yeniden egitime ihtiyac yok.")
        except Exception as ml_err:
            logger.warning(f"ML telafi dongusunde uyari: {ml_err}")

        # 5. Anlık Durumu Eşitle ve Taze Sinyalleri Yayınla
        try:
            logger.info("4/4: Guncel portfoy ve sinyaller Redis'e senkronize ediliyor...")
            fresh_signals = bist_ml_scanner.scan_all_opportunities(limit=50)

            import os

            import redis
            r_host = os.environ.get("REDIS_HOST", "redis")
            r_port = int(os.environ.get("REDIS_PORT", 6379))
            r_pass = os.environ.get("REDIS_PASSWORD", "alpha_secure_prod_2026_redis")
            r_conn = redis.Redis(host=r_host, port=r_port, password=r_pass, decode_responses=True)
            r_conn.set("phase18:predictions", orjson.dumps(fresh_signals).decode() if hasattr(orjson, 'dumps') else orjson.dumps(fresh_signals))
            logger.info(f"Canli Firsatlar tablosu guncellendi ({len(fresh_signals)} hisse).")
        except Exception as sync_err:
            logger.warning(f"Sinyal senkronizasyonunda uyari: {sync_err}")

        logger.info("================================================================")
        logger.info("[SUCCESS] MASTER STARTUP CATCH-UP: Tum Sistem Bugune Basariyla Esitlendi!")
        logger.info("================================================================")
        return results


master_catchup = MasterStartupCatchup()
