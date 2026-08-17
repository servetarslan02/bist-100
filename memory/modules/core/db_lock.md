# core/db_lock

**Dosya:** `services/core/db_lock.py`
**Satır:** 587

## Açıklama

ALPHA BIST — Database-Agnostic Lock Abstraction v2.0

Production-grade lock infrastructure.

Özellikler:
- PostgreSQL: pg_advisory_lock / pg_try_advisory_lock / pg_advisory_unlock
- SQLite: BEGIN IMMEDIATE / COMMIT / ROLLBACK
- Exponential backoff retry
- Lock lease renewal (uzun transaction'lar)
- Crash recovery (stale lock detection + cleanup)
- Monitoring: acquisition count, timeout, wait time, deadlock
- Health check integration
- Lock ordering (deadlock prevention)

Kullanım:
    async with

## Sınıflar (3)

- `LockMetrics`
- `DatabaseLock`
- `CoordinatedLock`

## Fonksiyonlar (18)

- `record_acquisition()`
- `record_release()`
- `record_timeout()`
- `record_deadlock()`
- `record_error()`
- `record_renewal()`
- `record_crash_recovery()`
- `to_dict()`
- `health_status()`
- `__init__()`
- `key()`
- `is_acquired()`
- `owner_id()`
- `_calc_backoff()`
- `_start_renewal()`
- `_stop_renewal()`
- `__init__()`
- `metrics()`

