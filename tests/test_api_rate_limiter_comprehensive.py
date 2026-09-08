"""Comprehensive unit tests for services.api.rate_limiter."""

from __future__ import annotations

import time

import pytest

from services.api.rate_limiter import (
    RATE_LIMITS,
    InMemoryRateLimiter,
    RateLimitConfig,
    rate_limiter,
)


def test_rate_limit_config():
    """Verify RateLimitConfig dataclass repr and default table."""
    cfg = RateLimitConfig(max_requests=100, window_seconds=60)
    assert repr(cfg) == "RateLimitConfig(max_requests=100, window_seconds=60)"

    assert "default" in RATE_LIMITS
    assert "backtest" in RATE_LIMITS
    assert "scanner" in RATE_LIMITS
    assert "websocket" in RATE_LIMITS
    assert "auth" in RATE_LIMITS


def test_get_endpoint_group():
    """Verify endpoint path classification."""
    limiter = InMemoryRateLimiter()

    assert limiter.get_endpoint_group("/api/v1/backtest/run", "POST") == "backtest"
    assert limiter.get_endpoint_group("/api/v1/scanner/status", "GET") == "scanner"
    assert limiter.get_endpoint_group("/api/v1/scan", "POST") == "scanner"
    assert limiter.get_endpoint_group("/api/v1/agents/evaluate", "POST") == "analysis"
    assert limiter.get_endpoint_group("/api/v1/intelligence/sentiment", "GET") == "analysis"
    assert limiter.get_endpoint_group("/ws/market", "GET") == "websocket"
    assert limiter.get_endpoint_group("/api/v1/auth/login", "POST") == "auth"
    assert limiter.get_endpoint_group("/api/v1/token", "POST") == "auth"
    assert limiter.get_endpoint_group("/api/v1/market/prices", "GET") == "default"


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_check_allowed_and_blocked():
    """Verify check() behavior when requests exceed token bucket limit."""
    limiter = InMemoryRateLimiter()

    # Create small mock config
    RATE_LIMITS["test_group"] = RateLimitConfig(max_requests=2, window_seconds=10)

    try:
        # Request 1: Allowed
        allowed_1, info_1 = await limiter.check(client_id="127.0.0.1", group="test_group")
        assert allowed_1 is True
        assert info_1["remaining"] == 1
        assert info_1["limit"] == 2

        # Request 2: Allowed
        allowed_2, info_2 = await limiter.check(client_id="127.0.0.1", group="test_group")
        assert allowed_2 is True
        assert info_2["remaining"] == 0

        # Request 3: Exceeded / Blocked
        allowed_3, info_3 = await limiter.check(client_id="127.0.0.1", group="test_group")
        assert allowed_3 is False
        assert info_3["remaining"] == 0
        assert "retry_after" in info_3
        assert info_3["retry_after"] > 0
    finally:
        RATE_LIMITS.pop("test_group", None)


@pytest.mark.asyncio
async def test_reset_and_cleanup_stale():
    """Verify bucket reset and stale bucket cleanup."""
    limiter = InMemoryRateLimiter()

    client_id = "test_client_reset"
    await limiter.check(client_id=client_id, group="default")
    key = f"{client_id}:default"
    assert key in limiter._buckets

    # Reset
    limiter.reset(client_id=client_id, group="default")
    assert key not in limiter._buckets

    # Cleanup stale
    await limiter.check(client_id="stale_client", group="default")
    stale_key = "stale_client:default"
    limiter._buckets[stale_key]["last_refill"] = time.monotonic() - 4000

    limiter.cleanup_stale(max_age_seconds=3600)
    assert stale_key not in limiter._buckets


def test_singleton_rate_limiter():
    """Verify singleton instance."""
    assert rate_limiter is not None
    assert isinstance(rate_limiter, InMemoryRateLimiter)
