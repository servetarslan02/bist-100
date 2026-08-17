# core/circuit_breaker

**Dosya:** `services/core/circuit_breaker.py`
**Satır:** 383

## Açıklama

ALPHA BIST — Circuit Breaker & Rate Limiter v1.0

Provider'lar için:
- Circuit Breaker: CLOSED → OPEN → HALF_OPEN → CLOSED
- Rate Limiter: Token bucket + exponential backoff
- Provider Reliability Score tracking

FAZ 1.3-1.5: Provider Failover + Circuit Breaker + Rate Limit

## Sınıflar (6)

- `CircuitState`
- `CircuitBreaker`
- `RateLimiter`
- `RetryPolicy`
- `ProviderReliability`
- `ProtectedProvider`

## Fonksiyonlar (14)

- `record_success()`
- `record_failure()`
- `can_execute()`
- `get_state()`
- `acquire()`
- `get_state()`
- `__init__()`
- `get_delay()`
- `__init__()`
- `record()`
- `get_score()`
- `get_stats()`
- `__init__()`
- `get_health()`

