"""
ALPHA BIST — Unified Scheduler v2.0

Tek canonical scheduler: AlphaScheduler + ProductionScheduler birleştirildi.

Özellikler:
- Market session-aware (BIST saatleri)
- Config-driven intervals
- 3 katmanlı tarama (live/batch/event)
- Daily workflow otomasyonu
- SIGTERM/SIGINT handler
- Graceful shutdown
- Job retry policy
- Job monitoring

Kaynaklar: arXiv Agentic Trading (2026), BIST resmi, APScheduler best practices
"""

import asyncio
import signal
import time
from datetime import datetime, time as dt_time, timezone, timedelta
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


# =====================================================
# Market Phases
# =====================================================

class MarketPhase(str, Enum):
    """BIST piyasa fazları."""
    CLOSED = "CLOSED"            # Piyasa kapalı (gece, hafta sonu)
    PRE_MARKET = "PRE_MARKET"    # 09:40-09:55 (emir toplama)
    SEANS_1 = "SEANS_1"          # 09:55-12:30 (tek fiyat)
    BREAK = "BREAK"              # 12:30-14:00 (ara)
    SEANS_2 = "SEANS_2"          # 14:00-17:40 (sürekli müzayede)
    CLOSING = "CLOSING"          # 17:40-18:00 (kapanış)
    POST_MARKET = "POST_MARKET"  # 18:00-18:30
    AFTER_HOURS = "AFTER_HOURS"  # 18:30-23:00
    NIGHT = "NIGHT"              # 23:00-09:40


# =====================================================
# Market Session Manager
# =====================================================

