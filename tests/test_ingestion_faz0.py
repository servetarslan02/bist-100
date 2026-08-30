from typing import Any

"""
ALPHA BIST — Ingestion Faz 0 Tests

Circuit Breaker, Rate Limiter, Retry Policy, Provider Manager testleri.
"""

# Import modules
import time

import pytest

from services.ingestion.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerManager,
    CircuitState,
)
from services.ingestion.provider_manager import ProviderManager
from services.ingestion.rate_limiter import RateLimiter, create_default_rate_limiter
from services.ingestion.retry_policy import (
    HTTPStatusError,
    RetryExhaustedError,
    RetryPolicy,
    get_retry_policy,
)

# =====================================================
# Circuit Breaker Tests
# =====================================================


class TestCircuitBreaker:
    """Circuit breaker testleri."""

    def test_initial_state_closed(self) -> Any:
        """Başlangıç durumu CLOSED."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self) -> Any:
        """Threshold altında kalır."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb._stats.consecutive_failures == 2

    def test_opens_at_threshold(self) -> Any:
        """Threshold'ta OPEN'a geçer."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_requests(self) -> Any:
        """OPEN iken istekleri reddeder."""
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()  # → OPEN
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self) -> Any:
        """Timeout sonra HALF_OPEN'a geçer."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_s=0.1)
        cb.record_failure()  # → OPEN
        time.sleep(0.15)  # Timeout bekle
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_limited_calls(self) -> Any:
        """HALF_OPEN'da sınırlı istek izni."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_s=0.1, half_open_max_calls=2)
        cb.record_failure()  # → OPEN
        time.sleep(0.15)
        assert cb.can_execute() is True  # 1. test
        assert cb.can_execute() is True  # 2. test
        assert cb.can_execute() is False  # 3. test → reddedildi

    def test_half_open_success_closes(self) -> Any:
        """HALF_OPEN'da başarı → CLOSED."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_s=0.1, success_threshold=2)
        cb.record_failure()  # → OPEN
        time.sleep(0.15)
        cb.record_success()  # HALF_OPEN → hâlâ HALF_OPEN
        cb.record_success()  # HALF_OPEN → CLOSED
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> Any:
        """HALF_OPEN'da hata → OPEN."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_s=0.1)
        cb.record_failure()  # → OPEN
        time.sleep(0.15)
        cb.record_failure()  # HALF_OPEN → OPEN
        assert cb.state == CircuitState.OPEN

    def test_success_resets_consecutive_failures(self) -> Any:
        """Başarı ardışık hataları sıfırlar."""
        cb = CircuitBreaker(name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._stats.consecutive_failures == 0
        assert cb._stats.consecutive_successes == 1

    def test_get_state(self) -> Any:
        """Durum bilgisi doğru."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        state = cb.get_state()
        assert state["name"] == "test"
        assert state["state"] == "CLOSED"
        assert state["failure_threshold"] == 3

    def test_reset(self) -> Any:
        """Sıfırlama çalışır."""
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._stats.total_failures == 0


@pytest.mark.asyncio
class TestCircuitBreakerAsync:
    """Async circuit breaker testleri."""

    async def test_call_success(self) -> Any:
        """Async call başarı."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def success_func() -> Any:
            """Otomatik eklendi."""
            return "ok"

        result = await cb.call(success_func)
        assert result == "ok"
        assert cb._stats.total_successes == 1

    async def test_call_failure(self) -> Any:
        """Async call hata."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def fail_func() -> Any:
            """Otomatik eklendi."""
            raise ValueError("test error")

        with pytest.raises(ValueError):
            await cb.call(fail_func)
        assert cb._stats.total_failures == 1

    async def test_call_open_raises(self) -> Any:
        """OPEN iken CircuitBreakerError fırlatır."""
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()  # → OPEN

        async def any_func() -> Any:
            """Otomatik eklendi."""
            return "ok"

        with pytest.raises(CircuitBreakerError):
            await cb.call(any_func)

    async def test_context_manager_success(self) -> Any:
        """Context manager başarı."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        async with cb.context():
            pass  # Başarılı
        assert cb._stats.total_successes == 1

    async def test_context_manager_failure(self) -> Any:
        """Context manager hata."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        with pytest.raises(ValueError):
            async with cb.context():
                raise ValueError("test")
        assert cb._stats.total_failures == 1


