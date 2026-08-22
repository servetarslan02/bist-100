# EVENTS — Olay Altyapısı

> Bu belge hedef mimariyi tanımlar, bugün kodda gerçekte var olan/olmayan kısımlar için `CURRENT-STATE.md`'ye bakın.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                      EVENT INFRASTRUCTURE                       │
├─────────────────────┬───────────────────────────────────────────┤
│  Event Tanımları    │  Transport & Dağıtım                      │
├─────────────────────┼───────────────────────────────────────────┤
│ event_schema.py     │ event_bus.py                              │
│  ├─ CanonicalEvent  │  ├─ InternalEventBus (Redis Pub/Sub)      │
│  ├─ EventType enum  │  ├─ InMemoryRedis fallback                │
│  ├─ EventMetadata   │  ├─ publish_event() (Redis + Kafka)       │
│  └─ Typed schemas:  │  ├─ _publish_with_idempotency()           │
│    MarketTickData   │  ├─ _publish_to_stream() (durable ledger) │
│    NewsEventData    │  └─ EventConsumer (push-based)             │
│    KAPEventData     │                                           │
│    MacroEventData   │ dead_letter_queue.py                      │
│    SignalData       │  ├─ DLQEntry (PENDING/RETRYING/           │
│    AnomalyData      │  │   RESOLVED/EXHAUSTED)                   │
│    ImpactPropagat.  │  ├─ Exponential backoff retry              │
│                     │  └─ Handler registry                       │
│                     │                                           │
│                     │ services/events/ (dizin — henüz boş)       │
│                     │  └─ .gitkeep                               │
└─────────────────────┴───────────────────────────────────────────┘
```

> **Not**: `services/events/` dizini henüz boş (sadece `.gitkeep`). Tüm event altyapısı `services/core/event_bus.py`, `services/core/event_schema.py` ve `services/core/dead_letter_queue.py` içinde tanımlıdır.

## Neden Bu Teknoloji / Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Redis Pub/Sub** (primary transport) | Düşük latency, push-based, polling yok; mevcut event volume için Kafka gerektirmez |
| **Redis Stream** (durable ledger) | Subscriber kapalıyken event kaybolmamalı; `XADD` ile append-only log |
| **Kafka/Redpanda** (opsiyonel) | Yüksek volume senaryoları için hazır; `REDPANDA_BROKERS` env var tanımlıysa kullanılır |
| **In-memory fallback** | Docker/Redis yokken bile event sistemi çalışır |
| **Idempotent publish** | Aynı `event_id` tekrar publish edilmez (Redis `SET NX` + PostgreSQL fallback) |
| **Schema validation** | Yanlış payload event bus'a giremez; `_REQUIRED_FIELDS` ile zorunlu alanlar |
| **Dead Letter Queue** | Handler crash ederse event kaybolmaz; exponential backoff ile retry |
| **Pydantic BaseModel** | `CanonicalEvent` ve typed data schemas; JSON serialization, validation |

## Uçtan Uca Veri Akışı

```
1. Veri üretici (provider, orchestrator, agent) event oluşturur:
   event = CanonicalEvent(event_type=EventType.MARKET_TICK, payload={...})

2. publish_event(event) çağrılır:
   2a. Schema validation → eksik alan varsa publish etme
   2b. Kafka producer (opsiyonel) → REDPANDA_BROKERS tanımlıysa
   2c. _publish_with_idempotency(event):
       - Redis SET NX ile idempotency check
       - Duplicate ise skip
       - InternalEventBus.publish() → Redis Pub/Sub (push)
       - _publish_to_stream() → Redis Stream (durable ledger)
       - Fallback: PostgreSQL event_ledger tablosu

3. Subscriber'lar (EventConsumer) push ile event alır:
   3a. EventConsumer.start() → Redis Pub/Sub'a subscribe olur
   3b. Event geldiğinde _handle_event() çalışır
   3c. Idempotency check (in-memory set)
   3d. Handler çağrılır
   3e. Başarısız olursa → Dead Letter Queue'ya düşer

4. Dead Letter Queue:
   4a. DLQEntry oluşturulur (exponential backoff: 5s, 10s, 20s...)
   4b. retry_failed() → hazır entry'leri tekrar dener
   4c. Max retry aşılırsa → EXHAUSTED
   4d. Başarılı retry → RESOLVED (1 saat sonra temizlenir)
