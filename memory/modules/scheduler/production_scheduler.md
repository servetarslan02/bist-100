# scheduler/production_scheduler

**Dosya:** `services/scheduler/production_scheduler.py`
**Satır:** 199

## Açıklama

ALPHA BIST — Production Scheduler v3.0

Market session-aware job scheduling.
Uses: MarketSessionManager + JobWorker + system_jobs DB table.

## Sınıflar (1)

- `ProductionScheduler`

## Fonksiyonlar (4)

- `__init__()`
- `register_handler()`
- `update_interval()`
- `_signal_handler()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/market_session`
- `core/production_metrics`
- `core/worker`
- `core/database`
- `core/config`

