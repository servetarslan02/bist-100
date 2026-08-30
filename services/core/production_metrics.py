"""ALPHA BIST — Production Metrics v1.0

Structured metric abstraction.
Prometheus bağımlılığı yok — in-memory counter/gauge/histogram.
"""

import functools
import time
from collections import defaultdict
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.production_metrics")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class ProductionMetrics:
    """Production metric collector.

    Prometheus bağımlılığı yok — in-memory storage.
    Export: get_all() ile JSON formatında alınabilir.
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list] = defaultdict(list)
        self._last_reset = time.time()

    @otel_trace("production_metrics.inc")
    def inc(self, name: str, value: float = 1.0, labels: dict | None = None) -> Any:
        """Counter artır."""
        key = self._key(name, labels)
        self._counters[key] += value

    @otel_trace("production_metrics.set_gauge")
    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> Any:
        """Gauge ayarla."""
        key = self._key(name, labels)
        self._gauges[key] = value

    @otel_trace("production_metrics.observe")
    def observe(self, name: str, value: float, labels: dict | None = None) -> Any:
        """Histogram gözlem."""
        key = self._key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = __import__('collections').deque(maxlen=1000)
        self._histograms[key].append(value)

    @otel_trace("production_metrics.timer")
    def timer(self, name: str, labels: dict | None = None) -> Any:
        """Context manager — zaman ölçümü."""
        return _Timer(self, name, labels)

    @otel_trace("production_metrics.get_all")
    def get_all(self) -> dict[str, Any]:
        """Tüm metrikleri döndür."""
        result = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
            "uptime_seconds": round(time.time() - self._last_reset, 1),
        }
        for key, values in self._histograms.items():
            if values:
                result["histograms"][key] = {
                    "count": len(values),
                    "mean": round(sum(values) / len(values), 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "p50": round(sorted(values)[len(values) // 2], 4),
                    "p95": round(sorted(values)[int(len(values) * 0.95)], 4)
                    if len(values) >= 20
                    else round(max(values), 4),
                }
        return result

    @otel_trace("production_metrics.reset")
    def reset(self) -> Any:
        """Tüm metrikleri sıfırla."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._last_reset = time.time()

    @staticmethod
    def _key(name: str, labels: dict | None) -> str:
        """Otomatik eklendi."""
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name


class _Timer:
    """Context manager for timing."""

    def __init__(self, metrics: ProductionMetrics, name: str, labels: dict | None):
        """Otomatik eklendi."""
        self._metrics = metrics
        self._name = name
        self._labels = labels
        self._start = 0

    def __enter__(self) -> Any:
        """Otomatik eklendi."""
        self._start = time.time()
        return self

    def __exit__(self, *args) -> Any:
        """Otomatik eklendi."""
        elapsed = time.time() - self._start
        self._metrics.observe(self._name, elapsed, self._labels)


# Pre-defined metric names
class Metrics:
    """Sabit metric isimleri."""

    # Data
    DATA_FETCH_TOTAL = "data_fetch_total"
    DATA_FETCH_ERRORS = "data_fetch_errors"
    DATA_FETCH_LATENCY = "data_fetch_latency_seconds"
    DATA_STALE_COUNT = "data_stale_count"

    # Feature
    FEATURE_CALC_TOTAL = "feature_calc_total"
    FEATURE_CALC_LATENCY = "feature_calc_latency_seconds"
    FEATURE_NAN_COUNT = "feature_nan_count"

    # Model
    MODEL_INFERENCE_TOTAL = "model_inference_total"
    MODEL_INFERENCE_LATENCY = "model_inference_latency_seconds"
    MODEL_CONFIDENCE = "model_confidence"
    MODEL_PREDICTION_STD = "model_prediction_std"

    # Signal
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_DIRECTION_UP = "signal_direction_up"
    SIGNAL_DIRECTION_DOWN = "signal_direction_down"
    SIGNAL_DIRECTION_NEUTRAL = "signal_direction_neutral"

    # Risk
    RISK_CHECK_TOTAL = "risk_check_total"
    RISK_REJECTED = "risk_rejected"
    RISK_REJECTED_REASON = "risk_rejected_reason"

    # Circuit Breaker
    CIRCUIT_STATE = "circuit_breaker_state"
    CIRCUIT_TRIPS = "circuit_breaker_trips"

    # Paper Trading
    PAPER_ORDER_TOTAL = "paper_order_total"
    PAPER_ORDER_FILLED = "paper_order_filled"
    PAPER_ORDER_REJECTED = "paper_order_rejected"
    PAPER_PNL = "paper_pnl"

    # Worker
    WORKER_JOB_TOTAL = "worker_job_total"
    WORKER_JOB_FAILED = "worker_job_failed"
    WORKER_JOB_LATENCY = "worker_job_latency_seconds"

    # DB
    DB_QUERY_TOTAL = "db_query_total"
    DB_QUERY_ERRORS = "db_query_errors"
    DB_POOL_SIZE = "db_pool_size"


# Singleton
production_metrics = ProductionMetrics()
