from typing import Any
"""
ALPHA BIST — Ingestion Metrics v1.0

Prometheus metrics for ingestion pipeline monitoring.

Her provider, circuit breaker, rate limiter ve data quality için metrics.
Grafana dashboard'u bu metriklerden beslenir.
"""

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

import time
from contextlib import contextmanager

import structlog

logger = structlog.get_logger()


# =====================================================
# Prometheus Metrics Tanımları
# =====================================================

if PROMETHEUS_AVAILABLE:
    # Provider metrics
    PROVIDER_REQUESTS = Counter(
        "ingestion_provider_requests_total",
        "Toplam provider istek sayısı",
        ["provider", "data_type", "status"],
    )
    PROVIDER_LATENCY = Histogram(
        "ingestion_provider_latency_seconds",
        "Provider istek gecikmesi",
        ["provider", "data_type"],
        buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    )

    # Circuit breaker metrics
    CB_STATE = Gauge(
        "ingestion_circuit_breaker_state",
        "Circuit breaker durumu (0=closed, 1=open, 2=half_open)",
        ["provider"],
    )
    CB_FAILURES = Counter(
        "ingestion_circuit_breaker_failures_total",
        "Circuit breaker toplam hata sayısı",
        ["provider"],
    )

    # Rate limiter metrics
    RL_WAIT_SECONDS = Histogram(
        "ingestion_rate_limiter_wait_seconds",
        "Rate limiter bekleme süresi",
        ["provider"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    )
    RL_REJECTED = Counter(
        "ingestion_rate_limiter_rejected_total",
        "Rate limiter reddedilen istek sayısı",
        ["provider"],
    )

    # Data quality metrics
    DQ_SCORE = Histogram(
        "ingestion_data_quality_score",
        "Veri kalite skoru dağılımı",
        ["ticker", "source"],
        buckets=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    )
    DQ_RECONCILIATION_CONFLICTS = Counter(
        "ingestion_reconciliation_conflicts_total",
        "Toplam kaynak çelişkisi sayısı",
        ["ticker"],
    )

    # Dedup metrics
    DEDUP_DUPLICATES = Counter(
        "ingestion_dedup_duplicates_total",
        "Filtrelenen tekrar event sayısı",
        ["event_type"],
    )

    # Pipeline metrics
    PIPELINE_DURATION = Histogram(
        "ingestion_pipeline_duration_seconds",
        "Pipeline çalışma süresi",
        ["pipeline_type"],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600],
    )
    PIPELINE_EVENTS = Counter(
        "ingestion_pipeline_events_total",
        "Pipeline'den geçen event sayısı",
        ["event_type", "source"],
    )

    # PIT metrics
    PIT_VIOLATIONS = Counter(
        "ingestion_pit_violations_total",
        "Look-ahead bias ihlali sayısı",
        ["data_type"],
    )

    # Incremental metrics
    INC_FETCHES = Counter(
        "ingestion_incremental_fetches_total",
        "Incremental fetch sayısı",
        ["ticker"],
    )
    INC_SKIPS = Counter(
        "ingestion_incremental_skips_total",
        "Atlanan fetch sayısı",
        ["ticker"],
    )


# =====================================================
# Metrics Collector
# =====================================================


class IngestionMetrics:
    """Ingestion metrics toplayıcı.

    Prometheus mevcut değilse no-op çalışır.
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._enabled = PROMETHEUS_AVAILABLE
        if not self._enabled:
            logger.info("Prometheus not available, metrics disabled")

    # Provider metrics
    def record_provider_request(self, provider: str, data_type: str, status: str, latency_s: float) -> Any:
        """Provider istek kaydı."""
        if not self._enabled:
            return
        PROVIDER_REQUESTS.labels(provider=provider, data_type=data_type, status=status).inc()
        PROVIDER_LATENCY.labels(provider=provider, data_type=data_type).observe(latency_s)

    @contextmanager
    def track_provider(self, provider: str, data_type: str) -> Any:
        """Provider istek takip context manager."""
        start = time.time()
        status = "success"
        try:
            yield
        except Exception:
            status = "failure"
            raise
        finally:
            latency = time.time() - start
            self.record_provider_request(provider, data_type, status, latency)

    # Circuit breaker metrics
    def update_circuit_breaker_state(self, provider: str, state: str) -> Any:
        """Circuit breaker durumu güncelle."""
        if not self._enabled:
            return
        state_value = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}.get(state, 0)
        CB_STATE.labels(provider=provider).set(state_value)

    def record_circuit_breaker_failure(self, provider: str) -> Any:
        """Circuit breaker hata kaydı."""
        if not self._enabled:
            return
        CB_FAILURES.labels(provider=provider).inc()

    # Rate limiter metrics
    def record_rate_limit_wait(self, provider: str, wait_seconds: float) -> Any:
        """Rate limiter bekleme kaydı."""
        if not self._enabled:
            return
        RL_WAIT_SECONDS.labels(provider=provider).observe(wait_seconds)

    def record_rate_limit_rejected(self, provider: str) -> Any:
        """Rate limiter red kaydı."""
        if not self._enabled:
            return
        RL_REJECTED.labels(provider=provider).inc()

    # Data quality metrics
    def record_quality_score(self, ticker: str, source: str, score: float) -> Any:
        """Kalite skoru kaydı."""
        if not self._enabled:
            return
        DQ_SCORE.labels(ticker=ticker, source=source).observe(score)

    def record_reconciliation_conflict(self, ticker: str) -> Any:
        """Kaynak çelişkisi kaydı."""
        if not self._enabled:
            return
        DQ_RECONCILIATION_CONFLICTS.labels(ticker=ticker).inc()

    # Dedup metrics
    def record_dedup_duplicate(self, event_type: str) -> Any:
        """Tekrar event kaydı."""
        if not self._enabled:
            return
        DEDUP_DUPLICATES.labels(event_type=event_type).inc()

    # Pipeline metrics
    @contextmanager
    def track_pipeline(self, pipeline_type: str) -> Any:
        """Pipeline takip context manager."""
        start = time.time()
        try:
            yield
        finally:
            duration = time.time() - start
            if self._enabled:
                PIPELINE_DURATION.labels(pipeline_type=pipeline_type).observe(duration)

    def record_pipeline_event(self, event_type: str, source: str) -> Any:
        """Pipeline event kaydı."""
        if not self._enabled:
            return
        PIPELINE_EVENTS.labels(event_type=event_type, source=source).inc()

    # PIT metrics
    def record_pit_violation(self, data_type: str) -> Any:
        """Look-ahead bias ihlali kaydı."""
        if not self._enabled:
            return
        PIT_VIOLATIONS.labels(data_type=data_type).inc()

    # Incremental metrics
    def record_incremental_fetch(self, ticker: str) -> Any:
        """Incremental fetch kaydı."""
        if not self._enabled:
            return
        INC_FETCHES.labels(ticker=ticker).inc()

    def record_incremental_skip(self, ticker: str) -> Any:
        """Incremental skip kaydı."""
        if not self._enabled:
            return
        INC_SKIPS.labels(ticker=ticker).inc()


# Singleton
ingestion_metrics = IngestionMetrics()
