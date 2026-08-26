"""
ALPHA BIST — Circuit Breaker & Rate Limiter v1.0

Provider'lar için:
- Circuit Breaker: CLOSED → OPEN → HALF_OPEN → CLOSED
- Rate Limiter: Token bucket + exponential backoff
- Provider Reliability Score tracking

FAZ 1.3-1.5: Provider Failover + Circuit Breaker + Rate Limit
"""

import time
import random
import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


class CircuitState(str, Enum):
    CLOSED = "CLOSED"           # Normal çalışıyor
    OPEN = "OPEN"               # Hatalı, atla
    HALF_OPEN = "HALF_OPEN"     # Dene, başarırsa CLOSED


@dataclass
class CircuitBreaker:
    """Circuit Breaker — provider sürekli hata veriyorsa durdur.

    State machine:
    CLOSED (normal) → 5 failure → OPEN (skip)
    OPEN → 60s timeout → HALF_OPEN (try 1)
    HALF_OPEN → success → CLOSED
    HALF_OPEN → failure → OPEN
    """
    name: str
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    half_open_calls: int = 0

    def record_success(self):
        """Başarılı çağrı kaydet."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("Circuit breaker CLOSED", name=self.name)
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)

        self.last_success_time = datetime.now(timezone.utc)
        self._persist_state()

    def record_failure(self):
        """Başarısız çağrı kaydet."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)

        if self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPENED", name=self.name,
                         failures=self.failure_count)
        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker re-OPENED (half-open failure)", name=self.name)

        self._persist_state()

    def can_execute(self) -> bool:
        """Çağrı yapılabilir mi?"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Recovery timeout doldu mu?
            if self.last_failure_time:
                elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("Circuit breaker HALF_OPEN", name=self.name)
                    return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Half-open'da sadece 1 çağrıya izin ver
            if self.half_open_calls < 1:
                self.half_open_calls += 1
                return True
            return False

        return False

    def get_state(self) -> Dict[str, Any]:
        """Durum bilgisi."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success": self.last_success_time.isoformat() if self.last_success_time else None,
        }

    def _persist_state(self):
        """Durumu DuckDB'ye kaydet (SSD dostu — buffered)."""
        try:
            from .state_store import state_store
            state_store.save_circuit_state(
                self.name,
                self.state.value,
                self.failure_count,
                self.last_failure_time.isoformat() if self.last_failure_time else None,
                self.last_success_time.isoformat() if self.last_success_time else None,
            )
        except Exception:
            logger.warning("Caught Exception in _persist_state", exc_info=True)

    def restore_state(self):
        """Durumu DuckDB'den geri yükle."""
        try:
            from .state_store import state_store
            saved = state_store.load_circuit_state(self.name)
            if saved:
                self.state = CircuitState(saved["state"])
                self.failure_count = saved["failure_count"]
                if saved.get("last_failure_at"):
                    self.last_failure_time = datetime.fromisoformat(saved["last_failure_at"])
                if saved.get("last_success_at"):
                    self.last_success_time = datetime.fromisoformat(saved["last_success_at"])
                logger.info("Circuit breaker state restored",
                           name=self.name, state=self.state.value)
        except Exception as e:
            logger.debug("Circuit breaker restore skipped", name=self.name, error=str(e))


@dataclass
class RateLimiter:
    """Rate Limiter — token bucket algoritması.

    Her provider için saniyede max istek sayısı.
    Limit dolduğunda bekle, hata verme.
    """
    name: str
    max_tokens: float = 10.0          # Bucket kapasitesi
    refill_rate: float = 1.0          # Saniyede kaç token yenilenir
    tokens: float = 10.0              # Mevcut token
    last_refill: float = field(default_factory=time.monotonic)

    def acquire(self) -> float:
        """Token al. Dönen değer: beklenmesi gereken saniye (0 = hemen yapılabilir)."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        else:
            # Bekleme süresi
            wait_time = (1.0 - self.tokens) / self.refill_rate
            self.tokens = 0
            return wait_time

    async def acquire_async(self):
        """Async token al — gerekirse bekle."""
        wait = self.acquire()
        if wait > 0:
            logger.debug("Rate limiter waiting", name=self.name, seconds=round(wait, 2))
            await asyncio.sleep(wait)

    def get_state(self) -> Dict[str, Any]:
        """Durum bilgisi."""
        return {
            "name": self.name,
            "tokens": round(self.tokens, 2),
            "max_tokens": self.max_tokens,
            "refill_rate": self.refill_rate,
        }


class RetryPolicy:
    """Exponential backoff retry politikası.

    Retry: 1s → 2s → 4s → 8s → 16s
    Max retry: 5
    Jitter: ±%10
    """

    def __init__(self, max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 32.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def get_delay(self, attempt: int) -> float:
        """Retry gecikmesi hesapla (exponential backoff + jitter)."""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = delay * 0.1 * (2 * random.random() - 1)  # ±%10
        return max(0, delay + jitter)

    async def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Fonksiyonu retry ile çalıştır."""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    logger.warning("Retry", attempt=attempt + 1, delay=round(delay, 2), error=str(e))
                    await asyncio.sleep(delay)
                else:
                    logger.error("Max retries exceeded", attempts=self.max_retries + 1, error=str(e))

        raise last_error


