"""
ALPHA BIST — Learning Scheduler v1.0

Learning cycle ve model bakım job'larını zamanlar:
- Learning cycle (günlük)
- Model drift detection (günlük)
- Model retrain (haftalık)
- Backtest (haftalık)
- Calibration update (aylık)

Kaynaklar: arXiv Agentic Trading (2026), Endüstri standardı
"""

import asyncio
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class LearningJobConfig:
    """Learning job konfigürasyonu."""
    job_type: str
    interval_hours: int
    enabled: bool = True
    last_run: Optional[str] = None
    handler: Optional[Callable] = None
    description: str = ""


class LearningScheduler:
    """Learning cycle scheduler.

    After-hours'da çalışır:
    - Günlük: Learning cycle, drift detection
    - Haftalık: Model retrain, backtest
    - Aylık: Calibration update
    """

    def __init__(self):
        self._jobs: Dict[str, LearningJobConfig] = {}
        self._running = False
        self._setup_default_jobs()

    def _setup_default_jobs(self):
        """Varsayılan learning job'ları."""
        self._jobs = {
            "learning_cycle": LearningJobConfig(
                job_type="learning_cycle",
                interval_hours=24,
                description="Günlük öğrenme döngüsü — outcome tracking, pattern learning",
            ),
            "model_drift_detection": LearningJobConfig(
                job_type="model_drift_detection",
                interval_hours=24,
                description="Model drift tespiti — performans düşüşü kontrolü",
            ),
            "model_retrain": LearningJobConfig(
                job_type="model_retrain",
                interval_hours=168,  # Haftalık
                description="Model yeniden eğitim — haftalık",
            ),
            "backtest": LearningJobConfig(
                job_type="backtest",
                interval_hours=168,  # Haftalık
                description="Strateji backtest — haftalık",
            ),
            "calibration_update": LearningJobConfig(
                job_type="calibration_update",
                interval_hours=720,  # Aylık
                description="Calibration güncelleme — aylık",
            ),
        }

    def register_handler(self, job_type: str, handler: Callable[..., Awaitable[Any]]):
        """Learning job handler'ı kaydet.

        Args:
            job_type: Job türü
            handler: Async handler fonksiyonu
        """
        if job_type in self._jobs:
            self._jobs[job_type].handler = handler
            logger.info("Learning handler registered", job_type=job_type)

    def enable_job(self, job_type: str, enabled: bool = True):
        """Job'ı aktif/pasif yap.

        Args:
            job_type: Job türü
            enabled: Aktif mi?
        """
        if job_type in self._jobs:
            self._jobs[job_type].enabled = enabled

    def update_interval(self, job_type: str, interval_hours: int):
        """Job interval'ını güncelle.

        Args:
            job_type: Job türü
            interval_hours: Aralık (saat)
        """
        if job_type in self._jobs:
            self._jobs[job_type].interval_hours = interval_hours

    async def run_pending_jobs(self) -> Dict[str, Any]:
        """Zamanı gelen job'ları çalıştır.

        Returns:
            Çalıştırılan job'ların sonuçları
        """
        results = {}

        for job_type, config in self._jobs.items():
            if not config.enabled or config.handler is None:
                continue

            if self._should_run(config):
                logger.info("Running learning job", job_type=job_type)

                try:
                    start = datetime.now(timezone.utc)
                    result = await config.handler()
                    end = datetime.now(timezone.utc)

                    config.last_run = start.isoformat()
                    duration = (end - start).total_seconds()

                    results[job_type] = {
                        "status": "SUCCESS",
                        "duration_seconds": round(duration, 2),
                        "result": result,
                    }

                    logger.info("Learning job completed",
                               job_type=job_type,
                               duration=f"{duration:.1f}s")

                except Exception as e:
                    results[job_type] = {
                        "status": "FAILED",
                        "error": str(e),
                    }
                    logger.error("Learning job failed",
                               job_type=job_type, error=str(e))

        return results

    def _should_run(self, config: LearningJobConfig) -> bool:
        """Job çalıştırılmalı mı?

        Args:
            config: Job konfigürasyonu

        Returns:
            True: Çalıştırılmalı
        """
        if config.last_run is None:
            return True

        try:
            last = datetime.fromisoformat(config.last_run)
            elapsed_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            return elapsed_hours >= config.interval_hours
        except Exception:
            return True

    def get_status(self) -> Dict[str, Any]:
        """Scheduler durumu.

        Returns:
            Durum bilgisi
        """
        return {
            "total_jobs": len(self._jobs),
            "enabled_jobs": sum(1 for j in self._jobs.values() if j.enabled),
            "jobs": {
                name: {
                    "enabled": config.enabled,
                    "interval_hours": config.interval_hours,
                    "last_run": config.last_run,
                    "has_handler": config.handler is not None,
                    "description": config.description,
                }
                for name, config in self._jobs.items()
            },
        }

    def get_pending_jobs(self) -> list:
        """Zamanı gelen job'ları al.

        Returns:
            Bekleyen job listesi
        """
        pending = []
        for job_type, config in self._jobs.items():
            if config.enabled and config.handler is not None and self._should_run(config):
                pending.append({
                    "job_type": job_type,
                    "interval_hours": config.interval_hours,
                    "last_run": config.last_run,
                    "description": config.description,
                })
        return pending


# Singleton
learning_scheduler = LearningScheduler()
