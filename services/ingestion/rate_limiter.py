"""
ALPHA BIST — Rate Limiter v1.0

Sliding window rate limiter — API limit aşılmasını önler.

Token bucket'tan daha adil: her istek window içinde sayılır.
Provider bazlı limit: yfinance 60/dk, KAP 30/dk, TCMB 20/dk.

Kullanım:
    limiter = RateLimiter()
    limiter.set_limit("yfinance", max_requests=60, window_seconds=60)

    wait = await limiter.acquire("yfinance")
    result = await fetch_data()
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RateLimitConfig:
    """Rate limit yapılandırması.

    Attributes:
        max_requests: Pencerede izin verilen maksimum istek.
        window_seconds: Pencere süresi (saniye).
        burst_size: Anlık patlama izni (0 = max_requests ile aynı).
    """

    max_requests: int
    window_seconds: float
    burst_size: int = 0

    def __repr__(self) -> str:
        return (
            f"RateLimitConfig(max={self.max_requests}, "
            f"window={self.window_seconds}s)"
        )


@dataclass
class RateLimitStats:
    """Rate limit istatistikleri.

    Attributes:
        total_requests: Toplam istek sayısı.
        total_waits: Bekleme yapılan istek sayısı.
        total_wait_seconds: Toplam bekleme süresi.
        total_rejected: Reddedilen istek sayısı.
        current_window_requests: Mevcut penceredeki istek sayısı.
        last_request_time: Son istek zamanı (epoch).
    """

    total_requests: int = 0
    total_waits: int = 0
    total_wait_seconds: float = 0.0
    total_rejected: int = 0
    current_window_requests: int = 0
    last_request_time: float | None = None

    def __repr__(self) -> str:
        return (
            f"RateLimitStats(requests={self.total_requests}, "
            f"waits={self.total_waits}, rejected={self.total_rejected})"
        )


class RateLimiter:
    """Sliding window rate limiter.

    Her provider için ayrı limit tanımlanabilir.
    Limit aşılırsa async olarak bekler.
    """

    def __init__(self) -> None:
        """RateLimiter örneği oluşturur."""
        self._limits: dict[str, RateLimitConfig] = {}
        self._timestamps: dict[str, list[float]] = {}
        self._stats: dict[str, RateLimitStats] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_limit(
        self,
        provider: str,
        max_requests: int,
        window_seconds: float = 60.0,
        burst_size: int = 0,
    ) -> None:
        """Rate limit ayarlar.

        Args:
            provider: Provider adı.
            max_requests: Pencerede izin verilen maksimum istek.
            window_seconds: Pencere süresi (saniye).
            burst_size: Anlık patlama izni (0 = max_requests ile aynı).
        """
        self._limits[provider] = RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
            burst_size=burst_size or max_requests,
        )
        if provider not in self._stats:
            self._stats[provider] = RateLimitStats()
        if provider not in self._timestamps:
            self._timestamps[provider] = []
        if provider not in self._locks:
            self._locks[provider] = asyncio.Lock()

        logger.info("Rate limit set", provider=provider, max_requests=max_requests, window_seconds=window_seconds)

    def _cleanup_window(self, provider: str) -> None:
        """Eski istekleri pencereden çıkarır.

        Args:
            provider: Provider adı.
        """
        config = self._limits.get(provider)
        if not config:
            return

        cutoff = time.time() - config.window_seconds
        timestamps = self._timestamps.get(provider, [])
        self._timestamps[provider] = [t for t in timestamps if t > cutoff]

    def _get_wait_time(self, provider: str) -> float:
        """Bekleme süresini hesaplar.

        Args:
            provider: Provider adı.

        Returns:
            Bekleme süresi (saniye). 0 = bekleme yok.
        """
        config = self._limits.get(provider)
        if not config:
            return 0.0

        self._cleanup_window(provider)
        timestamps = self._timestamps.get(provider, [])

        if len(timestamps) < config.max_requests:
            return 0.0

        oldest = timestamps[0]
        wait_time = config.window_seconds - (time.time() - oldest)
        return max(0.0, wait_time)

    async def acquire(self, provider: str) -> float:
        """Rate limit kontrolü yapar ve gerekirse bekler.

        Args:
            provider: Provider adı.

        Returns:
            Bekleme süresi (saniye). 0 = beklemedi.
        """
        config = self._limits.get(provider)
        if not config:
            return 0.0

        async with self._locks.get(provider, asyncio.Lock()):
            stats = self._stats[provider]
            stats.total_requests += 1
            stats.last_request_time = time.time()

            wait_time = self._get_wait_time(provider)

            if wait_time > 0:
                stats.total_waits += 1
                stats.total_wait_seconds += wait_time
                logger.debug("Rate limit wait", provider=provider, wait_seconds=round(wait_time, 2))
                await asyncio.sleep(wait_time)

            self._timestamps[provider].append(time.time())
            stats.current_window_requests = len(self._timestamps[provider])

            return wait_time

    class _AcquireContext:
        """async with limiter.acquire_context(provider): ... kullanımı için bağlam yöneticisi.

        Not: Bu sınıf alternatif API olarak sunulmuştur.
        Tercih edilen kullanım: doğrudan `await limiter.acquire(provider)`.

        Args:
            limiter: Üst RateLimiter örneği.
            provider: Provider adı.
        """

        def __init__(self, limiter: "RateLimiter", provider: str) -> None:
            """_AcquireContext örneği oluşturur.

            Args:
                limiter: Üst RateLimiter örneği.
                provider: Provider adı.
            """
            self._limiter = limiter
            self._provider = provider
            self._wait_time = 0.0

        async def __aenter__(self) -> "RateLimiter._AcquireContext":
            """Bağlama girer — rate limit kontrolü yapar.

            Returns:
                Kendisi (context manager).
            """
            self._wait_time = await self._limiter.acquire(self._provider)
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: Any,
        ) -> bool:
            """Bağlamdan çıkar.

            Returns:
                False — istisnayı yeniden fırlatır.
            """
            return False

    def acquire_context(self, provider: str) -> "RateLimiter._AcquireContext":
        """Context manager kullanımı için bağlam yöneticisi döndürür.

        Args:
            provider: Provider adı.

        Returns:
            _AcquireContext örneği.
        """
        return self._AcquireContext(self, provider)

    def get_stats(self, provider: str) -> dict[str, Any]:
        """Provider istatistiklerini döndürür.

        Args:
            provider: Provider adı.

        Returns:
            İstatistik sözlüğü.
        """
        stats = self._stats.get(provider, RateLimitStats())
        config = self._limits.get(provider)

        return {
            "provider": provider,
            "limit": config.max_requests if config else None,
            "window_seconds": config.window_seconds if config else None,
            "current_window_requests": stats.current_window_requests,
            "total_requests": stats.total_requests,
            "total_waits": stats.total_waits,
            "total_wait_seconds": round(stats.total_wait_seconds, 2),
            "avg_wait_ms": round((stats.total_wait_seconds / max(stats.total_waits, 1)) * 1000, 1),
        }

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Tüm provider istatistiklerini döndürür.

        Returns:
            {provider_adı: istatistik_sözlüğü} yapısı.
        """
        return {provider: self.get_stats(provider) for provider in self._limits}

    def is_limited(self, provider: str) -> bool:
        """Provider şu an limitli mi kontrol eder.

        Args:
            provider: Provider adı.

        Returns:
            True: Limitli (bekleme gerekli), False: Değil.
        """
        return self._get_wait_time(provider) > 0


