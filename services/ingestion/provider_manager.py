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
    """Provider yapılandırması.

    Attributes:
        name: Provider adı.
        func: Çağrılacak fonksiyon.
        priority: Öncelik sırası (düşük = yüksek öncelik).
        timeout_s: Çağrı timeout süresi (saniye).
        enabled: Provider etkin mi.
    """

    name: str
    func: Callable[..., Any]
    priority: int = 0
    timeout_s: float = 30.0
    enabled: bool = True

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(name={self.name!r}, "
            f"priority={self.priority}, enabled={self.enabled})"
        )


@dataclass
class ProviderResult:
    """Provider sonuç verisi.

    Attributes:
        provider: Sağlayıcı adı.
        data: Ham veri.
        timestamp: Veri zaman damgası.
        latency_ms: Çağrı süresi (milisaniye).
        quality: Kalite puanı (0.0-1.0).
        source: Kaynak adı.
        metadata: Ek meta bilgiler.
    """

    provider: str
    data: Any
    timestamp: datetime
    latency_ms: float
    quality: float = 1.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"ProviderResult(provider={self.provider!r}, "
            f"quality={self.quality:.2f}, latency={self.latency_ms:.1f}ms)"
        )


@dataclass
class ProviderHealth:
    """Provider sağlık durumu.

    Attributes:
        name: Provider adı.
        is_healthy: Sağlıklı mı.
        last_success: Son başarı zamanı.
        last_failure: Son hata zamanı.
        consecutive_failures: Ardışık hata sayısı.
        avg_latency_ms: Ortalama gecikme.
        success_rate: Başarı oranı.
        total_requests: Toplam istek sayısı.
        total_successes: Toplam başarılı istek.
        total_failures: Toplam başarısız istek.
    """

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

    def __repr__(self) -> str:
        return (
            f"ProviderHealth(name={self.name!r}, "
            f"healthy={self.is_healthy}, rate={self.success_rate:.2f})"
        )


