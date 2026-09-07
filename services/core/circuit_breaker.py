"""ALPHA BIST — Kurumsal Circuit Breaker, Rate Limiter ve Sağlayıcı Güvenilirlik Çerçevesi.

Bu modül, dış veri sağlayıcıları ve kritik mikroservis çağrıları için dayanıklılık (resilience)
ve hata toleransı mimarisini yürütür:
1. Circuit Breaker (Durum Makinesi: CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
2. Rate Limiter (Token Bucket algoritması ile milisaniye hassasiyetinde hız limitleme)
3. Retry Policy (Exponential Backoff + Jitter ile yeniden deneme)
4. Provider Reliability (Başarı oranı, gecikme ve tazelik metrikleriyle dinamik güvenilirlik skoru)
5. ProtectedProvider Wrapper (Tüm koruma katmanlarını ve zaman aşımı guard'ını birleştiren sarmalayıcı)
6. Polars & DuckDB Metrik Entegrasyonu (Sağlayıcı güvenilirlik ve durumlarının analitiği)
7. DuckDB StateStore entegrasyonu (Yeniden başlatmalarda durum kurtarma)
"""

from __future__ import annotations

import asyncio
import inspect
import math
import random
import threading
import time
from collections import deque
from contextlib import nullcontext, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# OpenTelemetry Güvenli Başlatma
try:
    from opentelemetry import metrics, trace

    tracer = trace.get_tracer("alpha-bist.circuit-breaker")
    meter = metrics.get_meter("alpha.circuit_breaker")
    CB_STATE_GAUGE = meter.create_gauge(
        "alpha.circuit_breaker.state",
        description="Circuit Breaker durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    )
    CB_FAILURES_COUNTER = meter.create_counter(
        "alpha.circuit_breaker.failures.total",
        description="Circuit Breaker tarafından kaydedilen toplam hata sayısı",
    )
except Exception:
    class _NoOpSpan:
        def set_attribute(self, *args: Any, **kwargs: Any) -> None:
            pass

        def record_exception(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _NoOpTracer:
        def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> Any:
            return nullcontext(_NoOpSpan())

    class _NoOpMetric:
        def set(self, val: Any, *args: Any, **kwargs: Any) -> None:
            pass

        def add(self, val: Any, *args: Any, **kwargs: Any) -> None:
            pass

    tracer = _NoOpTracer()  # type: ignore[assignment]
    CB_STATE_GAUGE = _NoOpMetric()  # type: ignore[assignment]
    CB_FAILURES_COUNTER = _NoOpMetric()  # type: ignore[assignment]

# Varsayılan Yapılandırma Sabitleri
DEFAULT_FAILURE_THRESHOLD: Final[int] = 5
DEFAULT_RECOVERY_TIMEOUT_SECONDS: Final[int] = 60
DEFAULT_RATE_LIMIT_TOKENS: Final[float] = 10.0
DEFAULT_REFILL_RATE: Final[float] = 1.0
DEFAULT_MAX_RETRIES: Final[int] = 5
DEFAULT_BASE_DELAY: Final[float] = 1.0
DEFAULT_MAX_DELAY: Final[float] = 32.0
DEFAULT_WINDOW_SIZE: Final[int] = 100
DEFAULT_RELIABILITY_DB_PATH: Final[str] = "data/provider_reliability.duckdb"
DEFAULT_CB_DB_PATH: Final[str] = "data/circuit_breakers.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri.

    Returns:
        bytes: orjson ile kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


class CircuitState(StrEnum):
    """Circuit Breaker durum makinesi durumları."""

    CLOSED = "CLOSED"  # Normal çalışma (isteklere izin verilir)
    OPEN = "OPEN"  # Devre açık (hata eşiği aşıldı, istekler doğrudan reddedilir)
    HALF_OPEN = "HALF_OPEN"  # Yarı açık (deneme çağrısı yapılıyor)


@dataclass
class CircuitBreaker:
    """Sürekli hata veren dış servis ve sağlayıcıları geçici olarak devre dışı bırakan koruma mekanizması.

    Durum Makinesi:
    - CLOSED -> N adet hata -> OPEN (istekler engellenir)
    - OPEN -> recovery_timeout_seconds süresi dolunca -> HALF_OPEN (deneme çağrılarına izin verilir)
    - HALF_OPEN -> Başarılı çağrı -> CLOSED (sıfırlanır)
    - HALF_OPEN -> Başarısız çağrı -> OPEN (yeniden kilitlenir)
    """

    name: str
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_timeout_seconds: int = DEFAULT_RECOVERY_TIMEOUT_SECONDS
    half_open_max_calls: int = 1
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    half_open_calls: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        """Kalıcı durumu yükler ve merkezi metrik toplayıcıya otomatik kaydeder."""
        self.restore_state()
        try:
            from services.core.circuit_breaker_metrics import circuit_breaker_metrics

            circuit_breaker_metrics.track(self)
        except Exception as exc:
            logger.debug("circuit_breaker_metrics_track_atlandi", name=self.name, error=str(exc))

    def _notify_state_change(self, old_state: str, new_state: str) -> None:
        """Metrik toplayıcıya durum değişikliğini bildirir."""
        try:
            from services.core.circuit_breaker_metrics import circuit_breaker_metrics

            circuit_breaker_metrics.record_state_change(self.name, old_state, new_state)
        except Exception as exc:
            logger.debug("circuit_breaker_state_change_bildirilemedi", name=self.name, error=str(exc))

    def _update_telemetry(self) -> None:
        """OpenTelemetry ölçüm göstergelerini günceller."""
        try:
            state_val = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}.get(self.state, 0)
            CB_STATE_GAUGE.set(state_val, {"provider": self.name})
        except Exception as exc:
            logger.debug("telemetry_update_hatasi", name=self.name, error=str(exc))

    def _persist_to_store(self) -> None:
        """Durumu DuckDB state_store bileşenine kaydeder."""
        try:
            from .state_store import state_store

            state_store.save_circuit_state(
                self.name,
                self.state.value,
                self.failure_count,
                self.last_failure_time.isoformat() if self.last_failure_time else None,
                self.last_success_time.isoformat() if self.last_success_time else None,
            )
        except Exception as exc:
            logger.debug("circuit_breaker_state_persist_edilemedi", name=self.name, error=str(exc))

    def record_success(self) -> None:
        """Başarılı çağrıyı kaydeder ve durum makinesini günceller."""
        state_changed = False
        old_state_str = ""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                old_state_str = self.state.value
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.half_open_calls = 0
                state_changed = True
                logger.info("circuit_breaker_kapandi", name=self.name, durum="CLOSED")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

            self.last_success_time = datetime.now(UTC)
            self._update_telemetry()
            self._persist_to_store()

        if state_changed:
            self._notify_state_change(old_state_str, CircuitState.CLOSED.value)

    def record_failure(self) -> None:
        """Başarısız çağrıyı kaydeder ve gerekirse devreyi OPEN durumuna geçirir."""
        state_changed = False
        old_state_str = ""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now(UTC)
            with suppress(Exception):
                CB_FAILURES_COUNTER.add(1, {"provider": self.name})

            if self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                old_state_str = self.state.value
                self.state = CircuitState.OPEN
                state_changed = True
                logger.warning(
                    "circuit_breaker_acildi",
                    name=self.name,
                    durum="OPEN",
                    hata_sayisi=self.failure_count,
                    esik=self.failure_threshold,
                )
            elif self.state == CircuitState.HALF_OPEN:
                old_state_str = self.state.value
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                state_changed = True
                logger.warning(
                    "circuit_breaker_yeniden_acildi",
                    name=self.name,
                    durum="OPEN",
                    neden="half_open_hatasi",
                )

            self._update_telemetry()
            self._persist_to_store()

        if state_changed:
            self._notify_state_change(old_state_str, CircuitState.OPEN.value)

    def can_execute(self) -> bool:
        """Yeni bir çağrı yapılmasına izin verilip verilmeyeceğini denetler.

        Returns:
            bool: İstek çalıştırılabilir ise True, engellendiyse False.
        """
        state_changed = False
        old_state_val = ""
        new_state_val = ""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                if self.last_failure_time:
                    elapsed = (datetime.now(UTC) - self.last_failure_time).total_seconds()
                    if elapsed >= self.recovery_timeout_seconds:
                        old_state_val = self.state.value
                        self.state = CircuitState.HALF_OPEN
                        new_state_val = self.state.value
                        self.half_open_calls = 1
                        state_changed = True
                        logger.info("circuit_breaker_yari_acik_modda", name=self.name, durum="HALF_OPEN")
                        self._update_telemetry()
                        self._persist_to_store()
                        result = True
                    else:
                        result = False
                else:
                    result = False

            elif self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.half_open_max_calls:
                    self.half_open_calls += 1
                    result = True
                else:
                    result = False
            else:
                result = False

        if state_changed:
            self._notify_state_change(old_state_val, new_state_val)

        return result

    def reset(self) -> None:
        """Devre kesiciyi sıfırlayarak kapalı (CLOSED) duruma döndürür."""
        old_state_str = ""
        state_changed = False
        with self._lock:
            if self.state != CircuitState.CLOSED:
                old_state_str = self.state.value
                self.state = CircuitState.CLOSED
                state_changed = True
            self.failure_count = 0
            self.half_open_calls = 0
            self._update_telemetry()
            self._persist_to_store()

        if state_changed:
            self._notify_state_change(old_state_str, CircuitState.CLOSED.value)
        logger.info("circuit_breaker_sifirlandi", name=self.name)

    def get_state(self) -> dict[str, Any]:
        """Devre kesicinin anlık durum ve sayaç bilgilerini döner.

        Returns:
            dict[str, Any]: Durum sözlüğü.
        """
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout_seconds,
                "half_open_max_calls": self.half_open_max_calls,
                "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
                "last_success": self.last_success_time.isoformat() if self.last_success_time else None,
            }

    def restore_state(self) -> None:
        """Kalıcı depodan (DuckDB) son durumu geri yükler (restart recovery)."""
        try:
            from .state_store import state_store

            saved = state_store.load_circuit_state(self.name)
            if saved:
                with self._lock:
                    self.state = CircuitState(saved["state"])
                    self.failure_count = saved.get("failure_count", 0)
                    if saved.get("last_failure_at"):
                        self.last_failure_time = datetime.fromisoformat(saved["last_failure_at"])
                    if saved.get("last_success_at"):
                        self.last_success_time = datetime.fromisoformat(saved["last_success_at"])
                logger.info("circuit_breaker_durumu_yuklendi", name=self.name, durum=self.state.value)
        except Exception as exc:
            logger.debug("circuit_breaker_restore_atlandi", name=self.name, error=str(exc))

    def to_dict(self) -> dict[str, Any]:
        """Devre kesicinin anlık durum ve sayaç bilgilerini sözlük olarak döner."""
        return self.get_state()

    def to_orjson_bytes(self) -> bytes:
        """Devre kesici durumunu orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Devre kesicinin okunabilir dize temsilini döner."""
        with self._lock:
            return (
                f"CircuitBreaker(name='{self.name}', state='{self.state.value}', "
                f"failures={self.failure_count}/{self.failure_threshold})"
            )


