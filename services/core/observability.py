"""
ALPHA BIST — Observability & Monitoring v2.0

- Prometheus Metrics (via official prometheus_client)
- Distributed Tracing (via OpenTelemetry API)
- Performance Monitoring
- Cost Monitoring
- Resource Management (via psutil)
- Config System
- Health Check endpoints
"""

import functools
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import psutil
import structlog
from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.observability")


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


# Standart histogram bucket'ları (saniye cinsinden)
DEFAULT_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class PrometheusMetrics:
    """Prometheus uyumlu metric sistemi — resmi prometheus_client ile."""

    def __init__(self):
        """Otomatik eklendi."""
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def _get_or_create_counter(self, name: str, labels: list[str] = None) -> Counter:
        """Otomatik eklendi."""
        if name not in self._counters:
            self._counters[name] = Counter(name, f"{name} counter", labels or [])
        return self._counters[name]

    def _get_or_create_gauge(self, name: str, labels: list[str] = None) -> Gauge:
        """Otomatik eklendi."""
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, f"{name} gauge", labels or [])
        return self._gauges[name]

    def _get_or_create_histogram(
        self, name: str, labels: list[str] = None, buckets: tuple = DEFAULT_BUCKETS
    ) -> Histogram:
        """Otomatik eklendi."""
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, f"{name} histogram", labels or [], buckets=buckets)
        return self._histograms[name]

    def inc(self, name: str, value: int = 1, labels: dict[str, str] = None) -> Any:
        """Counter artır."""
        label_names = list(labels.keys()) if labels else []
        counter = self._get_or_create_counter(name, label_names)
        if labels:
            counter.labels(**labels).inc(value)
        else:
            counter.inc(value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] = None) -> Any:
        """Gauge ayarla."""
        label_names = list(labels.keys()) if labels else []
        gauge = self._get_or_create_gauge(name, label_names)
        if labels:
            gauge.labels(**labels).set(value)
        else:
            gauge.set(value)

    def observe(self, name: str, value: float, labels: dict[str, str] = None, buckets: tuple = None) -> Any:
        """Histogram gözlem (bucket desteği ile)."""
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        if labels:
            hist.labels(**labels).observe(value)
        else:
            hist.observe(value)

    def timed(self, name: str, labels: dict[str, str] = None, buckets: tuple = None) -> Any:
        """Context manager — işlem süresini ölçer."""
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        if labels:
            return hist.labels(**labels).time()
        return hist.time()

    def record_api_call(self, endpoint: str, duration_seconds: float, success: bool = True) -> None:
        """API istek süresi ve durumunu kaydet."""
        status = "success" if success else "failure"
        self.observe("api_latency_seconds", duration_seconds, labels={"endpoint": endpoint, "status": status})
        self.inc("api_requests_total", 1, labels={"endpoint": endpoint, "status": status})

    def record_db_query(self, db_type: str, operation: str, duration_seconds: float) -> None:
        """Veritabanı sorgu süresini kaydet."""
        self.observe("db_query_duration_seconds", duration_seconds, labels={"db_type": db_type, "operation": operation})

    def record_feature_computation(self, feature_set: str, duration_seconds: float, num_tickers: int = 1) -> None:
        """Özellik hesaplama süresini kaydet."""
        self.observe("feature_computation_duration_seconds", duration_seconds, labels={"feature_set": feature_set})
        self.inc("feature_ticks_processed_total", num_tickers, labels={"feature_set": feature_set})

    def record_ml_inference(self, model_name: str, duration_seconds: float, num_samples: int = 1) -> None:
        """ML model tahmin süresini kaydet."""
        self.observe("ml_inference_duration_seconds", duration_seconds, labels={"model_name": model_name})
        self.inc("ml_predictions_total", num_samples, labels={"model_name": model_name})

    def record_cache_access(self, cache_name: str, hit: bool) -> None:
        """Önbellek isabet ve ıskalama durumunu kaydet."""
        res = "hit" if hit else "miss"
        self.inc("cache_access_total", 1, labels={"cache_name": cache_name, "result": res})

    def record_error(self, component: str, error_type: str) -> None:
        """Hata sayacını artır."""
        self.inc("system_errors_total", 1, labels={"component": component, "error_type": error_type})

    def get_metrics(self) -> dict[str, Any]:
        """Geriye dönük uyumluluk için dict formatında metrikler."""
        histograms_dict = {}
        for name, hist in self._histograms.items():
            try:
                collected = hist.collect()
                samples = collected[0].samples if collected else []
                buckets = {}
                count = 0
                sum_val = 0.0
                for s in samples:
                    if s.name.endswith("_bucket"):
                        le = s.labels.get("le", "")
                        buckets[le] = int(s.value)
                    elif s.name.endswith("_count"):
                        count = int(s.value)
                    elif s.name.endswith("_sum"):
                        sum_val = float(s.value)
                histograms_dict[name] = {
                    "count": count,
                    "sum": sum_val,
                    "buckets": buckets,
                }
            except Exception:
                histograms_dict[name] = {"count": 0, "sum": 0.0, "buckets": {}}
        return {
            "counters": self._counters,
            "gauges": self._gauges,
            "histograms": histograms_dict,
        }

    def get_prometheus_text(self) -> str:
        """Prometheus text exposition format (OpenMetrics compliant)."""
        return generate_latest(REGISTRY).decode("utf-8")


