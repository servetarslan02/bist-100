"""ALPHA BIST — Job Worker v1.0

Production-grade job execution with:
- Retry with exponential backoff
- Timeout
- Idempotency
- Duplicate prevention
- DB-backed state persistence
- Graceful failure
"""

import asyncio
import hashlib
import orjson
import time
from typing import Optional, Dict, Any, Callable, Awaitable
from enum import Enum
import structlog

from services.core.production_metrics import production_metrics, Metrics

logger = structlog.get_logger()


class JobStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class JobType(Enum):
    MARKET_DATA_UPDATE = "market_data_update"
    FEATURE_CALCULATION = "feature_calculation"
    LIVE_INFERENCE = "live_inference"
    RANKING = "ranking"
    SIGNAL_GENERATION = "signal_generation"
    DECISION_PIPELINE = "decision_pipeline"
    PERSISTENCE = "persistence"
    HEALTH_CHECK = "health_check"
    DAILY_REPORT = "daily_report"
    MODEL_RETRAIN = "model_retrain"


class JobWorker:
    """Job execution worker.

    DB-backed idempotency: Aynı job_type + idempotency_key kombinasyonu
    ikinci kez işlenmez.
    """

    def __init__(
        self,
        worker_id: str = "worker-1",
        default_timeout: int = 300,
        default_max_retries: int = 3,
        retry_base_delay: float = 5.0,
    ):
        self._worker_id = worker_id
        self._default_timeout = default_timeout
        self._default_max_retries = default_max_retries
        self._retry_base_delay = retry_base_delay
        self._running = False
        self._active_jobs: Dict[str, asyncio.Task] = {}

    async def submit_job(
        self,
        job_type: str,
        handler: Callable[..., Awaitable[Any]],
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> Optional[int]:
        """Job gönder.

        Args:
            job_type: Job tipi (JobType enum value)
            handler: Async handler fonksiyonu
            payload: Job parametreleri
            idempotency_key: Duplicate prevention key
            priority: Öncelük (yüksek = önce)
            timeout: Saniye cinsinden timeout
            max_retries: Maksimum retry sayısı

        Returns:
            job_id veya None (duplicate ise)
        """
        idem_key = idempotency_key or self._generate_idempotency_key(job_type, payload)

        # DB'de duplicate kontrolü
        existing_id = await self._check_idempotency(idem_key)
        if existing_id is not None:
            logger.info("Job already exists (idempotent)", job_type=job_type, existing_id=existing_id)
            return existing_id

        # DB'ye job kaydet
        job_id = await self._create_job(
            job_type=job_type,
            payload=payload or {},
            priority=priority,
            max_retries=max_retries or self._default_max_retries,
            idempotency_key=idem_key,
        )

        if job_id is None:
            logger.error("Failed to create job", job_type=job_type)
            return None

        # Async çalıştır
        task = asyncio.create_task(
            self._execute_job(job_id, handler, payload or {},
                              timeout or self._default_timeout,
                              max_retries or self._default_max_retries)
        )
        self._active_jobs[str(job_id)] = task

        logger.info("Job submitted", job_id=job_id, job_type=job_type, worker=self._worker_id)
        return job_id

    async def get_job_status(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Job durumunu sorgula."""
        try:
            from .database import pg_fetchrow
            row = await pg_fetchrow(
                "SELECT * FROM system_jobs WHERE id = $1", job_id
            )
            return dict(row) if row else None
        except Exception:
            return None

    async def cancel_job(self, job_id: int) -> bool:
        """Job iptal et."""
        try:
            from .database import pg_execute
            await pg_execute(
                "UPDATE system_jobs SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1 AND status IN ('PENDING', 'RUNNING')",
                job_id
            )
            task = self._active_jobs.get(str(job_id))
            if task and not task.done():
                task.cancel()
            return True
        except Exception:
            return False

    async def shutdown(self, timeout: int = 30):
        """Graceful shutdown — tüm aktif job'ları bekle."""
        logger.info("Worker shutting down", active_jobs=len(self._active_jobs))
        self._running = False

        if self._active_jobs:
            done, pending = await asyncio.wait(
                self._active_jobs.values(), timeout=timeout
            )
            for task in pending:
                task.cancel()
                logger.warning("Job cancelled on shutdown", task=task.get_name())

        logger.info("Worker shutdown complete")

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    async def _execute_job(
        self,
        job_id: int,
        handler: Callable,
        payload: Dict[str, Any],
        timeout: int,
        max_retries: int,
    ):
        """Job çalıştır — retry + timeout ile."""
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Status = RUNNING
                await self._update_job_status(job_id, JobStatus.RUNNING, retry_count=attempt)

                # Timeout ile çalıştır
                result = await asyncio.wait_for(handler(**payload), timeout=timeout)

                # Success
                await self._complete_job(job_id, result)
                logger.info("Job completed", job_id=job_id, attempt=attempt + 1)
                production_metrics.inc(Metrics.WORKER_JOB_TOTAL)
                return

            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout}s"
                logger.warning("Job timeout", job_id=job_id, attempt=attempt + 1)

            except asyncio.CancelledError:
                await self._update_job_status(job_id, JobStatus.CANCELLED)
                logger.info("Job cancelled", job_id=job_id)
                return

            except Exception as e:
                last_error = str(e)
                logger.warning("Job failed", job_id=job_id, attempt=attempt + 1,
                             error=last_error)

            # Retry delay (exponential backoff)
            if attempt < max_retries:
                delay = self._retry_base_delay * (2 ** attempt)
                logger.info("Retrying job", job_id=job_id, delay=delay)
                await asyncio.sleep(delay)

        # Tüm retry'lar başarısız
        await self._fail_job(job_id, last_error)
        logger.error("Job failed permanently", job_id=job_id, retries=max_retries)
        production_metrics.inc(Metrics.WORKER_JOB_FAILED)

    def _generate_idempotency_key(self, job_type: str, payload: Optional[Dict]) -> str:
        """Idempotency key üret."""
        content = f"{job_type}:{orjson.dumps(payload or {}, option=orjson.OPT_SORT_KEYS).decode()}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def _check_idempotency(self, idempotency_key: str) -> Optional[int]:
        """DB'de aynı idempotency_key ile completed/running job var mı?"""
        if not self._db_available():
            return None
        try:
            from .database import pg_fetchval
            return await asyncio.wait_for(
                pg_fetchval(
                    """SELECT id FROM system_jobs
                       WHERE idempotency_key = $1
                       AND status IN ('RUNNING', 'COMPLETED')
                       ORDER BY created_at DESC LIMIT 1""",
                    idempotency_key
                ),
                timeout=3.0
            )
        except Exception:
            return None

    async def _create_job(self, job_type: str, payload: Dict, priority: int,
                          max_retries: int, idempotency_key: str) -> Optional[int]:
        """DB'ye job kaydet."""
        if not self._db_available():
            return None
        try:
            from .database import pg_fetchval
            return await asyncio.wait_for(
                pg_fetchval(
                    """INSERT INTO system_jobs
                       (job_type, status, priority, payload, max_retries, idempotency_key)
                       VALUES ($1, 'PENDING', $2, $3, $4, $5)
                       RETURNING id""",
                    job_type, priority, orjson.dumps(payload).decode(), max_retries, idempotency_key
                ),
                timeout=3.0
            )
        except Exception as e:
            logger.warning("Failed to create job in DB (DB unavailable)", error=str(e)[:100])
            return None

    _db_cache_until: float = 0.0

    @staticmethod
    def _db_available() -> bool:
        """DB hızlı erişim kontrolü (5s TTL cache)."""
        now = time.monotonic()
        if now < JobWorker._db_cache_until:
            return JobWorker._db_cache_result
        try:
            import socket
            from .config import settings
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex((settings.postgres_host, settings.postgres_port))
            s.close()
            available = result == 0
        except Exception as e:
            logger.debug("db_availability_check_failed", error=str(e))
            available = False
        JobWorker._db_cache_result = available
        JobWorker._db_cache_until = now + 5.0
        return available

    _db_cache_result: bool = False

    async def _update_job_status(self, job_id: int, status: JobStatus,
                                 retry_count: Optional[int] = None):
        """Job durumunu güncelle."""
        if not self._db_available():
            return
        try:
            from .database import pg_execute
            if retry_count is not None:
                await pg_execute(
                    """UPDATE system_jobs SET status = $1, retry_count = $2,
                       started_at = COALESCE(started_at, NOW()), updated_at = NOW()
                       WHERE id = $3""",
                    status.value, retry_count, job_id
                )
            else:
                await pg_execute(
                    "UPDATE system_jobs SET status = $1, updated_at = NOW() WHERE id = $2",
                    status.value, job_id
                )
        except Exception as e:
            logger.error("Failed to update job status", job_id=job_id, error=str(e))

    async def _complete_job(self, job_id: int, result: Any):
        """Job başarıyla tamamlandı."""
        if not self._db_available():
            return
        try:
            from .database import pg_execute
            result_json = orjson.dumps(result, default=str).decode() if result else '{}'
            await pg_execute(
                """UPDATE system_jobs SET status = 'COMPLETED', result = $1,
                   completed_at = NOW(), updated_at = NOW() WHERE id = $2""",
                result_json, job_id
            )
        except Exception as e:
            logger.error("Failed to complete job", job_id=job_id, error=str(e))

    async def _fail_job(self, job_id: int, error_message: str):
        """Job başarısız oldu."""
        if not self._db_available():
            return
        try:
            from .database import pg_execute
            await pg_execute(
                """UPDATE system_jobs SET status = 'FAILED', error_message = $1,
                   completed_at = NOW(), updated_at = NOW() WHERE id = $2""",
                error_message, job_id
            )
        except Exception as e:
            logger.error("Failed to mark job as failed", job_id=job_id, error=str(e))


# Singleton
job_worker = JobWorker()
