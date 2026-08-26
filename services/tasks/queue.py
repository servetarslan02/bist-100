"""ALPHA BIST — Async Task Queue (Celery + Redis Broker)

Arka plan görevleri için Celery task queue.
Redis broker olarak kullanır (mevcut Redis stack'in üzerine).

Kullanım:
    from services.tasks.queue import celery_app, run_backtest_task

    # Async görev başlat
    result = run_backtest_task.delay(ticker="THYAO", days=30)

    # Sonucu bekle
    value = result.get(timeout=60)
"""

import os
from typing import Any, Dict, Optional
import structlog

try:
    from celery import Celery
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False

logger = structlog.get_logger()


# =====================================================
# Celery App
# =====================================================

def _get_broker_url() -> str:
    """Redis broker URL'ini oluştur."""
    password = os.environ.get("REDIS_PASSWORD", "")
    host = os.environ.get("REDIS_HOST", "redis")
    port = os.environ.get("REDIS_PORT", "6379")
    if password:
        return f"redis://:{password}@{host}:{port}/1"  # DB 1: task queue
    return f"redis://{host}:{port}/1"


if HAS_CELERY:
    celery_app = Celery(
        "alpha_bist",
        broker=_get_broker_url(),
        backend=_get_broker_url(),
    )

    # Task configuration
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Europe/Istanbul",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,  # Task tamamlanmadan ack'leme (crash safety)
        worker_prefetch_multiplier=1,  # Adaletli task dağıtımı
        task_soft_time_limit=300,  # 5 dakika soft limit
        task_time_limit=600,  # 10 dakika hard limit
        task_default_retry_delay=30,  # 30 saniye retry
        task_max_retries=3,
        broker_connection_retry_on_startup=True,
    )

    # =====================================================
    # Task Definitions
    # =====================================================

    @celery_app.task(bind=True, name="tasks.backtest")
    def run_backtest_task(self, ticker: str, days: int = 30) -> Dict[str, Any]:
        """Backtest görevi — arka planda çalışır."""
        try:
            from services.backtest.engine import BacktestEngine
            engine = BacktestEngine()
            result = engine.run_walk_forward(ticker=ticker, lookback_days=days)
            return {"status": "completed", "ticker": ticker, "result": result}
        except Exception as e:
            logger.error("Backtest task failed", ticker=ticker, error=str(e))
            raise self.retry(exc=e)

    @celery_app.task(bind=True, name="tasks.model_train")
    def train_model_task(self, model_type: str = "lightgbm") -> Dict[str, Any]:
        """Model eğitim görevi — GPU gerektirir."""
        try:
            from services.ml.train_all_models import train_all
            result = train_all(model_type=model_type)
            return {"status": "completed", "model_type": model_type, "result": result}
        except Exception as e:
            logger.error("Model train task failed", error=str(e))
            raise self.retry(exc=e)

    @celery_app.task(bind=True, name="tasks.data_backfill")
    def data_backfill_task(self, days: int = 30) -> Dict[str, Any]:
        """Veri backfill görevi — eksik günleri tamamla."""
        try:
            from scripts.backfill_data import backfill
            result = backfill(days=days)
            return {"status": "completed", "days": days, "result": result}
        except Exception as e:
            logger.error("Data backfill task failed", error=str(e))
            raise self.retry(exc=e)

    @celery_app.task(bind=True, name="tasks.report_generate")
    def generate_report_task(self, report_type: str = "daily") -> Dict[str, Any]:
        """Rapor oluşturma görevi."""
        try:
            from services.core.reporting import generate_report
            result = generate_report(report_type=report_type)
            return {"status": "completed", "report_type": report_type}
        except Exception as e:
            logger.error("Report task failed", error=str(e))
            raise self.retry(exc=e)

    @celery_app.task(bind=True, name="tasks.risk_stress_test")
    def stress_test_task(self, portfolio_value: float = 10_000_000) -> Dict[str, Any]:
        """Stres testi görevi — Monte Carlo simülasyonu."""
        try:
            from services.risk.stress_test import StressTestEngine
            engine = StressTestEngine()
            portfolio = {"total_value": portfolio_value, "positions": {}}
            report = engine.run_all_scenarios(portfolio)
            return {"status": "completed", "risk_score": report.risk_score}
        except Exception as e:
            logger.error("Stress test task failed", error=str(e))
            raise self.retry(exc=e)

    logger.info("Celery task queue initialized", broker=_get_broker_url())

else:
    celery_app = None
    logger.warning("Celery not installed — task queue unavailable")

# =====================================================
# Convenience Functions (sync wrapper)
# =====================================================

def submit_task(task_name: str, *args, **kwargs) -> Optional[str]:
    """Görevi kuyruğa al. Task ID döndürür."""
    if not celery_app:
        logger.warning("Celery not available, running inline")
        return None

    task_map = {
        "backtest": run_backtest_task,
        "model_train": train_model_task,
        "data_backfill": data_backfill_task,
        "report": generate_report_task,
        "stress_test": stress_test_task,
    }

    task = task_map.get(task_name)
    if not task:
        logger.error("Unknown task", task_name=task_name)
        return None

    result = task.delay(*args, **kwargs)
    logger.info("Task submitted", task_name=task_name, task_id=result.id)
    return result.id


def get_task_status(task_id: str) -> Dict[str, Any]:
    """Görev durumunu sorgula."""
    if not celery_app:
        return {"status": "unavailable", "error": "Celery not installed"}

    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
