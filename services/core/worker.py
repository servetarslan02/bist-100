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
import contextlib
import hashlib
import threading
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace
from services.core.production_metrics import Metrics, production_metrics

DEFAULT_WORKER_STATUS_DB: Final[str] = "data/worker_status.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


class JobStatus(StrEnum):
    """İş çalıştırma durumlarını tanımlayan numaralandırma (Enum)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class JobType(StrEnum):
    """İş türlerini tanımlayan numaralandırma (Enum)."""

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
    """Üretim sınıfı iş yürütücü (Job Execution Worker).

    Veritabanı veya bellek içi idempotency: Aynı job_type + idempotency_key
    kombinasyonu ikinci kez işlenmez.
    """

    def __init__(
        self,
        worker_id: str = "worker-1",
        default_timeout: int = 300,
        default_max_retries: int = 3,
        retry_base_delay: float = 5.0,
    ) -> None:
        """JobWorker başlatıcı metodu.

        Args:
            worker_id: Çalışan işçi kimliği.
            default_timeout: Varsayılan zaman aşımı süresi (saniye).
            default_max_retries: Varsayılan en fazla yeniden deneme sayısı.
            retry_base_delay: Üstel geri çekilme taban bekleme süresi (saniye).
        """
        self._worker_id = worker_id
        self._default_timeout = default_timeout
        self._default_max_retries = default_max_retries
        self._retry_base_delay = retry_base_delay
        self._running = False
        self._active_jobs: dict[str, asyncio.Task] = {}
        self._memory_jobs: dict[int, dict[str, Any]] = {}
        self._memory_job_seq: int = 0
        self._lock = threading.RLock()

    @otel_trace("worker.submit_job")
    async def submit_job(
        self,
        job_type: str,
        handler: Callable[..., Awaitable[Any]],
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        priority: int = 0,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> int | None:
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
            with self._lock:
                self._memory_job_seq += 1
                job_id = self._memory_job_seq
            logger.info("veritabani_yok_bellek_kullanildi", job_id=job_id, job_type=job_type)

        # Async çalıştır
        task = asyncio.create_task(
            self._execute_job(
                job_id,
                handler,
                payload or {},
                timeout or self._default_timeout,
                max_retries or self._default_max_retries,
            )
        )
        with self._lock:
            self._active_jobs[str(job_id)] = task
            self._memory_jobs[job_id] = {
                "id": job_id,
                "job_type": job_type,
                "status": JobStatus.PENDING.value,
                "created_at": time.time(),
            }

        logger.info("Job submitted", job_id=job_id, job_type=job_type, worker=self._worker_id)
        return job_id

    async def get_job_status(self, job_id: int) -> dict[str, Any] | None:
        """Job durumunu sorgula."""
        with self._lock:
            if job_id in self._memory_jobs:
                return dict(self._memory_jobs[job_id])
        try:
            from .database import pg_fetchrow

            row = await pg_fetchrow("SELECT * FROM system_jobs WHERE id = $1", job_id)
            return dict(row) if row else None
        except Exception:
            return None

    async def cancel_job(self, job_id: int) -> bool:
        """Job iptal et."""
        with self._lock:
            task = self._active_jobs.get(str(job_id))
            if task and not task.done():
                task.cancel()
            if job_id in self._memory_jobs:
                self._memory_jobs[job_id]["status"] = JobStatus.CANCELLED.value
        try:
            from .database import pg_execute

            await pg_execute(
                "UPDATE system_jobs SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1 AND status IN ('PENDING', 'RUNNING')",
                job_id,
            )
            return True
        except Exception:
            return True

    async def shutdown(self, timeout: int = 30) -> None:
        """Graceful shutdown — tüm aktif job'ları bekle."""
        with self._lock:
            active_count = len(self._active_jobs)
            tasks = list(self._active_jobs.values())
        logger.info("Worker shutting down", active_jobs=active_count)
        self._running = False

        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
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
        handler: Callable[..., Awaitable[Any]],
        payload: dict[str, Any],
        timeout: int,
        max_retries: int,
    ) -> Any:
        """Job çalıştır — retry + timeout ile."""
        last_error = None

        try:
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

                except TimeoutError:
                    last_error = f"Timeout after {timeout}s"
                    logger.warning("Job timeout", job_id=job_id, attempt=attempt + 1)

                except asyncio.CancelledError:
                    await self._update_job_status(job_id, JobStatus.CANCELLED)
                    logger.info("Job cancelled", job_id=job_id)
                    return

                except Exception as e:
                    last_error = str(e)
                    logger.warning("Job failed", job_id=job_id, attempt=attempt + 1, error=last_error)

                # Retry delay (exponential backoff)
                if attempt < max_retries:
                    delay = self._retry_base_delay * (2**attempt)
                    logger.info("Retrying job", job_id=job_id, delay=delay)
                    await asyncio.sleep(delay)

            # Tüm retry'lar başarısız
            await self._fail_job(job_id, last_error or "Bilinmeyen hata")
            logger.error("Job failed permanently", job_id=job_id, retries=max_retries)
            production_metrics.inc(Metrics.WORKER_JOB_FAILED)
        finally:
            with self._lock:
                self._active_jobs.pop(str(job_id), None)

    def _generate_idempotency_key(self, job_type: str, payload: dict | None) -> str:
        """Idempotency key üret."""
        content = f"{job_type}:{orjson.dumps(payload or {}, option=orjson.OPT_SORT_KEYS, default=str).decode()}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]


    async def _check_idempotency(self, idempotency_key: str) -> int | None:
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
                    idempotency_key,
                ),
                timeout=3.0,
            )
        except Exception:
            return None

    async def _create_job(
        self, job_type: str, payload: dict, priority: int, max_retries: int, idempotency_key: str
    ) -> int | None:
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
                    job_type,
                    priority,
                    orjson.dumps(payload).decode(),
                    max_retries,
                    idempotency_key,
                ),
                timeout=3.0,
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

    async def _update_job_status(self, job_id: int, status: JobStatus, retry_count: int | None = None) -> None:
        """Job durumunu güncelle."""
        with self._lock:
            mem = self._memory_jobs.setdefault(job_id, {"id": job_id})
            mem["status"] = status.value
            if retry_count is not None:
                mem["retry_count"] = retry_count

        if not self._db_available():
            return
        try:
            from .database import pg_execute

            if retry_count is not None:
                await pg_execute(
                    """UPDATE system_jobs SET status = $1, retry_count = $2,
                       started_at = COALESCE(started_at, NOW()), updated_at = NOW()
                       WHERE id = $3""",
                    status.value,
                    retry_count,
                    job_id,
                )
            else:
                await pg_execute(
                    "UPDATE system_jobs SET status = $1, updated_at = NOW() WHERE id = $2", status.value, job_id
                )
        except Exception as e:
            logger.error("Failed to update job status", job_id=job_id, error=str(e))

    async def _complete_job(self, job_id: int, result: Any) -> None:
        """Job başarıyla tamamlandı."""
        with self._lock:
            mem = self._memory_jobs.setdefault(job_id, {"id": job_id})
            mem["status"] = JobStatus.COMPLETED.value
            mem["result"] = result

        if not self._db_available():
            return
        try:
            from .database import pg_execute

            result_json = orjson.dumps(result, default=str).decode() if result else "{}"
            await pg_execute(
                """UPDATE system_jobs SET status = 'COMPLETED', result = $1,
                   completed_at = NOW(), updated_at = NOW() WHERE id = $2""",
                result_json,
                job_id,
            )
        except Exception as e:
            logger.error("Failed to complete job", job_id=job_id, error=str(e))

    async def _fail_job(self, job_id: int, error_message: str) -> None:
        """Job başarısız oldu."""
        with self._lock:
            mem = self._memory_jobs.setdefault(job_id, {"id": job_id})
            mem["status"] = JobStatus.FAILED.value
            mem["error_message"] = error_message

        if not self._db_available():
            return
        try:
            from .database import pg_execute

            await pg_execute(
                """UPDATE system_jobs SET status = 'FAILED', error_message = $1,
                   completed_at = NOW(), updated_at = NOW() WHERE id = $2""",
                error_message,
                job_id,
            )
        except Exception as e:
            logger.error("Failed to mark job as failed", job_id=job_id, error=str(e))

    def export_jobs_to_polars(self) -> pl.DataFrame:
        """Kayıtlı bellek içi ve aktif işleri Polars DataFrame olarak aktarır."""
        rows: list[dict[str, Any]] = []
        with self._lock:
            for jid, data in self._memory_jobs.items():
                rows.append({
                    "job_id": int(jid),
                    "job_type": str(data.get("job_type", "UNKNOWN")),
                    "status": str(data.get("status", "UNKNOWN")),
                    "retry_count": int(data.get("retry_count", 0) or 0),
                    "error_message": str(data.get("error_message", "") or ""),
                    "is_active": str(jid) in self._active_jobs,
                })
        schema = {
            "job_id": pl.Int64,
            "job_type": pl.String,
            "status": pl.String,
            "retry_count": pl.Int64,
            "error_message": pl.String,
            "is_active": pl.Boolean,
        }
        if not rows:
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(rows, schema=schema)

    def to_orjson_bytes(self) -> bytes:
        """Worker durum ve iş özetini orjson ikili serileştirilmiş bayt olarak döndürür."""
        return export_worker_status_to_orjson_bytes(self)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            return (
                f"JobWorker(worker_id={self._worker_id!r}, "
                f"active_jobs={len(self._active_jobs)}, "
                f"memory_jobs={len(self._memory_jobs)})"
            )


