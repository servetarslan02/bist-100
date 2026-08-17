# Bölüm 21 — Hata Yönetimi ve Dayanıklılık

## Amaç

Bir veri kaynağı, servis veya model hata verdiğinde tüm sistemin bozulmasını engellemek.

**Kaynak:** Zylos Research (2026) Graceful Degradation in AI Agent Systems, Temporal (2025) Error Handling in Distributed Systems, arXiv (2025) Resilient Microservices Recovery Patterns, Groundcover (2025) Circuit Breaker Pattern.

---

## Kullanılacak sistemler

- Error Handling
- Retry / Backoff
- Timeout
- Circuit Breaker
- Fallback
- Idempotency
- Failure Detection
- Health Check
- Recovery
- Dead Letter Queue
- Event Replay

---

## Çalışma mantığı

```
İşlem → Hata oluştu mu? → Hata sınıflandır → Retry mümkün mü? →
Fallback → Güvenilir mi? → NO_TRADE / BLOCK
```

---

## 1. Circuit Breaker

**Araştırma bulgusu:** Groundcover (2025) — "The circuit breaker pattern stops cascading failures before they happen."

### Durum makinesi:
```
CLOSED (normal) → 5 hata → OPEN (durur) → 60s → HALF_OPEN (dener) → başarı → CLOSED
```

### Örnek: Circuit breaker

```python
# services/core/circuit_breaker.py
from services.core.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(name="yfinance", failure_threshold=5)
cb.can_execute()  # True

for _ in range(5):
    cb.record_failure()
cb.can_execute()  # False (OPEN)

# 60 saniye sonra
cb.can_execute()  # True (HALF_OPEN)
cb.record_success()  # → CLOSED
```

---

## 2. Retry with Backoff

**Araştırma bulgusu:** Temporal (2025) — "Essential error handling patterns like retries, sagas, and circuit breakers."

### Örnek: Exponential backoff

```python
from services.core.circuit_breaker import RetryPolicy

retry = RetryPolicy(max_retries=3, base_delay=1.0)
# 1s → 2s → 4s bekleme ile retry
```

---

## 3. Fail-Closed

**Kritik:** Risk Engine ve karar motoru fail-closed çalışır.

```
Risk limits yüklenemez → TÜM İŞLEMLER ENGELLENİR
Veri kalitesi düşük → NO_TRADE
Model geçersiz → NO_TRADE
```

---

## 4. Recovery

**Araştırma bulgusu:** arXiv (2025) — "Circuit breakers, retries with backoff, bulkheads, sagas, and chaos engineering."

```
Failure → Detect → Retry/Restart → Resume from State → Event Replay → Continue
```

---


## Çıktı

```
Circuit Breaker:      CLOSED
Retry count:          0
Last failure:         None
Fallback:             Available
Health status:        OK
```

## Temel prensip

> "Retry, timeout, and circuit breaker are the baseline layers of any resilient automation system." — LinkedIn (2026)

Hata olduğunda sistem yanlış karar vermek yerine **kontrollü olarak yavaşlar, fallback kullanır veya işlemi durdurur**.
