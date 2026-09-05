"""ALPHA BIST — Kurumsal Circuit Breaker, Rate Limiter ve Sağlayıcı Güvenilirlik Çerçevesi.

Bu modül, dış veri sağlayıcıları ve kritik mikroservis çağrıları için dayanıklılık (resilience)
ve hata toleransı mimarisini yürütür:
1. Circuit Breaker (Durum Makinesi: CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
2. Rate Limiter (Token Bucket algoritması ile milisaniye hassasiyetinde hız limitleme)
3. Retry Policy (Exponential Backoff + Jitter ile yeniden deneme)
4. Provider Reliability (Başarı oranı, gecikme ve tazelik metrikleriyle dinamik güvenilirlik skoru)
5. ProtectedProvider Wrapper (Tüm koruma katmanlarını birleştiren yüksek performanslı sarmalayıcı)
6. DuckDB StateStore entegrasyonu (Yeniden başlatmalarda durum kurtarma)
"""

from __future__ import annotations

import asyncio
import inspect
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import structlog
from opentelemetry import metrics, trace

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.circuit-breaker")
meter = metrics.get_meter("alpha.circuit_breaker")

# OTel Metrikleri
CB_STATE_GAUGE = meter.create_gauge(
    "alpha.circuit_breaker.state",
    description="Circuit Breaker durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
)
CB_FAILURES_COUNTER = meter.create_counter(
    "alpha.circuit_breaker.failures.total",
    description="Circuit Breaker tarafından kaydedilen toplam hata sayısı",
)

