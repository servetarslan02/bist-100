# core/event_bus

**Dosya:** `services/core/event_bus.py`
**Satır:** 396

## Açıklama

ALPHA BIST - Event Bus v1.3 (Push-Based Internal Architecture)

Dış kaynaklardan veri PUSH ile gelir.
İç servisler arası iletişim REDIS PUB/SUB ile olur.
Sürekli API isteği YOKTUR.

## Sınıflar (3)

- `InternalEventBus`
- `InMemoryRedis`
- `EventConsumer`

## Fonksiyonlar (7)

- `__init__()`
- `__init__()`
- `pubsub()`
- `publish_local()`
- `__init__()`
- `on()`
- `stop()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/database_dev`

