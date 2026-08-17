# core/database_dev

**Dosya:** `services/core/database_dev.py`
**Satır:** 336

## Açıklama

ALPHA BIST — Development Database Adapter

Docker/PostgreSQL/Redis olmadığında SQLite + InMemory kullanır.
Production'da database.py kullanılır.

Kullanım:
  from services.core.database_dev import dev_db

## Sınıflar (1)

- `DevDatabase`

## Fonksiyonlar (3)

- `__init__()`
- `_translate_query()`
- `redis_subscribe()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/database_dev`

