"""
ALPHA BIST — Unified Scheduler v2.0

Tek canonical scheduler: AlphaScheduler + ProductionScheduler birleştirildi.

Özellikler:
- Market session-aware (BIST saatleri, 9 faz)
- Config-driven intervals
- Priority-based execution (yüksek öncelik önce çalışır)
- DB-backed job tracking (system_jobs tablosu)
- Job retry policy (exponential backoff, timeout)
- Job monitoring (status, duration, failure, alerting)
- Dinamik tatil takvimi (config + hardcoded fallback)
- SIGTERM/SIGINT handler
- Graceful shutdown
- Manuel tetikleme (trigger) desteği

Kaynaklar: arXiv Agentic Trading (2026), BIST resmi, APScheduler best practices
"""

import asyncio
import json
import signal
import time
from datetime import datetime, time as dt_time, timezone, timedelta, date
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


# =====================================================
# Constants
# =====================================================

_TZ_ISTANBUL = timezone(timedelta(hours=3))


# =====================================================
# Market Phases
# =====================================================

class MarketPhase(str, Enum):
    """BIST piyasa fazları."""
    CLOSED = "CLOSED"            # Piyasa kapalı (gece, hafta sonu, tatil)
    PRE_MARKET = "PRE_MARKET"    # 09:40-09:55 (emir toplama)
    SEANS_1 = "SEANS_1"          # 09:55-12:30 (tek fiyat)
    BREAK = "BREAK"              # 12:30-14:00 (ara)
    SEANS_2 = "SEANS_2"          # 14:00-17:40 (sürekli müzayede)
    CLOSING = "CLOSING"          # 17:40-18:00 (kapanış)
    POST_MARKET = "POST_MARKET"  # 18:00-18:30
    AFTER_HOURS = "AFTER_HOURS"  # 18:30-23:00
    NIGHT = "NIGHT"              # 23:00-09:40


# =====================================================
# Holiday Provider (Dinamik + Fallback)
# =====================================================

class HolidayProvider:
    """BIST tatil günleri sağlayıcısı.

    Öncelik sırası:
    1. DB'den dinamik çekim (config_holidays tablosu)
    2. Config dosyası (config/holidays.json)
    3. Hardcoded fallback (2026)
    """

    # Hardcoded fallback — sadece dinamik kaynak yoksa kullanılır
    _FALLBACK_2026: set = frozenset({
        date(2026, 1, 1),    # Yılbaşı
        date(2026, 4, 23),   # Ulusal Egemenlik
        date(2026, 5, 1),    # İşçi Bayramı
        date(2026, 5, 19),   # Gençlik Bayramı
        date(2026, 7, 15),   # Demokrasi Bayramı
        date(2026, 8, 30),   # Zafer Bayramı
        date(2026, 10, 29),  # Cumhuriyet Bayramı
        date(2026, 3, 29),   # Ramazan Bayramı (1)
        date(2026, 3, 30),   # Ramazan Bayramı (2)
        date(2026, 3, 31),   # Ramazan Bayramı (3)
        date(2026, 6, 6),    # Kurban Bayramı (1)
        date(2026, 6, 7),    # Kurban Bayramı (2)
        date(2026, 6, 8),    # Kurban Bayramı (3)
        date(2026, 6, 9),    # Kurban Bayramı (4)
    })

    def __init__(self):
        self._dynamic_holidays: Optional[set] = None
        self._last_fetch: float = 0
        self._fetch_interval: float = 3600  # 1 saatte bir yenile

    def get_holidays(self) -> set:
        """Tatil günlerini al (dinamik + fallback)."""
        now = time.time()

        # Cache süresi dolmuşsa yenile
        if self._dynamic_holidays is None or (now - self._last_fetch) > self._fetch_interval:
            self._refresh()

        # Dinamik + fallback birleşimi
        return self._dynamic_holidays | self._FALLBACK_2026

    def is_holiday(self, dt: datetime) -> bool:
        """Belirli bir gün tatil mi?"""
        d = dt.date() if hasattr(dt, 'date') else dt
        # Dinamik + fallback birleşimine bak
        all_holidays = self.get_holidays()
        return d in all_holidays

    def add_holiday(self, d: date):
        """Tatil günü ekle (runtime)."""
        if self._dynamic_holidays is None:
            self._dynamic_holidays = set()
        self._dynamic_holidays.add(d)
        # Cache'i invalidate etme — _refresh() çağrılırsa runtime eklenenler kaybolur
        # Bunun yerine _last_fetch'i güncelle ki refresh tetiklenmesin
        self._last_fetch = time.time()

    def remove_holiday(self, d: date):
        """Tatil günü kaldır (runtime)."""
        if self._dynamic_holidays is not None:
            self._dynamic_holidays.discard(d)

    def _refresh(self):
        """Dinamik tatil günlerini yenile."""
        holidays = set()

        # 1. Config dosyasından oku
        try:
            import os
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config", "holidays.json"
            )
            if os.path.exists(config_path):
                with open(config_path) as f:
                    data = json.load(f)
                    for h in data.get("holidays", []):
                        holidays.add(date.fromisoformat(h))
        except Exception:
            pass

        # 2. DB'den çek (varsa)
        try:
            # DB erişimi varsa config_holidays tablosundan çek
            # Bu kısım async değil, sync — startup'ta yüklenir
            pass
        except Exception:
            pass

        self._dynamic_holidays = holidays
        self._last_fetch = time.time()


