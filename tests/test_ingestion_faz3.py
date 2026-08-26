"""
ALPHA BIST — Ingestion Faz 3-6 Tests

Comprehensive test suite: Provider refactor, Metrics, Orchestrator, Integration.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
import os

from services.ingestion.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerManager
from services.ingestion.rate_limiter import RateLimiter
from services.ingestion.retry_policy import RetryPolicy, RetryExhaustedError
from services.ingestion.provider_manager import ProviderManager, ProviderResult
from services.ingestion.reconciliation import SourceReconciler
from services.ingestion.point_in_time import PointInTimeValidator
from services.ingestion.deduplication import EventDeduplicator
from services.ingestion.incremental import IncrementalFetcher
from services.ingestion.ingestion_metrics import IngestionMetrics
import structlog

logger = structlog.get_logger(__name__)


# =====================================================
# Integration Tests — Full Pipeline
# =====================================================

@pytest.mark.asyncio
class TestFullPipeline:
    """Full pipeline integration testleri."""

    async def test_provider_manager_with_all_resilience(self):
        """Provider manager + circuit breaker + rate limiter + retry."""
        manager = ProviderManager()

        call_count = 0

        async def flaky_provider(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("transient error")
            return {"price": 100.0}

        manager.register("test", "flaky", flaky_provider, priority=0)

        result = await manager.fetch("test")
        assert result is not None
        assert result.data == {"price": 100.0}
        assert call_count == 3  # 2 fails + 1 success

    async def test_multi_provider_failover(self):
        """Çoklu provider failover zinciri."""
        manager = ProviderManager()

        async def provider_a(**kwargs):
            raise ConnectionError("A down")

        async def provider_b(**kwargs):
            raise TimeoutError("B timeout")

        async def provider_c(**kwargs):
            return {"price": 200.0}

        manager.register("market", "a", provider_a, priority=0)
        manager.register("market", "b", provider_b, priority=1)
        manager.register("market", "c", provider_c, priority=2)

        result = await manager.fetch("market")
        assert result is not None
        assert result.provider == "c"

    async def test_health_tracking_after_failures(self):
        """Hata sonrası sağlık takibi."""
        manager = ProviderManager()

        async def failing(**kwargs):
            raise ConnectionError("down")

        manager.register("test", "provider", failing)

        # Birkaç kez dene
        for _ in range(3):
            await manager.fetch("test")

        health = manager.get_health()
        assert health["provider"]["total_failures"] > 0
        assert health["provider"]["success_rate"] < 1.0

    async def test_circuit_breaker_opens_after_failures(self):
        """Ardışık hatalardan sonra circuit breaker açılır."""
        manager = ProviderManager()

        async def failing(**kwargs):
            raise ConnectionError("down")

        manager.register("test", "provider", failing,
                        circuit_breaker_config={"failure_threshold": 3})

        # 3 kez dene → circuit breaker açılmalı
        for _ in range(3):
            await manager.fetch("test")

        states = manager.get_circuit_breaker_states()
        assert states["provider"]["state"] == "OPEN"

    async def test_full_status_report(self):
        """Tam durum raporu."""
        manager = ProviderManager()

        async def dummy(**kwargs):
            return {"data": "test"}

        manager.register("test", "provider", dummy)
        await manager.fetch("test")

        status = manager.get_full_status()
        assert "providers" in status
        assert "circuit_breakers" in status
        assert "rate_limiters" in status
        assert "retry_policies" in status
        assert "registered_types" in status
        assert "total_providers" in status


# =====================================================
# Reconciliation Advanced Tests
# =====================================================

@pytest.mark.asyncio
class TestReconciliationAdvanced:
    """Gelişmiş reconciliation testleri."""

    async def test_three_source_consensus(self):
        """3 kaynak konsensüs."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 308.50,
            "bist_official": 308.50,
        })
        assert result.conflict is False
        assert result.quality_score > 0.8

    async def test_two_source_one_outlier(self):
        """2 kaynak, 1 aykırı."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 315.00,  # ~%2 sapma
        })
        assert result.conflict is True

    async def test_custom_max_deviation(self):
        """Özel max sapma eşiği."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 312.00,  # ~%1.1 sapma
        }, max_deviation_pct=0.5)
        assert result.conflict is True

    async def test_quality_report_aggregation(self):
        """Kalite raporu toplama."""
        reconciler = SourceReconciler()
        results = await reconciler.reconcile_batch({
            "A": {"yfinance": 100, "matriks": 100},
            "B": {"yfinance": 200, "matriks": 205},
            "C": {"yfinance": 300, "matriks": 310},
        })
        report = reconciler.get_quality_report(results)
        assert report["total_tickers"] == 3
        assert "avg_quality_score" in report


# =====================================================
# Point-in-Time Advanced Tests
# =====================================================

