"""
ALPHA BIST — Job Monitor v1.0

Job çalıştırma takibi ve istatistikleri:
- Job status tracking
- Duration monitoring
- Failure rate tracking
- Slow job detection
- Job failure alerts

Kaynaklar: APScheduler best practices, Endüstri standardı
"""

import time
import numpy as np
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import structlog

logger = structlog.get_logger()


class JobStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    RETRY = "RETRY"
    RUNNING = "RUNNING"
    SKIPPED = "SKIPPED"


@dataclass
class JobRecord:
    """Job kayıt kaydı."""
    job_type: str
    status: JobStatus
    duration_ms: float
    timestamp: str
    error: Optional[str] = None
    retry_count: int = 0
    phase: str = ""


@dataclass
class JobAlert:
    """Job alert."""
    alert_type: str      # FAILURE, SLOW, HIGH_FAILURE_RATE
    job_type: str
    message: str
    severity: str        # INFO, WARNING, CRITICAL
    timestamp: str


class JobMonitor:
    """Job izleme ve alerting sistemi.

    Metrikler:
    - Success rate (job bazlı)
    - Average duration
    - Failure rate
    - Slow jobs
    - Consecutive failures
    """

    def __init__(self, max_history: int = 1000, slow_threshold_ms: float = 30000):
        self._max_history = max_history
        self._slow_threshold = slow_threshold_ms
        self._records: List[JobRecord] = []
        self._alerts: List[JobAlert] = []
        self._callbacks: List[Callable] = []

        # Consecutive failure tracking
        self._consecutive_failures: Dict[str, int] = {}

    def record_job(
        self,
        job_type: str,
        status: str,
        duration_ms: float,
        error: str = None,
        retry_count: int = 0,
        phase: str = "",
    ):
        """Job kaydet.

        Args:
            job_type: Job türü
            status: Durum (SUCCESS, FAILED, vb.)
            duration_ms: Süre (ms)
            error: Hata mesajı
            retry_count: Retry sayısı
            phase: Piyasa fazı
        """
        record = JobRecord(
            job_type=job_type,
            status=JobStatus(status),
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=error,
            retry_count=retry_count,
            phase=phase,
        )

        self._records.append(record)

        # Limit
        if len(self._records) > self._max_history:
            self._records = self._records[-self._max_history:]

        # Consecutive failure tracking
        if status == "FAILED":
            self._consecutive_failures[job_type] = \
                self._consecutive_failures.get(job_type, 0) + 1

            # 3 ardışık failure → alert
            if self._consecutive_failures[job_type] >= 3:
                self._fire_alert(JobAlert(
                    alert_type="CONSECUTIVE_FAILURE",
                    job_type=job_type,
                    message=f"{job_type}: {self._consecutive_failures[job_type]} ardışık failure!",
                    severity="CRITICAL",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
        else:
            self._consecutive_failures[job_type] = 0

        # Slow job alert
        if duration_ms > self._slow_threshold:
            self._fire_alert(JobAlert(
                alert_type="SLOW_JOB",
                job_type=job_type,
                message=f"{job_type}: {duration_ms:.0f}ms (eşik: {self._slow_threshold:.0f}ms)",
                severity="WARNING",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

    def get_stats(self, job_type: str = None) -> Dict[str, Any]:
        """Job istatistikleri.

        Args:
            job_type: Job türü filtresi

        Returns:
            İstatistikler
        """
        records = self._records
        if job_type:
            records = [r for r in records if r.job_type == job_type]

        if not records:
            return {"total_jobs": 0, "job_type": job_type or "all"}

        total = len(records)
        failed = sum(1 for r in records if r.status == JobStatus.FAILED)
        success = sum(1 for r in records if r.status == JobStatus.SUCCESS)
        timeouts = sum(1 for r in records if r.status == JobStatus.TIMEOUT)
        durations = [r.duration_ms for r in records]

        return {
            "total_jobs": total,
            "success": success,
            "failed": failed,
            "timeouts": timeouts,
            "success_rate": round(success / total, 4) if total > 0 else 0,
            "failure_rate": round(failed / total, 4) if total > 0 else 0,
            "avg_duration_ms": round(np.mean(durations), 2),
            "median_duration_ms": round(np.median(durations), 2),
            "p95_duration_ms": round(np.percentile(durations, 95), 2),
            "max_duration_ms": round(max(durations), 2),
            "consecutive_failures": self._consecutive_failures.get(job_type or "", 0),
            "job_type": job_type or "all",
        }

    def get_failure_rate(self, job_type: str = None, window: int = 100) -> float:
        """Failure rate (son N job).

        Args:
            job_type: Job türü
            window: Pencere boyutu

        Returns:
            Failure rate (0-1)
        """
        records = self._records[-window:]
        if job_type:
            records = [r for r in records if r.job_type == job_type]

        if not records:
            return 0.0

        failed = sum(1 for r in records if r.status == JobStatus.FAILED)
        return round(failed / len(records), 4)

    def get_slow_jobs(self, threshold_ms: float = None) -> List[Dict[str, Any]]:
        """Yavaş job'ları al.

        Args:
            threshold_ms: Eşik (ms)

        Returns:
            Yavaş job'lar
        """
        threshold = threshold_ms or self._slow_threshold
        slow = [r for r in self._records if r.duration_ms > threshold]

        return [
            {
                "job_type": r.job_type,
                "duration_ms": round(r.duration_ms, 2),
                "timestamp": r.timestamp,
                "phase": r.phase,
            }
            for r in slow[-20:]  # Son 20
        ]

    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Alert'leri al.

        Args:
            limit: Maksimum alert

        Returns:
            Alert listesi
        """
        return [
            {
                "alert_type": a.alert_type,
                "job_type": a.job_type,
                "message": a.message,
                "severity": a.severity,
                "timestamp": a.timestamp,
            }
            for a in self._alerts[-limit:]
        ]

    def register_callback(self, callback: Callable):
        """Alert callback kaydet."""
        self._callbacks.append(callback)

    def _fire_alert(self, alert: JobAlert):
        """Alert tetikle."""
        self._alerts.append(alert)

        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]

        logger.warning("Job alert",
                      alert_type=alert.alert_type,
                      job_type=alert.job_type,
                      severity=alert.severity)

        for cb in self._callbacks:
            try:
                cb(alert)
            except Exception as e:
                logger.error("Alert callback error", error=str(e))

    def get_all_job_types(self) -> List[str]:
        """Tüm job türlerini al."""
        return list(set(r.job_type for r in self._records))

    def get_summary(self) -> Dict[str, Any]:
        """Genel özet."""
        job_types = self.get_all_job_types()

        return {
            "total_records": len(self._records),
            "total_alerts": len(self._alerts),
            "job_types": job_types,
            "overall_stats": self.get_stats(),
            "per_job_stats": {
                jt: self.get_stats(jt) for jt in job_types
            },
        }

    def clear(self):
        """Geçmişi temizle."""
        self._records.clear()
        self._alerts.clear()
        self._consecutive_failures.clear()


# Singleton
job_monitor = JobMonitor()