@dataclass
class RateLimiter:
    """Token Bucket algoritması ile istek sıklığını kontrol eden hız limitleyici.

    Limit dolduğunda hata fırlatmak yerine gereken bekleme süresini hesaplar.
    """

    name: str
    max_tokens: float = DEFAULT_RATE_LIMIT_TOKENS
    refill_rate: float = DEFAULT_REFILL_RATE  # Saniyede yenilenen token miktarı
    tokens: float = DEFAULT_RATE_LIMIT_TOKENS
    last_refill: float = field(default_factory=time.monotonic)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def acquire(self, cost: float = 1.0) -> float:
        """Token alır veya bekleme süresi döner.

        Args:
            cost: Talep edilen token miktarı (Varsayılan: 1.0).

        Returns:
            float: Hemen yapılabilirse 0.0, aksi halde beklenmesi gereken saniye.
        """
        cost = max(0.001, cost)
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.last_refill)
            safe_rate = max(1e-6, self.refill_rate)

            self.tokens = min(self.max_tokens, self.tokens + (elapsed * safe_rate))
            self.last_refill = now

            if self.tokens >= cost:
                self.tokens -= cost
                return 0.0
            else:
                deficit = cost - self.tokens
                wait_time = deficit / safe_rate
                return max(0.0, wait_time)

    async def acquire_async(self, cost: float = 1.0) -> None:
        """Asenkron token alır, gerekirse hesaplanan süre kadar bekler."""
        cost = max(0.001, cost)
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self.last_refill)
                safe_rate = max(1e-6, self.refill_rate)
                self.tokens = min(self.max_tokens, self.tokens + (elapsed * safe_rate))
                self.last_refill = now
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
                wait = (cost - self.tokens) / safe_rate

            logger.debug("rate_limiter_bekliyor", name=self.name, saniye=round(wait, 3))
            await asyncio.sleep(wait)

    def reset(self) -> None:
        """Token havuzunu tam kapasiteye sıfırlar."""
        with self._lock:
            self.tokens = self.max_tokens
            self.last_refill = time.monotonic()

    def get_state(self) -> dict[str, Any]:
        """Hız limitleyicinin anlık token ve kapasite durumunu döner."""
        with self._lock:
            return {
                "name": self.name,
                "tokens": round(self.tokens, 2),
                "max_tokens": self.max_tokens,
                "refill_rate": self.refill_rate,
            }

    def to_dict(self) -> dict[str, Any]:
        """Hız limitleyicinin anlık token ve kapasite durumunu döner."""
        return self.get_state()

    def to_orjson_bytes(self) -> bytes:
        """Hız limitleyici durumunu orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Hız limitleyicinin okunabilir dize temsilini döner."""
        with self._lock:
            return (
                f"RateLimiter(name='{self.name}', tokens={round(self.tokens, 2)}/{self.max_tokens}, "
                f"refill_rate={self.refill_rate}/s)"
            )


