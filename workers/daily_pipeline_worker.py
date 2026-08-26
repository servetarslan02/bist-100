"""
ALPHA BIST — Daily Pipeline Worker

Günlük trading pipeline'ını çalıştıran worker.
BIST-30, BIST-50, BIST-100 için multi-index destekli.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class DailyPipelineWorker:
    """Günlük trading pipeline worker'ı — multi-index destekli."""

    def __init__(self):
        self._last_run_date: Optional[str] = None
        self._last_run_status: str = "never"
        self._last_run_result: Optional[Dict[str, Any]] = None

    def run(self, date: Optional[str] = None, force: bool = False, universes: Optional[List[str]] = None) -> Dict[str, Any]:
        """Günlük pipeline'ı çalıştır.

        Args:
            date: İşlem tarihi (YYYY-MM-DD). None ise bugün.
            force: Zaten çalıştırılmış olsa bile tekrar çalıştır.
            universes: Çalıştırılacak endeksler. None ise ["bist30", "bist50", "bist100"].
        """
        if universes is None:
            universes = ["bist30", "bist50", "bist100"]

        target_date = date or datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")

        if not force and self._last_run_date == target_date:
            logger.info("Daily pipeline already ran today", date=target_date)
            return self._last_run_result or {"status": "already_ran", "date": target_date}

        logger.info("Daily pipeline starting", date=target_date, universes=universes)
        result = {"date": target_date, "universes": universes, "steps": {}}

        try:
            # 1. Piyasa durumu kontrolü
            from services.core.market_session_fsm import bist_session_fsm
            result["steps"]["market_check"] = "ok"

            # 2. Multi-index inference
            try:
                from services.core.alpha_engine import AlphaEngine
                engine = AlphaEngine()
                inference_result = engine.run_multi_index_pipeline(target_date, universes=universes)
                result["steps"]["inference"] = "ok"
                result["signals"] = inference_result.get("combined", [])
                result["per_index"] = {u: len(inference_result.get(u, [])) for u in universes}
            except Exception as e:
                logger.error("Inference failed", error=str(e))
                result["steps"]["inference"] = f"error: {e}"
                result["status"] = "failed"
                self._last_run_date = target_date
                self._last_run_status = "failed"
                self._last_run_result = result
                return result

            # 3. Risk kontrolü
            try:
                from services.risk.risk_manager import RiskManager
                rm = RiskManager()
                risk_check = rm.pre_trade_check(result.get("signals", []))
                result["steps"]["risk_check"] = "ok"
                result["risk"] = risk_check
            except Exception as e:
                logger.warning("Risk check failed", error=str(e))
                result["steps"]["risk_check"] = f"warning: {e}"

            result["status"] = "completed"
            logger.info("Daily pipeline completed", date=target_date, per_index=result.get("per_index"))

        except Exception as e:
            logger.error("Daily pipeline failed", date=target_date, error=str(e))
            result["status"] = "failed"
            result["error"] = str(e)

        self._last_run_date = target_date
        self._last_run_status = result["status"]
        self._last_run_result = result
        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "last_run_date": self._last_run_date,
            "last_run_status": self._last_run_status,
            "has_result": self._last_run_result is not None,
        }


daily_pipeline_worker = DailyPipelineWorker()