```

## Servis Sınırları ve Sorumlulukları

| Dosya | Sorumluluk | Katman |
|-------|-----------|--------|
| `services/core/event_schema.py` | `CanonicalEvent` yapısı, `EventType` enum (40+ tip), payload validation, typed data schemas | Tanımlama |
| `services/core/event_bus.py` | `InternalEventBus` (Redis Pub/Sub), `publish_event()` (Redis + Kafka), `EventConsumer` (push-based), idempotent publish, durable stream | Transport |
| `services/core/dead_letter_queue.py` | Başarısız event'ler için kalıcı kuyruk, exponential backoff retry, handler registry | Dayanıklılık |
| `services/events/` | Dizin henüz boş; gelecekte event-specific servisler buraya taşınabilir | Rezerv |

## Event Tipleri (EventType Enum)

| Kategori | Event Tipleri |
|----------|--------------|
| **Market** | `MARKET_TICK`, `MARKET_TRADE`, `MARKET_QUOTE`, `MARKET_ORDERBOOK` |
| **Haber/Olay** | `NEWS_RAW`, `NEWS_EVENT`, `KAP_EVENT`, `MACRO_EVENT`, `SOCIAL_EVENT` |
| **Durum** | `FEATURE_UPDATED`, `STATE_UPDATED`, `MARKET_STATE_CHANGED`, `WORLD_STATE_CHANGED`, `IMPACT_PROPAGATED` |
| **Sinyal** | `SIGNAL_GENERATED`, `ANOMALY_DETECTED`, `REGIME_CHANGED` |
| **Simülasyon** | `SIMULATION_REQUESTED`, `SIMULATION_COMPLETED` |
| **Risk** | `RISK_CHANGED`, `RISK_ALERT`, `KILL_SWITCH_TRIGGERED` |
| **Karar/Sipariş** | `DECISION_CREATED`, `ORDER_PLACED`, `ORDER_FILLED` |
| **Agent** | `AGENT_ANALYSIS_COMPLETED`, `AGENT_DEBATE_COMPLETED`, `AGENT_CONFLICT_DETECTED`, `AGENT_RISK_VETO`, `AGENT_EVALUATION_COMPLETED`, `AGENT_DRIFT_DETECTED` |
| **Öğrenme** | `PREDICTION_CREATED`, `OUTCOME_CREATED` |
| **Piyasa Durumu** | `BREADTH_ALERT`, `LIQUIDITY_ALERT`, `REGIME_TRANSITION`, `ANOMALY_CLUSTER`, `SENTIMENT_SHIFT`, `MULTI_TF_DIVERGENCE` |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Push-Based**: Sürekli polling yok; veri olduğunda anında push
2. **Idempotent**: Aynı event_id tekrar publish edilmez
3. **Durable**: Redis Stream ile subscriber kapalıyken event kaybolmaz
4. **Fail-Safe**: Handler crash → DLQ'ya düşer; event kaybolmaz
5. **Schema-Valid**: Yanlış payload publish edilemez
6. **Graceful Fallback**: Redis yoksa in-memory; Kafka yoksa Redis

### Kırmızı Çizgiler

- ❌ Schema validation geçmeyen event publish edilemez
- ❌ Aynı event_id iki kez publish edilemez (idempotency)
- ❌ Handler crash eden event kaybolamaz (DLQ'ya düşmeli)
- ❌ Polling tabanlı tüketim yapılamaz (push-based zorunlu)

## Bilinen Sınırlamalar

1. **In-memory DLQ**: Restart sonrası DLQ kayıtları kaybolur
2. **In-memory idempotency set**: `EventConsumer._processed_ids` 50.000'e kadar büyür, sonra temizlenir
3. **Redis Stream maxlen**: 10.000 event ile sınırlı; eski event'ler atılır
4. **Kafka opsiyonel**: `REDPANDA_BROKERS` tanımlı değilse Kafka hiç kullanılmaz
5. **`services/events/` boş**: Event-specific servisler henüz bu dizine taşınmadı
6. **PostgreSQL fallback**: `event_ledger` tablosu varsayılıyor; tablo yoksa fallback başarısız olur

## Cross-Reference

| Modül | Bağlantı |
|-------|----------|
| **core** | `orchestrator.py` → `publish_event()` ile DECISION_CREATED, AGENT_ANALYSIS_COMPLETED publish eder; `event_bus.py` singleton olarak tüm servisler tarafından kullanılır |
| **data** | `ingestion_pipeline.py` → KAP/News event'leri `EventSnapshot` olarak kaydeder; event_bus üzerinden publish edilebilir |
| **labels** | `generator.py` → event'lerden değil, fiyat verisinden label üretir; ama event'ler label kalitesini etkileyebilir |
| **intelligence** | `news_pipeline.py` → `NEWS_EVENT` tüketir; `regime.py` → `REGIME_CHANGED` publish eder |
| **risk** | `risk_gate.py` → `RISK_ALERT` publish eder; `kill_switch` → `KILL_SWITCH_TRIGGERED` |
| **agents** | `agent_pipeline.py` → `AGENT_ANALYSIS_COMPLETED`, `AGENT_DEBATE_COMPLETED` publish eder |
| **learning** | `outcome_tracker.py` → `PREDICTION_CREATED`, `OUTCOME_CREATED` tüketir |
