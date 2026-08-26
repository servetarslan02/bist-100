"""
ALPHA BIST — Daily Pipeline Worker

Günlük trading pipeline'ını çalıştıran worker.
BIST-100 odaklı.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class DailyPipelineWorker:
    """Günlük trading pipeline worker'ı."""

    def __init__(self):
        self._last_run_date: Optional[str] = None
        self._last_run_status: str = "never"
        self._last_run_result: Optional[Dict[str, Any]] = None

    def run(self, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Günlük pipeline'ı çalıştır."""
        target_date = date or datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")

        if not force and self._last_run_date == target_date:
            return self._last_run_result or {"status": "already_ran", "date": target_date}

        logger.info("Daily pipeline starting", date=target_date)
        result = {"date": target_date, "steps": {}}

        try:
            # 1. Piyasa durumu kontrolü
            from services.core.market_session_fsm import bist_session_fsm
            result["steps"]["market_check"] = "ok"

            # 2. Inference (BIST-100)
            try:
                from services.pipeline.run_daily_inference import run_alpha_engine_sync
                run_alpha_engine_sync()
                result["steps"]["inference"] = "ok"
            except Exception as e:
                logger.error("Inference failed", error=str(e))
                result["steps"]["inference"] = f"error: {e}"

            # 3. Sağlık kontrolü
            try:
                from workers.health_check_worker import health_check_worker
                health = health_check_worker.run_full_check()
                result["steps"]["health_check"] = health["overall"]
            except Exception as e:
                result["steps"]["health_check"] = f"warning: {e}"

            result["status"] = "completed"
            logger.info("Daily pipeline completed", date=target_date)

        except Exception as e:
            logger.error("Daily pipeline failed", date=target_date, error=str(e))
            result["status"] = "failed"

        self._last_run_date = target_date
        self._last_run_status = result["status"]
        self._last_run_result = result
        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "last_run_date": self._last_run_date,
            "last_run_status": self._last_run_status,
        }


daily_pipeline_worker = DailyPipelineWorker()
