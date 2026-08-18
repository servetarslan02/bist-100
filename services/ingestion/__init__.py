"""
ALPHA BIST — Ingestion Service v2.0

Data ingestion pipeline: veri çekme, doğrulama, düzeltme, publish.
Tüm resilience katmanları ile korumalı.
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

# Metrics
from .ingestion_metrics import IngestionMetrics, ingestion_metrics

# Orchestrator integration
from .orchestrator_integration import IngestionOrchestrator, IngestionResult, PipelineReport, ingestion_orchestrator

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
    # Metrics
    "IngestionMetrics",
    "ingestion_metrics",
    # Orchestrator
    "IngestionOrchestrator",
    "IngestionResult",
    "PipelineReport",
    "ingestion_orchestrator",
]
