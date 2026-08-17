# core/worker

**Dosya:** `services/core/worker.py`
**Satır:** 331

## Açıklama

ALPHA BIST — Job Worker v1.0

Production-grade job execution with:
- Retry with exponential backoff
- Timeout
- Idempotency
- Duplicate prevention
- DB-backed state persistence
- Graceful failure

## Sınıflar (3)

- `JobStatus`
- `JobType`
- `JobWorker`

## Fonksiyonlar (3)

- `__init__()`
- `_generate_idempotency_key()`
- `_db_available()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/production_metrics`