class MarketSessionManager:
    """BIST piyasa saatleri yöneticisi."""

    # BIST saatleri (UTC+3)
    PHASE_TIMES = [
        (dt_time(9, 40), MarketPhase.PRE_MARKET),
        (dt_time(9, 55), MarketPhase.SEANS_1),
        (dt_time(12, 30), MarketPhase.BREAK),
        (dt_time(14, 0), MarketPhase.SEANS_2),
        (dt_time(17, 40), MarketPhase.CLOSING),
        (dt_time(18, 0), MarketPhase.POST_MARKET),
        (dt_time(18, 30), MarketPhase.AFTER_HOURS),
        (dt_time(23, 0), MarketPhase.NIGHT),
    ]

    # BIST tatil günleri (2026) — örnek
    HOLIDAYS_2026 = [
        (1, 1),    # Yılbaşı
        (4, 23),   # Ulusal Egemenlik
        (5, 1),    # İşçi Bayramı
        (5, 19),   # Gençlik Bayramı
        (7, 15),   # Demokrasi Bayramı
        (8, 30),   # Zafer Bayramı
        (10, 29),  # Cumhuriyet Bayramı
        (3, 29),   # Ramazan Bayramı (1)
        (3, 30),   # Ramazan Bayramı (2)
        (3, 31),   # Ramazan Bayramı (3)
        (6, 6),    # Kurban Bayramı (1)
        (6, 7),    # Kurban Bayramı (2)
        (6, 8),    # Kurban Bayramı (3)
        (6, 9),    # Kurban Bayramı (4)
    ]

    def __init__(self, timezone_offset: int = 3):
        self._tz_offset = timezone_offset
        self._current_phase: Optional[MarketPhase] = None
        self._phase_callbacks: Dict[MarketPhase, List[Callable]] = {}

    def current_phase(self) -> MarketPhase:
        """Mevcut piyasa fazını al."""
        now = datetime.now(timezone(timedelta(hours=self._tz_offset)))

        # Hafta sonu
        if now.weekday() >= 5:
            return MarketPhase.CLOSED

        # Tatil
        if self._is_holiday(now):
            return MarketPhase.CLOSED

        current_time = now.time()

        # Faz belirle
        phase = MarketPhase.NIGHT
        for phase_time, market_phase in self.PHASE_TIMES:
            if current_time >= phase_time:
                phase = market_phase

        # Phase transition callback
        if phase != self._current_phase:
            self._on_phase_change(self._current_phase, phase)
            self._current_phase = phase

        return phase

    def is_trading_hours(self) -> bool:
        """Piyasa işlem saatlerinde mi?"""
        phase = self.current_phase()
        return phase in [MarketPhase.SEANS_1, MarketPhase.SEANS_2, MarketPhase.CLOSING]

    def is_market_open(self) -> bool:
        """Piyasa açık mı? (işlem + pre/post dahil)"""
        phase = self.current_phase()
        return phase not in [MarketPhase.CLOSED, MarketPhase.NIGHT]

    def should_run_trading_job(self) -> bool:
        """Trading job'ları çalıştırılmalı mı?"""
        return self.is_trading_hours()

    def seconds_until_next_phase(self) -> float:
        """Bir sonraki faza kaç saniye var?"""
        now = datetime.now(timezone(timedelta(hours=self._tz_offset)))
        current_time = now.time()

        for phase_time, _ in self.PHASE_TIMES:
            if current_time < phase_time:
                target = now.replace(
                    hour=phase_time.hour,
                    minute=phase_time.minute,
                    second=0, microsecond=0
                )
                return max(0, (target - now).total_seconds())

        # Gece — bir sonraki günün ilk fazı
        tomorrow = now + timedelta(days=1)
        target = tomorrow.replace(hour=9, minute=40, second=0, microsecond=0)
        return max(0, (target - now).total_seconds())

    def get_status(self) -> Dict[str, Any]:
        """Piyasa durumu."""
        phase = self.current_phase()
        return {
            "phase": phase.value,
            "is_trading": self.is_trading_hours(),
            "is_open": self.is_market_open(),
            "seconds_until_next": round(self.seconds_until_next_phase()),
            "is_holiday": self._is_holiday(
                datetime.now(timezone(timedelta(hours=self._tz_offset)))
            ),
        }

    def _is_holiday(self, dt: datetime) -> bool:
        """Tatil günü mü?"""
        return (dt.month, dt.day) in self.HOLIDAYS_2026

    def _on_phase_change(self, old: Optional[MarketPhase], new: MarketPhase):
        """Faz değişikliği callback."""
        logger.info("Market phase changed",
                   old=old.value if old else None,
                   new=new.value)

        callbacks = self._phase_callbacks.get(new, [])
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(old, new))
                else:
                    cb(old, new)
            except Exception as e:
                logger.error("Phase callback error", error=str(e))

    def on_phase(self, phase: MarketPhase, callback: Callable):
        """Faz değişikliği callback'i kaydet."""
        if phase not in self._phase_callbacks:
            self._phase_callbacks[phase] = []
        self._phase_callbacks[phase].append(callback)


# =====================================================
# Job Types
# =====================================================

class JobType(str, Enum):
    """Job türleri."""
    # Data
    MARKET_DATA_UPDATE = "market_data_update"
    FEATURE_CALCULATION = "feature_calculation"
    UNIVERSE_REFRESH = "universe_refresh"

    # Scanning
    LIVE_SCANNING = "live_scanning"
    BATCH_SCAN = "batch_scan"
    SIGNAL_GENERATION = "signal_generation"

    # Risk
    RISK_MONITORING = "risk_monitoring"
    HEALTH_CHECK = "health_check"

    # Post-market
    PERSISTENCE = "persistence"
    DAILY_REPORT = "daily_report"
    PERFORMANCE_ATTRIBUTION = "performance_attribution"

    # After-hours
    LEARNING_CYCLE = "learning_cycle"
    MODEL_DRIFT_DETECTION = "model_drift_detection"
    MODEL_RETRAIN = "model_retrain"
    BACKTEST = "backtest"
    CALIBRATION_UPDATE = "calibration_update"

    # Night
    BACKUP = "backup"


# =====================================================
# Job Configuration
# =====================================================

@dataclass
class JobConfig:
    """Job konfigürasyonu."""
    job_type: str
    interval_seconds: int
    trading_only: bool = True       # Sadece piyasa açıkken çalışsın
    priority: int = 5               # 1=en yüksek, 10=en düşük
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: int = 300
    description: str = ""


