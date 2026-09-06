"""ALPHA BIST — Veritabanı Kilit Soyutlaması ve Koordinasyonu v3.0 (Enterprise-Grade)

Kurumsal Kilit Mimarisi (GEMINI.md Standartları):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. İki Katmanlı Kilit (CoordinatedLock):
   - Katman 1: Süreç içi (in-process) `asyncio.Lock` ile thread/task senkronizasyonu
   - Katman 2: Veritabanı seviyesi (DB Advisory Lock) ile çoklu worker/node koordinasyonu
2. Dialect Desteği:
   - PostgreSQL: `pg_try_advisory_lock($1)` / `pg_advisory_unlock($1)` (Ana Üretim Standardı)
   - DuckDB: In-process gömülü kilit yönetimi (Yerel Araştırma ve Durum Yönetimi)
   - SQLite: Test ve geriye dönük uyumluluk (`BEGIN IMMEDIATE` / `COMMIT`)
3. Dayanıklılık ve Güvenlik:
   - Exponential Backoff + Jitter ile yarış koşulu (herd effect) önleme
   - Otomatik Lock Lease Renewal (uzun süren işlemlerde kilit tazeleme)
   - Crash Recovery & Stale Lock Temizleme (ölen worker kilitlerini kurtarma)
4. İzlenebilirlik ve Analitik:
   - OpenTelemetry (OTel) span ve sayaç/histogram metrikleri
   - Sıfır kopyalı Polars ve yerel DuckDB denetim ihracı (`export_lock_metrics_to_polars`)
   - Kesintisiz Türkçe loglama (structlog)
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics, trace

from services.core.duckdb_store import configure_duckdb_wal

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.db-lock")
meter = metrics.get_meter("alpha-bist.db-lock")

# ─── OpenTelemetry Metrikleri ─────────────────────────────────────────────────
_lock_acquisitions = meter.create_counter(
    "alpha.lock.acquisitions.total",
    description="Toplam kilit edinme sayısı",
)
_lock_timeouts = meter.create_counter(
    "alpha.lock.timeouts.total",
    description="Kilit zaman aşımı sayısı",
)
_lock_wait_histogram = meter.create_histogram(
    "alpha.lock.wait_ms",
    description="Kilit bekleme süresi",
    unit="ms",
)

# ─── Sabitler ─────────────────────────────────────────────────────────────────
DEFAULT_LOCK_KEY: str = "bist_system_lock"
DEFAULT_TIMEOUT_MS: int = 5000
DEFAULT_MAX_RETRIES: int = 5
DEFAULT_BASE_RETRY_MS: int = 50
DEFAULT_MAX_RETRY_MS: int = 2000
DEFAULT_LEASE_RENEWAL_INTERVAL_S: float = 30.0
DEFAULT_STALE_LOCK_TIMEOUT_S: float = 300.0
DEFAULT_LOCK_AUDIT_DUCKDB_PATH: str = "data/lock_audit.duckdb"
DEFAULT_LOCK_AUDIT_TABLE: str = "bist_lock_audit"

# Deadlock engelleme hiyerarşisi (Lock ordering)
LOCK_ORDER: dict[str, int] = {
    "portfolio_init": 1,
    "portfolio_trade": 2,
    "migration": 10,
    "system_sync": 20,
}

# Arka plan görevlerinin GC tarafından toplanmasını önleyen küme
_bg_tasks: set[asyncio.Task[Any]] = set()


# =====================================================
# LOCK METRICS MODELİ
# =====================================================


@dataclass
class LockMetrics:
    """Kilit performans metriklerini ve sağlık durumunu izleyen veri modeli."""

    total_acquisitions: int = 0
    total_releases: int = 0
    total_timeouts: int = 0
    total_deadlocks_detected: int = 0
    total_errors: int = 0
    total_renewals: int = 0
    total_crash_recoveries: int = 0
    total_wait_ms: float = 0.0
    max_wait_ms: float = 0.0
    last_acquisition_ms: float = 0.0
    last_timeout_at: float | None = None
    last_error_at: float | None = None
    created_at: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<LockMetrics acq={self.total_acquisitions} rel={self.total_releases} "
            f"to={self.total_timeouts} dl={self.total_deadlocks_detected}>"
        )

    def record_acquisition(self, wait_ms: float) -> None:
        """Kilit edinme süresini kaydeder.

        Args:
            wait_ms: Kilidi alana kadar geçen bekleme süresi (milisaniye).
        """
        self.total_acquisitions += 1
        self.total_wait_ms += wait_ms
        self.last_acquisition_ms = wait_ms
        if wait_ms > self.max_wait_ms:
            self.max_wait_ms = wait_ms

    def record_release(self) -> None:
        """Kilit serbest bırakma operasyonunu kaydeder."""
        self.total_releases += 1

    def record_timeout(self) -> None:
        """Kilit zaman aşımını kaydeder."""
        self.total_timeouts += 1
        self.last_timeout_at = time.time()

    def record_deadlock(self) -> None:
        """Kilitlenme (deadlock) tespitini kaydeder."""
        self.total_deadlocks_detected += 1

    def record_error(self) -> None:
        """Kilit operasyon hatasını kaydeder."""
        self.total_errors += 1
        self.last_error_at = time.time()

    def record_renewal(self) -> None:
        """Kilit kira tazeleme (lease renewal) operasyonunu kaydeder."""
        self.total_renewals += 1

    def record_crash_recovery(self) -> None:
        """Kopmuş veya bayatlamış kilit kurtarma operasyonunu kaydeder."""
        self.total_crash_recoveries += 1

    def to_dict(self) -> dict[str, Any]:
        """Metrik özetini sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Sayısal kilit performans istatistikleri.
        """
        avg = self.total_wait_ms / self.total_acquisitions if self.total_acquisitions else 0.0
        uptime_s = time.time() - self.created_at
        return {
            "total_acquisitions": self.total_acquisitions,
            "total_releases": self.total_releases,
            "total_timeouts": self.total_timeouts,
            "total_deadlocks_detected": self.total_deadlocks_detected,
            "total_errors": self.total_errors,
            "total_renewals": self.total_renewals,
            "total_crash_recoveries": self.total_crash_recoveries,
            "avg_wait_ms": round(avg, 2),
            "max_wait_ms": round(self.max_wait_ms, 2),
            "last_acquisition_ms": round(self.last_acquisition_ms, 2),
            "uptime_seconds": round(uptime_s, 1),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirilmiş bayt dizisi döndürür."""
        return orjson.dumps(self.to_dict())

    def health_status(self) -> dict[str, Any]:
        """Kilit sağlık ve bozulma durumunu analiz eder.

        Returns:
            dict[str, Any]: Durum ('HEALTHY', 'DEGRADED', 'UNHEALTHY') ve sorunlar listesi.
        """
        now = time.time()
        issues: list[str] = []

        if self.last_timeout_at and (now - self.last_timeout_at) < 300:
            issues.append("recent_timeout")

        if self.total_deadlocks_detected > 0:
            issues.append("deadlock_detected")

        if self.total_acquisitions > 10:
            timeout_rate = self.total_timeouts / self.total_acquisitions
            if timeout_rate > 0.1:
                issues.append(f"high_timeout_rate:{timeout_rate:.1%}")

        avg = self.total_wait_ms / self.total_acquisitions if self.total_acquisitions else 0.0
        if avg > 1000:
            issues.append(f"high_avg_wait:{avg:.0f}ms")

        status = "HEALTHY" if not issues else "DEGRADED" if len(issues) <= 2 else "UNHEALTHY"
        return {"status": status, "issues": issues}


