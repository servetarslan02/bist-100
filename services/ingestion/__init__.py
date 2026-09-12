"""
ALPHA BIST — Ingestion Service v2.0

Veri çekme hattı: veri çekme, doğrulama, düzeltme ve yayınlama.
Tüm dayanıklılık (resilience) katmanları ile korumalı.

Kullanım:
    from services.ingestion import (
        CircuitBreaker, RateLimiter, RetryPolicy,
        ProviderManager, get_orchestrator,
    )

Raises:
    ImportError: Alt modüllerden biri eksik olduğunda.
"""

from typing import Any

# Core resilience
from .circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerManager, circuit_breaker_manager
from .deduplication import EventDeduplicator, event_deduplicator
from .incremental import IncrementalFetcher, incremental_fetcher

# Metrics
from .ingestion_metrics import IngestionMetrics, ingestion_metrics
from .point_in_time import PointInTimeValidator, pit_validator

# Provider management
from .provider_manager import ProviderManager, ProviderResult, provider_manager
from .rate_limiter import RateLimiter, create_default_rate_limiter, rate_limiter

# Data quality
from .reconciliation import ReconciliationResult, SourceReconciler, source_reconciler
from .retry_policy import HTTPStatusError, RetryExhaustedError, RetryPolicy, get_retry_policy

# Orchestrator integration — lazy import (providers need yfinance etc.)
# from .orchestrator_integration import IngestionOrchestrator, IngestionResult, PipelineReport, ingestion_orchestrator


def get_orchestrator() -> Any:
    """Gecikmeli (lazy) orchestrator yükleyici — sadece gerektiğinde import edilir.

    Returns:
        IngestionOrchestrator: Hazır orchestrator örneği.

    Raises:
        ImportError: orchestrator_integration modülü bulunamazsa.
    """
    from .orchestrator_integration import IngestionOrchestrator, ingestion_orchestrator

    return ingestion_orchestrator


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
    # Orchestrator (lazy)
    "get_orchestrator",
]
