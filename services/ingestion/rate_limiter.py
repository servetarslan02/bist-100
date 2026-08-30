from typing import Any

"""
ALPHA BIST — Rate Limiter v1.0

Sliding window rate limiter — API limit aşılmasını önler.

Token bucket'tan daha adil: her istek window içinde sayılır.
Provider bazlı limit: yfinance 60/dk, KAP 30/dk, TCMB 20/dk.

Kullanım:
    limiter = RateLimiter()
    limiter.set_limit("yfinance", max_requests=60, window_seconds=60)

    async with limiter.acquire("yfinance"):
        result = await fetch_data()
"""

import asyncio
import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class RateLimitConfig:
    """Rate limit yapılandırması."""

    max_requests: int  # Pencerede izin verilen maksimum istek
    window_seconds: float  # Pencere süresi (saniye)
    burst_size: int = 0  # Anlık patlama izni (0 = max_requests ile aynı)


@dataclass
class RateLimitStats:
    """Rate limit istatistikleri."""

    total_requests: int = 0
    total_waits: int = 0
    total_wait_seconds: float = 0.0
    total_rejected: int = 0
    current_window_requests: int = 0
    last_request_time: float | None = None


class RateLimiter:
    """
    Sliding window rate limiter.

    Her provider için ayrı limit tanımlanabilir.
    Limit aşılırsa async olarak bekler.
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._limits: dict[str, RateLimitConfig] = {}
        self._timestamps: dict[str, list[float]] = {}  # provider → [request_times]
        self._stats: dict[str, RateLimitStats] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_limit(
        self,
        provider: str,
        max_requests: int,
        window_seconds: float = 60.0,
        burst_size: int = 0,
    ) -> Any:
        """Rate limit ayarla."""
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

    def _cleanup_window(self, provider: str) -> Any:
        """Eski istekleri pencereden çıkar."""
        config = self._limits.get(provider)
        if not config:
            return

        cutoff = time.time() - config.window_seconds
        timestamps = self._timestamps.get(provider, [])
        self._timestamps[provider] = [t for t in timestamps if t > cutoff]

    def _get_wait_time(self, provider: str) -> float:
        """Bekleme süresini hesapla."""
        config = self._limits.get(provider)
        if not config:
            return 0.0

        self._cleanup_window(provider)
        timestamps = self._timestamps.get(provider, [])

        if len(timestamps) < config.max_requests:
            return 0.0

        # En eski isteğin pencereden çıkmasını bekle
        oldest = timestamps[0]
        wait_time = config.window_seconds - (time.time() - oldest)
        return max(0.0, wait_time)

    async def acquire(self, provider: str) -> float:
        """
        Rate limit kontrolü ve bekleme.

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

            # İsteği kaydet
            self._timestamps[provider].append(time.time())
            stats.current_window_requests = len(self._timestamps[provider])

            return wait_time

    class _AcquireContext:
        """async with limiter.acquire(provider): ... kullanımı için."""

        def __init__(self, limiter: "RateLimiter", provider: str):
            """Otomatik eklendi."""
            self._limiter = limiter
            self._provider = provider
            self._wait_time = 0.0

        async def __aenter__(self) -> Any:
            """Otomatik eklendi."""
            self._wait_time = await self._limiter.acquire(self._provider)
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> Any:
            """Otomatik eklendi."""
            return False

    def acquire_context(self, provider: str) -> "RateLimiter._AcquireContext":
        """Context manager kullanımı için."""
        return self._AcquireContext(self, provider)

    def get_stats(self, provider: str) -> dict:
        """Provider istatistikleri."""
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

    def get_all_stats(self) -> dict:
        """Tüm provider istatistikleri."""
        return {provider: self.get_stats(provider) for provider in self._limits}

    def is_limited(self, provider: str) -> bool:
        """Provider şu an limitli mi?"""
        return self._get_wait_time(provider) > 0


# BIST'e özgü varsayılan limitler
BIST_RATE_LIMITS = {
    "yfinance": {"max_requests": 60, "window_seconds": 60},  # 60 istek/dakika
    "kap": {"max_requests": 30, "window_seconds": 60},  # 30 istek/dakika
    "tcmb": {"max_requests": 20, "window_seconds": 60},  # 20 istek/dakika
    "bist": {"max_requests": 30, "window_seconds": 60},  # 30 istek/dakika
    "matriks": {"max_requests": 30, "window_seconds": 60},  # 30 istek/dakika
    "social": {"max_requests": 15, "window_seconds": 60},  # 15 istek/dakika
    "news": {"max_requests": 20, "window_seconds": 60},  # 20 istek/dakika
    "fundamental": {"max_requests": 30, "window_seconds": 60},  # 30 istek/dakika
    "macro": {"max_requests": 20, "window_seconds": 60},  # 20 istek/dakika
}


def create_default_rate_limiter() -> RateLimiter:
    """Varsayılan BIST limitleri ile rate limiter oluştur."""
    limiter = RateLimiter()
    for provider, config in BIST_RATE_LIMITS.items():
        limiter.set_limit(
            provider=provider,
            max_requests=config["max_requests"],
            window_seconds=config["window_seconds"],
        )
    return limiter


# Singleton
rate_limiter = create_default_rate_limiter()