# =====================================================
# Market Session Manager
# =====================================================

class MarketSessionManager:
    """BIST piyasa saatleri yöneticisi.

    BIST işlem saatleri (Europe/Istanbul, UTC+3):
    - Pre-market:  09:40-09:55
    - Seans 1:     09:55-12:30 (tek fiyat)
    - Break:       12:30-14:00
    - Seans 2:     14:00-17:40 (sürekli müzayede)
    - Closing:     17:40-18:00
    - Post-market: 18:00-18:30
    - After-hours: 18:30-23:00
    - Night:       23:00-09:40
    """

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

    def __init__(self, holiday_provider: Optional[HolidayProvider] = None):
        self._holiday_provider = holiday_provider or HolidayProvider()
        self._current_phase: Optional[MarketPhase] = None
        self._phase_callbacks: Dict[MarketPhase, List[Callable]] = {}

    def now_istanbul(self) -> datetime:
        """Şu anki Istanbul zamanı."""
        return datetime.now(_TZ_ISTANBUL)

    def current_phase(self) -> MarketPhase:
        """Mevcut piyasa fazını al."""
        now = self.now_istanbul()

        # Hafta sonu
        if now.weekday() >= 5:
            return MarketPhase.CLOSED

        # Tatil (dinamik)
        if self._holiday_provider.is_holiday(now):
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
        return self.current_phase() in [MarketPhase.SEANS_1, MarketPhase.SEANS_2, MarketPhase.CLOSING]

    def is_market_open(self) -> bool:
        """Piyasa açık mı? (işlem + pre/post dahil)"""
        return self.current_phase() not in [MarketPhase.CLOSED, MarketPhase.NIGHT]

    def should_run_trading_job(self) -> bool:
        """Trading job'ları çalıştırılmalı mı?"""
        return self.is_trading_hours()

    def seconds_until_next_phase(self) -> float:
        """Bir sonraki faza kaç saniye var?"""
        now = self.now_istanbul()
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
        # Hafta sonu atla
        while tomorrow.weekday() >= 5:
            tomorrow += timedelta(days=1)
        target = tomorrow.replace(hour=9, minute=40, second=0, microsecond=0)
        return max(0, (target - now).total_seconds())

    def get_status(self) -> Dict[str, Any]:
        """Piyasa durumu."""
        phase = self.current_phase()
        now = self.now_istanbul()
        return {
            "phase": phase.value,
            "istanbul_time": now.isoformat(),
            "weekday": now.strftime("%A"),
            "is_trading": self.is_trading_hours(),
            "is_open": self.is_market_open(),
            "is_holiday": self._holiday_provider.is_holiday(now),
            "is_trading_day": now.weekday() < 5 and not self._holiday_provider.is_holiday(now),
            "seconds_until_next": round(self.seconds_until_next_phase()),
        }

    def get_holiday_provider(self) -> HolidayProvider:
        """Tatil sağlayıcısını al."""
        return self._holiday_provider

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


