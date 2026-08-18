"""
ALPHA BIST — Ingestion Service

Data ingestion pipeline: veri çekme, doğrulama, düzeltme, publish.
"""

# Core resilience
from .circuit_breaker import CircuitBreaker, CircuitBreakerManager, CircuitBreakerError, circuit_breaker_manager
from .rate_limiter import RateLimiter, rate_limiter, create_default_rate_limiter
from .retry_policy import RetryPolicy, RetryExhaustedError, HTTPStatusError, get_retry_policy

# Provider management
from .provider_manager import ProviderManager, ProviderResult, provider_manager

# Data quality
from .reconciliation import SourceReconciler, ReconciliationResult, source_reconciler
from .point_in_time import PointInTimeValidator, pit_validator
from .deduplication import EventDeduplicator, event_deduplicator
from .incremental import IncrementalFetcher, incremental_fetcher

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerManager",
    "CircuitBreakerError",
    "circuit_breaker_manager",
    # Rate Limiter
    "RateLimiter",
    "rate_limiter",
    "create_default_rate_limiter",
    # Retry Policy
    "RetryPolicy",
    "RetryExhaustedError",
    "HTTPStatusError",
    "get_retry_policy",
    # Provider Manager
    "ProviderManager",
    "ProviderResult",
    "provider_manager",
    # Reconciliation
    "SourceReconciler",
    "ReconciliationResult",
    "source_reconciler",
    # Point-in-Time
    "PointInTimeValidator",
    "pit_validator",
    # Deduplication
    "EventDeduplicator",
    "event_deduplicator",
    # Incremental
    "IncrementalFetcher",
    "incremental_fetcher",
]
