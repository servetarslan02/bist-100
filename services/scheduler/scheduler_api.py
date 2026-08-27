"""
ALPHA BIST — Scheduler API v2.1

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

import time
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


# =====================================================
# Rate Limiter (Trigger endpoint için)
# =====================================================


class _RateLimiter:
    """Basit token bucket rate limiter.

    Trigger endpoint'inin spam'lanmasını önler.
    Varsayılan: dakikada 10 tetikleme.
    """

    def __init__(self, max_tokens: int = 10, refill_rate: float = 10 / 60):
        self._max_tokens = max_tokens
        self._tokens = float(max_tokens)
        self._refill_rate = refill_rate  # saniyede kaç token
        self._last_refill = time.time()

    def allow(self) -> bool:
        """İstek izin verilmeli mi?"""
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def remaining(self) -> int:
        """Kalan token sayısı."""
        now = time.time()
        elapsed = now - self._last_refill
        tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        return int(tokens)


# =====================================================
# Scheduler API
# =====================================================


class SchedulerAPI:
    """Scheduler API endpoint'leri.

    Tüm endpoint'ler Dict döndürür (JSON-serialize edilebilir).
    Hata durumunda {"status": "ERROR", "message": "..."} döndürür.
    """

    def __init__(self):
        from .daily_workflow import daily_workflow
        from .job_monitor import job_monitor
        from .learning_scheduler import learning_scheduler
        from .unified_scheduler import unified_scheduler

        self._scheduler = unified_scheduler
        self._monitor = job_monitor
        self._workflow = daily_workflow
        self._learning = learning_scheduler

        # Rate limiter — trigger endpoint'i için
        self._trigger_limiter = _RateLimiter(max_tokens=10, refill_rate=10 / 60)

    def get_status(self) -> dict[str, Any]:
        """Scheduler durumu.

        Returns:
            Tam durum bilgisi
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "scheduler": self._scheduler.get_status(),
                "workflow": self._workflow.get_status().__dict__,
                "learning": self._learning.get_status(),
            }
        except Exception as e:
            logger.error("get_status failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def get_jobs(self) -> dict[str, Any]:
        """Job listesi ve konfigürasyonları.

        Returns:
            Job konfigürasyonları
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "total_jobs": len(self._scheduler._configs),
                "jobs": self._scheduler.get_job_configs(),
            }
        except Exception as e:
            logger.error("get_jobs failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def get_monitor(self, job_type: str = None) -> dict[str, Any]:
        """Job monitoring.

        Args:
            job_type: Job türü filtresi

        Returns:
            Monitoring istatistikleri
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "stats": self._monitor.get_stats(job_type),
                "slow_jobs": self._monitor.get_slow_jobs(),
                "alerts": self._monitor.get_alerts(limit=20),
                "summary": self._monitor.get_summary(),
            }
        except Exception as e:
            logger.error("get_monitor failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def get_workflow(self) -> dict[str, Any]:
        """Workflow durumu.

        Returns:
            Workflow bilgileri
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": self._workflow.get_status().__dict__,
                "phases": self._workflow.get_phases(),
            }
        except Exception as e:
            logger.error("get_workflow failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def get_learning(self) -> dict[str, Any]:
        """Learning scheduler durumu.

        Returns:
            Learning bilgileri
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": self._learning.get_status(),
                "pending_jobs": self._learning.get_pending_jobs(),
            }
        except Exception as e:
            logger.error("get_learning failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def get_market_session(self) -> dict[str, Any]:
        """Market session durumu.

        Returns:
            Market session bilgileri
        """
        try:
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "market": self._scheduler.get_market_session().get_status(),
            }
        except Exception as e:
            logger.error("get_market_session failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    async def get_job_history(self, job_type: str = None, limit: int = 50) -> dict[str, Any]:
        """Job geçmişi (DB-backed).

        Args:
            job_type: Job türü filtresi
            limit: Maksimum kayıt

        Returns:
            Job geçmişi
        """
        try:
            db_history = await self._scheduler.get_db_tracker().get_job_history(job_type, limit)
            memory_history = self._scheduler.get_job_history(limit)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "db_history": db_history,
                "memory_history": memory_history,
                "total": len(db_history) + len(memory_history),
            }
        except Exception as e:
            logger.error("get_job_history failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}

    async def trigger_job(self, job_type: str) -> dict[str, Any]:
        """Job'ı manuel olarak tetikle.

        Rate limited: dakikada max 10 tetikleme.

        Args:
            job_type: Tetiklenecek job tipi

        Returns:
            Tetikleme sonucu
        """
        # Rate limit kontrolü
        if not self._trigger_limiter.allow():
            logger.warning("Trigger rate limited", job_type=job_type, remaining=self._trigger_limiter.remaining)
            return {
                "status": "RATE_LIMITED",
                "message": "Too many triggers. Max 10/minute.",
                "remaining": self._trigger_limiter.remaining,
            }

        try:
            result = await self._scheduler.trigger_job(job_type)

            logger.info("Job triggered via API", job_type=job_type, status=result.get("status"))

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                **result,
            }
        except Exception as e:
            logger.error("trigger_job failed", job_type=job_type, error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def update_interval(self, job_type: str, interval_seconds: int) -> dict[str, Any]:
        """Job interval'ını runtime'da güncelle.

        Args:
            job_type: Job türü
            interval_seconds: Yeni interval (saniye)

        Returns:
            Güncelleme sonucu
        """
        try:
            if job_type not in self._scheduler._configs:
                return {
                    "status": "ERROR",
                    "message": f"Unknown job type: {job_type}",
                }

            # Mantık kontrolü: interval negatif veya 0 olamaz
            if interval_seconds < 0:
                return {
                    "status": "ERROR",
                    "message": "Interval must be non-negative",
                }

            old_interval = self._scheduler._configs[job_type].interval_seconds
            self._scheduler.update_interval(job_type, interval_seconds)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "OK",
                "job_type": job_type,
                "old_interval": old_interval,
                "new_interval": interval_seconds,
            }
        except Exception as e:
            logger.error("update_interval failed", job_type=job_type, error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def enable_job(self, job_type: str, enabled: bool = True) -> dict[str, Any]:
        """Job'ı aktif/pasif yap.

        Args:
            job_type: Job türü
            enabled: Aktif mi?

        Returns:
            Güncelleme sonucu
        """
        try:
            if job_type not in self._scheduler._configs:
                return {
                    "status": "ERROR",
                    "message": f"Unknown job type: {job_type}",
                }

            self._scheduler.enable_job(job_type, enabled)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "OK",
                "job_type": job_type,
                "enabled": enabled,
            }
        except Exception as e:
            logger.error("enable_job failed", job_type=job_type, error=str(e))
            return {"status": "ERROR", "message": str(e)}

    def update_priority(self, job_type: str, priority: int) -> dict[str, Any]:
        """Job önceliğini güncelle.

        Args:
            job_type: Job türü
            priority: Yeni öncelik (1=en yüksek, 10=en düşük)

        Returns:
            Güncelleme sonucu
        """
        try:
            if job_type not in self._scheduler._configs:
                return {
                    "status": "ERROR",
                    "message": f"Unknown job type: {job_type}",
                }

            if not 1 <= priority <= 10:
                return {
                    "status": "ERROR",
                    "message": "Priority must be between 1 and 10",
                }

            old_priority = self._scheduler._configs[job_type].priority
            self._scheduler.update_priority(job_type, priority)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "OK",
                "job_type": job_type,
                "old_priority": old_priority,
                "new_priority": priority,
            }
        except Exception as e:
            logger.error("update_priority failed", job_type=job_type, error=str(e))
            return {"status": "ERROR", "message": str(e)}

    async def get_full_dashboard(self) -> dict[str, Any]:
        """Tam dashboard verisi.

        Returns:
            Tüm istatistikler
        """
        try:
            db_stats = await self._scheduler.get_db_tracker().get_failure_stats(24)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": self.get_status(),
                "jobs": self.get_jobs(),
                "monitor": self.get_monitor(),
                "workflow": self.get_workflow(),
                "learning": self.get_learning(),
                "market": self.get_market_session(),
                "db_stats": db_stats,
            }
        except Exception as e:
            logger.error("get_full_dashboard failed", error=str(e))
            return {"status": "ERROR", "message": str(e)}


# Singleton
scheduler_api = SchedulerAPI()