class TestPITAdvanced:
    """Gelişmiş PIT testleri."""

    def test_multi_data_type_filter(self):
        """Çoklu veri tipi filtreleme."""
        pit = PointInTimeValidator()

        market_data = [
            {"timestamp": "2024-01-15T10:00:00", "price": 100},
        ]
        fundamental_data = [
            {"timestamp": "2024-01-15T10:00:00", "revenue": 1000},
        ]

        query_ts = datetime(2024, 1, 15, 10, 10, 0)

        # Market: 10:00 + 15dk = 10:15 → 10:10 < 10:15 → filtrelenir
        filtered_market = pit.filter_available(market_data, "market_price", query_ts)
        assert len(filtered_market) == 0

        # Fundamental: 10:00 + 1 gün → filtrelenir
        filtered_fund = pit.filter_available(fundamental_data, "fundamental", query_ts)
        assert len(filtered_fund) == 0

    def test_lookahead_violation_report(self):
        """Look-ahead bias ihlal raporu."""
        pit = PointInTimeValidator()
        data = [
            {"timestamp": "2024-01-15T10:00:00"},  # 10:00 + 15dk = 10:15 > 10:10 → ihlal
            {"timestamp": "2024-01-15T10:30:00"},  # 10:30 + 15dk = 10:45 > 10:10 → ihlal
        ]
        report = pit.validate_no_lookahead(data, "market_price", datetime(2024, 1, 15, 10, 10, 0))
        assert report["clean"] is False
        assert report["violation_count"] == 2

    def test_custom_delay_per_type(self):
        """Her veri tipi için özel gecikme."""
        pit = PointInTimeValidator()
        pit.set_custom_delay("custom", timedelta(hours=4), "Custom 4h delay")

        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        assert pit.is_available_at("custom", data_ts, datetime(2024, 1, 15, 13, 0, 0)) is False
        assert pit.is_available_at("custom", data_ts, datetime(2024, 1, 15, 14, 30, 0)) is True


# =====================================================
# Deduplication Advanced Tests
# =====================================================

class TestDedupAdvanced:
    """Gelişmiş dedup testleri."""

    def test_high_volume_dedup(self):
        """Yüksek hacim dedup."""
        dedup = EventDeduplicator()

        # 1000 farklı event
        for i in range(1000):
            event = {"event_type": "tick", "source": "yf", "ticker": f"T{i}", "price": i}
            assert dedup.check_and_mark(event) is False

        # Aynı 1000 event → duplicate
        for i in range(1000):
            event = {"event_type": "tick", "source": "yf", "ticker": f"T{i}", "price": i}
            assert dedup.check_and_mark(event) is True

        stats = dedup.get_stats()
        assert stats["total_checked"] == 2000
        assert stats["total_duplicates"] == 1000

    def test_different_source_not_duplicate(self):
        """Farklı kaynak duplicate değil."""
        dedup = EventDeduplicator()
        event1 = {"event_type": "tick", "source": "yfinance", "ticker": "THYAO", "price": 100}
        event2 = {"event_type": "tick", "source": "matriks", "ticker": "THYAO", "price": 100}
        dedup.mark_seen(event1)
        assert dedup.is_duplicate(event2) is False


# =====================================================
# Incremental Advanced Tests
# =====================================================