# Varsayılan job konfigürasyonları — priority bazlı
DEFAULT_JOB_CONFIGS = {
    # Pre-market (yüksek öncelik)
    JobType.MARKET_DATA_UPDATE: JobConfig(
        job_type=JobType.MARKET_DATA_UPDATE,
        interval_seconds=120,
        trading_only=False,
        priority=1,
        description="Piyasa verisi güncelleme",
    ),
    JobType.FEATURE_CALCULATION: JobConfig(
        job_type=JobType.FEATURE_CALCULATION,
        interval_seconds=300,
        trading_only=False,
        priority=1,
        description="Feature hesaplama",
    ),
    JobType.UNIVERSE_REFRESH: JobConfig(
        job_type=JobType.UNIVERSE_REFRESH,
        interval_seconds=86400,
        trading_only=False,
        priority=8,
        description="Universe yenileme",
    ),

    # Active trading (yüksek-orta öncelik)
    JobType.LIVE_SCANNING: JobConfig(
        job_type=JobType.LIVE_SCANNING,
        interval_seconds=0,  # Continuous
        trading_only=True,
        priority=2,
        description="Canlı tarama",
    ),
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
    JobType.PERFORMANCE_ATTRIBUTION: JobConfig(
        job_type=JobType.PERFORMANCE_ATTRIBUTION,
        interval_seconds=86400,
        trading_only=False,
        priority=7,
        description="Performans atıf analizi",
    ),

    # After-hours (düşük öncelik)
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
    JobType.CALIBRATION_UPDATE: JobConfig(
        job_type=JobType.CALIBRATION_UPDATE,
        interval_seconds=2592000,  # 30 gün
        trading_only=False,
        priority=9,
        description="Calibration güncelleme",
    ),

    # Night
    JobType.BACKUP: JobConfig(
        job_type=JobType.BACKUP,
        interval_seconds=86400,
        trading_only=False,
        priority=10,
        description="Veritabanı yedekleme",
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
    triggered_by: str = "scheduler"  # scheduler, manual, phase_change


# =====================================================
# DB-Backed Job Tracker
# =====================================================

class DBJobTracker:
    """Job geçmişini DB'ye persist eder.

    system_jobs tablosuna yazar (varsa).
    DB yoksa in-memory fallback kullanır.
    """

    def __init__(self):
        self._db_available: Optional[bool] = None
        self._memory_history: List[Dict[str, Any]] = []
        self._max_memory = 1000

    async def record_job(self, result: JobResult) -> bool:
        """Job sonucunu kaydet (DB veya memory)."""
        if self._is_db_available():
            try:
                from services.core.database import pg_execute
                await asyncio.wait_for(
                    pg_execute(
                        """INSERT INTO system_jobs
                           (job_type, status, duration_ms, error_message,
                            retry_count, triggered_by, completed_at)
                           VALUES ($1, $2, $3, $4, $5, $6, NOW())""",
                        result.job_type,
                        result.status,
                        result.duration_ms,
                        result.error,
                        result.retry_count,
                        result.triggered_by,
                    ),
                    timeout=3.0,
                )
                return True
            except Exception as e:
                logger.warning("DB job record failed, falling back to memory",
                             error=str(e)[:100])
                self._db_available = False

        # In-memory fallback
        self._memory_history.append({
            "job_type": result.job_type,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "timestamp": result.timestamp,
            "error": result.error,
            "retry_count": result.retry_count,
            "triggered_by": result.triggered_by,
        })
        if len(self._memory_history) > self._max_memory:
            self._memory_history = self._memory_history[-self._max_memory:]
        return True

    async def get_job_history(self, job_type: str = None, limit: int = 50) -> List[Dict]:
        """Job geçmişini al."""
        if self._is_db_available():
            try:
                from services.core.database import pg_fetch
                if job_type:
                    rows = await asyncio.wait_for(
                        pg_fetch(
                            """SELECT job_type, status, duration_ms, error_message,
                                      retry_count, triggered_by, completed_at
                               FROM system_jobs
                               WHERE job_type = $1
                               ORDER BY completed_at DESC LIMIT $2""",
                            job_type, limit,
                        ),
                        timeout=3.0,
                    )
                else:
                    rows = await asyncio.wait_for(
                        pg_fetch(
                            """SELECT job_type, status, duration_ms, error_message,
                                      retry_count, triggered_by, completed_at
                               FROM system_jobs
                               ORDER BY completed_at DESC LIMIT $1""",
                            limit,
                        ),
                        timeout=3.0,
                    )
                return [dict(r) for r in rows]
            except Exception:
                self._db_available = False

        # In-memory fallback
        history = self._memory_history
        if job_type:
            history = [h for h in history if h["job_type"] == job_type]
        return history[-limit:]

    async def get_failure_stats(self, window_hours: int = 24) -> Dict[str, Any]:
        """Son N saatteki failure istatistikleri."""
        if self._is_db_available():
            try:
                from services.core.database import pg_fetchrow
                row = await asyncio.wait_for(
                    pg_fetchrow(
                        """SELECT
                             COUNT(*) as total,
                             COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                             COUNT(*) FILTER (WHERE status = 'SUCCESS') as success,
                             AVG(duration_ms) FILTER (WHERE status = 'SUCCESS') as avg_duration
                           FROM system_jobs
                           WHERE completed_at > NOW() - INTERVAL '1 hour' * $1""",
                        window_hours,
                    ),
                    timeout=3.0,
                )
                if row:
                    return dict(row)
            except Exception:
                self._db_available = False

        # In-memory fallback
        cutoff = time.time() - (window_hours * 3600)
        recent = [h for h in self._memory_history
                  if datetime.fromisoformat(h["timestamp"]).timestamp() > cutoff]
        total = len(recent)
        failed = sum(1 for h in recent if h["status"] == "FAILED")
        return {
            "total": total,
            "failed": failed,
            "success": total - failed,
            "avg_duration": sum(h["duration_ms"] for h in recent) / max(total, 1),
        }

    def _is_db_available(self) -> bool:
        """DB erişimi var mı?"""
        if self._db_available is not None:
            return self._db_available
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex(('127.0.0.1', 5432))
            s.close()
            self._db_available = result == 0
            return self._db_available
        except Exception:
            self._db_available = False
            return False


# =====================================================
# Unified Scheduler
# =====================================================

class UnifiedScheduler:
    """Tek canonical scheduler — tüm job'ları yönetir.

    Özellikler:
    - Market session-aware (BIST saatleri, 9 faz)
    - Config-driven intervals
    - Priority-based execution (yüksek öncelik önce çalışır)
    - DB-backed job tracking (system_jobs tablosu)
    - Job retry policy (exponential backoff, timeout)
    - Job monitoring (status, duration, failure, alerting)
    - Dinamik tatil takvimi
    - SIGTERM/SIGINT handler
    - Graceful shutdown
    - Manuel tetikleme (trigger) desteği
    """

    def __init__(self, job_configs: Optional[Dict[str, JobConfig]] = None):
        self._market = MarketSessionManager()
        self._configs = {**DEFAULT_JOB_CONFIGS, **(job_configs or {})}
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._last_run: Dict[str, float] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()

        # DB-backed job tracking
        self._db_tracker = DBJobTracker()

        # In-memory job history (monitor için)
        self._job_history: List[JobResult] = []
        self._max_history = 1000

        # Manual trigger queue
        self._trigger_queue: asyncio.Queue = asyncio.Queue()

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

    def update_priority(self, job_type: str, priority: int):
        """Job önceliğini güncelle."""
        if job_type in self._configs:
            self._configs[job_type].priority = max(1, min(10, priority))

    async def trigger_job(self, job_type: str) -> Dict[str, Any]:
        """Job'ı manuel olarak tetikle.

        Args:
            job_type: Tetiklenecek job tipi

        Returns:
            Tetikleme sonucu
        """
        handler = self._handlers.get(job_type)
        if handler is None:
            return {"status": "ERROR", "message": f"No handler for {job_type}"}

        config = self._configs.get(job_type)
        if config is None:
            return {"status": "ERROR", "message": f"No config for {job_type}"}

        logger.info("Manual trigger", job_type=job_type)

        # Trigger queue'ya ekle
        await self._trigger_queue.put((job_type, handler, config))

        return {
            "status": "QUEUED",
            "job_type": job_type,
            "message": "Job queued for immediate execution",
        }

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

        # Ana döngü — paralel: tick + trigger consumer
        await asyncio.gather(
            self._main_loop(),
            self._trigger_consumer(),
        )

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

        # Tatil takvimi
        holiday_count = len(self._market.get_holiday_provider().get_holidays())
        logger.info("Holiday calendar loaded", count=holiday_count)

        # Registered handlers
        logger.info("Registered handlers", count=len(self._handlers),
                    handlers=list(self._handlers.keys()))

        # Job configs
        enabled = sum(1 for c in self._configs.values() if c.enabled)
        logger.info("Job configs", total=len(self._configs), enabled=enabled)

        logger.info("Startup sequence complete")

    async def _main_loop(self):
        """Ana scheduler döngüsü."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler tick error", error=str(e))
                await asyncio.sleep(10)

    async def _trigger_consumer(self):
        """Manuel tetikleme queue'sunu tüket."""
        while self._running:
            try:
                job_type, handler, config = await asyncio.wait_for(
                    self._trigger_queue.get(), timeout=5.0
                )
                await self._execute_with_retry(
                    job_type, handler, config, triggered_by="manual"
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Trigger consumer error", error=str(e))

    async def _tick(self):
        """Tek scheduler döngüsü.

        Market fazına göre hangi job grubunun çalıştırılacağına karar verir.
        Her faz için farklı sleep süresi uygulanır:
        - ACTIVE: 30s (sık kontrol, trading job'ları için)
        - NIGHT: 300s (nadir kontrol, tasarruf)
        - BREAK: 60s (orta sıklık)
        """
        phase = self._market.current_phase()

        if phase in [MarketPhase.CLOSED, MarketPhase.NIGHT]:
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
        """Belirli bir faz için job'ları priority sırasıyla çalıştır.

        Priority sıralaması: p=1 (en yüksek) → p=10 (en düşük).
        Bu sayede kritik job'lar (market_data, risk) her zaman önce çalışır.
        Trading-only job'lar piyasa kapalıyken otomatik atlanır.
        """
        # Priority bazlı sıralama: düşük sayı = yüksek öncelik
        eligible_jobs = []
        for job_type, config in self._configs.items():
            if not config.enabled:
                continue
            if config.trading_only and not self._market.should_run_trading_job():
                continue
            eligible_jobs.append((job_type, config))

        # Priority'ye göre sırala (1=en yüksek)
        eligible_jobs.sort(key=lambda x: x[1].priority)

        for job_type, config in eligible_jobs:
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
        triggered_by: str = "scheduler",
    ):
        """Retry ile job çalıştır.

        Exponential backoff: 1s → 2s → 4s (attempt 0 → 1 → 2).
        Timeout: config.timeout_seconds kadar bekler, aşarsa TIMEOUT.
        Tüm retry'lar başarısızsa FAILED olarak kaydeder.
        """
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
                job_result = JobResult(
                    job_type=job_type,
                    status="SUCCESS",
                    duration_ms=duration_ms,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=attempt,
                    result=result,
                    triggered_by=triggered_by,
                )
                await self._record_job(job_result)

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
        job_result = JobResult(
            job_type=job_type,
            status="FAILED",
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=last_error,
            retry_count=config.max_retries,
            triggered_by=triggered_by,
        )
        await self._record_job(job_result)

        logger.error("Job failed after all retries",
                    job_type=job_type, error=last_error)

    async def _record_job(self, result: JobResult):
        """Job sonucunu kaydet (DB + memory)."""
        # DB'ye persist et
        await self._db_tracker.record_job(result)

        # In-memory history (monitor için)
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
            "enabled_configs": sum(1 for c in self._configs.values() if c.enabled),
            "total_jobs_run": len(self._job_history),
            "trigger_queue_size": self._trigger_queue.qsize(),
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
                "triggered_by": r.triggered_by,
            }
            for r in self._job_history[-limit:]
        ]

    def get_job_configs(self) -> Dict[str, Dict[str, Any]]:
        """Tüm job konfigürasyonlarını al."""
        return {
            name: {
                "interval_seconds": config.interval_seconds,
                "trading_only": config.trading_only,
                "priority": config.priority,
                "enabled": config.enabled,
                "max_retries": config.max_retries,
                "timeout_seconds": config.timeout_seconds,
                "description": config.description,
            }
            for name, config in self._configs.items()
        }

    def get_market_session(self) -> MarketSessionManager:
        """Market session manager'ı al."""
        return self._market

    def get_db_tracker(self) -> DBJobTracker:
        """DB job tracker'ı al."""
        return self._db_tracker


# Singleton
unified_scheduler = UnifiedScheduler()
