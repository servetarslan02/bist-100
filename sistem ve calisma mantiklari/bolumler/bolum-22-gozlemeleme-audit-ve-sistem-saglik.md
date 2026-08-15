# Bölüm 22 — Gözlemleme, Audit ve Sistem Sağlık Kontrolü

## Amaç

Sistemin sadece çalışıyor görünmesini değil, gerçekte doğru çalışıp çalışmadığını sürekli ölçmek.

**Kaynak:** TotalShiftLeft (2026) Observability vs Monitoring, SpectroCloud (2025) Kubernetes Monitoring Stack, LinkedIn (2025) Observability in Distributed Systems.

---

## Kullanılacak sistemler

- Monitoring
- Observability
- Metrics
- Structured Logging
- Distributed Tracing
- Alerting
- Audit Log
- Model Monitoring
- Agent Monitoring
- Cost Monitoring

---

## Çalışma mantığı

```
Tüm Sistemler → Logs + Metrics + Traces → Monitoring Engine →
Anomaly Detection → Health Score → Alert → Audit
```

---

## 1. Three Pillars of Observability

**Araştırma bulgusu:** TotalShiftLeft (2026) — "An observable system produces enough telemetry data—structured logs, metrics, and distributed traces—that an engineer can diagnose any issue."

### Üç temel:
- **Logs:** Olay kayıtları (ne oldu?)
- **Metrics:** Sayısal ölçüler (ne kadar?)
- **Traces:** İstek zinciri (nereden nereye?)

---

## 2. Structured Logging

### Örnek: Log

```python
# services/core/observability.py
import structlog
logger = structlog.get_logger()

logger.info("Decision made", ticker="THYAO", action="BUY", confidence=0.8)
# {"event": "Decision made", "ticker": "THYAO", "action": "BUY", "timestamp": "..."}
```

---

## 3. Prometheus Metrics

### Örnek: Metrics

```python
from services.core.observability import prometheus_metrics

prometheus_metrics.inc("decisions_total", labels={"action": "BUY"})
prometheus_metrics.observe("api_latency_ms", 150)
prometheus_metrics.set_gauge("portfolio_equity", 112450)
```

---

## 4. Health Check

### Örnek: Health score

```python
from services.core.observability import health_checker

health_checker.register("database")
health_checker.update_status("database", "HEALTHY")

result = health_checker.check_all()
# overall: HEALTHY
# components: {database: HEALTHY, redis: HEALTHY, ...}
```

---

## 5. Audit

Her kritik karar için zincir:

```
Karar → Model → Agent → Veriler → Kaynaklar → Hesaplamalar → Risk kontrolü → Sonuç
```

---

## Temel prensip

> "An observable system produces enough telemetry data that an engineer can diagnose any issue." — TotalShiftLeft (2026)

**"Sistem doğru veriyle, doğru modeli, doğru zamanda, doğru şekilde çalıştırıyor mu?"**
