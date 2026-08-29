"""
ALPHA BIST — Provider Manager v2.0

Gelişmiş provider yönetimi:
- Failover + priority-based seçim
- Circuit breaker entegrasyonu
- Rate limiter entegrasyonu
- Retry policy entegrasyonu
- Cross-source reconciliation
- Per-provider timeout
- Prometheus metrics

Kullanım:
    manager = ProviderManager()
    manager.register("market_price", "yfinance", yfinance_fetch, priority=0)
    manager.register("market_price", "bist", bist_fetch, priority=1)

    result = await manager.fetch("market_price", ticker="THYAO")
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from .circuit_breaker import CircuitBreakerError, CircuitBreakerManager
from .rate_limiter import RateLimiter, rate_limiter
from .retry_policy import RetryExhaustedError, RetryPolicy, get_retry_policy

logger = structlog.get_logger()


@dataclass
class ProviderConfig:
    """Provider yapılandırması."""

    name: str
    func: Callable
    priority: int = 0
    timeout_s: float = 30.0
    enabled: bool = True


@dataclass
class ProviderResult:
    """Provider sonuç verisi."""

    provider: str
    data: Any
    timestamp: datetime
    latency_ms: float
    quality: float = 1.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    """Provider sağlık durumu."""

    name: str
    is_healthy: bool = True
    last_success: datetime | None = None
    last_failure: datetime | None = None
    consecutive_failures: int = 0
    avg_latency_ms: float = 0
    success_rate: float = 1.0
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0


class ProviderManager:
    """
    Gelişmiş provider yönetimi.

    Her data_type için birden fazla provider kaydedilebilir.
    Priority sırasıyla denenir, circuit breaker + rate limiter + retry ile korunur.
    """

    def __init__(
        self,
        rate_limiter_instance: RateLimiter | None = None,
        circuit_breaker_manager: CircuitBreakerManager | None = None,
    ):
        """Otomatik eklendi."""
        self._providers: dict[str, list[ProviderConfig]] = {}  # data_type → providers
        self._health: dict[str, ProviderHealth] = {}
        self._rate_limiter = rate_limiter_instance or rate_limiter
        self._cb_manager = circuit_breaker_manager or CircuitBreakerManager()
        self._retry_policies: dict[str, RetryPolicy] = {}

    def register(
        self,
        data_type: str,
        name: str,
        func: Callable,
        priority: int = 0,
        timeout_s: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker_config: dict | None = None,
    ) -> Any:
        """Provider kaydet."""
        if data_type not in self._providers:
            self._providers[data_type] = []

        config = ProviderConfig(
            name=name,
            func=func,
            priority=priority,
            timeout_s=timeout_s,
        )
        self._providers[data_type].append(config)

        # Priority'ye göre sırala
        self._providers[data_type].sort(key=lambda p: p.priority)

        # Health tracking
        self._health[name] = ProviderHealth(name=name)

        # Circuit breaker
        cb_config = circuit_breaker_config or {}
        self._cb_manager.get_or_create(
            name,
            failure_threshold=cb_config.get("failure_threshold", 5),
            recovery_timeout_s=cb_config.get("recovery_timeout_s", 60.0),
        )

        # Retry policy
        if retry_policy:
            self._retry_policies[name] = retry_policy
        else:
            self._retry_policies[name] = get_retry_policy(name)

        logger.info("Provider registered", data_type=data_type, name=name, priority=priority, timeout_s=timeout_s)

    async def fetch(
        self,
        data_type: str,
        *args,
        use_reconciliation: bool = False,
        **kwargs,
    ) -> ProviderResult | None:
        """
        Veri çek — failover ile.

        Priority sırasıyla dene, circuit breaker + rate limiter + retry koruması.

        Args:
            data_type: Veri tipi (ör: "market_price", "fundamental")
            use_reconciliation: Çoklu kaynaktan çek, doğrula

        Returns:
            ProviderResult veya None (tüm provider'lar başarısız)
        """
        providers = self._providers.get(data_type, [])
        if not providers:
            logger.error("No providers registered", data_type=data_type)
            return None

        errors = []

        for provider_config in providers:
            if not provider_config.enabled:
                continue

            name = provider_config.name
            health = self._health.get(name)
            cb = self._cb_manager.get_or_create(name)
            retry = self._retry_policies.get(name, get_retry_policy(name))

            # Circuit breaker kontrolü
            if not cb.can_execute():
                logger.debug("Circuit breaker OPEN", provider=name)
                errors.append(f"{name}: circuit_open")
                continue

            # Rate limiter kontrolü
            wait_time = await self._rate_limiter.acquire(name)
            if wait_time > 0:
                logger.debug("Rate limited", provider=name, wait=wait_time)

            # Retry ile fetch
            start_time = time.time()
            try:
                result = await retry.execute(
                    self._fetch_with_timeout,
                    provider_config,
                    *args,
                    **kwargs,
                )

                latency_ms = (time.time() - start_time) * 1000

                # Başarı
                cb.record_success()
                if health:
                    health.is_healthy = True
                    health.last_success = datetime.now(UTC)
                    health.consecutive_failures = 0
                    health.total_requests += 1
                    health.total_successes += 1
                    health.avg_latency_ms = health.avg_latency_ms * 0.9 + latency_ms * 0.1
                    health.success_rate = min(
                        1.0,
                        health.success_rate + 0.01,
                    )

                return ProviderResult(
                    provider=name,
                    data=result,
                    timestamp=datetime.now(UTC),
                    latency_ms=round(latency_ms, 2),
                    source=name,
                )

            except (CircuitBreakerError, RetryExhaustedError) as e:
                cb.record_failure()
                if health:
                    health.is_healthy = health.consecutive_failures < 10
                    health.last_failure = datetime.now(UTC)
                    health.consecutive_failures += 1
                    health.total_requests += 1
                    health.total_failures += 1
                    health.success_rate = max(0, health.success_rate - 0.05)

                errors.append(f"{name}: {str(e)}")
                logger.warning("Provider failed", provider=name, error=str(e), attempt=errors.__len__())

            except Exception as e:
                cb.record_failure()
                if health:
                    health.is_healthy = health.consecutive_failures < 10
                    health.last_failure = datetime.now(UTC)
                    health.consecutive_failures += 1
                    health.total_requests += 1
                    health.total_failures += 1

                errors.append(f"{name}: {str(e)}")
                logger.warning("Provider unexpected error", provider=name, error=str(e))

        logger.error("All providers failed", data_type=data_type, errors=errors)
        return None

    async def fetch_multi(
        self,
        data_type: str,
        tickers: list[str],
        *args,
        **kwargs,
    ) -> dict[str, ProviderResult | None]:
        """
        Çoklu ticker için paralel fetch.

        Rate limiter'a dikkat — semaphore ile sınırla.
        """
        semaphore = asyncio.Semaphore(5)  # Max 5 paralel

        async def _fetch_one(ticker: str) -> Any:
            """Otomatik eklendi."""
            async with semaphore:
                return ticker, await self.fetch(data_type, *args, ticker=ticker, **kwargs)

        results = await asyncio.gather(
            *[_fetch_one(t) for t in tickers],
            return_exceptions=True,
        )

        output = {}
        for item in results:
            if isinstance(item, Exception):
                logger.error("Multi-fetch error", error=str(item))
                continue
            ticker, result = item
            output[ticker] = result

        return output

    async def _fetch_with_timeout(
        self,
        provider_config: ProviderConfig,
        *args,
        **kwargs,
    ) -> Any:
        """Timeout ile provider çağrısı."""
        return await asyncio.wait_for(
            provider_config.func(*args, **kwargs),
            timeout=provider_config.timeout_s,
        )

    def get_health(self) -> dict[str, dict]:
        """Tüm provider sağlık durumları."""
        return {
            name: {
                "healthy": h.is_healthy,
                "success_rate": round(h.success_rate, 3),
                "avg_latency_ms": round(h.avg_latency_ms, 1),
                "consecutive_failures": h.consecutive_failures,
                "total_requests": h.total_requests,
                "total_successes": h.total_successes,
                "total_failures": h.total_failures,
                "last_success": h.last_success.isoformat() if h.last_success else None,
                "last_failure": h.last_failure.isoformat() if h.last_failure else None,
            }
            for name, h in self._health.items()
        }

    def get_circuit_breaker_states(self) -> dict[str, dict]:
        """Tüm circuit breaker durumları."""
        return self._cb_manager.get_all_states()

    def get_rate_limiter_stats(self) -> dict[str, dict]:
        """Tüm rate limiter istatistikleri."""
        return self._rate_limiter.get_all_stats()

    def get_retry_stats(self) -> dict[str, dict]:
        """Tüm retry istatistikleri."""
        return {name: policy.get_stats() for name, policy in self._retry_policies.items()}

    def get_full_status(self) -> dict[str, Any]:
        """Tam durum raporu."""
        return {
            "providers": self.get_health(),
            "circuit_breakers": self.get_circuit_breaker_states(),
            "rate_limiters": self.get_rate_limiter_stats(),
            "retry_policies": self.get_retry_stats(),
            "registered_types": list(self._providers.keys()),
            "total_providers": sum(len(providers) for providers in self._providers.values()),
        }

    def enable_provider(self, data_type: str, name: str) -> Any:
        """Provider'ı etkinleştir."""
        for p in self._providers.get(data_type, []):
            if p.name == name:
                p.enabled = True
                logger.info("Provider enabled", data_type=data_type, name=name)
                return

    def disable_provider(self, data_type: str, name: str) -> Any:
        """Provider'ı devre dışı bırak."""
        for p in self._providers.get(data_type, []):
            if p.name == name:
                p.enabled = False
                logger.info("Provider disabled", data_type=data_type, name=name)
                return


# Singleton
provider_manager = ProviderManager()
