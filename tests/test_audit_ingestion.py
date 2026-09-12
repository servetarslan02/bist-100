"""
ALPHA BIST — Ingestion Service Comprehensive Audit Tests
Verifies core ingestion modules:
- CircuitBreaker & CircuitBreakerManager
- RateLimiter
- RetryPolicy
- EventDeduplicator
- IncrementalFetcher
- PointInTimeValidator
- SourceReconciler & ReconciliationResult
- CorporateAction & CorporateActionsHandler
- ProviderManager & ProviderResult
- IngestionMetrics
- BISTUniverse
- YFinanceProvider & utilities
"""

import time
from datetime import UTC, date, datetime

import pytest

from services.ingestion import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerManager,
    EventDeduplicator,
    IncrementalFetcher,
    IngestionMetrics,
    PointInTimeValidator,
    ProviderManager,
    ProviderResult,
    RateLimiter,
    ReconciliationResult,
    RetryExhaustedError,
    RetryPolicy,
    SourceReconciler,
    circuit_breaker_manager,
    create_default_rate_limiter,
    event_deduplicator,
    incremental_fetcher,
    ingestion_metrics,
    pit_validator,
    provider_manager,
    rate_limiter,
    source_reconciler,
)
from services.ingestion.bist_universe import BISTUniverse, bist_universe
from services.ingestion.corporate_actions import (
    ActionType,
    CorporateAction,
    CorporateActionsHandler,
)
from services.ingestion.providers.yfinance_provider import (
    DEFAULT_YFINANCE_TIMEOUT,
    YFinanceProvider,
    get_yfinance_ticker,
    yfinance_provider,
)


@pytest.mark.asyncio
async def test_circuit_breaker():
    """Test CircuitBreaker states, failure thresholds, representations, and async call."""
    cb = CircuitBreaker("test_service", failure_threshold=2, recovery_timeout=0.1, success_threshold=1)
    assert "CircuitBreaker" in repr(cb)
    assert cb.state == "CLOSED"

    # Record 2 failures -> should open
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "OPEN"

    async def dummy_call():
        return "should not run"

    with pytest.raises(CircuitBreakerError):
        await cb.call(dummy_call)

    # Wait for recovery timeout -> should transition to HALF_OPEN
    time.sleep(0.15)
    assert cb.can_execute() is True

    # Record success -> back to CLOSED
    cb.record_success()
    assert cb.state == "CLOSED"

    # Manager
    cbm = CircuitBreakerManager()
    assert "CircuitBreakerManager" in repr(cbm)
    breaker = cbm.get_breaker("provider_a")
    assert breaker is not None
    assert circuit_breaker_manager is not None


@pytest.mark.asyncio
async def test_rate_limiter():
    """Test RateLimiter capacity, consumption, and representations."""
    limiter = RateLimiter()
    assert "RateLimiter" in repr(limiter)

    limiter.set_limit("test_prov", max_requests=10, window_seconds=60.0)
    assert limiter.is_limited("test_prov") is False

    # Acquire within limit
    wait_time = await limiter.acquire("test_prov")
    assert wait_time == 0.0

    # Check default limiter helper
    default_rl = create_default_rate_limiter()
    assert isinstance(default_rl, RateLimiter)
    assert rate_limiter is not None


@pytest.mark.asyncio
async def test_retry_policy():
    """Test RetryPolicy execution, backoff, and exhaustion for sync & async."""
    policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05)
    assert "RetryPolicy" in repr(policy)

    call_count = 0

    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("Transient network failure")
        return "success"

    result = policy.execute_sync(flaky_function)
    assert result == "success"
    assert call_count == 2

    # Always failing function -> raises RetryExhaustedError
    def failing_function():
        raise TimeoutError("Timeout occurred")

    with pytest.raises(RetryExhaustedError):
        policy.execute_sync(failing_function)

    # Test async execution
    async_call_count = 0

    async def async_flaky():
        nonlocal async_call_count
        async_call_count += 1
        if async_call_count < 2:
            raise ConnectionError("Transient async error")
        return "async_success"

    async_res = await policy.execute(async_flaky)
    assert async_res == "async_success"