# Varsayılan job konfigürasyonları
DEFAULT_JOB_CONFIGS = {
    # Pre-market
    JobType.MARKET_DATA_UPDATE: JobConfig(
        job_type=JobType.MARKET_DATA_UPDATE,
        interval_seconds=120,
        trading_only=False,
        priority=2,
        description="Piyasa verisi güncelleme",
    ),
    JobType.FEATURE_CALCULATION: JobConfig(
        job_type=JobType.FEATURE_CALCULATION,
        interval_seconds=300,
        trading_only=False,
        priority=2,
        description="Feature hesaplama",
    ),
    JobType.UNIVERSE_REFRESH: JobConfig(
        job_type=JobType.UNIVERSE_REFRESH,
        interval_seconds=86400,
        trading_only=False,
        priority=8,
        description="Universe yenileme",
    ),

    # Active trading
    JobType.BATCH_SCAN: JobConfig(
        job_type=JobType.BATCH_SCAN,
        interval_seconds=3600,
        trading_only=True,
        priority=3,
        description="Batch tarama",
    ),
    JobType.SIGNAL_GENERATION: JobConfig(
        job_type=JobType.SIGNAL_GENERATION,
        interval_seconds=600,
        trading_only=True,
        priority=3,
        description="Sinyal üretimi",
    ),
    JobType.RISK_MONITORING: JobConfig(
        job_type=JobType.RISK_MONITORING,
        interval_seconds=120,
        trading_only=True,
        priority=2,
        description="Risk izleme",
    ),
    JobType.HEALTH_CHECK: JobConfig(
        job_type=JobType.HEALTH_CHECK,
        interval_seconds=60,
        trading_only=False,
        priority=9,
        description="Sistem sağlık kontrolü",
    ),

    # Post-market
    JobType.PERSISTENCE: JobConfig(
        job_type=JobType.PERSISTENCE,
        interval_seconds=900,
        trading_only=False,
        priority=5,
        description="Veri saklama",
    ),
    JobType.DAILY_REPORT: JobConfig(
        job_type=JobType.DAILY_REPORT,
        interval_seconds=86400,
        trading_only=False,
        priority=7,
        description="Günlük rapor",
    ),

    # After-hours
    JobType.LEARNING_CYCLE: JobConfig(
        job_type=JobType.LEARNING_CYCLE,
        interval_seconds=86400,
        trading_only=False,
        priority=6,
        description="Öğrenme döngüsü",
    ),
    JobType.MODEL_DRIFT_DETECTION: JobConfig(
        job_type=JobType.MODEL_DRIFT_DETECTION,
        interval_seconds=86400,
        trading_only=False,
        priority=6,
        description="Model drift tespiti",
    ),
    JobType.MODEL_RETRAIN: JobConfig(
        job_type=JobType.MODEL_RETRAIN,
        interval_seconds=604800,
        trading_only=False,
        priority=7,
        description="Model yeniden eğitim",
    ),
    JobType.BACKTEST: JobConfig(
        job_type=JobType.BACKTEST,
        interval_seconds=604800,
        trading_only=False,
        priority=8,
        description="Backtest",
    ),
}


# =====================================================
# Job Result
# =====================================================

@dataclass
class JobResult:
    """Job çalıştırma sonucu."""
    job_type: str
    status: str           # SUCCESS, FAILED, TIMEOUT, RETRY
    duration_ms: float
    timestamp: str
    error: Optional[str] = None
    retry_count: int = 0
    result: Any = None


# =====================================================
# Unified Scheduler
# =====================================================