class TestCircuitBreakerManager:
    """Circuit breaker manager testleri."""

    def test_get_or_create(self) -> Any:
        """GetOrCreate aynı instance'ı döndürür."""
        manager = CircuitBreakerManager()
        cb1 = manager.get_or_create("test", failure_threshold=5)
        cb2 = manager.get_or_create("test", failure_threshold=10)  # Farklı config → aynı instance
        assert cb1 is cb2
        assert cb1.failure_threshold == 5  # İlk config korunur

    def test_get_all_states(self) -> Any:
        """Tüm durumları döndürür."""
        manager = CircuitBreakerManager()
        manager.get_or_create("a")
        manager.get_or_create("b")
        states = manager.get_all_states()
        assert "a" in states
        assert "b" in states


# =====================================================
# Rate Limiter Tests
# =====================================================


class TestRateLimiter:
    """Rate limiter testleri."""

    def test_no_limit_by_default(self) -> Any:
        """Limit yoksa beklemez."""
        RateLimiter()
        # Limit tanımlanmamış → acquire hemen döner
        # (asyncio.run kullanmadan sync test)

    def test_set_limit(self) -> Any:
        """Limit ayarlama."""
        limiter = RateLimiter()
        limiter.set_limit("test", max_requests=10, window_seconds=60)
        stats = limiter.get_stats("test")
        assert stats["limit"] == 10
        assert stats["window_seconds"] == 60

    def test_is_limited(self) -> Any:
        """Limit durumu kontrolü."""
        limiter = RateLimiter()
        limiter.set_limit("test", max_requests=2, window_seconds=60)
        # Henüz limit yok
        assert limiter.is_limited("test") is False


@pytest.mark.asyncio
class TestRateLimiterAsync:
    """Async rate limiter testleri."""

    async def test_acquire_within_limit(self) -> Any:
        """Limit içinde beklemez."""
        limiter = RateLimiter()
        limiter.set_limit("test", max_requests=10, window_seconds=60)
        wait = await limiter.acquire("test")
        assert wait == 0.0

    async def test_acquire_at_limit(self) -> Any:
        """Limit aşılırsa bekler."""
        limiter = RateLimiter()
        limiter.set_limit("test", max_requests=2, window_seconds=1.0)

        # İlk 2 istek → beklemez
        await limiter.acquire("test")
        await limiter.acquire("test")

        # 3. istek → bekler
        start = time.time()
        await limiter.acquire("test")
        elapsed = time.time() - start
        assert elapsed >= 0.5  # En az 0.5 saniye beklemeli

    async def test_context_manager(self) -> Any:
        """Context manager çalışır."""
        limiter = RateLimiter()
        limiter.set_limit("test", max_requests=10, window_seconds=60)
        async with limiter.acquire_context("test"):
            pass  # Başarılı


class TestDefaultRateLimiter:
    """Varsayılan BIST limitleri testleri."""

    def test_create_default(self) -> Any:
        """Varsayılan limiter oluşur."""
        limiter = create_default_rate_limiter()
        stats = limiter.get_all_stats()
        assert "yfinance" in stats
        assert "kap" in stats
        assert stats["yfinance"]["limit"] == 60


# =====================================================
# Retry Policy Tests
# =====================================================


