# core/observability

**Dosya:** `services/core/observability.py`
**Satır:** 372

## Açıklama

ALPHA BIST — Observability & Monitoring v1.0

- Prometheus Metrics
- Distributed Tracing (correlation_id)
- Performance Monitoring
- Cost Monitoring
- Resource Management
- Config System
- Config Versioning
- Health Check endpoints

## Sınıflar (7)

- `PrometheusMetrics`
- `DistributedTracing`
- `PerformanceMonitor`
- `CostMonitor`
- `ResourceMonitor`
- `ConfigManager`
- `HealthChecker`

## Fonksiyonlar (32)

- `__init__()`
- `inc()`
- `set_gauge()`
- `observe()`
- `timed()`
- `get_metrics()`
- `get_prometheus_text()`
- `_make_key()`
- `__init__()`
- `start_trace()`
- `add_span()`
- `get_trace()`
- `get_recent_traces()`
- `__init__()`
- `record_latency()`
- `get_stats()`
- `get_all_stats()`
- `__init__()`
- `record()`
- `get_summary()`
- `__init__()`
- `snapshot()`
- `get_current()`
- `__init__()`
- `get()`
- `set()`
- `get_history()`
- `get_all()`
- `__init__()`
- `register()`
- ... ve 2 daha

