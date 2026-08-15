# Bölüm 21 — Hata Yönetimi ve Dayanıklılık

## Amaç

Bir veri kaynağı, servis veya model hata verdiğinde tüm sistemin bozulmasını engellemek.

**Kaynak:** Circuit breaker, retry/backoff, failure injection.

## Çalışma mantığı

```
İşlem → Hata oluştu mu? → Hata sınıflandır → Retry mümkün mü? →
Fallback → Güvenilir mi? → NO_TRADE / BLOCK
```

### Örnek: Circuit breaker

```python
from services.core.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(name="yfinance", failure_threshold=5)
cb.can_execute()  # True
for _ in range(5): cb.record_failure()
cb.can_execute()  # False (OPEN)
```

## Temel prensip

Hata olduğunda sistem yanlış karar vermek yerine kontrollü olarak yavaşlar, fallback kullanır veya işlemi durdurur.
