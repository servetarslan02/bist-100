# core/config

**Dosya:** `services/core/config.py`
**Satır:** 190

## Açıklama

ALPHA BIST - Configuration Management v2.0

P0-1: Security hardened.
- Production'da insecure default'lara izin verilmez.
- Startup validation zorunlu.
- Environment ayrımı (development/staging/production).
- Secret minimum length kontrolü.

## Sınıflar (1)

- `Settings`

## Fonksiyonlar (7)

- `is_production()`
- `postgres_url()`
- `postgres_url_sync()`
- `redis_url()`
- `_validate_production_security()`
- `_validate_port()`
- `_validate_pg_port()`