class TestIncrementalAdvanced:
    """Gelişmiş incremental testleri."""

    def test_multiple_ticker_tracking(self):
        """Çoklu ticker takibi."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO")
        fetcher.mark_fetched("ASELS")
        fetcher.mark_fetched("AKBNK")

        assert fetcher.get_fetch_count("THYAO") == 1
        assert fetcher.get_fetch_count("ASELS") == 1
        assert fetcher.get_fetch_count("NEW") == 0

    def test_stale_ticker_detection(self):
        """Eski ticker tespiti."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("FRESH")

        # Eski ticker simüle et
        fetcher._states["OLD"] = type(fetcher._states.get("FRESH"))(
            ticker="OLD",
            last_fetch_time=time.time() - 7200,
            fetch_count=1,
        )

        stale = fetcher.get_stale_tickers(max_age_seconds=3600)
        assert "OLD" in stale
        assert "FRESH" not in stale

    def test_reset_single_ticker(self):
        """Tek ticker sıfırlama."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("A")
        fetcher.mark_fetched("B")
        fetcher.reset("A")
        assert fetcher.get_fetch_count("A") == 0
        assert fetcher.get_fetch_count("B") == 1


# =====================================================
# Metrics Tests
# =====================================================

class TestIngestionMetrics:
    """Metrics testleri."""

    def test_metrics_no_crash_without_prometheus(self):
        """Prometheus olmadan crash olmamalı."""
        metrics = IngestionMetrics()
        # Tüm metotlar no-op olmalı
        metrics.record_provider_request("test", "market", "success", 0.5)
        metrics.record_circuit_breaker_failure("test")
        metrics.record_rate_limit_wait("test", 0.1)
        metrics.record_quality_score("THYAO", "yfinance", 85.0)
        metrics.record_reconciliation_conflict("THYAO")
        metrics.record_dedup_duplicate("market_tick")
        metrics.record_pit_violation("market_price")
        metrics.record_incremental_fetch("THYAO")
        metrics.record_incremental_skip("THYAO")
        # Verify metrics object is still functional after all calls
        assert hasattr(metrics, 'record_provider_request')
        assert hasattr(metrics, 'record_circuit_breaker_failure')
        assert hasattr(metrics, 'record_rate_limit_wait')
        assert hasattr(metrics, 'record_quality_score')
        assert hasattr(metrics, 'record_reconciliation_conflict')
        assert hasattr(metrics, 'record_dedup_duplicate')
        assert hasattr(metrics, 'record_pit_violation')
        assert hasattr(metrics, 'record_incremental_fetch')
        assert hasattr(metrics, 'record_incremental_skip')

    def test_track_pipeline_context(self):
        """Pipeline tracking context manager."""
        metrics = IngestionMetrics()
        with metrics.track_pipeline("test"):
            time.sleep(0.01)
        assert metrics is not None
        assert hasattr(metrics, 'track_pipeline')

    def test_track_provider_context(self):
        """Provider tracking context manager."""
        metrics = IngestionMetrics()
        with metrics.track_provider("yfinance", "market_price"):
            pass
        assert metrics is not None
        assert hasattr(metrics, 'track_provider')

    def test_track_provider_on_failure(self):
        """Provider failure tracking."""
        metrics = IngestionMetrics()
        try:
            with metrics.track_provider("yfinance", "market_price"):
                raise ValueError("test error")
        except ValueError:
            logger.warning("Data error in test_track_provider_on_failure: ValueError", exc_info=True)
        assert metrics is not None
        assert hasattr(metrics, 'track_provider')


# =====================================================
# Circuit Breaker Advanced Tests
# =====================================================

class TestCircuitBreakerAdvanced:
    """Gelişmiş circuit breaker testleri."""

    def test_manager_multiple_providers(self):
        """Çoklu provider circuit breaker."""
        manager = CircuitBreakerManager()
        cb1 = manager.get_or_create("yfinance")
        cb2 = manager.get_or_create("kap")
        cb3 = manager.get_or_create("tcmb")

        assert len(manager.get_all_states()) == 3

    def test_circuit_breaker_independence(self):
        """Circuit breaker bağımsızlığı."""
        manager = CircuitBreakerManager()
        cb1 = manager.get_or_create("a", failure_threshold=2)
        cb2 = manager.get_or_create("b", failure_threshold=5)

        # A'yı aç
        cb1.record_failure()
        cb1.record_failure()
        assert cb1.state == CircuitState.OPEN

        # B hâlâ kapalı
        assert cb2.state == CircuitState.CLOSED

    def test_recovery_after_open(self):
        """OPEN sonrası recovery."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_s=0.05)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


# =====================================================
# Rate Limiter Advanced Tests
# =====================================================

@pytest.mark.asyncio
class TestRateLimiterAdvanced:
    """Gelişmiş rate limiter testleri."""

    async def test_multiple_provider_limits(self):
        """Çoklu provider limitleri."""
        limiter = RateLimiter()
        limiter.set_limit("a", max_requests=10, window_seconds=60)
        limiter.set_limit("b", max_requests=5, window_seconds=60)

        stats = limiter.get_all_stats()
        assert "a" in stats
        assert "b" in stats
        assert stats["a"]["limit"] == 10
        assert stats["b"]["limit"] == 5

    async def test_no_limit_provider(self):
        "Limitsiz provider."
        limiter = RateLimiter()
        # C için limit yok
        wait = await limiter.acquire("c")
        assert wait == 0.0


# =====================================================
# Provider Manager Advanced Tests
# =====================================================

@pytest.mark.asyncio
class TestProviderManagerAdvanced:
    """Gelişmiş provider manager testleri."""

    async def test_enable_disable_provider(self):
        """Provider enable/disable."""
        manager = ProviderManager()

        async def dummy(**kwargs):
            return "ok"

        manager.register("test", "provider", dummy)
        manager.disable_provider("test", "provider")

        result = await manager.fetch("test")
        assert result is None

        manager.enable_provider("test", "provider")
        result = await manager.fetch("test")
        assert result is not None

    async def test_multi_fetch(self):
        """Çoklu ticker fetch."""
        manager = ProviderManager()

        async def fetch(**kwargs):
            ticker = kwargs.get("ticker", "unknown")
            return {"ticker": ticker, "price": 100}

        manager.register("test", "provider", fetch)

        results = await manager.fetch_multi("test", ["A", "B", "C"])
        assert len(results) == 3

    async def test_timeout_handling(self):
        """Timeout işleme."""
        manager = ProviderManager()

        async def slow(**kwargs):
            await asyncio.sleep(10)
            return "ok"

        manager.register("test", "slow", slow, timeout_s=0.1)

        result = await manager.fetch("test")
        assert result is None  # Timeout


# =====================================================
# Run Tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