class DistributedTracing:
    """Dağıtık izleme — OpenTelemetry entegrasyonu ile."""

    def __init__(self):
        """Otomatik eklendi."""
        self._tracer = trace.get_tracer(__name__)

    def start_trace(self, operation: str) -> str:
        """Yeni trace başlat."""
        span = self._tracer.start_span(operation)
        ctx = span.get_span_context()
        trace_id = format(ctx.trace_id, "032x")
        span.set_attribute("status", "started")
        return trace_id

    def add_span(self, trace_id: str, operation: str, duration_ms: float = 0, status: str = "completed") -> Any:
        """Mevcut sisteme uyumlu dummy. Artık with tracer.start_as_current_span kullanılmalı."""
        pass

    def get_trace(self, trace_id: str) -> list[dict]:
        """Geriye dönük uyumluluk (Mock). Trace'ler Jaeger/Tempo'da."""
        return []

    def get_spans(self, trace_id: str) -> list[dict]:
        """Otomatik eklendi."""
        return []

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """Otomatik eklendi."""
        return []


class PerformanceMonitor:
    """Performans izleme - Prometheus Histogramlara entegre."""

    def __init__(self):
        """Otomatik eklendi."""
        pass

    @otel_trace("observability.PerformanceMonitor.record_latency")
    def record_latency(self, operation: str, latency_ms: float) -> Any:
        """Gecikme kaydet."""
        prometheus_metrics.observe("operation_latency_seconds", latency_ms / 1000.0, labels={"operation": operation})

    @otel_trace("observability.PerformanceMonitor.get_stats")
    def get_stats(self, operation: str) -> dict[str, float]:
        """Otomatik eklendi."""
        return {"note": "Metrics exported to Prometheus"}

    @otel_trace("observability.PerformanceMonitor.get_all_stats")
    def get_all_stats(self) -> dict[str, dict]:
        """Otomatik eklendi."""
        return {}


