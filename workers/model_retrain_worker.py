"""
ALPHA BIST — Model Retrain Worker

ML modellerini yeniden eğitim worker'ı.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class ModelRetrainWorker:
    """ML model yeniden eğitim worker'ı."""

    def __init__(self):
        self._last_train_date: str | None = None
        self._train_count: int = 0

    def run(self, force: bool = False) -> dict[str, Any]:
        """Model yeniden eğitimini çalıştır."""
        today = datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")

        if not force and self._last_train_date == today:
            return {"status": "already_trained", "date": today}

        logger.info("Model retrain starting", date=today)
        result = {"date": today, "steps": {}}

        try:
            try:
                from services.learning.closed_loop import ClosedLoopLearning

                loop = ClosedLoopLearning()
                loop.evaluate_recent_predictions()
                result["steps"]["evaluation"] = "ok"
            except Exception as e:
                result["steps"]["evaluation"] = f"warning: {e}"

            try:
                from services.learning.weight_adjuster import WeightAdjuster

                adjuster = WeightAdjuster()
                adjuster.update_weights()
                result["steps"]["weight_update"] = "ok"
            except Exception as e:
                result["steps"]["weight_update"] = f"warning: {e}"

            result["status"] = "completed"
            self._last_train_date = today
            self._train_count += 1

        except Exception:
            result["status"] = "failed"

        return result

    def should_retrain(self) -> bool:
        if self._last_train_date is None:
            return True
        try:
            last = datetime.strptime(self._last_train_date, "%Y-%m-%d")
            return (datetime.now(UTC) - last).days >= 7
        except ValueError:
            return True

    def get_status(self) -> dict[str, Any]:
        return {
            "last_train_date": self._last_train_date,
            "train_count": self._train_count,
            "should_retrain": self.should_retrain(),
        }


model_retrain_worker = ModelRetrainWorker()