class ProviderReliability:
    """Provider güvenilirlik skoru takibi.

    Skor: 0-1 arası
    Hesaplama: success rate × latency factor × freshness factor
    """

    def __init__(self, name: str, window_size: int = 100):
        self.name = name
        self.window_size = window_size
        self._results: list = []  # (success: bool, latency_ms: float, timestamp: datetime)
        self._total_calls: int = 0
        self._total_failures: int = 0

    def record(self, success: bool, latency_ms: float = 0):
        """Sonuç kaydet."""
        self._total_calls += 1
        if not success:
            self._total_failures += 1

        self._results.append({
            "success": success,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc),
        })
        if len(self._results) > 1000:
            self._results = self._results[-1000:]

        # Pencere boyutunu aş
        if len(self._results) > self.window_size:
            self._results = self._results[-self.window_size:]

    def get_score(self) -> float:
        """Güvenilirlik skoru (0-1)."""
        if not self._results:
            return 1.0  # Veri yoksa varsayılan

        # Success rate
        successes = sum(1 for r in self._results if r["success"])
        success_rate = successes / len(self._results)

        # Latency factor (düşük latency = yüksek skor)
        latencies = [r["latency_ms"] for r in self._results if r["success"]]
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            # 1000ms üzeri cezalandır
            latency_factor = max(0, 1 - (avg_latency / 5000))
        else:
            latency_factor = 0.5

        # Freshness factor (son başarılı çağrı ne kadar yakın?)
        last_success = None
        for r in reversed(self._results):
            if r["success"]:
                last_success = r["timestamp"]
                break

        if last_success:
            minutes_since = (datetime.now(timezone.utc) - last_success).total_seconds() / 60
            freshness_factor = max(0, 1 - (minutes_since / 60))  # 1 saat içinde
        else:
            freshness_factor = 0

        score = success_rate * 0.6 + latency_factor * 0.2 + freshness_factor * 0.2
        return round(min(1.0, max(0.001, score)), 3)  # 0.001 minimum (tam 0 olamaz)

    def get_stats(self) -> Dict[str, Any]:
        """İstatistikler."""
        return {
            "name": self.name,
            "reliability_score": self.get_score(),
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "success_rate": round(1 - (self._total_failures / max(1, self._total_calls)), 3),
            "window_size": len(self._results),
        }


class ProtectedProvider:
    """Circuit Breaker + Rate Limiter + Retry + Reliability ile korunan provider.

    Tüm provider'lar bu wrapper ile sarılmalı.
    """

    def __init__(
        self,
        name: str,
        func: Callable,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        retry_policy: Optional[RetryPolicy] = None,
        reliability: Optional[ProviderReliability] = None,
    ):
        self.name = name
        self.func = func
        self.circuit = circuit_breaker or CircuitBreaker(name=name)
        self.rate_limiter = rate_limiter or RateLimiter(name=name)
        self.retry_policy = retry_policy or RetryPolicy()
        self.reliability = reliability or ProviderReliability(name=name)

    async def execute(self, *args, **kwargs) -> Optional[Any]:
        """Korumalı çağrı yap.

        Akış:
        1. Circuit breaker kontrolü
        2. Rate limiter
        3. Retry ile çağrı
        4. Sonuç kaydet
        """
        # Circuit breaker
        if not self.circuit.can_execute():
            logger.warning("Circuit breaker OPEN, skipping", provider=self.name)
            return None

        # Rate limiter
        await self.rate_limiter.acquire_async()

        # Retry ile çağır
        start_time = time.monotonic()
        try:
            result = await self.retry_policy.execute_with_retry(self.func, *args, **kwargs)
            latency = (time.monotonic() - start_time) * 1000

            # Başarılı
            self.circuit.record_success()
            self.reliability.record(True, latency)

            return result

        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000

            # Başarısız
            self.circuit.record_failure()
            self.reliability.record(False, latency)

            logger.error("Provider call failed", provider=self.name, error=str(e))
            return None

    def get_health(self) -> Dict[str, Any]:
        """Sağlık durumu."""
        return {
            "provider": self.name,
            "circuit": self.circuit.get_state(),
            "rate_limiter": self.rate_limiter.get_state(),
            "reliability": self.reliability.get_stats(),
        }


# =====================================================
# Global Registry
# =====================================================

_providers: Dict[str, ProtectedProvider] = {}


def register_protected_provider(
    name: str,
    func: Callable,
    max_calls_per_second: float = 2.0,
    circuit_failure_threshold: int = 5,
) -> ProtectedProvider:
    """Korumalı provider kaydet."""
    provider = ProtectedProvider(
        name=name,
        func=func,
        circuit_breaker=CircuitBreaker(
            name=name,
            failure_threshold=circuit_failure_threshold,
        ),
        rate_limiter=RateLimiter(
            name=name,
            max_tokens=max_calls_per_second * 2,
            refill_rate=max_calls_per_second,
        ),
        retry_policy=RetryPolicy(max_retries=3),
        reliability=ProviderReliability(name=name),
    )
    _providers[name] = provider
    logger.info("Protected provider registered", name=name, rate=max_calls_per_second)
    return provider


def get_provider(name: str) -> Optional[ProtectedProvider]:
    """Provider getir."""
    return _providers.get(name)


def get_all_health() -> Dict[str, Dict]:
    """Tüm provider sağlık durumları."""
    return {name: p.get_health() for name, p in _providers.items()}
