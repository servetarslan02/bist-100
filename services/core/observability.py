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

import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import psutil
import structlog
from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

logger = structlog.get_logger()

# Standart histogram bucket'ları (saniye cinsinden)
DEFAULT_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class PrometheusMetrics:
    """Prometheus uyumlu metric sistemi — resmi prometheus_client ile."""

    def __init__(self):
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def _get_or_create_counter(self, name: str, labels: list[str] = None) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, f"{name} counter", labels or [])
        return self._counters[name]

    def _get_or_create_gauge(self, name: str, labels: list[str] = None) -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, f"{name} gauge", labels or [])
        return self._gauges[name]

    def _get_or_create_histogram(
        self, name: str, labels: list[str] = None, buckets: tuple = DEFAULT_BUCKETS
    ) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, f"{name} histogram", labels or [], buckets=buckets)
        return self._histograms[name]

    def inc(self, name: str, value: int = 1, labels: dict[str, str] = None):
        """Counter artır."""
        label_names = list(labels.keys()) if labels else []
        counter = self._get_or_create_counter(name, label_names)
        if labels:
            counter.labels(**labels).inc(value)
        else:
            counter.inc(value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] = None):
        """Gauge ayarla."""
        label_names = list(labels.keys()) if labels else []
        gauge = self._get_or_create_gauge(name, label_names)
        if labels:
            gauge.labels(**labels).set(value)
        else:
            gauge.set(value)

    def observe(self, name: str, value: float, labels: dict[str, str] = None, buckets: tuple = None):
        """Histogram gözlem (bucket desteği ile)."""
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        if labels:
            hist.labels(**labels).observe(value)
        else:
            hist.observe(value)

    def timed(self, name: str, labels: dict[str, str] = None, buckets: tuple = None):
        """Context manager — işlem süresini ölçer."""
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        if labels:
            return hist.labels(**labels).time()
        return hist.time()

    def get_metrics(self) -> dict[str, Any]:
        """Geriye dönük uyumluluk için. Artık doğrudan /metrics üzerinden exposition kullanılıyor."""
        return {"note": "Use /metrics endpoint for exposition."}

    def get_prometheus_text(self) -> str:
        """Prometheus text exposition format (OpenMetrics compliant)."""
        return generate_latest(REGISTRY).decode("utf-8")


class DistributedTracing:
    """Dağıtık izleme — OpenTelemetry entegrasyonu ile."""

    def __init__(self):
        self._tracer = trace.get_tracer(__name__)

    def start_trace(self, operation: str) -> str:
        """Yeni trace başlat."""
        span = self._tracer.start_span(operation)
        ctx = span.get_span_context()
        trace_id = format(ctx.trace_id, "032x")
        span.set_attribute("status", "started")
        return trace_id

    def add_span(self, trace_id: str, operation: str, duration_ms: float = 0, status: str = "completed"):
        """Mevcut sisteme uyumlu dummy. Artık with tracer.start_as_current_span kullanılmalı."""
        pass

    def get_trace(self, trace_id: str) -> list[dict]:
        """Geriye dönük uyumluluk (Mock). Trace'ler Jaeger/Tempo'da."""
        return []

    def get_spans(self, trace_id: str) -> list[dict]:
        return []

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        return []


class PerformanceMonitor:
    """Performans izleme - Prometheus Histogramlara entegre."""

    def __init__(self):
        pass

    def record_latency(self, operation: str, latency_ms: float):
        """Gecikme kaydet."""
        prometheus_metrics.observe("operation_latency_seconds", latency_ms / 1000.0, labels={"operation": operation})

    def get_stats(self, operation: str) -> dict[str, float]:
        return {"note": "Metrics exported to Prometheus"}

    def get_all_stats(self) -> dict[str, dict]:
        return {}


class CostMonitor:
    """Maliyet izleme - Prometheus Gaugelara entegre."""

    def __init__(self):
        self._total_cost: float = 0.0

    def record(self, provider: str, model: str, tokens: int, cost_usd: float):
        """Maliyet kaydet."""
        self._total_cost += cost_usd
        prometheus_metrics.inc("llm_tokens_total", tokens, labels={"provider": provider, "model": model})
        prometheus_metrics.inc("llm_cost_usd_total", cost_usd, labels={"provider": provider, "model": model})
        prometheus_metrics.set_gauge("llm_cost_usd_cumulative", self._total_cost)

    def get_summary(self) -> dict[str, Any]:
        return {"total_cost_usd": self._total_cost}


class ResourceMonitor:
    """Kaynak kullanımı izleme - psutil tabanlı ve arka plan destekli."""

    def __init__(self):
        self._process = psutil.Process(os.getpid())
        self._running = False
        self._thread = None

    def start_background_monitoring(self, interval_seconds: int = 15):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, args=(interval_seconds,), daemon=True)
        self._thread.start()

    def stop_background_monitoring(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self, interval: int):
        while self._running:
            try:
                self.snapshot()
            except Exception as e:
                logger.error("Resource monitoring failed", error=str(e))
            time.sleep(interval)

    def snapshot(self, cpu_pct: float = 0, memory_mb: float = 0, gpu_pct: float = 0, disk_mb: float = 0):
        """Gerçek donanım verilerini okur ve Prometheus'a yazar."""
        actual_cpu = self._process.cpu_percent(interval=None)
        actual_mem = self._process.memory_info().rss / (1024 * 1024)

        prometheus_metrics.set_gauge("process_cpu_percent", actual_cpu)
        prometheus_metrics.set_gauge("process_memory_mb", actual_mem)

        try:
            disk = psutil.disk_usage("/")
            prometheus_metrics.set_gauge("system_disk_used_percent", disk.percent)
        except Exception:
            pass

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

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, self._defaults.get(key, default))

    def set(self, key: str, value: Any, actor: str = "system", reason: str = ""):
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

    def get_history(self, key: str) -> list[dict]:
        return [v for v in self._versions if v["key"] == key]

    def get_all(self) -> dict[str, Any]:
        result = dict(self._defaults)
        result.update(self._config)
        return result


class HealthChecker:
    """Sistem sağlık kontrolü."""

    def __init__(self):
        self._components: dict[str, dict] = {}

    def register(self, component: str, check_fn: Any = None):
        self._components[component] = {
            "status": "UNKNOWN",
            "last_check": None,
            "check_fn": check_fn,
        }

    def update_status(self, component: str, status: str, details: str = ""):
        if component in self._components:
            self._components[component]["status"] = status
            self._components[component]["details"] = details
            self._components[component]["last_check"] = datetime.now(UTC).isoformat()

            # Update metric
            status_val = 1 if status == "HEALTHY" else 0
            prometheus_metrics.set_gauge("component_health_status", status_val, labels={"component": component})

    def check_all(self) -> dict[str, Any]:
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
