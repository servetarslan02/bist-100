"""
ALPHA BIST — Scheduler API v2.0

Scheduler istatistiklerini API'den erişilebilir yapar.
Dashboard ve monitoring için endpoint'ler.

Endpoint'ler:
- GET  /api/scheduler/status         — scheduler durumu
- GET  /api/scheduler/jobs           — job listesi + konfigürasyonlar
- GET  /api/scheduler/monitor        — job monitoring istatistikleri
- GET  /api/scheduler/workflow       — workflow durumu
- GET  /api/scheduler/learning       — learning scheduler durumu
- GET  /api/scheduler/market         — market session durumu
- GET  /api/scheduler/history        — job geçmişi
- GET  /api/scheduler/dashboard      — tam dashboard verisi
- POST /api/scheduler/trigger/{job}  — manuel job tetikleme
- POST /api/scheduler/interval       — runtime interval güncelleme
- POST /api/scheduler/enable         — job enable/disable
"""

from typing import Dict, Any, Optional
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
        """Job listesi ve konfigürasyonları.

        Returns:
            Job konfigürasyonları
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_jobs": len(self._scheduler._configs),
            "jobs": self._scheduler.get_job_configs(),
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

    async def get_job_history(self, job_type: str = None, limit: int = 50) -> Dict[str, Any]:
        """Job geçmişi (DB-backed).

        Args:
            job_type: Job türü filtresi
            limit: Maksimum kayıt

        Returns:
            Job geçmişi
        """
        db_history = await self._scheduler.get_db_tracker().get_job_history(job_type, limit)
        memory_history = self._scheduler.get_job_history(limit)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "db_history": db_history,
            "memory_history": memory_history,
            "total": len(db_history) + len(memory_history),
        }

    async def trigger_job(self, job_type: str) -> Dict[str, Any]:
        """Job'ı manuel olarak tetikle.

        Args:
            job_type: Tetiklenecek job tipi

        Returns:
            Tetikleme sonucu
        """
        result = await self._scheduler.trigger_job(job_type)

        logger.info("Job triggered via API",
                   job_type=job_type,
                   status=result.get("status"))

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **result,
        }

    def update_interval(self, job_type: str, interval_seconds: int) -> Dict[str, Any]:
        """Job interval'ını runtime'da güncelle.

        Args:
            job_type: Job türü
            interval_seconds: Yeni interval (saniye)

        Returns:
            Güncelleme sonucu
        """
        if job_type not in self._scheduler._configs:
            return {
                "status": "ERROR",
                "message": f"Unknown job type: {job_type}",
            }

        old_interval = self._scheduler._configs[job_type].interval_seconds
        self._scheduler.update_interval(job_type, interval_seconds)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "job_type": job_type,
            "old_interval": old_interval,
            "new_interval": interval_seconds,
        }

    def enable_job(self, job_type: str, enabled: bool = True) -> Dict[str, Any]:
        """Job'ı aktif/pasif yap.

        Args:
            job_type: Job türü
            enabled: Aktif mi?

        Returns:
            Güncelleme sonucu
        """
        if job_type not in self._scheduler._configs:
            return {
                "status": "ERROR",
                "message": f"Unknown job type: {job_type}",
            }

        self._scheduler.enable_job(job_type, enabled)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "job_type": job_type,
            "enabled": enabled,
        }

    def update_priority(self, job_type: str, priority: int) -> Dict[str, Any]:
        """Job önceliğini güncelle.

        Args:
            job_type: Job türü
            priority: Yeni öncelik (1=en yüksek, 10=en düşük)

        Returns:
            Güncelleme sonucu
        """
        if job_type not in self._scheduler._configs:
            return {
                "status": "ERROR",
                "message": f"Unknown job type: {job_type}",
            }

        old_priority = self._scheduler._configs[job_type].priority
        self._scheduler.update_priority(job_type, priority)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "job_type": job_type,
            "old_priority": old_priority,
            "new_priority": priority,
        }

    async def get_full_dashboard(self) -> Dict[str, Any]:
        """Tam dashboard verisi.

        Returns:
            Tüm istatistikler
        """
        db_stats = await self._scheduler.get_db_tracker().get_failure_stats(24)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self.get_status(),
            "jobs": self.get_jobs(),
            "monitor": self.get_monitor(),
            "workflow": self.get_workflow(),
            "learning": self.get_learning(),
            "market": self.get_market_session(),
            "db_stats": db_stats,
        }


# Singleton
scheduler_api = SchedulerAPI()