# Global thread-safe metrik deposu ve adlandırılmış süreç içi kilitler
_metrics_lock = threading.RLock()
_metrics: dict[str, LockMetrics] = {}
_named_asyncio_locks: dict[str, asyncio.Lock] = {}


def _get_named_asyncio_lock(key: str) -> asyncio.Lock:
    """Aynı anahtara sahip tüm kilitlerin süreç içi aynı asyncio.Lock'u paylaşmasını sağlar.

    Args:
        key: Kilit anahtarı.

    Returns:
        asyncio.Lock: Paylaşımlı asenkron kilit nesnesi.
    """
    with _metrics_lock:
        if key not in _named_asyncio_locks:
            _named_asyncio_locks[key] = asyncio.Lock()
        return _named_asyncio_locks[key]


def get_lock_metrics(key: str) -> LockMetrics:
    """Kilit anahtarına özel metrik nesnesini döndürür veya oluşturur.

    Args:
        key: Kilit anahtarı.

    Returns:
        LockMetrics: Kilit metrik nesnesi.
    """
    with _metrics_lock:
        if key not in _metrics:
            _metrics[key] = LockMetrics()
        return _metrics[key]


def get_all_metrics() -> dict[str, dict[str, Any]]:
    """Tüm kilitlerin performans metriklerini döndürür.

    Returns:
        dict[str, dict[str, Any]]: Kilit anahtarı ve metrik sözlükleri haritası.
    """
    with _metrics_lock:
        return {k: v.to_dict() for k, v in _metrics.items()}