# BIST'e özgü varsayılan limitler
BIST_RATE_LIMITS: dict[str, dict[str, int | float]] = {
    "yfinance": {"max_requests": 60, "window_seconds": 60},
    "kap": {"max_requests": 30, "window_seconds": 60},
    "tcmb": {"max_requests": 20, "window_seconds": 60},
    "bist": {"max_requests": 30, "window_seconds": 60},
    "matriks": {"max_requests": 30, "window_seconds": 60},
    "social": {"max_requests": 15, "window_seconds": 60},
    "news": {"max_requests": 20, "window_seconds": 60},
    "fundamental": {"max_requests": 30, "window_seconds": 60},
    "macro": {"max_requests": 20, "window_seconds": 60},
}


def create_default_rate_limiter() -> RateLimiter:
    """Varsayılan BIST limitleri ile rate limiter oluşturur.

    Returns:
        Yapılandırılmış RateLimiter örneği.
    """
    limiter = RateLimiter()
    for provider, config in BIST_RATE_LIMITS.items():
        limiter.set_limit(
            provider=provider,
            max_requests=int(config["max_requests"]),
            window_seconds=float(config["window_seconds"]),
        )
    return limiter


# Singleton
rate_limiter = create_default_rate_limiter()


__all__ = [
    "RateLimitConfig",
    "RateLimitStats",
    "RateLimiter",
    "BIST_RATE_LIMITS",
    "create_default_rate_limiter",
    "rate_limiter",
]