# Singleton
job_worker = JobWorker()


def export_worker_status_to_orjson_bytes(worker: JobWorker = job_worker) -> bytes:
    """Worker durum ve iş özetini orjson ikili serileştirilmiş bayt olarak döndürür."""
    df = worker.export_jobs_to_polars()
    with worker._lock:
        worker_id = worker._worker_id
        active_count = len(worker._active_jobs)
    payload = {
        "worker_id": worker_id,
        "active_jobs_count": active_count,
        "jobs": df.to_dicts(),
    }
    return orjson.dumps(payload, default=str)


def export_worker_status_to_duckdb(
    worker: JobWorker = job_worker,
    db_path: str = DEFAULT_WORKER_STATUS_DB,
) -> int:
    """Worker durumunu ve kayıtlı işleri yerel DuckDB tablosuna anlık görüntü olarak kaydeder.

    Args:
        worker: JobWorker örneği.
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        Kaydedilen iş sayısı.
    """
    df = worker.export_jobs_to_polars()
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(db_path) as conn:
        configure_duckdb_wal(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS worker_job_audit (
                job_id BIGINT,
                job_type VARCHAR,
                status VARCHAR,
                retry_count BIGINT,
                error_message VARCHAR,
                is_active BOOLEAN,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_job_id ON worker_job_audit (job_id);")
        if df.height > 0:
            conn.register("df_worker_view", df.to_arrow())
            try:
                conn.execute("""
                    INSERT INTO worker_job_audit (job_id, job_type, status, retry_count, error_message, is_active)
                    SELECT job_id, job_type, status, retry_count, error_message, is_active
                    FROM df_worker_view
                """)
            finally:
                with contextlib.suppress(Exception):
                    conn.unregister("df_worker_view")
    return df.height


def read_worker_jobs_from_duckdb(
    db_path: str = DEFAULT_WORKER_STATUS_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan worker iş kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(db_path)
        try:
            return conn.execute(
                """
                SELECT job_id, job_type, status, retry_count, error_message, is_active, recorded_at
                FROM worker_job_audit
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan worker kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_worker_duckdb(db_path: str = DEFAULT_WORKER_STATUS_DB) -> None:
    """DuckDB üzerindeki worker tablolarını temizler."""
    target = Path(db_path)
    if not target.exists():
        return
    try:
        with duckdb.connect(db_path) as conn:
            conn.execute("DROP TABLE IF EXISTS worker_job_audit")
    except Exception as exc:
        logger.warning("DuckDB worker tablosu temizlenemedi", hata=str(exc))


__all__: list[str] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_WAL_SIZE",
    "DEFAULT_WORKER_STATUS_DB",
    "JobStatus",
    "JobType",
    "JobWorker",
    "clear_worker_duckdb",
    "configure_duckdb_wal",
    "export_worker_status_to_duckdb",
    "export_worker_status_to_orjson_bytes",
    "job_worker",
    "read_worker_jobs_from_duckdb",
    "to_orjson_bytes",
]

