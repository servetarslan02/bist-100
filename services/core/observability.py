"""
ALPHA BIST — Observability & Monitoring v1.0

- Prometheus Metrics
- Distributed Tracing (correlation_id)
- Performance Monitoring
- Cost Monitoring
- Resource Management
- Config System
- Config Versioning
- Health Check endpoints
"""

import time
import uuid
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
import structlog

logger = structlog.get_logger()


# Standart histogram bucket'ları (saniye cinsinden)
DEFAULT_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class PrometheusMetrics:
    """Prometheus uyumlu metric sistemi — histogram bucket desteği ile."""

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._histogram_buckets: Dict[str, tuple] = {}

    def inc(self, name: str, value: int = 1, labels: Dict[str, str] = None):
        """Counter artır."""
        key = self._make_key(name, labels)
        self._counters[key] += value

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Gauge ayarla."""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def observe(self, name: str, value: float, labels: Dict[str, str] = None,
                buckets: tuple = None):
        """Histogram gözlem (bucket desteği ile)."""
        key = self._make_key(name, labels)
        self._histograms[key].append(value)
        self._histograms[key] = self._histograms[key][-1000:]
        if buckets:
            self._histogram_buckets[name] = buckets

    def timed(self, name: str, labels: Dict[str, str] = None, buckets: tuple = None):
        """Context manager — işlem süresini ölçer."""
        import time as _time
        class _Timer:
            def __init__(self, metrics, n, l, b):
                self._metrics = metrics
                self._name = n
                self._labels = l
                self._buckets = b
                self._start = None
            def __enter__(self):
                self._start = _time.monotonic()
                return self
            def __exit__(self, *args):
                elapsed = _time.monotonic() - self._start
                self._metrics.observe(self._name, elapsed, self._labels, self._buckets)
        return _Timer(self, name, labels, buckets)

    def get_metrics(self) -> Dict[str, Any]:
        """Tüm metrikleri döndür."""
        result = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
        }
        for key, values in self._histograms.items():
            if values:
                base_name = key.split("{")[0]
                buckets = self._histogram_buckets.get(base_name, DEFAULT_BUCKETS)
                bucket_counts = {}
                for b in buckets:
                    bucket_counts[str(b)] = sum(1 for v in values if v <= b)
                bucket_counts["+Inf"] = len(values)
                result["histograms"][key] = {
                    "count": len(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "p50": sorted(values)[len(values) // 2],
                    "p95": sorted(values)[int(len(values) * 0.95)],
                    "p99": sorted(values)[int(len(values) * 0.99)],
                    "buckets": bucket_counts,
                }
        return result

    def get_prometheus_text(self) -> str:
        """Prometheus text exposition format."""
        lines = []
        for key, value in self._counters.items():
            name = key.split("{")[0]
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{key} {value}")
        for key, value in self._gauges.items():
            name = key.split("{")[0]
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{key} {value}")
        for key, stats in self.get_metrics()["histograms"].items():
            name = key.split("{")[0]
            lines.append(f"# TYPE {name} histogram")
            for b, count in stats.get("buckets", {}).items():
                lines.append(f'{name}_bucket{{le="{b}"}} {count}')
            lines.append(f"{name}_count {stats['count']}")
            lines.append(f"{name}_sum {stats['sum']:.6f}")
        return "\n".join(lines) + "\n"

    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name


class DistributedTracing:
    """Dağıtık izleme — correlation_id zinciri."""

    def __init__(self):
        self._traces: Dict[str, List[Dict]] = {}

    def start_trace(self, operation: str) -> str:
        """Yeni trace başlat."""
        trace_id = str(uuid.uuid4())[:16]
        self._traces[trace_id] = [{
            "trace_id": trace_id,
            "operation": operation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "started",
        }]
        return trace_id

    def add_span(self, trace_id: str, operation: str, duration_ms: float = 0, status: str = "completed"):
        """Span ekle."""
        if trace_id not in self._traces:
            self._traces[trace_id] = []

        self._traces[trace_id].append({
            "trace_id": trace_id,
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_trace(self, trace_id: str) -> List[Dict]:
        """Trace getir."""
        return self._traces.get(trace_id, [])

    def get_recent_traces(self, limit: int = 20) -> List[Dict]:
        """Son trace'ler."""
        all_traces = []
        for trace_id, spans in self._traces.items():
            if spans:
                all_traces.append({
                    "trace_id": trace_id,
                    "operation": spans[0].get("operation", ""),
                    "span_count": len(spans),
                    "total_ms": sum(s.get("duration_ms", 0) for s in spans),
                    "timestamp": spans[0].get("timestamp", ""),
                })
        return sorted(all_traces, key=lambda x: x["timestamp"], reverse=True)[:limit]