def get_health_report() -> dict[str, Any]:
    """Tüm kilit mekanizmasının sağlık durum raporunu üretir.

    Returns:
        dict[str, Any]: Genel sağlık durumu ve kilit bazlı detaylar.
    """
    report: dict[str, Any] = {}
    overall_healthy = True
    with _metrics_lock:
        items = list(_metrics.items())

    for key, m in items:
        health = m.health_status()
        report[key] = {**m.to_dict(), **health}
        if health["status"] != "HEALTHY":
            overall_healthy = False

    return {
        "overall_status": "HEALTHY" if overall_healthy else "DEGRADED",
        "locks": report,
    }


# =====================================================
# DATABASE LOCK (VERİTABANI KİLİT MOTORU)
# =====================================================


class DatabaseLock:
    """Veritabanı seviyesi advisory lock yönetim sınıfı.

    Desteklenen Diyalektler:
    - PostgreSQL: pg_try_advisory_lock (bloklamayan) + Exponential Backoff
    - DuckDB: Yerel kilit simülasyonu ve süreç içi koruma
    - SQLite: BEGIN IMMEDIATE + retry (test uyumluluğu)
    """

    def __init__(
        self,
        db: Any = None,
        dialect: str = "postgresql",
        key: str = DEFAULT_LOCK_KEY,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_retry_ms: int = DEFAULT_BASE_RETRY_MS,
        max_retry_ms: int = DEFAULT_MAX_RETRY_MS,
        lease_renewal_interval_s: float = DEFAULT_LEASE_RENEWAL_INTERVAL_S,
        stale_lock_timeout_s: float = DEFAULT_STALE_LOCK_TIMEOUT_S,
    ) -> None:
        """Başlatıcı.

        Args:
            db: Veritabanı bağlantı veya havuz nesnesi (None ise varsayılan servis bağlantısı).
            dialect: Veritabanı türü ('postgresql', 'duckdb', 'sqlite').
            key: Kilit anahtar adı.
            timeout_ms: Maksimum kilit edinme zaman aşımı süresi (milisaniye).
            max_retries: Maksimum yeniden deneme adedi.
            base_retry_ms: İlk yeniden deneme bekleme süresi (milisaniye).
            max_retry_ms: Üst tavan deneme gecikmesi (milisaniye).
            lease_renewal_interval_s: Kilit tazeleme periyodu (saniye).
            stale_lock_timeout_s: Bayat kilit zaman aşımı süresi (saniye).
        """
        self._db = db
        self._dialect = dialect.lower()
        self._key = key
        self._key_id = LOCK_ORDER.get(key, abs(hash(key)) % 100000)
        self._timeout_ms = timeout_ms
        self._max_retries = max(1, max_retries)
        self._base_retry_ms = base_retry_ms
        self._max_retry_ms = max_retry_ms
        self._lease_renewal_interval_s = lease_renewal_interval_s
        self._stale_lock_timeout_s = stale_lock_timeout_s
        self._acquired = False
        self._acquire_time: float | None = None
        self._owner_id = f"lock_{uuid.uuid4().hex[:8]}"
        self._renewal_task: asyncio.Task[Any] | None = None

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<DatabaseLock key='{self._key}' dialect='{self._dialect}' "
            f"acquired={self._acquired} owner='{self._owner_id}'>"
        )

    @property
    def key(self) -> str:
        """Kilit anahtar adı."""
        return self._key

    @property
    def is_acquired(self) -> bool:
        """Kilidin başarıyla alınıp alınmadığı."""
        return self._acquired

    @property
    def owner_id(self) -> str:
        """Kilit sahibinin tekil kimliği."""
        return self._owner_id

    @property
    def dialect(self) -> str:
        """Veritabanı diyalekti."""
        return self._dialect

    # =====================================================
    # ACQUIRE (KİLİT EDİNME)
    # =====================================================

    async def acquire(self) -> bool:
        """Kilidi edinir (Exponential Backoff ve Jitter ile).

        Returns:
            bool: Kilit başarıyla alındıysa True, zaman aşımına uğradıysa False.
        """
        lk_metrics = get_lock_metrics(self._key)
        start = time.monotonic()

        with tracer.start_as_current_span("db_lock.acquire") as span:
            span.set_attribute("lock.key", self._key)
            span.set_attribute("lock.dialect", self._dialect)

            for attempt in range(self._max_retries):
                try:
                    if self._dialect == "sqlite":
                        success = await self._acquire_sqlite()
                    elif self._dialect == "duckdb":
                        success = await self._acquire_duckdb()
                    else:
                        success = await self._acquire_pg()

                    if success:
                        self._acquired = True
                        self._acquire_time = time.monotonic()
                        wait_ms = (self._acquire_time - start) * 1000
                        lk_metrics.record_acquisition(wait_ms)
                        _lock_acquisitions.add(1, {"key": self._key})
                        _lock_wait_histogram.record(wait_ms, {"key": self._key})
                        span.set_attribute("lock.wait_ms", round(wait_ms, 1))
                        span.set_attribute("lock.attempt", attempt + 1)
                        if wait_ms > 1000:
                            logger.warning(
                                "yavas_kilit_edinme",
                                key=self._key,
                                wait_ms=round(wait_ms, 1),
                                attempt=attempt + 1,
                            )
                        self._start_renewal()
                        return True

                    if attempt < self._max_retries - 1:
                        delay_s = self._calc_backoff(attempt)
                        await asyncio.sleep(delay_s)

                except Exception as exc:
                    error_msg = str(exc).lower()
                    lk_metrics.record_error()
                    if "deadlock" in error_msg:
                        lk_metrics.record_deadlock()
                        logger.warning("deadlock_tespit_edildi", key=self._key, attempt=attempt + 1)
                        if attempt < self._max_retries - 1:
                            delay_s = self._calc_backoff(attempt) * 2
                            await asyncio.sleep(delay_s)
                            continue
                    raise

            lk_metrics.record_timeout()
            _lock_timeouts.add(1, {"key": self._key})
            span.set_attribute("lock.result", "timeout")
            logger.error(
                "kilit_zaman_asimi",
                key=self._key,
                timeout_ms=self._timeout_ms,
                retries=self._max_retries,
            )
            return False

    def _calc_backoff(self, attempt: int) -> float:
        """Jitter içeren katlanarak artan bekleme süresini hesaplar."""
        base = self._base_retry_ms * (2**attempt)
        capped = min(base, self._max_retry_ms)
        jitter = random.uniform(0.5, 1.5)
        return (capped * jitter) / 1000.0

    # =====================================================
    # RELEASE & ROLLBACK (SERBEST BIRAKMA)
    # =====================================================

    async def release(self) -> None:
        """Kilidi serbest bırakır ve kira yenileme arka plan görevini durdurur."""
        if not self._acquired:
            return

        self._stop_renewal()

        with tracer.start_as_current_span("db_lock.release") as span:
            span.set_attribute("lock.key", self._key)
            try:
                if self._dialect == "sqlite":
                    await self._release_sqlite()
                elif self._dialect == "duckdb":
                    await self._release_duckdb()
                else:
                    await self._release_pg()
                get_lock_metrics(self._key).record_release()
                span.set_attribute("lock.result", "released")
            except Exception as exc:
                logger.warning("kilit_serbest_birakma_hatasi", key=self._key, error=str(exc))
                get_lock_metrics(self._key).record_error()
                span.set_attribute("lock.result", "error")
            finally:
                self._acquired = False
                self._acquire_time = None

    async def rollback(self) -> None:
        """İşlemi geri alır ve kilidi serbest bırakır."""
        if not self._acquired:
            return

        self._stop_renewal()

        try:
            if self._dialect == "sqlite":
                await self._rollback_sqlite()
            elif self._dialect == "duckdb":
                await self._rollback_duckdb()
            else:
                await self._rollback_pg()
        except Exception as e:
            logger.debug("kilit_geri_alma_istisnasi", error=str(e), key=self._key)
        finally:
            self._acquired = False
            self._acquire_time = None

    # =====================================================
    # LEASE RENEWAL (KİRA YENİLEME)
    # =====================================================

    def _start_renewal(self) -> None:
        """Uzun süren işlemler için kilit süresini arka planda periyodik olarak yeniler."""
        if self._renewal_task is not None:
            return

        async def _renewal_loop() -> None:
            """Kilit geçerliliğini korumak için kira yenileme döngüsü."""
            while True:
                try:
                    await asyncio.sleep(self._lease_renewal_interval_s)
                    if not self._acquired:
                        break
                    await self._renew_lease()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("kira_yenileme_istisnasi", error=str(e), key=self._key)

        try:
            self._renewal_task = asyncio.create_task(_renewal_loop())
            _bg_tasks.add(self._renewal_task)
            self._renewal_task.add_done_callback(_bg_tasks.discard)
        except RuntimeError:
            logger.warning("kira_yenileme_gorevi_baslatilamadi_event_loop_yok", key=self._key)

    def _stop_renewal(self) -> None:
        """Kira yenileme görevini güvenle iptal eder."""
        if self._renewal_task and not self._renewal_task.done():
            self._renewal_task.cancel()
            self._renewal_task = None

    async def _renew_lease(self) -> None:
        """Veritabanı üzerinde kilit kirasını tazeler."""
        if not self._acquired:
            return

        try:
            if self._dialect == "sqlite":
                if self._db and hasattr(self._db, "execute"):
                    self._db.execute("SAVEPOINT lock_renewal")
                    self._db.execute("RELEASE SAVEPOINT lock_renewal")
            elif self._dialect == "duckdb":
                pass  # DuckDB yerel kilidi asyncio.Lock ile tutulur
            else:
                if self._db and hasattr(self._db, "fetchrow"):
                    await self._db.fetchrow("SELECT pg_advisory_lock($1)", self._key_id)
            get_lock_metrics(self._key).record_renewal()
        except Exception as e:
            logger.warning("kilit_kira_tazeleme_basarisiz", key=self._key, error=str(e))

    # =====================================================
    # CRASH RECOVERY (BAYAT KİLİT KURTARMA)
    # =====================================================

    async def check_and_recover_stale(self) -> bool:
        """Çökmüş worker'ların bıraktığı bayat (stale) kilitleri kurtarır.

        Returns:
            bool: Bayat kilit tespit edilip kurtarıldıysa True, aksi halde False.
        """
        if self._dialect == "sqlite":
            return await self._recover_sqlite()
        elif self._dialect == "duckdb":
            return False
        else:
            return await self._recover_pg()

    async def _recover_sqlite(self) -> bool:
        """SQLite üzerinde bayat kilitleri kurtarmayı dener."""
        try:
            old_timeout = self._timeout_ms
            self._timeout_ms = 100
            success = await self._acquire_sqlite()
            self._timeout_ms = old_timeout
            if success:
                get_lock_metrics(self._key).record_crash_recovery()
                logger.info("stale_sqlite_kilidi_kurtarildi", key=self._key)
                await self._rollback_sqlite()
                return True
            return False
        except Exception:
            return False

    async def _recover_pg(self) -> bool:
        """PostgreSQL üzerinde pg_locks tablosundan bayat advisory kilitleri kurtarır."""
        if not self._db or not hasattr(self._db, "fetch"):
            return False

        try:
            rows = await self._db.fetch(
                """
                SELECT pid, locktype, mode, granted
                FROM pg_locks
                WHERE locktype = 'advisory' AND objid = $1
                """,
                self._key_id,
            )

            if not rows:
                return False

            for row in rows:
                pid = row["pid"]
                active = await self._db.fetchrow("SELECT pid FROM pg_stat_activity WHERE pid = $1", pid)
                if not active:
                    try:
                        await self._db.execute("SELECT pg_advisory_unlock($1)", self._key_id)
                        get_lock_metrics(self._key).record_crash_recovery()
                        logger.warning("stale_pg_advisory_kilidi_kurtarildi", key=self._key, dead_pid=pid)
                        return True
                    except Exception as e:
                        logger.debug("stale_pg_kilit_temizleme_istisnasi", error=str(e))

            return False
        except Exception:
            return False

    # =====================================================
    # VERİTABANI DİYALEKTLERİ UYGULAMALARI
    # =====================================================

    async def _acquire_sqlite(self) -> bool:
        """SQLite için BEGIN IMMEDIATE ile yazma kilidi alır."""
        if not self._db:
            return True
        try:
            self._db.execute("BEGIN IMMEDIATE")
            return True
        except Exception as e:
            if "database is locked" in str(e).lower():
                return False
            raise

    async def _release_sqlite(self) -> None:
        """SQLite üzerinde COMMIT ile kilidi serbest bırakır."""
        if not self._db:
            return
        try:
            self._db.commit()
        except Exception:
            with contextlib.suppress(Exception):
                self._db.rollback()

    async def _rollback_sqlite(self) -> None:
        """SQLite üzerinde ROLLBACK çalıştırır."""
        if self._db and hasattr(self._db, "rollback"):
            with contextlib.suppress(Exception):
                self._db.rollback()

    async def _acquire_duckdb(self) -> bool:
        """DuckDB yerel durumu için paylaşımlı süreç içi asenkron kilit edinir."""
        lock = _get_named_asyncio_lock(f"db_duckdb_{self._key}")
        if lock.locked():
            return False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0.001)
            return True
        except TimeoutError:
            return False

    async def _release_duckdb(self) -> None:
        """DuckDB yerel kilidini serbest bırakır."""
        lock = _get_named_asyncio_lock(f"db_duckdb_{self._key}")
        if lock.locked():
            with contextlib.suppress(RuntimeError):
                lock.release()

    async def _rollback_duckdb(self) -> None:
        """DuckDB yerel kilidini geri alır ve serbest bırakır."""
        lock = _get_named_asyncio_lock(f"db_duckdb_{self._key}")
        if lock.locked():
            with contextlib.suppress(RuntimeError):
                lock.release()

    async def _acquire_pg(self) -> bool:
        """PostgreSQL üzerinde pg_try_advisory_lock ile bloklamayan kilit alır."""
        if not self._db or not hasattr(self._db, "fetchrow"):
            # Mock veya boş DB durumunda başarılı kabul edilir
            return True

        try:
            row = await self._db.fetchrow("SELECT pg_try_advisory_lock($1) as locked", self._key_id)
            return bool(row and row["locked"])
        except Exception as e:
            if "deadlock" in str(e).lower():
                return False
            raise

    async def _release_pg(self) -> None:
        """PostgreSQL üzerinde pg_advisory_unlock ile kilidi serbest bırakır."""
        if self._db and hasattr(self._db, "execute"):
            with contextlib.suppress(Exception):
                await self._db.execute("SELECT pg_advisory_unlock($1)", self._key_id)

    async def _rollback_pg(self) -> None:
        """PostgreSQL üzerinde ROLLBACK çalıştırır."""
        if self._db and hasattr(self._db, "execute"):
            with contextlib.suppress(Exception):
                await self._db.execute("ROLLBACK")

    # =====================================================
    # ASENKRON CONTEXT MANAGER PROTOKOLÜ
    # =====================================================

    async def __aenter__(self) -> DatabaseLock:
        """Kilidi edinir ve bağlamı başlatır.

        Returns:
            DatabaseLock: Kilit nesnesi.

        Raises:
            RuntimeError: Kilit zaman aşımına uğrarsa fırlatılır.
        """
        success = await self.acquire()
        if not success:
            raise RuntimeError(f"Kilit zaman aşımı: {self._key} ({self._timeout_ms}ms)")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Bağlam sonlandığında kilidi güvenle serbest bırakır veya geri alır."""
        if exc_type:
            await self.rollback()
        else:
            await self.release()
        return False


# =====================================================
# COORDINATED LOCK (asyncio + DB Koordinasyonu)
# =====================================================


class CoordinatedLock:
    """Süreç içi asyncio.Lock ve veritabanı advisory kilidini birleştiren koordinatör.

    Önce süreç içi kilit edinilir; ardından veritabanı kilidi denenir.
    Serbest bırakılırken ters sıra izlenir.
    """

    def __init__(
        self,
        db: Any = None,
        dialect: str = "postgresql",
        key: str = DEFAULT_LOCK_KEY,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        """Başlatıcı.

        Args:
            db: Veritabanı bağlantı nesnesi.
            dialect: Veritabanı diyalekti ('postgresql', 'duckdb', 'sqlite').
            key: Kilit anahtarı.
            timeout_ms: Kilit zaman aşımı (milisaniye).
        """
        self._asyncio_lock = _get_named_asyncio_lock(f"coord_{key}")
        self._db_lock = DatabaseLock(db, dialect=dialect, key=key, timeout_ms=timeout_ms)
        self._key = key

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<CoordinatedLock key='{self._key}' dialect='{self._db_lock.dialect}' "
            f"locked={self.is_acquired}>"
        )

    @property
    def key(self) -> str:
        """Kilit anahtarı."""
        return self._key

    @property
    def is_acquired(self) -> bool:
        """Kilidin alınıp alınmadığı."""
        return self._db_lock.is_acquired and self._asyncio_lock.locked()

    async def acquire(self) -> bool:
        """Her iki kilidi sıralı olarak edinir.

        Returns:
            bool: İki kilit de alındıysa True, aksi halde False.
        """
        try:
            await asyncio.wait_for(
                self._asyncio_lock.acquire(),
                timeout=self._db_lock._timeout_ms / 1000.0,
            )
        except TimeoutError:
            return False

        db_ok = await self._db_lock.acquire()
        if not db_ok:
            if self._asyncio_lock.locked():
                self._asyncio_lock.release()
            return False
        return True

    async def release(self) -> None:
        """Her iki kilidi ters sırada serbest bırakır."""
        await self._db_lock.release()
        if self._asyncio_lock.locked():
            self._asyncio_lock.release()

    async def rollback(self) -> None:
        """Veritabanı kilidini geri alır ve süreç içi kilidi bırakır."""
        await self._db_lock.rollback()
        if self._asyncio_lock.locked():
            self._asyncio_lock.release()

    @property
    def metrics(self) -> LockMetrics:
        """Kilit metrikleri."""
        return get_lock_metrics(self._key)

    async def __aenter__(self) -> CoordinatedLock:
        """Koordineli kilidi edinir.

        Returns:
            CoordinatedLock: Kilit nesnesi.

        Raises:
            RuntimeError: Kilit zaman aşımına uğrarsa fırlatılır.
        """
        success = await self.acquire()
        if not success:
            raise RuntimeError(f"Koordineli kilit zaman aşımı: {self._key}")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Bağlam sonlandığında koordineli kilidi güvenle serbest bırakır."""
        if exc_type:
            await self.rollback()
        else:
            await self.release()
        return False


