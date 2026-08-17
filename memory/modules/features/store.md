# features/store

**Dosya:** `services/features/store.py`
**Satır:** 175

## Açıklama

ALPHA BIST — Feature Store v1.0

Tüm feature'ların canonical kaynağı:
- Versioned storage (v1, v2, ...)
- Redis hot cache
- DB persistence
- Feature history
- Feature metadata

FAZ 2.5: Feature Store + Versioning

## Sınıflar (2)

- `FeatureValue`
- `FeatureStore`

## Fonksiyonlar (13)

- `__init__()`
- `to_dict()`
- `__init__()`
- `get()`
- `get_all()`
- `set()`
- `get_history()`
- `get_metadata()`
- `register_version()`
- `get_version_info()`
- `get_feature_hash()`
- `get_stats()`
- `clear()`

