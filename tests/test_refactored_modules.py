"""Tests for refactored modules — SWRCache, risk_config, otel_trace."""

import time
import threading

import pytest

from services.core.swr_cache import SWRCache
from services.core.risk_config import (
    risk_config,
    backtest_config,
    portfolio_config,
    circuit_breaker_config,
    RiskManagerConfig,
    BacktestConfig,
    PortfolioOptimizerConfig,
    CircuitBreakerConfig,
)


# =====================================================
# SWRCache Tests
# =====================================================


class TestSWRCache:
    """SWRCache thread-safe cache tests."""

    def test_basic_get_set(self) -> None:
        """Cache set ve get temel işlevi."""
        cache = SWRCache(ttl_seconds=60)
        assert cache.get() is None

        cache.set({"key": "value"})
        result = cache.get()
        assert result == {"key": "value"}

    def test_ttl_expiry(self) -> None:
        """TTL dolduğunda cache boş dönmeli."""
        cache = SWRCache(ttl_seconds=0.1)
        cache.set({"key": "value"})

        assert cache.get() is not None
        time.sleep(0.15)
        assert cache.get() is None

    def test_etag_generation(self) -> None:
        """Her set işleminde yeni ETag oluşmalı."""
        cache = SWRCache(ttl_seconds=60)

        etag1 = cache.set({"data": "v1"})
        etag2 = cache.set({"data": "v2"})

        assert etag1 != etag2
        assert cache.etag == etag2

    def test_is_fresh(self) -> None:
        """is_fresh property doğru çalışmalı."""
        cache = SWRCache(ttl_seconds=1)
        assert not cache.is_fresh

        cache.set({"data": "test"})
        assert cache.is_fresh

        time.sleep(1.1)
        assert not cache.is_fresh

    def test_invalidate(self) -> None:
        """Cache invalidation çalışmalı."""
        cache = SWRCache(ttl_seconds=60)
        cache.set({"data": "test"})
        assert cache.get() is not None

        cache.invalidate()
        assert cache.get() is None
        assert cache.etag == ""

    def test_thread_safety(self) -> None:
        """Concurrent erişimde thread safety."""
        cache = SWRCache(ttl_seconds=60)
        errors = []

        def writer(n: int) -> None:
            try:
                for i in range(100):
                    cache.set({"thread": n, "iteration": i})
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(100):
                    cache.get()
                    cache.is_fresh
                    cache.etag
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(i,)) for i in range(5)
        ] + [
            threading.Thread(target=reader) for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =====================================================
# Risk Config Tests
# =====================================================


class TestRiskConfig:
    """Risk config singleton ve default değer testleri."""

    def test_risk_config_defaults(self) -> None:
        """Risk config varsayılan değerleri doğru olmalı."""
        assert risk_config.max_position_pct == 0.10
        assert risk_config.max_sector_pct == 0.25
        assert risk_config.stop_loss_pct == 0.07
        assert risk_config.max_open_positions == 15

    def test_backtest_config_defaults(self) -> None:
        """Backtest config varsayılan değerleri."""
        assert backtest_config.base_slippage_pct == 0.05
        assert backtest_config.max_participation == 0.10
        assert backtest_config.default_commission_pct == 0.0015

    def test_portfolio_config_defaults(self) -> None:
        """Portfolio config varsayılan değerleri."""
        assert portfolio_config.max_position_pct == 0.10
        assert portfolio_config.min_position_pct == 0.015
        assert portfolio_config.max_sector_pct == 0.35

    def test_circuit_breaker_config_defaults(self) -> None:
        """Circuit breaker config varsayılan değerleri."""
        assert circuit_breaker_config.failure_threshold == 5
        assert circuit_breaker_config.recovery_timeout_seconds == 60

    def test_custom_config(self) -> None:
        """Özel config değerleri override edilebilmeli."""
        custom = RiskManagerConfig(
            max_position_pct=0.15,
            stop_loss_pct=0.10,
        )
        assert custom.max_position_pct == 0.15
        assert custom.stop_loss_pct == 0.10
        # Other defaults should be unchanged
        assert custom.max_sector_pct == 0.25


# =====================================================
# Otel Trace Import Tests
# =====================================================


class TestOtelTrace:
    """otel_trace merkezi import testleri."""

    def test_otel_trace_importable(self) -> None:
        """otel_trace merkezi modülden import edilebilmeli."""
        from services.core.otel import otel_trace

        assert callable(otel_trace)

    def test_otel_trace_decorator(self) -> None:
        """otel_trace decorator olarak çalışmalı."""
        from services.core.otel import otel_trace

        @otel_trace("test_span")
        def sample_function() -> str:
            return "ok"

        result = sample_function()
        assert result == "ok"

    def test_otel_trace_async(self) -> None:
        """otel_trace async fonksiyonlarda çalışmalı."""
        from services.core.otel import otel_trace

        @otel_trace("test_async_span")
        async def sample_async() -> str:
            return "ok"

        import asyncio
        result = asyncio.run(sample_async())
        assert result == "ok"