class PerformanceMonitor:
    """Performans izleme."""

    def __init__(self):
        self._latencies: Dict[str, List[float]] = defaultdict(list)

    def record_latency(self, operation: str, latency_ms: float):
        """Gecikme kaydet."""
        self._latencies[operation].append(latency_ms)
        self._latencies[operation] = self._latencies[operation][-1000:]

    def get_stats(self, operation: str) -> Dict[str, float]:
        """İşlem istatistikleri."""
        values = self._latencies.get(operation, [])
        if not values:
            return {"count": 0}

        return {
            "count": len(values),
            "avg_ms": round(sum(values) / len(values), 2),
            "min_ms": round(min(values), 2),
            "max_ms": round(max(values), 2),
            "p50_ms": round(sorted(values)[len(values) // 2], 2),
            "p95_ms": round(sorted(values)[int(len(values) * 0.95)], 2),
        }

    def get_all_stats(self) -> Dict[str, Dict]:
        """Tüm işlem istatistikleri."""
        return {op: self.get_stats(op) for op in self._latencies}


class CostMonitor:
    """Maliyet izleme."""

    def __init__(self):
        self._costs: List[Dict] = []
        self._total_cost: float = 0.0

    def record(self, provider: str, model: str, tokens: int, cost_usd: float):
        """Maliyet kaydet."""
        entry = {
            "provider": provider,
            "model": model,
            "tokens": tokens,
            "cost_usd": round(cost_usd, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._costs.append(entry)
        if len(self._costs) > 1000:
            self._costs = self._costs[-1000:]
        self._total_cost += cost_usd
        self._costs = self._costs[-10000:]

    def get_summary(self) -> Dict[str, Any]:
        """Maliyet özeti."""
        by_provider = {}
        by_model = {}
        for c in self._costs:
            p = c["provider"]
            m = c["model"]
            by_provider[p] = by_provider.get(p, 0) + c["cost_usd"]
            by_model[m] = by_model.get(m, 0) + c["cost_usd"]

        return {
            "total_cost_usd": round(self._total_cost, 4),
            "total_entries": len(self._costs),
            "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
        }


class ResourceMonitor:
    """Kaynak kullanımı izleme."""

    def __init__(self):
        self._snapshots: List[Dict] = []

    def snapshot(self, cpu_pct: float = 0, memory_mb: float = 0, gpu_pct: float = 0, disk_mb: float = 0):
        """Kaynak kullanımı snapshot."""
        self._snapshots.append({
            "cpu_pct": cpu_pct,
            "memory_mb": memory_mb,
            "gpu_pct": gpu_pct,
            "disk_mb": disk_mb,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._snapshots = self._snapshots[-1000]

    def get_current(self) -> Dict[str, Any]:
        """Mevcut kaynak kullanımı."""
        if self._snapshots:
            return self._snapshots[-1]
        return {"cpu_pct": 0, "memory_mb": 0, "gpu_pct": 0, "disk_mb": 0}


class ConfigManager:
    """Config yönetimi — versioned, auditable."""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._versions: List[Dict] = []
        self._defaults: Dict[str, Any] = {
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
        """Config değeri getir."""
        return self._config.get(key, self._defaults.get(key, default))

    def set(self, key: str, value: Any, actor: str = "system", reason: str = ""):
        """Config değeri ayarla (versioned)."""
        old_value = self._config.get(key)
        self._config[key] = value

        self._versions.append({
            "key": key,
            "old": str(old_value),
            "new": str(value),
            "actor": actor,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info("Config changed", key=key, old=old_value, new=value, actor=actor)

    def get_history(self, key: str) -> List[Dict]:
        """Config değişiklik geçmişi."""
        return [v for v in self._versions if v["key"] == key]

    def get_all(self) -> Dict[str, Any]:
        """Tüm config."""
        result = dict(self._defaults)
        result.update(self._config)
        return result


class HealthChecker:
    """Sistem sağlık kontrolü."""

    def __init__(self):
        self._components: Dict[str, Dict] = {}

    def register(self, component: str, check_fn: Any = None):
        """Bileşen kaydet."""
        self._components[component] = {
            "status": "UNKNOWN",
            "last_check": None,
            "check_fn": check_fn,
        }

    def update_status(self, component: str, status: str, details: str = ""):
        """Bileşen durumu güncelle."""
        if component in self._components:
            self._components[component]["status"] = status
            self._components[component]["details"] = details
            self._components[component]["last_check"] = datetime.now(timezone.utc).isoformat()

    def check_all(self) -> Dict[str, Any]:
        """Tüm bileşenlerin sağlık durumu."""
        results = {}
        overall = "HEALTHY"

        for name, comp in self._components.items():
            results[name] = {
                "status": comp["status"],
                "details": comp.get("details", ""),
                "last_check": comp.get("last_check"),
            }
            if comp["status"] == "FAILED":
                overall = "DEGRADED"
            elif comp["status"] == "DEGRADED" and overall == "HEALTHY":
                overall = "DEGRADED"

        return {
            "overall": overall,
            "components": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singletons
prometheus_metrics = PrometheusMetrics()
distributed_tracing = DistributedTracing()
performance_monitor = PerformanceMonitor()
cost_monitor = CostMonitor()
resource_monitor = ResourceMonitor()
config_manager = ConfigManager()
health_checker = HealthChecker()
