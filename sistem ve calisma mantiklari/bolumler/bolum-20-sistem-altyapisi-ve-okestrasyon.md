# Bölüm 20 — Sistem Altyapısı ve Orkestrasyon

## Amaç

Tüm motorların güvenilir, hızlı ve birbirleriyle düzenli şekilde çalışmasını sağlayan teknik omurga.

**Kaynak:** Streamkap (2025) Event-Driven Architecture Examples, Gravitee (2025) Architectural Patterns for Event-Driven Systems.

---

## Kullanılacak sistemler

- Database
- Cache
- Event Bus
- Message Queue
- Worker System
- Feature Store
- Configuration Service
- Scheduler
- Logging
- Monitoring
- Backup / Recovery
- Event Replay

---

## Çalışma mantığı

```
Veri Kaynakları → ETL → Validation → Database → Feature Store →
Event Bus → Queue → Worker'lar → Analiz Motorları → AI Agent'lar → Sonuç
```

---

## 1. Event-Driven Architecture

**Araştırma bulgusu:** Streamkap (2025) — "Real-time data streaming unlocks new possibilities for event-driven systems."

### Örnek: Event bus

```python
# services/core/infrastructure.py
from services.core.infrastructure import event_orchestrator

# KAP geldiğinde tetikle
await event_orchestrator.dispatch("kap.new", data)
```

---

## 2. Cache System

### Örnek: Cache

```python
from services.core.infrastructure import cache_system

cache_system.set("market_state", state_data, ttl_seconds=300)
cached = cache_system.get("market_state")
```

---

## 3. Job Queue

### Örnek: Ağır işler

```python
from services.core.infrastructure import job_queue

job_id = job_queue.enqueue("backtest", {"strategy": "momentum"}, priority="HIGH")
job = job_queue.dequeue()
job_queue.complete(job_id, {"result": "success"})
```

---

## Temel prensip

Bu bölüm yatırım kararı vermez; diğer bölümlerin **hızlı, ölçeklenebilir, event-driven ve hata durumunda toparlanabilir** şekilde çalışmasını sağlar.
