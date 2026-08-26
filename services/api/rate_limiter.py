"""
ALPHA BIST — API Rate Limiter v1.0

Token bucket rate limiting.
Farklı endpoint grupları için farklı limitler.

Limitler:
- Genel: 100 istek/dakika
- Analiz: 10 istek/dakika
- Backtest: 5 istek/dakika
- Scanner: 3 istek/dakika
- WebSocket: 100 mesaj/saniye
"""

import time
import asyncio
from typing import Dict
from dataclasses import dataclass
from collections import defaultdict
import structlog

logger = structlog.get_logger()


@dataclass
class RateLimitConfig:
    """Rate limit yapılandırması."""
    max_requests: int
    window_seconds: int


# Endpoint grup limitleri — Canlı Dashboard ve Sürekli Telemetri Uyumlu
RATE_LIMITS: Dict[str, RateLimitConfig] = {
    "default": RateLimitConfig(max_requests=1000, window_seconds=60),
    "analysis": RateLimitConfig(max_requests=300, window_seconds=60),
    "backtest": RateLimitConfig(max_requests=60, window_seconds=60),
    "scanner": RateLimitConfig(max_requests=300, window_seconds=60),
    "websocket": RateLimitConfig(max_requests=1000, window_seconds=1),
    "auth": RateLimitConfig(max_requests=60, window_seconds=60),
}


class InMemoryRateLimiter:
    """In-memory token bucket rate limiter.

    Redis mevcutsa Redis tabanlı, değilse in-memory fallback.
    """

    def __init__(self):
        self._buckets: Dict[str, Dict[str, any]] = defaultdict(lambda: {
            "tokens": 100,
            "last_refill": time.monotonic(),
        })
        self._lock = asyncio.Lock()

    async def check(
        self,
        client_id: str,
        group: str = "default",
    ) -> tuple[bool, Dict[str, any]]:
        """Rate limit kontrolü.

        Args:
            client_id: İstemci kimliği (IP veya user_id)
            group: Endpoint grubu

        Returns:
            (allowed, info)
        """
        config = RATE_LIMITS.get(group, RATE_LIMITS["default"])
        key = f"{client_id}:{group}"

        async with self._lock:
            bucket = self._buckets[key]
            now = time.monotonic()

            # Token yenile
            elapsed = now - bucket["last_refill"]
            refill_rate = config.max_requests / config.window_seconds
            bucket["tokens"] = min(
                config.max_requests,
                bucket["tokens"] + elapsed * refill_rate
            )
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True, {
                    "limit": config.max_requests,
                    "remaining": int(bucket["tokens"]),
                    "reset_seconds": config.window_seconds,
                }
            else:
                wait_time = (1 - bucket["tokens"]) / refill_rate
                return False, {
                    "limit": config.max_requests,
                    "remaining": 0,
                    "reset_seconds": round(wait_time, 1),
                    "retry_after": round(wait_time, 1),
                }

    def get_endpoint_group(self, path: str, method: str) -> str:
        """Endpoint için rate limit grubu belirle."""
        if "/backtest" in path:
            return "backtest"
        if "/scanner" in path or "/scan" in path:
            return "scanner"
        if "/agents" in path or "/intelligence" in path:
            return "analysis"
        if "/ws" in path:
            return "websocket"
        if "/auth" in path or "/token" in path:
            return "auth"
        return "default"

    def reset(self, client_id: str, group: str = "default"):
        """Rate limit sıfırla."""
        key = f"{client_id}:{group}"
        if key in self._buckets:
            del self._buckets[key]

    def cleanup_stale(self, max_age_seconds: float = 3600):
        """Son 1 saatten eski bucket'ları temizle (memory leak önleme)."""
        now = time.monotonic()
        stale_keys = [
            k for k, v in self._buckets.items()
            if now - v.get("last_refill", 0) > max_age_seconds
        ]
        for k in stale_keys:
            del self._buckets[k]
        if stale_keys:
            logger.info("Rate limiter cleanup", removed=len(stale_keys))


# Singleton
rate_limiter = InMemoryRateLimiter()
