# core/monitoring

**Dosya:** `services/core/monitoring.py`
**Satır:** 216

## Açıklama

ALPHA BIST — Portfolio & Lock Monitoring Integration

Prometheus metrics + FastAPI endpoints for production observability.

Endpoints:
  GET /health/detailed     — Full system health (portfolio + locks)
  GET /metrics             — Prometheus format metrics
  GET /admin/lock-metrics  — Lock performance metrics
  GET /admin/portfolio     — Portfolio health + accounting

Metrics:
  lock_acquisition_total      — Counter
  lock_timeout_total          — Counter
  lock_deadlock_total         — Counter

## Sınıflar (1)

- `PortfolioMonitor`

## Fonksiyonlar (2)

- `__init__()`
- `bind()`

