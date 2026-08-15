# Bölüm 20 — Sistem Altyapısı ve Orkestrasyon

## Amaç

Tüm motorların güvenilir, hızlı ve birbirleriyle düzenli şekilde çalışmasını sağlayan teknik omurga.

**Kaynak:** Event-driven architecture, cache, job queue, worker system.

## Çalışma mantığı

```
Veri Kaynakları → ETL → Validation → Database → Feature Store →
Event Bus → Queue → Worker'lar → Analiz Motorları → AI Agent'lar → Sonuç
```

### Örnek: Cache system

```python
from services.core.infrastructure import cache_system

cache_system.set("market_state", state_data, ttl_seconds=300)
cached = cache_system.get("market_state")
```

### Örnek: Job queue

```python
from services.core.infrastructure import job_queue

job_id = job_queue.enqueue("backtest", {"strategy": "momentum"}, priority="HIGH")
```

## Temel prensip

Bu bölüm yatırım kararı vermez; diğer bölümlerin hızlı, ölçeklenebilir ve hata durumunda toparlanabilir şekilde çalışmasını sağlar.