class UnifiedScheduler:
    """Tek canonical scheduler — tüm job'ları yönetir.

    Özellikler:
    - Market session-aware (BIST saatleri)
    - Config-driven intervals
    - Job retry policy (exponential backoff)
    - Job monitoring (status, duration, failure)
    - SIGTERM/SIGINT handler
    - Graceful shutdown
    """

    def __init__(self, job_configs: Optional[Dict[str, JobConfig]] = None):
        self._market = MarketSessionManager()
        self._configs = {**DEFAULT_JOB_CONFIGS, **(job_configs or {})}
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._last_run: Dict[str, float] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Job monitoring
        self._job_history: List[JobResult] = []
        self._max_history = 1000

        # Phase callbacks
        self._phase_callbacks: Dict[str, List[Callable]] = {}

    def register_handler(self, job_type: str, handler: Callable[..., Awaitable[Any]]):
        """Job handler kaydet."""
        self._handlers[job_type] = handler
        logger.info("Handler registered", job_type=job_type)

    def register_phase_callback(self, phase: str, callback: Callable):
        """Faz değişikliği callback'i kaydet."""
        if phase not in self._phase_callbacks:
            self._phase_callbacks[phase] = []
        self._phase_callbacks[phase].append(callback)

    def update_interval(self, job_type: str, interval_seconds: int):
        """Job interval'ını runtime'da güncelle."""
        if job_type in self._configs:
            self._configs[job_type].interval_seconds = interval_seconds
            logger.info("Interval updated", job_type=job_type, interval=interval_seconds)

    def enable_job(self, job_type: str, enabled: bool = True):
        """Job'ı aktif/pasif yap."""
        if job_type in self._configs:
            self._configs[job_type].enabled = enabled

    async def start(self):
        """Scheduler'ı başlat."""
        self._running = True

        # Signal handler
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._signal_handler, sig)
            except NotImplementedError:
                pass

        logger.info("=== UNIFIED SCHEDULER STARTING ===",
                    phase=self._market.current_phase().value)

        # Startup sequence
        await self._startup_sequence()

        # Ana döngü
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler tick error", error=str(e))
                await asyncio.sleep(10)

        logger.info("=== UNIFIED SCHEDULER STOPPED ===")

    async def stop(self):
        """Scheduler'ı durdur."""
        self._running = False
        self._shutdown_event.set()
        logger.info("Scheduler stop requested")

    def _signal_handler(self, sig):
        """SIGTERM/SIGINT callback."""
        logger.info(f"Signal {sig} received, shutting down")
        self._running = False
        self._shutdown_event.set()

    async def _startup_sequence(self):
        """Startup kontrolleri."""
        logger.info("Running startup sequence...")

        # Market session
        status = self._market.get_status()
        logger.info("Market session", **status)

        # Registered handlers
        logger.info("Registered handlers", count=len(self._handlers),
                    handlers=list(self._handlers.keys()))

        logger.info("Startup sequence complete")

    async def _tick(self):
        """Tek scheduler döngüsü."""
        phase = self._market.current_phase()

        # Faz bazlı job'ları çalıştır
        if phase == MarketPhase.CLOSED or phase == MarketPhase.NIGHT:
            await self._run_jobs_for_phase("night")
            sleep_time = min(self._market.seconds_until_next_phase(), 300)
            await asyncio.sleep(max(sleep_time, 30))

        elif phase == MarketPhase.PRE_MARKET:
            await self._run_jobs_for_phase("pre_market")
            await asyncio.sleep(30)

        elif phase in [MarketPhase.SEANS_1, MarketPhase.SEANS_2]:
            await self._run_jobs_for_phase("active")
            await asyncio.sleep(30)

        elif phase == MarketPhase.BREAK:
            await self._run_jobs_for_phase("break")
            await asyncio.sleep(60)

        elif phase == MarketPhase.CLOSING:
            await self._run_jobs_for_phase("closing")
            await asyncio.sleep(30)

        elif phase == MarketPhase.POST_MARKET:
            await self._run_jobs_for_phase("post_market")
            await asyncio.sleep(30)

        elif phase == MarketPhase.AFTER_HOURS:
            await self._run_jobs_for_phase("after_hours")
            await asyncio.sleep(120)

    async def _run_jobs_for_phase(self, phase_name: str):
        """Belirli bir faz için job'ları çalıştır."""
        for job_type, config in self._configs.items():
            if not config.enabled:
                continue

            # Trading-only kontrolü
            if config.trading_only and not self._market.should_run_trading_job():
                continue

            await self._maybe_run_job(job_type, config)

    async def _maybe_run_job(self, job_type: str, config: JobConfig):
        """Job çalıştırılmalı mı? Interval kontrolü."""
        now = time.time()
        last = self._last_run.get(job_type, 0)

        if now - last < config.interval_seconds:
            return

        handler = self._handlers.get(job_type)
        if handler is None:
            return

        self._last_run[job_type] = now

        # Job çalıştır (retry ile)
        await self._execute_with_retry(job_type, handler, config)

    async def _execute_with_retry(
        self,
        job_type: str,
        handler: Callable,
        config: JobConfig,
    ):
        """Retry ile job çalıştır."""
        last_error = None
        start_time = time.time()

        for attempt in range(config.max_retries + 1):
            try:
                # Timeout ile çalıştır
                result = await asyncio.wait_for(
                    handler(),
                    timeout=config.timeout_seconds,
                )

                duration_ms = (time.time() - start_time) * 1000

                # Başarılı
                self._record_job(JobResult(
                    job_type=job_type,
                    status="SUCCESS",
                    duration_ms=duration_ms,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=attempt,
                    result=result,
                ))

                if attempt > 0:
                    logger.info("Job succeeded after retry",
                               job_type=job_type, attempt=attempt)

                return result

            except asyncio.TimeoutError:
                last_error = f"Timeout after {config.timeout_seconds}s"
                if attempt < config.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning("Job timeout, retrying",
                                 job_type=job_type, attempt=attempt, delay=delay)
                    await asyncio.sleep(delay)

            except Exception as e:
                last_error = str(e)
                if attempt < config.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning("Job failed, retrying",
                                 job_type=job_type, attempt=attempt,
                                 delay=delay, error=str(e))
                    await asyncio.sleep(delay)

        # Tüm retry'lar başarısız
        duration_ms = (time.time() - start_time) * 1000
        self._record_job(JobResult(
            job_type=job_type,
            status="FAILED",
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=last_error,
            retry_count=config.max_retries,
        ))

        logger.error("Job failed after all retries",
                    job_type=job_type, error=last_error)

    def _record_job(self, result: JobResult):
        """Job sonucunu kaydet."""
        self._job_history.append(result)
        if len(self._job_history) > self._max_history:
            self._job_history = self._job_history[-self._max_history:]

    def get_status(self) -> Dict[str, Any]:
        """Scheduler durumu."""
        return {
            "running": self._running,
            "market": self._market.get_status(),
            "registered_handlers": len(self._handlers),
            "job_configs": len(self._configs),
            "total_jobs_run": len(self._job_history),
            "last_runs": {
                job_type: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                for job_type, ts in self._last_run.items()
            },
        }

    def get_job_stats(self, job_type: str = None) -> Dict[str, Any]:
        """Job istatistikleri."""
        history = self._job_history
        if job_type:
            history = [h for h in history if h.job_type == job_type]

        if not history:
            return {"total_jobs": 0}

        total = len(history)
        failed = sum(1 for h in history if h.status == "FAILED")
        durations = [h.duration_ms for h in history]

        return {
            "total_jobs": total,
            "failed_jobs": failed,
            "success_rate": round((total - failed) / total, 4) if total > 0 else 0,
            "avg_duration_ms": round(sum(durations) / len(durations), 2),
            "max_duration_ms": round(max(durations), 2),
            "last_failure": next(
                (h.timestamp for h in reversed(history) if h.status == "FAILED"),
                None
            ),
        }

    def get_job_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Job geçmişini al."""
        return [
            {
                "job_type": r.job_type,
                "status": r.status,
                "duration_ms": round(r.duration_ms, 2),
                "timestamp": r.timestamp,
                "error": r.error,
                "retry_count": r.retry_count,
            }
            for r in self._job_history[-limit:]
        ]

    def get_market_session(self) -> MarketSessionManager:
        """Market session manager'ı al."""
        return self._market


# Singleton
unified_scheduler = UnifiedScheduler()
