# Bölüm 20 — Sistem Altyapısı ve Orkestrasyon

## Amaç

Önceki bölümlerdeki tüm motorların güvenilir, hızlı ve birbirleriyle düzenli şekilde çalışmasını sağlayan teknik omurga.

---

## Kullanılacak sistemler

- Database
- Time-Series Database
- Vector Database
- Cache
- Event Bus
- Message Queue
- Worker System
- ETL / Data Pipeline
- Feature Store
- Configuration Service
- Scheduler
- Logging
- Metrics
- Tracing
- Monitoring
- Backup / Recovery
- Event Replay

---

## Çalışma mantığı

```
Veri Kaynakları
    ↓
ETL / Data Pipeline
    ↓
Validation
    ↓
Database / Time-Series DB
    ↓
Feature Store
    ↓
Event Bus
    ↓
Queue
    ↓
Worker'lar
    ↓
Analiz Motorları
    ↓
AI Agent'lar
    ↓
Sonuç / Memory / Portfolio
```

---

## Event-driven çalışma

Örneğin yeni bir KAP geldiğinde bütün sistemi baştan çalıştırmak yerine:

```
Yeni KAP
    ↓
Event Bus
    ↓
News/KAP Worker
    ↓
Event Analysis
    ↓
Şirket State güncelle
    ↓
Forecast/Risk etkileniyorsa
    ↓
ilgili motorları tetikle
```

Böylece sistem incremental çalışır.

---

## Cache

Her veriyi sürekli yeniden hesaplamak yerine sık kullanılan sonuçlar cache'lenir.

Örneğin:

- BIST100 Market State
- Sector Strength
- Company Features

gereksiz yere tekrar tekrar hesaplanmaz.

---

## Worker sistemi

Ağır işlemler ayrı worker'lara dağıtılır:

- Monte Carlo Worker
- Backtest Worker
- Embedding Worker
- News Worker
- Fundamental Worker
- Forecast Worker

Böylece bir işlem diğerlerini bloke etmez.

---

## Monitoring

Sistem sürekli:

- servis sağlığı
- veri gecikmesi
- queue uzunluğu
- hata oranı
- model gecikmesi
- CPU/RAM
- API maliyeti

gibi metrikleri takip eder.

---

## Recovery

Bir servis çökerse:

```
Failure
    ↓
Detect
    ↓
Retry / Restart
    ↓
Resume from State
    ↓
Event Replay gerekiyorsa
    ↓
Continue
```

süreci çalışır.

---


---

**Kaynak:** Infrastructure — event-driven architecture. Cache. Job queue. Worker system.


### Örnek: Cache system

```python
# services/core/infrastructure.py
from services.core.infrastructure import cache_system

cache_system.set("market_state", state_data, ttl_seconds=300)
cached = cache_system.get("market_state")  # 5 dakika içinde
```

### Örnek: Job queue

```python
from services.core.infrastructure import job_queue

job_id = job_queue.enqueue("backtest", {"strategy": "momentum"}, priority="HIGH")
job = job_queue.dequeue()  # Priority sırasına göre
job_queue.complete(job_id, {"result": "success"})
```

## Temel prensip

Bu bölüm yatırım kararı vermez.

Diğer bütün bölümlerin:

> hızlı, ölçeklenebilir, event-driven, izlenebilir ve hata durumunda toparlanabilir

şekilde çalışmasını sağlar.

**Yani sistemin sinir sistemi + veri taşıma ağı + çalışma altyapısıdır.**