# Varsayılan Yapılandırma Sabitleri
DEFAULT_FAILURE_THRESHOLD: Final[int] = 5
DEFAULT_RECOVERY_TIMEOUT_SECONDS: Final[int] = 60
DEFAULT_RATE_LIMIT_TOKENS: Final[float] = 10.0
DEFAULT_REFILL_RATE: Final[float] = 1.0
DEFAULT_MAX_RETRIES: Final[int] = 5
DEFAULT_BASE_DELAY: Final[float] = 1.0
DEFAULT_MAX_DELAY: Final[float] = 32.0
DEFAULT_WINDOW_SIZE: Final[int] = 100


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
    - OPEN -> recovery_timeout_seconds süresi dolunca -> HALF_OPEN (1 deneme çağrısına izin verilir)
    - HALF_OPEN -> Başarılı çağrı -> CLOSED (sıfırlanır)
    - HALF_OPEN -> Başarısız çağrı -> OPEN (yeniden kilitlenir)
    """

    name: str
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_timeout_seconds: int = DEFAULT_RECOVERY_TIMEOUT_SECONDS
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    half_open_calls: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def _update_telemetry(self) -> None:
        """OpenTelemetry ölçüm göstergelerini günceller."""
        state_val = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}.get(self.state, 0)
        CB_STATE_GAUGE.set(state_val, {"provider": self.name})

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
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.half_open_calls = 0
                logger.info("circuit_breaker_kapandi", name=self.name, durum="CLOSED")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

            self.last_success_time = datetime.now(UTC)
            self._update_telemetry()
            self._persist_to_store()

    def record_failure(self) -> None:
        """Başarısız çağrıyı kaydeder ve gerekirse devreyi OPEN durumuna geçirir."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now(UTC)
            CB_FAILURES_COUNTER.add(1, {"provider": self.name})

            if self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_acildi",
                    name=self.name,
                    durum="OPEN",
                    hata_sayisi=self.failure_count,
                    esik=self.failure_threshold,
                )
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                logger.warning(
                    "circuit_breaker_yeniden_acildi",
                    name=self.name,
                    durum="OPEN",
                    neden="half_open_hatasi",
                )

            self._update_telemetry()
            self._persist_to_store()

    def can_execute(self) -> bool:
        """Yeni bir çağrı yapılmasına izin verilip verilmeyeceğini denetler.

        Returns:
            bool: İstek çalıştırılabilir ise True, engellendiyse False.
        """
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                if self.last_failure_time:
                    elapsed = (datetime.now(UTC) - self.last_failure_time).total_seconds()
                    if elapsed >= self.recovery_timeout_seconds:
                        self.state = CircuitState.HALF_OPEN
                        self.half_open_calls = 1
                        logger.info("circuit_breaker_yari_acik_modda", name=self.name, durum="HALF_OPEN")
                        return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < 1:
                    self.half_open_calls += 1
                    return True
                return False

            return False

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

    def acquire(self) -> float:
        """Token alır veya bekleme süresi döner.

        Returns:
            float: Hemen yapılabilirse 0.0, aksi halde beklenmesi gereken saniye.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.last_refill)
            safe_rate = max(1e-6, self.refill_rate)

            self.tokens = min(self.max_tokens, self.tokens + (elapsed * safe_rate))
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return 0.0
            else:
                wait_time = (1.0 - self.tokens) / safe_rate
                self.tokens = 0.0
                return max(0.0, wait_time)

    async def acquire_async(self) -> None:
        """Asenkron token alır, gerekirse hesaplanan süre kadar bekler."""
        wait = self.acquire()
        if wait > 0:
            logger.debug("rate_limiter_bekliyor", name=self.name, saniye=round(wait, 3))
            await asyncio.sleep(wait)

    def get_state(self) -> dict[str, Any]:
        """Hız limitleyicinin anlık token ve kapasite durumunu döner."""
        with self._lock:
            return {
                "name": self.name,
                "tokens": round(self.tokens, 2),
                "max_tokens": self.max_tokens,
                "refill_rate": self.refill_rate,
            }

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
        """Fonksiyonu yeniden deneme korumasıyla çalıştırır (sync ve async callable destekler).

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
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
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

            # 2. Gecikme Faktörü (Latency Factor)
            latencies = [r["latency_ms"] for r in self._results if r["success"]]
            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                latency_factor = max(0.0, 1.0 - (avg_latency / 5000.0))
            else:
                latency_factor = 0.5

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
                return 0.5
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
            raise_on_failure: Başarısızlıkta istisna fırlatılsın mı yoksa None mı dönülsün.
        """
        self.name: str = name
        self.func: Callable[..., Any] = func
        self.circuit: CircuitBreaker = circuit_breaker or CircuitBreaker(name=name)
        self.rate_limiter: RateLimiter = rate_limiter or RateLimiter(name=name)
        self.retry_policy: RetryPolicy = retry_policy or RetryPolicy()
        self.reliability: ProviderReliability = reliability or ProviderReliability(name=name)
        self.raise_on_failure: bool = raise_on_failure

    async def execute(self, *args: Any, **kwargs: Any) -> Any | None:
        """Korumalı yürütme hattını işletir.

        Adımlar:
        1. Circuit Breaker kontrolü (erken engelleme)
        2. Rate Limiter beklemesi (token kontrolü)
        3. Retry ile yürütme
        4. Başarı / gecikme / telemetri kaydı

        Args:
            *args: Fonksiyon argümanları.
            **kwargs: Anahtar kelime argümanları.

        Returns:
            Any | None: Fonksiyon çıktısı veya engel/hata durumunda None.

        Raises:
            asyncio.CancelledError: İptal durumunda yukarı fırlatılır.
            Exception: raise_on_failure True ise fırlatılır.
        """
        if not self.circuit.can_execute():
            logger.warning("circuit_breaker_acik_cagri_engellendi", provider=self.name)
            return None

        await self.rate_limiter.acquire_async()

        start_time = time.monotonic()
        with tracer.start_as_current_span("circuit_breaker.execute") as span:
            span.set_attribute("provider.name", self.name)
            try:
                result = await self.retry_policy.execute_with_retry(self.func, *args, **kwargs)
                latency = (time.monotonic() - start_time) * 1000.0
                self.circuit.record_success()
                self.reliability.record(True, latency)
                span.set_attribute("result", "success")
                return result

            except asyncio.CancelledError:
                span.set_attribute("result", "cancelled")
                logger.warning("korumali_cagri_iptal_edildi", provider=self.name)
                raise

            except Exception as exc:
                latency = (time.monotonic() - start_time) * 1000.0
                self.circuit.record_failure()
                self.reliability.record(False, latency)
                span.set_attribute("result", "failure")
                span.record_exception(exc)
                logger.error("provider_cagrisi_basarisiz", provider=self.name, hata=str(exc))

                if self.raise_on_failure:
                    raise
                return None

    def get_health(self) -> dict[str, Any]:
        """Sağlayıcının sağlık ve performans özetini döner."""
        return {
            "provider": self.name,
            "circuit": self.circuit.get_state(),
            "rate_limiter": self.rate_limiter.get_state(),
            "reliability": self.reliability.get_stats(),
        }

    def __repr__(self) -> str:
        """Korumalı sağlayıcının okunabilir dize temsilini döner."""
        return (
            f"ProtectedProvider(name='{self.name}', state='{self.circuit.state.value}', "
            f"reliability={self.reliability.get_score()})"
        )


# =====================================================
# Global Registry (Thread-Safe)
# =====================================================

_registry_lock = threading.Lock()
_providers: dict[str, ProtectedProvider] = {}


def register_protected_provider(
    name: str,
    func: Callable[..., Any],
    max_calls_per_second: float = 2.0,
    circuit_failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    raise_on_failure: bool = False,
) -> ProtectedProvider:
    """Yeni bir korumalı sağlayıcıyı merkezi kayıt defterine ekler.

    Args:
        name: Sağlayıcının tekil adı.
        func: Korunacak fonksiyon.
        max_calls_per_second: Saniyede izin verilen maksimum istek adedi.
        circuit_failure_threshold: Devrenin açılması için gereken ardışık hata sayısı.
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


def get_all_health() -> dict[str, dict[str, Any]]:
    """Tüm kayıtlı sağlayıcıların anlık sağlık durumlarını döner.

    Returns:
        dict[str, dict[str, Any]]: Sağlayıcı sağlık raporları haritası.
    """
    with _registry_lock:
        providers_snapshot = list(_providers.items())
    return {name: p.get_health() for name, p in providers_snapshot}


__all__ = [
    "CB_FAILURES_COUNTER",
    "CB_STATE_GAUGE",
    "DEFAULT_BASE_DELAY",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RATE_LIMIT_TOKENS",
    "DEFAULT_RECOVERY_TIMEOUT_SECONDS",
    "DEFAULT_REFILL_RATE",
    "DEFAULT_WINDOW_SIZE",
    "CircuitBreaker",
    "CircuitState",
    "ProtectedProvider",
    "ProviderReliability",
    "RateLimiter",
    "RetryPolicy",
    "get_all_health",
    "get_provider",
    "otel_trace",
    "register_protected_provider",
]