class RetryPolicy:
    """Üstel geri çekilme ve rastgele sapmalı (Exponential Backoff + Jitter) yeniden deneme politikası."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ) -> None:
        """Yeniden deneme politikasını başlatır.

        Args:
            max_retries: Maksimum yeniden deneme adedi.
            base_delay: İlk bekleme süresi (saniye).
            max_delay: Tavan bekleme süresi (saniye).
        """
        self.max_retries: int = max(0, max_retries)
        self.base_delay: float = max(0.001, base_delay)
        self.max_delay: float = max(self.base_delay, max_delay)

    def get_delay(self, attempt: int) -> float:
        """Yeniden deneme bekleme süresini hesaplar (exponential backoff + jitter).

        Args:
            attempt: Deneme sırası (0 tabanlı).

        Returns:
            float: Beklenecek süre (saniye).
        """
        safe_attempt = min(attempt, 20)
        delay = min(self.base_delay * (2**safe_attempt), self.max_delay)
        jitter = delay * 0.1 * (2 * random.random() - 1)  # ±%10 jitter
        return max(0.0, delay + jitter)

    async def execute_with_retry(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Fonksiyonu yeniden deneme korumasıyla çalıştırır (sync, async, lambda, partial callable destekler).

        Args:
            func: Yürütülecek fonksiyon veya coroutine.
            *args: Pozisyonel argümanlar.
            **kwargs: Anahtar kelime argümanları.

        Returns:
            Any: Fonksiyonun başarılı dönüş değeri.

        Raises:
            asyncio.CancelledError: Görev iptal edilirse doğrudan yukarı fırlatılır.
            Exception: Tüm denemeler tükendiğinde fırlatılan son hata.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                res = func(*args, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except asyncio.CancelledError:
                logger.warning("retry_islemi_iptal_edildi")
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    logger.warning(
                        "yeniden_deneme_yapiliyor",
                        deneme=attempt + 1,
                        maksimum_deneme=self.max_retries,
                        bekleme_suresi=round(delay, 2),
                        hata=str(exc),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "maksimum_yeniden_deneme_asildi",
                        toplam_deneme=self.max_retries + 1,
                        hata=str(exc),
                    )

        if last_error is not None:
            raise last_error
        raise RuntimeError("Yeniden deneme döngüsü sonuç üretemedi.")

    def __repr__(self) -> str:
        """Politikanın okunabilir dize temsilini döner."""
        return (
            f"RetryPolicy(max_retries={self.max_retries}, base_delay={self.base_delay}s, "
            f"max_delay={self.max_delay}s)"
        )


class ProviderReliability:
    """Sağlayıcı güvenilirlik skoru ve çağrı istatistikleri takipçisi.

    Skor Formülü (0.001 - 1.0):
    Skor = (Başarı Oranı × 0.6) + (Gecikme Faktörü × 0.2) + (Tazelik Faktörü × 0.2)
    """

    def __init__(self, name: str, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        """Güvenilirlik takipçisini başlatır.

        Args:
            name: Sağlayıcı adı.
            window_size: Bellekte tutulacak kayan pencere boyutu (O(1) deque maxlen).
        """
        self.name: str = name
        self.window_size: int = max(10, window_size)
        self._results: deque[dict[str, Any]] = deque(maxlen=self.window_size)
        self._total_calls: int = 0
        self._total_failures: int = 0
        self._lock: threading.RLock = threading.RLock()

    def record(self, success: bool, latency_ms: float = 0.0) -> None:
        """Çağrı sonucunu kaydeder.

        Args:
            success: İsteğin başarılı olup olmadığı.
            latency_ms: İstek gecikme süresi (milisaniye).
        """
        with self._lock:
            self._total_calls += 1
            if not success:
                self._total_failures += 1

            self._results.append(
                {
                    "success": success,
                    "latency_ms": max(0.0, latency_ms),
                    "timestamp": datetime.now(UTC),
                }
            )

    def get_score(self) -> float:
        """Sağlayıcının anlık birleşik güvenilirlik skorunu (0.001 - 1.0) hesaplar."""
        with self._lock:
            if not self._results:
                return 1.0

            # 1. Başarı Oranı (Success Rate)
            successes = sum(1 for r in self._results if r["success"])
            success_rate = successes / len(self._results)

            # 2. Gecikme Faktörü (Latency Factor) - Yalnızca başarılı çağrılarda hesaplanır
            latencies = [r["latency_ms"] for r in self._results if r["success"]]
            if latencies and successes > 0:
                avg_latency = sum(latencies) / len(latencies)
                latency_factor = max(0.0, 1.0 - (avg_latency / 5000.0))
            else:
                latency_factor = 0.0

            # 3. Tazelik Faktörü (Freshness Factor)
            last_success: datetime | None = None
            for r in reversed(self._results):
                if r["success"]:
                    last_success = r["timestamp"]
                    break

            if last_success:
                minutes_since = (datetime.now(UTC) - last_success).total_seconds() / 60.0
                freshness_factor = max(0.0, 1.0 - (minutes_since / 60.0))
            else:
                freshness_factor = 0.0

            score = (success_rate * 0.6) + (latency_factor * 0.2) + (freshness_factor * 0.2)
            if math.isnan(score) or math.isinf(score):
                return 0.001
            return round(min(1.0, max(0.001, score)), 3)

    def get_stats(self) -> dict[str, Any]:
        """Detaylı güvenilirlik istatistiklerini döner."""
        with self._lock:
            total = max(1, self._total_calls)
            return {
                "name": self.name,
                "reliability_score": self.get_score(),
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "success_rate": round(1.0 - (self._total_failures / total), 3),
                "window_size": len(self._results),
            }

    def reset(self) -> None:
        """Güvenilirlik geçmişini ve sayaçlarını sıfırlar."""
        with self._lock:
            self._results.clear()
            self._total_calls = 0
            self._total_failures = 0

    def export_to_polars(self) -> pl.DataFrame:
        """Kayıtlı çağrı geçmişini Polars DataFrame olarak döner.

        Returns:
            pl.DataFrame: Çağrı geçmişi tablosu.
        """
        with self._lock:
            records = [
                {
                    "provider": self.name,
                    "success": r["success"],
                    "latency_ms": float(r["latency_ms"]),
                    "timestamp": r["timestamp"].isoformat()
                    if isinstance(r["timestamp"], datetime)
                    else str(r["timestamp"]),
                }
                for r in self._results
            ]
        if not records:
            return pl.DataFrame(
                schema={
                    "provider": pl.Utf8,
                    "success": pl.Boolean,
                    "latency_ms": pl.Float64,
                    "timestamp": pl.Utf8,
                }
            )
        return pl.DataFrame(records)

    def to_dict(self) -> dict[str, Any]:
        """Sağlayıcı güvenilirlik istatistiklerini sözlük olarak döner."""
        return self.get_stats()

    def to_orjson_bytes(self) -> bytes:
        """Güvenilirlik verilerini orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_RELIABILITY_DB_PATH) -> None:
        """Sağlayıcı güvenilirlik DuckDB tablosunu sıfırlar."""
        clear_reliability_logs_duckdb(db_path=db_path)

    def export_to_duckdb(self, db_path: str = DEFAULT_RELIABILITY_DB_PATH) -> int:
        """Çağrı geçmişini DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            int: Kaydedilen satır adedi.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0
        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_reliability_logs (
                    provider VARCHAR,
                    success BOOLEAN,
                    latency_ms DOUBLE,
                    timestamp VARCHAR
                )
                """
            )
            conn.register("tmp_rel_df", df)
            conn.execute("INSERT INTO provider_reliability_logs SELECT * FROM tmp_rel_df")
            return len(df)

    def __repr__(self) -> str:
        """Güvenilirlik takipçisinin okunabilir dize temsilini döner."""
        with self._lock:
            return (
                f"ProviderReliability(name='{self.name}', score={self.get_score()}, "
                f"calls={self._total_calls}, failures={self._total_failures})"
            )


