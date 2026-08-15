# Bölüm 22 — Gözlemleme, Audit ve Sistem Sağlık Kontrolü

## Amaç

Sistemin sadece çalışıyor görünmesini değil, gerçekte doğru çalışıp çalışmadığını sürekli ölçmek.

**Kaynak:** Prometheus metrics, distributed tracing, structured logging.

## Çalışma mantığı

```
Tüm Sistemler → Logs + Metrics + Traces → Monitoring Engine →
Anomaly Detection → Health Score → Alert → Audit
```

### Örnek: Prometheus metrics

```python
from services.core.observability import prometheus_metrics

prometheus_metrics.inc("decisions_total", labels={"action": "BUY"})
prometheus_metrics.observe("api_latency_ms", 150)
```

### Örnek: Health check

```python
from services.core.observability import health_checker

health_checker.register("database")
health_checker.update_status("database", "HEALTHY")
result = health_checker.check_all()
# overall: HEALTHY
```

## Temel prensip

"Sistem doğru veriyle, doğru modeli, doğru zamanda, doğru şekilde çalıştırıyor mu?"
