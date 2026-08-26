"""
ALPHA BIST — Model Retrain Worker

ML modellerini yeniden eğitim worker'ı.
Kapalı devre öğrenme döngüsü ile entegre.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class ModelRetrainWorker:
    """ML model yeniden eğitim worker'ı."""

    def __init__(self):
        self._last_train_date: Optional[str] = None
        self._last_train_status: str = "never"
        self._train_count: int = 0

    def run(self, force: bool = False, universes: Optional[list] = None) -> Dict[str, Any]:
        """Model yeniden eğitimini çalıştır.

        Args:
            force: Zaten eğitilmiş olsa bile tekrar eğit.
            universes: Eğitilecek endeksler. None ise tümü.
        """
        today = datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")

        if not force and self._last_train_date == today:
            return {"status": "already_trained", "date": today}

        if universes is None:
            universes = ["bist30", "bist50", "bist100"]

        logger.info("Model retrain starting", date=today, universes=universes)
        result = {"date": today, "universes": universes, "steps": {}}

        try:
            # Kapalı devre öğrenme
            try:
                from services.learning.closed_loop import ClosedLoopLearning
                loop = ClosedLoopLearning()
                eval_result = loop.evaluate_recent_predictions()
                result["steps"]["evaluation"] = "ok"
                result["evaluation"] = eval_result
            except Exception as e:
                result["steps"]["evaluation"] = f"warning: {e}"

            # Ağırlık güncelleme
            try:
                from services.learning.weight_adjuster import WeightAdjuster
                adjuster = WeightAdjuster()
                weights = adjuster.update_weights()
                result["steps"]["weight_update"] = "ok"
            except Exception as e:
                result["steps"]["weight_update"] = f"warning: {e}"

            result["status"] = "completed"
            self._last_train_date = today
            self._last_train_status = "completed"
            self._train_count += 1

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            self._last_train_status = "failed"

        return result

    def should_retrain(self) -> bool:
        """Yeniden eğitim gerekli mi?"""
        if self._last_train_date is None:
            return True
        try:
            last = datetime.strptime(self._last_train_date, "%Y-%m-%d")
            return (datetime.now() - last).days >= 7
        except ValueError:
            return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "last_train_date": self._last_train_date,
            "last_train_status": self._last_train_status,
            "train_count": self._train_count,
            "should_retrain": self.should_retrain(),
        }


model_retrain_worker = ModelRetrainWorker()