class TestRetryPolicy:
    """Retry policy testleri."""

    def test_default_config(self) -> Any:
        """Varsayılan config."""
        policy = RetryPolicy(max_attempts=3, base_delay_s=1.0)
        assert policy.config.max_attempts == 3
        assert policy.config.base_delay_s == 1.0

    def test_calculate_delay(self) -> Any:
        """Gecikme hesaplama."""
        policy = RetryPolicy(base_delay_s=1.0, backoff_factor=2.0, jitter=False)
        assert policy._calculate_delay(1) == 1.0  # 1s
        assert policy._calculate_delay(2) == 2.0  # 2s
        assert policy._calculate_delay(3) == 4.0  # 4s

    def test_calculate_delay_with_max(self) -> Any:
        """Max delay sınırı."""
        policy = RetryPolicy(base_delay_s=1.0, backoff_factor=2.0, max_delay_s=5.0, jitter=False)
        assert policy._calculate_delay(4) == 5.0  # 8s → 5s (max)

    def test_calculate_delay_with_jitter(self) -> Any:
        """Jitter ile gecikme."""
        policy = RetryPolicy(base_delay_s=1.0, backoff_factor=2.0, jitter=True, jitter_range=0.2)
        delays = [policy._calculate_delay(1) for _ in range(100)]
        # Jitter nedeniyle farklı değerler olmalı
        assert len(set(delays)) > 1
        # Hepsi 0.8-1.2 aralığında olmalı
        assert all(0.8 <= d <= 1.2 for d in delays)

    def test_is_retryable_timeout(self) -> Any:
        """Timeout retry yapılabilir."""
        policy = RetryPolicy()
        assert policy._is_retryable(TimeoutError()) is True
        assert policy._is_retryable(TimeoutError()) is True

    def test_is_retryable_connection(self) -> Any:
        """ConnectionError retry yapılabilir."""
        policy = RetryPolicy()
        assert policy._is_retryable(ConnectionError()) is True

    def test_is_retryable_http_429(self) -> Any:
        """HTTP 429 retry yapılabilir."""
        policy = RetryPolicy()
        assert policy._is_retryable(HTTPStatusError(429, "Rate limited")) is True

    def test_is_retryable_http_500(self) -> Any:
        """HTTP 500 retry yapılabilir."""
        policy = RetryPolicy()
        assert policy._is_retryable(HTTPStatusError(500, "Server error")) is True

    def test_not_retryable_http_400(self) -> Any:
        """HTTP 400 retry yapılamaz."""
        policy = RetryPolicy()
        assert policy._is_retryable(HTTPStatusError(400, "Bad request")) is False

    def test_not_retryable_http_404(self) -> Any:
        """HTTP 404 retry yapılamaz."""
        policy = RetryPolicy()
        assert policy._is_retryable(HTTPStatusError(404, "Not found")) is False


@pytest.mark.asyncio
class TestRetryPolicyAsync:
    """Async retry policy testleri."""

    async def test_execute_success_first_try(self) -> Any:
        """İlk denemede başarı."""
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.01)

        async def success() -> Any:
            """Otomatik eklendi."""
            return "ok"

        result = await policy.execute(success)
        assert result == "ok"
        assert policy.stats.total_successes == 1
        assert policy.stats.total_retries == 0

    async def test_execute_success_after_retry(self) -> Any:
        """Retry sonrası başarı."""
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.01, jitter=False)
        call_count = 0

        async def fail_then_succeed() -> Any:
            """Otomatik eklendi."""
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await policy.execute(fail_then_succeed)
        assert result == "ok"
        assert call_count == 3
        assert policy.stats.total_retries == 2

    async def test_execute_exhausted(self) -> Any:
        """Tüm denemeler tükenir."""
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.01, jitter=False)

        async def always_fail() -> Any:
            """Otomatik eklendi."""
            raise ConnectionError("permanent")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await policy.execute(always_fail)
        assert exc_info.value.attempts == 3

    async def test_execute_non_retryable(self) -> Any:
        """Non-retryable hata hemen fırlatılır."""
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.01)

        async def non_retryable() -> Any:
            """Otomatik eklendi."""
            raise HTTPStatusError(400, "Bad request")

        with pytest.raises(HTTPStatusError):
            await policy.execute(non_retryable)
        assert policy.stats.total_failures == 1