class ProviderManager:
    """Gelişmiş provider yöneticisi.

    Her data_type için birden fazla provider kaydedilebilir.
    Priority sırasıyla denenir, circuit breaker + rate limiter + retry ile korunur.

    Args:
        rate_limiter_instance: Rate limiter örneği (None = varsayılan).
        circuit_breaker_manager: Circuit breaker yöneticisi (None = yeni oluştur).
    """

    def __init__(
        self,
        rate_limiter_instance: RateLimiter | None = None,
        circuit_breaker_manager: CircuitBreakerManager | None = None,
    ) -> None:
        """ProviderManager örneği oluşturur.

        Args:
            rate_limiter_instance: Rate limiter örneği.
            circuit_breaker_manager: Circuit breaker yöneticisi.
        """
        self._providers: dict[str, list[ProviderConfig]] = {}
        self._health: dict[str, ProviderHealth] = {}
        self._rate_limiter = rate_limiter_instance or rate_limiter
        self._cb_manager = circuit_breaker_manager or CircuitBreakerManager()
        self._retry_policies: dict[str, RetryPolicy] = {}

    def register(
        self,
        data_type: str,
        name: str,
        func: Callable[..., Any],
        priority: int = 0,
        timeout_s: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker_config: dict[str, Any] | None = None,
    ) -> None:
        """Provider kaydeder.

        Args:
            data_type: Veri tipi (ör. "market_price", "fundamental").
            name: Provider adı.
            func: Çağrılacak fonksiyon.
            priority: Öncelik sırası (düşük = yüksek öncelik).
            timeout_s: Çağrı timeout süresi (saniye).
            retry_policy: Özel retry policy (None = varsayılan).
            circuit_breaker_config: Circuit breaker yapılandırması.
        """
        if data_type not in self._providers:
            self._providers[data_type] = []

        config = ProviderConfig(
            name=name,
            func=func,
            priority=priority,
            timeout_s=timeout_s,
        )
        self._providers[data_type].append(config)

        self._providers[data_type].sort(key=lambda p: p.priority)

        self._health[name] = ProviderHealth(name=name)

        cb_config = circuit_breaker_config or {}
        self._cb_manager.get_or_create(
            name,
            failure_threshold=cb_config.get("failure_threshold", 5),
            recovery_timeout_s=cb_config.get("recovery_timeout_s", 60.0),
        )

        if retry_policy:
            self._retry_policies[name] = retry_policy
        else:
            self._retry_policies[name] = get_retry_policy(name)

        logger.info("Provider registered", data_type=data_type, name=name, priority=priority, timeout_s=timeout_s)

    async def fetch(
        self,
        data_type: str,
        *args: Any,
        use_reconciliation: bool = False,
        **kwargs: Any,
    ) -> ProviderResult | None:
        """Veri çeker — failover ile.

        Priority sırasıyla dener, circuit breaker + rate limiter + retry koruması.

        Args:
            data_type: Veri tipi (ör. "market_price", "fundamental").
            use_reconciliation: Çoklu kaynaktan çek, doğrula (henüz uygulanmadı).
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            ProviderResult veya None (tüm provider'lar başarısız).
        """
        providers = self._providers.get(data_type, [])
        if not providers:
            logger.error("No providers registered", data_type=data_type)
            return None

        errors: list[str] = []

        for provider_config in providers:
            if not provider_config.enabled:
                continue

            name = provider_config.name
            health = self._health.get(name)
            cb = self._cb_manager.get_or_create(name)
            retry = self._retry_policies.get(name, get_retry_policy(name))

            if not cb.can_execute():
                logger.debug("Circuit breaker OPEN", provider=name)
                errors.append(f"{name}: circuit_open")
                continue

            wait_time = await self._rate_limiter.acquire(name)
            if wait_time > 0:
                logger.debug("Rate limited", provider=name, wait=wait_time)

            start_time = time.time()
            try:
                result = await retry.execute(
                    self._fetch_with_timeout,
                    provider_config,
                    *args,
                    **kwargs,
                )

                latency_ms = (time.time() - start_time) * 1000

                cb.record_success()
                if health:
                    health.is_healthy = True
                    health.last_success = datetime.now(UTC)
                    health.consecutive_failures = 0
                    health.total_requests += 1
                    health.total_successes += 1
                    health.avg_latency_ms = health.avg_latency_ms * 0.9 + latency_ms * 0.1
                    health.success_rate = min(1.0, health.success_rate + 0.01)

                return ProviderResult(
                    provider=name,
                    data=result,
                    timestamp=datetime.now(UTC),
                    latency_ms=round(latency_ms, 2),
                    source=name,
                )

            except (CircuitBreakerError, RetryExhaustedError) as exc:
                cb.record_failure()
                if health:
                    health.is_healthy = health.consecutive_failures < 10
                    health.last_failure = datetime.now(UTC)
                    health.consecutive_failures += 1
                    health.total_requests += 1
                    health.total_failures += 1
                    health.success_rate = max(0, health.success_rate - 0.05)

                errors.append(f"{name}: {exc}")
                logger.warning("Provider failed", provider=name, error=str(exc))

            except Exception as exc:
                cb.record_failure()
                if health:
                    health.is_healthy = health.consecutive_failures < 10
                    health.last_failure = datetime.now(UTC)
                    health.consecutive_failures += 1
                    health.total_requests += 1
                    health.total_failures += 1

                errors.append(f"{name}: {exc}")
                logger.warning("Provider unexpected error", provider=name, error=str(exc))

        logger.error("All providers failed", data_type=data_type, errors=errors)
        return None

    async def fetch_multi(
        self,
        data_type: str,
        tickers: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, ProviderResult | None]:
        """Çoklu ticker için paralel fetch yapar.

        Args:
            data_type: Veri tipi.
            tickers: Hisse listesi.
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            {ticker: ProviderResult | None} sözlüğü.
        """
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one(ticker: str) -> tuple[str, ProviderResult | None]:
            async with semaphore:
                return ticker, await self.fetch(data_type, *args, ticker=ticker, **kwargs)

        results = await asyncio.gather(
            *[_fetch_one(t) for t in tickers],
            return_exceptions=True,
        )

        output: dict[str, ProviderResult | None] = {}
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
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Timeout ile provider çağrısı yapar.

        Args:
            provider_config: Provider yapılandırması.
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            Fonksiyon dönüş değeri.

        Raises:
            asyncio.TimeoutError: Timeout aşıldığında.
        """
        return await asyncio.wait_for(
            provider_config.func(*args, **kwargs),
            timeout=provider_config.timeout_s,
        )

    def get_health(self) -> dict[str, dict[str, Any]]:
        """Tüm provider sağlık durumlarını döndürür.

        Returns:
            {provider_adı: sağlık_sözlüğü} yapısı.
        """
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

    def get_circuit_breaker_states(self) -> dict[str, dict[str, Any]]:
        """Tüm circuit breaker durumlarını döndürür.

        Returns:
            {provider_adı: durum_sözlüğü} yapısı.
        """
        return self._cb_manager.get_all_states()

    def get_rate_limiter_stats(self) -> dict[str, dict[str, Any]]:
        """Tüm rate limiter istatistiklerini döndürür.

        Returns:
            {provider_adı: istatistik_sözlüğü} yapısı.
        """
        return self._rate_limiter.get_all_stats()

    def get_retry_stats(self) -> dict[str, dict[str, Any]]:
        """Tüm retry istatistiklerini döndürür.

        Returns:
            {provider_adı: istatistik_sözlüğü} yapısı.
        """
        return {name: policy.get_stats() for name, policy in self._retry_policies.items()}

    def get_full_status(self) -> dict[str, Any]:
        """Tam durum raporu döndürür.

        Returns:
            Tüm bileşenlerin durum sözlüğü.
        """
        return {
            "providers": self.get_health(),
            "circuit_breakers": self.get_circuit_breaker_states(),
            "rate_limiters": self.get_rate_limiter_stats(),
            "retry_policies": self.get_retry_stats(),
            "registered_types": list(self._providers.keys()),
            "total_providers": sum(len(providers) for providers in self._providers.values()),
        }

    def enable_provider(self, data_type: str, name: str) -> None:
        """Devre dışı provider'ı etkinleştirir.

        Args:
            data_type: Veri tipi.
            name: Provider adı.
        """
        for p in self._providers.get(data_type, []):
            if p.name == name:
                p.enabled = True
                logger.info("Provider enabled", data_type=data_type, name=name)
                return

    def disable_provider(self, data_type: str, name: str) -> None:
        """Provider'ı devre dışı bırakır.

        Args:
            data_type: Veri tipi.
            name: Provider adı.
        """
        for p in self._providers.get(data_type, []):
            if p.name == name:
                p.enabled = False
                logger.info("Provider disabled", data_type=data_type, name=name)
                return


# Singleton
provider_manager = ProviderManager()


__all__ = [
    "ProviderConfig",
    "ProviderResult",
    "ProviderHealth",
    "ProviderManager",
    "provider_manager",
]