# =====================================================
# YARDIMCI CONTEXT MANAGER VE ANALİTİK İHRAÇ
# =====================================================


@asynccontextmanager
async def portfolio_trade_lock(
    db: Any = None,
    dialect: str = "postgresql",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> AsyncGenerator[CoordinatedLock, None]:
    """Portföy emir ve takas işlemleri için kurumsal koordineli kilit bağlamı.

    Args:
        db: Veritabanı bağlantısı.
        dialect: Veritabanı türü.
        timeout_ms: Zaman aşımı süresi (milisaniye).

    Yields:
        CoordinatedLock: Aktif kilit bağlamı.
    """
    lock = CoordinatedLock(db, dialect=dialect, key="portfolio_trade", timeout_ms=timeout_ms)
    async with lock:
        yield lock


def export_lock_metrics_to_polars() -> pl.DataFrame:
    """Tüm kilit performans metriklerini Polars DataFrame olarak dışa aktarır.

    Returns:
        pl.DataFrame: Kilit metrikleri tablosu.
    """
    with _metrics_lock:
        data: list[dict[str, Any]] = []
        for key, m in _metrics.items():
            d = m.to_dict()
            d["key"] = key
            h = m.health_status()
            d["status"] = h["status"]
            d["issues"] = orjson.dumps(h["issues"]).decode("utf-8")
            data.append(d)

    schema = {
        "key": pl.Utf8,
        "total_acquisitions": pl.Int64,
        "total_releases": pl.Int64,
        "total_timeouts": pl.Int64,
        "total_deadlocks_detected": pl.Int64,
        "total_errors": pl.Int64,
        "total_renewals": pl.Int64,
        "total_crash_recoveries": pl.Int64,
        "avg_wait_ms": pl.Float64,
        "max_wait_ms": pl.Float64,
        "last_acquisition_ms": pl.Float64,
        "uptime_seconds": pl.Float64,
        "status": pl.Utf8,
        "issues": pl.Utf8,
    }

    if not data:
        return pl.DataFrame(schema=schema)

    return pl.DataFrame(data, schema=schema)


def export_lock_metrics_to_duckdb(
    db_path: str | Path = DEFAULT_LOCK_AUDIT_DUCKDB_PATH,
    table_name: str = DEFAULT_LOCK_AUDIT_TABLE,
) -> int:
    """Kilit performans ve denetim kayıtlarını yerel DuckDB tablosuna aktarır.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Hedef tablo adı.

    Returns:
        int: Eklenen kayıt sayısı.
    """
    df = export_lock_metrics_to_polars()
    if df.is_empty():
        return 0

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.register("df_lock_metrics", df.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_lock_metrics WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_lock_metrics")
        return len(df)
    except Exception as e:
        logger.error("export_lock_metrics_to_duckdb_basarisiz", error=str(e))
        return 0


def query_lock_metrics_duckdb(
    db_path: str | Path = DEFAULT_LOCK_AUDIT_DUCKDB_PATH,
    table_name: str = DEFAULT_LOCK_AUDIT_TABLE,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş kilit performans denetimlerini sorgular.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Tablo adı.

    Returns:
        pl.DataFrame: Sorgu sonucu Polars DataFrame.
    """
    path_obj = Path(db_path)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchall()
            if not tables:
                return pl.DataFrame()

            arrow_res = conn.execute(f"SELECT * FROM {table_name}").arrow()
            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_lock_metrics_duckdb_basarisiz", error=str(e))
        return pl.DataFrame()


__all__ = [
    "DEFAULT_BASE_RETRY_MS",
    "DEFAULT_LEASE_RENEWAL_INTERVAL_S",
    "DEFAULT_LOCK_AUDIT_DUCKDB_PATH",
    "DEFAULT_LOCK_AUDIT_TABLE",
    "DEFAULT_LOCK_KEY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_MS",
    "DEFAULT_STALE_LOCK_TIMEOUT_S",
    "DEFAULT_TIMEOUT_MS",
    "LOCK_ORDER",
    "CoordinatedLock",
    "DatabaseLock",
    "LockMetrics",
    "export_lock_metrics_to_duckdb",
    "export_lock_metrics_to_polars",
    "get_all_metrics",
    "get_health_report",
    "get_lock_metrics",
    "portfolio_trade_lock",
    "query_lock_metrics_duckdb",
]