class TestBISTRetryPolicies:
    """BIST retry policy testleri."""

    def test_get_yfinance_policy(self) -> Any:
        """yfinance policy."""
        policy = get_retry_policy("yfinance")
        assert policy.config.max_attempts == 3

    def test_get_unknown_policy(self) -> Any:
        """Bilinmeyen provider için varsayılan."""
        policy = get_retry_policy("unknown_provider")
        assert policy.config.max_attempts == 3

    def test_all_policies_exist(self) -> Any:
        """Tüm BIST policy'leri var."""
        providers = ["yfinance", "kap", "tcmb", "bist", "matriks", "social", "news"]
        for provider in providers:
            policy = get_retry_policy(provider)
            assert policy.config.max_attempts >= 2


# =====================================================
# Provider Manager Tests
# =====================================================


@pytest.mark.asyncio
class TestProviderManager:
    """Provider manager testleri."""

    async def test_register_and_fetch(self) -> Any:
        """Kayıt ve fetch."""
        manager = ProviderManager()

        async def mock_fetch(**kwargs) -> Any:
            """Otomatik eklendi."""
            return {"price": 100}

        manager.register("market_price", "test_provider", mock_fetch, priority=0)
        result = await manager.fetch("market_price")
        assert result is not None
        assert result.data == {"price": 100}
        assert result.provider == "test_provider"

    async def test_failover(self) -> Any:
        """Failover — birinci başarısız, ikinci başarılı."""
        manager = ProviderManager()

        async def failing_fetch(**kwargs) -> Any:
            """Otomatik eklendi."""
            raise ConnectionError("down")

        async def working_fetch(**kwargs) -> Any:
            """Otomatik eklendi."""
            return {"price": 100}

        manager.register("market_price", "failing", failing_fetch, priority=0)
        manager.register("market_price", "working", working_fetch, priority=1)

        result = await manager.fetch("market_price")
        assert result is not None
        assert result.provider == "working"

    async def test_all_fail(self) -> Any:
        """Tüm provider'lar başarısız."""
        manager = ProviderManager()

        async def failing(**kwargs) -> Any:
            """Otomatik eklendi."""
            raise ConnectionError("down")

        manager.register("market_price", "a", failing, priority=0)
        manager.register("market_price", "b", failing, priority=1)

        result = await manager.fetch("market_price")
        assert result is None

    async def test_no_providers(self) -> Any:
        """Provider yok."""
        manager = ProviderManager()
        result = await manager.fetch("nonexistent")
        assert result is None

    async def test_priority_order(self) -> Any:
        """Priority sırası."""
        manager = ProviderManager()

        async def low_priority(**kwargs) -> Any:
            """Otomatik eklendi."""
            return {"source": "low"}

        async def high_priority(**kwargs) -> Any:
            """Otomatik eklendi."""
            return {"source": "high"}

        manager.register("test", "low", low_priority, priority=10)
        manager.register("test", "high", high_priority, priority=0)

        result = await manager.fetch("test")
        assert result.provider == "high"

    async def test_health_tracking(self) -> Any:
        """Sağlık takibi."""
        manager = ProviderManager()

        async def success(**kwargs) -> Any:
            """Otomatik eklendi."""
            return "ok"

        manager.register("test", "provider", success)
        await manager.fetch("test")

        health = manager.get_health()
        assert "provider" in health
        assert health["provider"]["total_successes"] == 1

    async def test_get_full_status(self) -> Any:
        """Tam durum raporu."""
        manager = ProviderManager()

        async def dummy(**kwargs) -> Any:
            """Otomatik eklendi."""
            return None

        manager.register("test", "provider", dummy)
        status = manager.get_full_status()
        assert "providers" in status
        assert "circuit_breakers" in status
        assert "rate_limiters" in status
        assert "retry_policies" in status


# =====================================================
# Run Tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