class CostMonitor:
    """Maliyet izleme - Prometheus Gaugelara entegre."""

    def __init__(self):
        """Otomatik eklendi."""
        self._total_cost: float = 0.0

    @otel_trace("observability.CostMonitor.record")
    def record(self, provider: str, model: str, tokens: int, cost_usd: float) -> Any:
        """Maliyet kaydet."""
        self._total_cost += cost_usd
        prometheus_metrics.inc("llm_tokens_total", tokens, labels={"provider": provider, "model": model})
        prometheus_metrics.inc("llm_cost_usd_total", cost_usd, labels={"provider": provider, "model": model})
        prometheus_metrics.set_gauge("llm_cost_usd_cumulative", self._total_cost)

    @otel_trace("observability.CostMonitor.get_summary")
    def get_summary(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {"total_cost_usd": self._total_cost}


class ResourceMonitor:
    """Kaynak kullanımı izleme - psutil tabanlı ve arka plan destekli."""

    def __init__(self):
        """Otomatik eklendi."""
        self._process = psutil.Process(os.getpid())
        self._running = False
        self._thread = None

    @otel_trace("observability.ResourceMonitor.start_background_monitoring")
    def start_background_monitoring(self, interval_seconds: int = 15) -> Any:
        """Otomatik eklendi."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, args=(interval_seconds,), daemon=True)
        self._thread.start()

    @otel_trace("observability.ResourceMonitor.stop_background_monitoring")
    def stop_background_monitoring(self) -> Any:
        """Otomatik eklendi."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self, interval: int) -> Any:
        """Otomatik eklendi."""
        while self._running:
            try:
                self.snapshot()
            except Exception as e:
                logger.error("Resource monitoring failed", error=str(e))
            time.sleep(interval)

    @otel_trace("observability.ResourceMonitor.snapshot")
    def snapshot(self, cpu_pct: float = 0, memory_mb: float = 0, gpu_pct: float = 0, disk_mb: float = 0) -> Any:
        """Gerçek donanım verilerini okur ve Prometheus'a yazar."""
        actual_cpu = self._process.cpu_percent(interval=None)
        actual_mem = self._process.memory_info().rss / (1024 * 1024)

        prometheus_metrics.set_gauge("process_cpu_percent", actual_cpu)
        prometheus_metrics.set_gauge("process_memory_mb", actual_mem)

        try:
            disk = psutil.disk_usage("/")
            prometheus_metrics.set_gauge("system_disk_used_percent", disk.percent)
        except Exception:
            logger.error("Exception caught", exc_info=True)

    @otel_trace("observability.ResourceMonitor.get_current")
    def get_current(self) -> dict[str, Any]:
        """Mevcut kaynak kullanımı."""
        return {
            "cpu_pct": self._process.cpu_percent(interval=None),
            "memory_mb": self._process.memory_info().rss / (1024 * 1024),
            "gpu_pct": 0,
            "disk_mb": 0,
        }


class ConfigManager:
    """Config yönetimi — versioned, auditable."""

    def __init__(self):
        """Otomatik eklendi."""
        self._config: dict[str, Any] = {}
        self._versions: list[dict] = []
        self._defaults: dict[str, Any] = {
            "risk.max_position_pct": 10.0,
            "risk.max_sector_pct": 30.0,
            "risk.max_drawdown_pct": 15.0,
            "risk.daily_loss_limit_pct": 5.0,
            "ml.retrain_interval_hours": 168,
            "llm.context_size": 8192,
            "market.open_hour": "10:00",
            "market.close_hour": "18:00",
        }

    @otel_trace("observability.ConfigManager.get")
    def get(self, key: str, default: Any = None) -> Any:
        """Otomatik eklendi."""
        return self._config.get(key, self._defaults.get(key, default))

    @otel_trace("observability.ConfigManager.set")
    def set(self, key: str, value: Any, actor: str = "system", reason: str = "") -> Any:
        """Otomatik eklendi."""
        old_value = self._config.get(key)
        self._config[key] = value

        self._versions.append(
            {
                "key": key,
                "old": str(old_value),
                "new": str(value),
                "actor": actor,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._versions) > 500:
            self._versions = self._versions[-500:]

        logger.info("Config changed", key=key, old=old_value, new=value, actor=actor)

    @otel_trace("observability.ConfigManager.get_history")
    def get_history(self, key: str) -> list[dict]:
        """Otomatik eklendi."""
        return [v for v in self._versions if v["key"] == key]

    @otel_trace("observability.ConfigManager.get_all")
    def get_all(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        result = dict(self._defaults)
        result.update(self._config)
        return result


class HealthChecker:
    """Sistem sağlık kontrolü."""

    def __init__(self):
        """Otomatik eklendi."""
        self._components: dict[str, dict] = {}

    @otel_trace("observability.HealthChecker.register")
    def register(self, component: str, check_fn: Any = None) -> Any:
        """Otomatik eklendi."""
        self._components[component] = {
            "status": "UNKNOWN",
            "last_check": None,
            "check_fn": check_fn,
        }

    @otel_trace("observability.HealthChecker.update_status")
    def update_status(self, component: str, status: str, details: str = "") -> Any:
        """Otomatik eklendi."""
        if component in self._components:
            self._components[component]["status"] = status
            self._components[component]["details"] = details
            self._components[component]["last_check"] = datetime.now(UTC).isoformat()

            # Update metric
            status_val = 1 if status == "HEALTHY" else 0
            prometheus_metrics.set_gauge("component_health_status", status_val, labels={"component": component})

    @otel_trace("observability.HealthChecker.check_all")
    def check_all(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        results = {}
        overall = "HEALTHY"

        for name, comp in self._components.items():
            results[name] = {
                "status": comp["status"],
                "details": comp.get("details", ""),
                "last_check": comp.get("last_check"),
            }
            if comp["status"] == "FAILED" or comp["status"] == "DEGRADED" and overall == "HEALTHY":
                overall = "DEGRADED"

        return {
            "overall": overall,
            "components": results,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Singletons
prometheus_metrics = PrometheusMetrics()
distributed_tracing = DistributedTracing()
performance_monitor = PerformanceMonitor()
cost_monitor = CostMonitor()
resource_monitor = ResourceMonitor()
config_manager = ConfigManager()
health_checker = HealthChecker()
