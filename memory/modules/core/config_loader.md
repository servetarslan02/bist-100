# core/config_loader

**Dosya:** `services/core/config_loader.py`
**Satır:** 198

## Açıklama

ALPHA BIST — Config Loader with Environment Override

Özellikler:
- JSON config dosyasından yükleme
- Environment variable override
- development/test/production ayrımı
- Secret değerler config dosyasında tutulmaz
- Nested key desteği (dot notation)

Kullanım:
    config = ConfigLoader.load("config/alpha_config.json")
    port = config.get("app.port", 8000)
    secret = config.get_secret("jwt_secret")  # ENV'den okur

## Sınıflar (1)

- `ConfigLoader`

## Fonksiyonlar (17)

- `load()`
- `reset()`
- `get()`
- `get_secret()`
- `get_int()`
- `get_float()`
- `get_bool()`
- `get_list()`
- `environment()`
- `is_production()`
- `is_development()`
- `is_test()`
- `to_dict()`
- `_apply_env_overrides()`
- `_convert_value()`
- `_set_nested()`
- `_deep_merge()`

