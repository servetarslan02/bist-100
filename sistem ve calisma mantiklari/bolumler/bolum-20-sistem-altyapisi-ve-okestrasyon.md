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


## Çıktı

```
Cache entries:        15
Queue jobs:           3
Worker status:        Active
Database:             Healthy
Event Bus:            Connected
Monitoring:           Active
```

## Temel prensip

Bu bölüm yatırım kararı vermez; diğer bölümlerin **hızlı, ölçeklenebilir, event-driven ve hata durumunda toparlanabilir** şekilde çalışmasını sağlar.

---

## BIST Piyasa Kuralları Entegrasyonu

**Kaynak:** Bölüm 23 — BIST Piyasa Kuralları

Bu bölümün altyapı motoru, Bölüm 23'teki BIST-specific mekanizmalarla genişler:

| Mekanizma | Bölüm 23 Motoru | Bölüm 20 Kullanımı |
|-----------|----------------|-------------------|
| Devre kesici | `core/circuit_breaker.py` | BIST-specific eşikler |
| Brüt takas | `core/gross_settlement.py` | T+0 kısıtlaması |
| VIOP monitor | `core/viop_monitor.py` | Teminat takibi |
| Seans saatleri | `core/market_calendar.py` | BIST seans yapısı |

### Örnek: BIST devre kesici

```python
from services.core.market_calendar import market_calendar

# BIST-specific halt
market_calendar.add_halt(date(2026, 8, 16), time(11, 0), time(11, 30))
is_open = market_calendar.is_market_open(datetime(2026, 8, 16, 11, 15))
# is_open: False (devre kesici aktif)
```
