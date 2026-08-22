# Events

**Modül sayısı:** 3 (core içinde) | **Toplam satır:** ~1,000 | **Test sayısı:** 8

## Modüller

| Modül | Dosya | Sınıf/Fonksiyon | Açıklama |
|-------|-------|-----------------|----------|
| Event Schema | `core/event_schema.py` | CanonicalEvent, EventType (40+ tip), EventMetadata, Typed data schemas | Canonical event yapısı, payload validation |
| Event Bus | `core/event_bus.py` | InternalEventBus, EventConsumer, publish_event() | Redis Pub/Sub + Stream (durable ledger) + Kafka opsiyonel |
| Dead Letter Queue | `core/dead_letter_queue.py` | DLQEntry, DLQStatus (PENDING/RETRYING/RESOLVED/EXHAUSTED) | Başarısız event'ler için kalıcı kuyruk, exponential backoff retry |

> **Not**: `services/events/` dizini henüz boş (sadece `.gitkeep`). Tüm event altyapısı `services/core/` içinde tanımlıdır.

## Spec Uyumu

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Push-based tüketim | ✅ TAM | Redis Pub/Sub, polling yok |
| Idempotent publish | ✅ TAM | Redis SET NX + PostgreSQL fallback |
| Durable stream | ✅ TAM | Redis Stream, maxlen 10.000 |
| DLQ entegrasyonu | ✅ TAM | Handler crash → DLQ push |
| Schema validation | ✅ TAM | `_REQUIRED_FIELDS` ile zorunlu alanlar |
| Kafka opsiyonel | ✅ TAM | `REDPANDA_BROKERS` tanımlıysa aktif |

## Düzeltilen Sorunlar (2026-08-20)

1. **Event Bus → DLQ entegrasyonu** — `event_bus.py`'de handler crash → DLQ push mekanizması eklendi
2. **Sessiz hata yönetimi** — `except: pass` blokları logger'larla değiştirildi
