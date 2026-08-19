"""
ALPHA BIST — Scheduler API v1.0

Scheduler istatistiklerini API'den erişilebilir yapar.
Dashboard ve monitoring için endpoint'ler.

Endpoint'ler:
- GET /api/scheduler/status — scheduler durumu
- GET /api/scheduler/jobs — job listesi
- GET /api/scheduler/monitor — job monitoring
- GET /api/scheduler/workflow — workflow durumu
- GET /api/scheduler/learning — learning scheduler durumu
- POST /api/scheduler/trigger/{job} — manuel tetikleme
"""

from typing import Dict, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class SchedulerAPI:
    """Scheduler API endpoint'leri."""

    def __init__(self):
        from .unified_scheduler import unified_scheduler
        from .job_monitor import job_monitor
        from .daily_workflow import daily_workflow
        from .learning_scheduler import learning_scheduler

        self._scheduler = unified_scheduler
        self._monitor = job_monitor
        self._workflow = daily_workflow
        self._learning = learning_scheduler

    def get_status(self) -> Dict[str, Any]:
        """Scheduler durumu.

        Returns:
            Tam durum bilgisi
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scheduler": self._scheduler.get_status(),
            "workflow": self._workflow.get_status().__dict__,
            "learning": self._learning.get_status(),
        }

    def get_jobs(self) -> Dict[str, Any]:
        """Job listesi.

        Returns:
            Job konfigürasyonları
        """
        configs = self._scheduler._configs
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_jobs": len(configs),
            "jobs": {
                name: {
                    "interval_seconds": config.interval_seconds,
                    "trading_only": config.trading_only,
                    "priority": config.priority,
                    "enabled": config.enabled,
                    "max_retries": config.max_retries,
                    "timeout_seconds": config.timeout_seconds,
                    "description": config.description,
                }
                for name, config in configs.items()
            },
        }

    def get_monitor(self, job_type: str = None) -> Dict[str, Any]:
        """Job monitoring.

        Args:
            job_type: Job türü filtresi

        Returns:
            Monitoring istatistikleri
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": self._monitor.get_stats(job_type),
            "slow_jobs": self._monitor.get_slow_jobs(),
            "alerts": self._monitor.get_alerts(limit=20),
            "summary": self._monitor.get_summary(),
        }

    def get_workflow(self) -> Dict[str, Any]:
        """Workflow durumu.

        Returns:
            Workflow bilgileri
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self._workflow.get_status().__dict__,
            "phases": self._workflow.get_phases(),
        }

    def get_learning(self) -> Dict[str, Any]:
        """Learning scheduler durumu.

        Returns:
            Learning bilgileri
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self._learning.get_status(),
            "pending_jobs": self._learning.get_pending_jobs(),
        }

    def get_market_session(self) -> Dict[str, Any]:
        """Market session durumu.

        Returns:
            Market session bilgileri
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market": self._scheduler.get_market_session().get_status(),
        }

    def get_job_history(self, limit: int = 50) -> Dict[str, Any]:
        """Job geçmişi.

        Args:
            limit: Maksimum kayıt

        Returns:
            Job geçmişi
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "history": self._scheduler.get_job_history(limit),
        }

    def get_full_dashboard(self) -> Dict[str, Any]:
        """Tam dashboard verisi.

        Returns:
            Tüm istatistikler
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self.get_status(),
            "jobs": self.get_jobs(),
            "monitor": self.get_monitor(),
            "workflow": self.get_workflow(),
            "learning": self.get_learning(),
            "market": self.get_market_session(),
        }


# Singleton
scheduler_api = SchedulerAPI()