class ProtectedProvider:
    """Circuit Breaker, Rate Limiter, Retry Policy ve Reliability katmanlarıyla tam korumalı sağlayıcı sarmalayıcısı."""

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        circuit_breaker: CircuitBreaker | None = None,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        reliability: ProviderReliability | None = None,
        timeout_seconds: float | None = None,
        raise_on_failure: bool = False,
    ) -> None:
        """Korumalı sağlayıcı örneğini başlatır.

        Args:
            name: Sağlayıcı adı.
            func: Korunacak asıl iş fonksiyonu.
            circuit_breaker: Devre kesici örneği.
            rate_limiter: Hız limitleyici örneği.
            retry_policy: Yeniden deneme politikası.
            reliability: Güvenilirlik takipçisi.
            timeout_seconds: İşlem başına maksimum zaman aşımı süresi (saniye).
            raise_on_failure: Başarısızlıkta istisna fırlatılsın mı yoksa None mı dönülsün.
        """
        self.name: str = name
        self.func: Callable[..., Any] = func
        self.circuit: CircuitBreaker = circuit_breaker or CircuitBreaker(name=name)
        self.rate_limiter: RateLimiter = rate_limiter or RateLimiter(name=name)
        self.retry_policy: RetryPolicy = retry_policy or RetryPolicy()
        self.reliability: ProviderReliability = reliability or ProviderReliability(name=name)
        self.timeout_seconds: float | None = timeout_seconds
        self.raise_on_failure: bool = raise_on_failure

    async def execute(self, *args: Any, **kwargs: Any) -> Any | None:
        """Korumalı yürütme hattını işletir.

        Adımlar:
        1. Circuit Breaker kontrolü (erken engelleme)
        2. Rate Limiter beklemesi (token kontrolü)
        3. Zaman aşımı ve Retry ile yürütme
        4. Başarı / gecikme / telemetri kaydı

        Args:
            *args: Fonksiyon argümanları.
            **kwargs: Anahtar kelime argümanları.

        Returns:
            Any | None: Fonksiyon çıktısı veya engel/hata durumunda None.

        Raises:
            asyncio.CancelledError: İptal durumunda yukarı fırlatılır.
            RuntimeError: Devre kesici açıkken raise_on_failure True ise.
            Exception: raise_on_failure True ise son hata fırlatılır.
        """
        if not self.circuit.can_execute():
            logger.warning("circuit_breaker_acik_cagri_engellendi", provider=self.name)
            if self.raise_on_failure:
                raise RuntimeError(f"[{self.name}] Devre Kesici AÇIK! İstek engellendi.")
            return None

        await self.rate_limiter.acquire_async()

        start_time = time.monotonic()
        with tracer.start_as_current_span("circuit_breaker.execute") as span:
            if hasattr(span, "set_attribute"):
                span.set_attribute("provider.name", self.name)
            try:
                if self.timeout_seconds and self.timeout_seconds > 0:
                    result = await asyncio.wait_for(
                        self.retry_policy.execute_with_retry(self.func, *args, **kwargs),
                        timeout=self.timeout_seconds,
                    )
                else:
                    result = await self.retry_policy.execute_with_retry(self.func, *args, **kwargs)

                latency = (time.monotonic() - start_time) * 1000.0
                self.circuit.record_success()
                self.reliability.record(True, latency)
                if hasattr(span, "set_attribute"):
                    span.set_attribute("result", "success")
                return result

            except asyncio.CancelledError:
                if hasattr(span, "set_attribute"):
                    span.set_attribute("result", "cancelled")
                logger.warning("korumali_cagri_iptal_edildi", provider=self.name)
                raise

            except Exception as exc:
                latency = (time.monotonic() - start_time) * 1000.0
                self.circuit.record_failure()
                self.reliability.record(False, latency)
                if hasattr(span, "set_attribute"):
                    span.set_attribute("result", "failure")
                if hasattr(span, "record_exception"):
                    span.record_exception(exc)
                logger.error("provider_cagrisi_basarisiz", provider=self.name, hata=str(exc))

                if self.raise_on_failure:
                    raise
                return None

    def reset(self) -> None:
        """Devre kesici, hız limitleyici ve güvenilirlik takipçisini sıfırlar."""
        self.circuit.reset()
        self.rate_limiter.reset()
        self.reliability.reset()
        logger.info("korumali_saglayici_sifirlandi", provider=self.name)

    def get_health(self) -> dict[str, Any]:
        """Sağlayıcının sağlık ve performans özetini döner."""
        return {
            "provider": self.name,
            "circuit": self.circuit.get_state(),
            "rate_limiter": self.rate_limiter.get_state(),
            "reliability": self.reliability.get_stats(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Sağlayıcının sağlık ve performans özetini döner."""
        return self.get_health()

    def to_orjson_bytes(self) -> bytes:
        """Sağlayıcı verilerini orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Korumalı sağlayıcının okunabilir dize temsilini döner."""
        return (
            f"ProtectedProvider(name='{self.name}', state='{self.circuit.state.value}', "
            f"reliability={self.reliability.get_score()})"
        )


# =====================================================
# Global Registry (Thread-Safe & RLock)
# =====================================================

_registry_lock: threading.RLock = threading.RLock()
_providers: dict[str, ProtectedProvider] = {}


def register_protected_provider(
    name: str,
    func: Callable[..., Any],
    max_calls_per_second: float = 2.0,
    circuit_failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    timeout_seconds: float | None = None,
    raise_on_failure: bool = False,
) -> ProtectedProvider:
    """Yeni bir korumalı sağlayıcıyı merkezi kayıt defterine ekler.

    Args:
        name: Sağlayıcının tekil adı.
        func: Korunacak fonksiyon.
        max_calls_per_second: Saniyede izin verilen maksimum istek adedi.
        circuit_failure_threshold: Devrenin açılması için gereken ardışık hata sayısı.
        timeout_seconds: İstek başına zaman aşımı süresi.
        raise_on_failure: Hata durumunda istisna fırlatılsın mı.

    Returns:
        ProtectedProvider: Oluşturulan korumalı sağlayıcı nesnesi.
    """
    safe_rate = max(0.1, max_calls_per_second)
    provider = ProtectedProvider(
        name=name,
        func=func,
        circuit_breaker=CircuitBreaker(
            name=name,
            failure_threshold=circuit_failure_threshold,
        ),
        rate_limiter=RateLimiter(
            name=name,
            max_tokens=safe_rate * 2.0,
            refill_rate=safe_rate,
        ),
        retry_policy=RetryPolicy(max_retries=3),
        reliability=ProviderReliability(name=name),
        timeout_seconds=timeout_seconds,
        raise_on_failure=raise_on_failure,
    )
    with _registry_lock:
        _providers[name] = provider

    logger.info("korumali_saglayici_kaydedildi", name=name, rate=safe_rate)
    return provider


def get_provider(name: str) -> ProtectedProvider | None:
    """Merkezi kayıt defterinden belirtilen sağlayıcıyı getirir.

    Args:
        name: Sağlayıcı adı.

    Returns:
        ProtectedProvider | None: Varsa sağlayıcı, yoksa None.
    """
    with _registry_lock:
        return _providers.get(name)


def unregister_protected_provider(name: str) -> bool:
    """Sağlayıcıyı kayıt defterinden siler.

    Args:
        name: Sağlayıcı adı.

    Returns:
        bool: Sağlayıcı bulunup silindiyse True, aksi halde False.
    """
    with _registry_lock:
        return _providers.pop(name, None) is not None


def clear_all_providers() -> int:
    """Kayıt defterindeki tüm sağlayıcıları temizler.

    Returns:
        int: Temizlenen sağlayıcı adedi.
    """
    with _registry_lock:
        cnt = len(_providers)
        _providers.clear()
        return cnt


def get_all_health() -> dict[str, dict[str, Any]]:
    """Tüm kayıtlı sağlayıcıların anlık sağlık durumlarını döner.

    Returns:
        dict[str, dict[str, Any]]: Sağlayıcı sağlık raporları haritası.
    """
    with _registry_lock:
        providers_snapshot = list(_providers.items())
    return {name: p.get_health() for name, p in providers_snapshot}


def export_all_providers_to_polars() -> pl.DataFrame:
    """Kayıtlı tüm sağlayıcıların özet metriklerini Polars DataFrame olarak döner.

    Returns:
        pl.DataFrame: Sağlayıcı durum tablosu.
    """
    with _registry_lock:
        data = []
        for name, p in _providers.items():
            health = p.get_health()
            cb_st = health["circuit"]
            rl_st = health["rate_limiter"]
            rel_st = health["reliability"]
            data.append(
                {
                    "provider": name,
                    "circuit_state": cb_st["state"],
                    "failure_count": cb_st["failure_count"],
                    "tokens": rl_st["tokens"],
                    "reliability_score": rel_st["reliability_score"],
                    "total_calls": rel_st["total_calls"],
                    "total_failures": rel_st["total_failures"],
                    "success_rate": rel_st["success_rate"],
                }
            )

    if not data:
        return pl.DataFrame(
            schema={
                "provider": pl.Utf8,
                "circuit_state": pl.Utf8,
                "failure_count": pl.Int64,
                "tokens": pl.Float64,
                "reliability_score": pl.Float64,
                "total_calls": pl.Int64,
                "total_failures": pl.Int64,
                "success_rate": pl.Float64,
            }
        )
    return pl.DataFrame(data)


def export_all_providers_to_duckdb(db_path: str = DEFAULT_CB_DB_PATH) -> int:
    """Kayıtlı tüm sağlayıcıların durum özetini DuckDB tablosuna kaydeder.

    Args:
        db_path: DuckDB dosya yolu.

    Returns:
        int: Kaydedilen sağlayıcı sayısı.
    """
    df = export_all_providers_to_polars()
    if df.is_empty():
        return 0
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path_obj)) as conn:
        configure_duckdb_wal(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS providers_summary (
                provider VARCHAR PRIMARY KEY,
                circuit_state VARCHAR,
                failure_count BIGINT,
                tokens DOUBLE,
                reliability_score DOUBLE,
                total_calls BIGINT,
                total_failures BIGINT,
                success_rate DOUBLE
            )
            """
        )
        conn.register("tmp_prov_df", df)
        conn.execute("DELETE FROM providers_summary WHERE provider IN (SELECT provider FROM tmp_prov_df)")
        conn.execute("INSERT INTO providers_summary SELECT * FROM tmp_prov_df")
        return len(df)


def read_reliability_logs_from_duckdb(
    db_path: str = DEFAULT_RELIABILITY_DB_PATH,
    provider: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB'de depolanan sağlayıcı güvenilirlik kayıtlarını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        provider: İsteğe bağlı sağlayıcı adı filtresi.
        limit: Dönecek maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan güvenilirlik kayıtları.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame(
            schema={
                "provider": pl.Utf8,
                "success": pl.Boolean,
                "latency_ms": pl.Float64,
                "timestamp": pl.Utf8,
            }
        )

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'provider_reliability_logs'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(
                    schema={
                        "provider": pl.Utf8,
                        "success": pl.Boolean,
                        "latency_ms": pl.Float64,
                        "timestamp": pl.Utf8,
                    }
                )

            query = "SELECT * FROM provider_reliability_logs"
            clauses: list[str] = []
            params: list[Any] = []
            if provider:
                clauses.append("provider = ?")
                params.append(provider)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY timestamp DESC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            arrow_table = conn.execute(query, params).arrow()
            return pl.from_arrow(arrow_table)
    except Exception as exc:
        logger.warning("duckdb_reliability_logs_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(
            schema={
                "provider": pl.Utf8,
                "success": pl.Boolean,
                "latency_ms": pl.Float64,
                "timestamp": pl.Utf8,
            }
        )


def clear_reliability_logs_duckdb(db_path: str = DEFAULT_RELIABILITY_DB_PATH) -> None:
    """DuckDB'de depolanan sağlayıcı güvenilirlik kayıtları tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS provider_reliability_logs;")
    except Exception as exc:
        logger.error("duckdb_reliability_logs_temizleme_hatasi", db_path=db_path, hata=str(exc))


def read_providers_summary_from_duckdb(
    db_path: str = DEFAULT_CB_DB_PATH,
    provider: str | None = None,
) -> pl.DataFrame:
    """DuckDB'de depolanan sağlayıcı özet durumlarını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        provider: İsteğe bağlı sağlayıcı adı filtresi.

    Returns:
        pl.DataFrame: Okunan sağlayıcı özet kayıtları.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame(
            schema={
                "provider": pl.Utf8,
                "circuit_state": pl.Utf8,
                "failure_count": pl.Int64,
                "tokens": pl.Float64,
                "reliability_score": pl.Float64,
                "total_calls": pl.Int64,
                "total_failures": pl.Int64,
                "success_rate": pl.Float64,
            }
        )

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'providers_summary'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(
                    schema={
                        "provider": pl.Utf8,
                        "circuit_state": pl.Utf8,
                        "failure_count": pl.Int64,
                        "tokens": pl.Float64,
                        "reliability_score": pl.Float64,
                        "total_calls": pl.Int64,
                        "total_failures": pl.Int64,
                        "success_rate": pl.Float64,
                    }
                )

            query = "SELECT * FROM providers_summary"
            params: list[Any] = []
            if provider:
                query += " WHERE provider = ?"
                params.append(provider)
            query += " ORDER BY provider ASC"

            arrow_table = conn.execute(query, params).arrow()
            return pl.from_arrow(arrow_table)
    except Exception as exc:
        logger.warning("duckdb_providers_summary_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(
            schema={
                "provider": pl.Utf8,
                "circuit_state": pl.Utf8,
                "failure_count": pl.Int64,
                "tokens": pl.Float64,
                "reliability_score": pl.Float64,
                "total_calls": pl.Int64,
                "total_failures": pl.Int64,
                "success_rate": pl.Float64,
            }
        )


def clear_providers_summary_duckdb(db_path: str = DEFAULT_CB_DB_PATH) -> None:
    """DuckDB'de depolanan sağlayıcı özet tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS providers_summary;")
    except Exception as exc:
        logger.error("duckdb_providers_summary_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__ = [
    "CB_FAILURES_COUNTER",
    "CB_STATE_GAUGE",
    "DEFAULT_BASE_DELAY",
    "DEFAULT_CB_DB_PATH",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RATE_LIMIT_TOKENS",
    "DEFAULT_RECOVERY_TIMEOUT_SECONDS",
    "DEFAULT_REFILL_RATE",
    "DEFAULT_RELIABILITY_DB_PATH",
    "DEFAULT_WAL_SIZE",
    "DEFAULT_WINDOW_SIZE",
    "CircuitBreaker",
    "CircuitState",
    "ProtectedProvider",
    "ProviderReliability",
    "RateLimiter",
    "RetryPolicy",
    "clear_all_providers",
    "clear_providers_summary_duckdb",
    "clear_reliability_logs_duckdb",
    "configure_duckdb_wal",
    "export_all_providers_to_duckdb",
    "export_all_providers_to_polars",
    "get_all_health",
    "get_provider",
    "otel_trace",
    "read_providers_summary_from_duckdb",
    "read_reliability_logs_from_duckdb",
    "register_protected_provider",
    "to_orjson_bytes",
    "unregister_protected_provider",
]