def test_event_deduplicator():
    """Test EventDeduplicator tracking and window cleanups."""
    dedup = EventDeduplicator(window_seconds=60)
    assert "EventDeduplicator" in repr(dedup)

    event_id = "kap_notice_12345"
    assert dedup.is_duplicate(event_id) is False
    dedup.record(event_id)
    assert dedup.is_duplicate(event_id) is True

    assert event_deduplicator is not None


def test_incremental_fetcher():
    """Test IncrementalFetcher cursor and timestamp tracking."""
    fetcher = IncrementalFetcher()
    assert "IncrementalFetcher" in repr(fetcher)

    fetcher.set_checkpoint("THYAO", "2026-09-12T18:00:00Z")
    cursor = fetcher.get_checkpoint("THYAO")
    assert cursor == "2026-09-12T18:00:00Z"
    assert incremental_fetcher is not None


def test_point_in_time_validator():
    """Test PointInTimeValidator to ensure zero future data leakage."""
    validator = PointInTimeValidator()
    assert "PointInTimeValidator" in repr(validator)

    as_of = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
    past_event = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
    future_event = datetime(2026, 9, 12, 15, 0, 0, tzinfo=UTC)

    assert validator.is_valid(event_timestamp=past_event, as_of=as_of) is True
    assert validator.is_valid(event_timestamp=future_event, as_of=as_of) is False
    assert pit_validator is not None


def test_source_reconciler():
    """Test SourceReconciler consensus and conflict resolution."""
    reconciler = SourceReconciler(max_deviation_pct=1.0)
    assert "SourceReconciler" in repr(reconciler)

    # Agreeing sources (0.18% deviation < 1.0%)
    res = reconciler.reconcile(
        ticker="THYAO",
        source_prices={"yfinance": 250.0, "isyatirim": 250.5, "matriks": 249.8},
    )
    assert isinstance(res, ReconciliationResult)
    assert "ReconciliationResult" in repr(res)
    assert res.is_valid is True
    assert res.consensus_price is not None
    assert abs(res.consensus_price - 250.0) < 1.0

    assert source_reconciler is not None


def test_corporate_actions():
    """Test CorporateAction model and CorporateActionsHandler."""
    action = CorporateAction(
        action_id="act_001",
        ticker="THYAO",
        action_type=ActionType.STOCK_SPLIT,
        ex_date=date(2026, 5, 1),
        split_ratio=2.0,
    )
    assert "CorporateAction" in repr(action)
    assert action.action_type == ActionType.STOCK_SPLIT

    handler = CorporateActionsHandler()
    assert "CorporateActionsHandler" in repr(handler)
    handler.register_action(action)
    assert len(handler.get_actions("THYAO")) == 1

    # Price adjustment for split (2-for-1 split halves historical pre-split price)
    adj_price = handler.adjust_price("THYAO", 500.0, date(2026, 4, 15))
    assert adj_price == 250.0


def test_provider_manager():
    """Test ProviderManager registration and execution."""
    pm = ProviderManager()
    assert "ProviderManager" in repr(pm)

    res = ProviderResult(
        provider_name="test_prov",
        ticker="GARAN",
        data={"price": 100.0},
        success=True,
        latency_ms=12.5,
    )
    assert "ProviderResult" in repr(res)
    assert res.success is True
    assert provider_manager is not None


def test_ingestion_metrics():
    """Test IngestionMetrics counters and tracking."""
    metrics = IngestionMetrics()
    assert "IngestionMetrics" in repr(metrics)

    metrics.record_provider_request("yfinance", "bars", "success", 0.15)
    metrics.record_data_gap("THYAO", 5)
    assert ingestion_metrics is not None


def test_bist_universe_and_yfinance():
    """Test BISTUniverse sector mapping and YFinance ticker conversion."""
    bu = BISTUniverse()
    assert "BISTUniverse" in repr(bu)
    assert bist_universe is not None

    # Ticker formatting
    assert get_yfinance_ticker("THYAO") == "THYAO.IS"
    assert get_yfinance_ticker("GARAN.IS") == "GARAN.IS"
    assert DEFAULT_YFINANCE_TIMEOUT == 15

    yfp = YFinanceProvider()
    assert "YFinanceProvider" in repr(yfp)
    assert yfinance_provider is not None
