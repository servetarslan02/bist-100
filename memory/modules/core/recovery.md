# core/recovery

**Dosya:** `services/core/recovery.py`
**Satır:** 190

## Açıklama

ALPHA BIST — Recovery & Resilience v1.0

- Event Replay
- Graceful Shutdown
- Startup Recovery
- Failure Injection (testing)
- Chaos Testing helpers

## Sınıflar (4)

- `EventReplay`
- `GracefulShutdown`
- `StartupRecovery`
- `FailureInjector`

## Fonksiyonlar (15)

- `__init__()`
- `log_event()`
- `replay_from()`
- `replay_range()`
- `get_log_count()`
- `__init__()`
- `register_handler()`
- `is_shutting_down()`
- `__init__()`
- `__init__()`
- `inject()`
- `clear()`
- `is_failing()`
- `clear_all()`
- `get_active()`

