# core/config_watcher

**Dosya:** `services/core/config_watcher.py`
**Satır:** 224

## Açıklama

ALPHA BIST — Config Hot Reload Watcher

Runtime config değişiklik algılama, güvenli reload, audit logging.

Özellikler:
- Dosya değişikliği algılama (mtime-based)
- Geçersiz config → eski config koruma
- Config değişiklik audit log
- Concurrent access safety

Kullanım:
    watcher = ConfigWatcher("config/alpha_config.json", ConfigLoader.load)
    watcher.start()
    # Config değişirse otomatik reload
    watcher.stop()

## Sınıflar (2)

- `ConfigAuditEntry`
- `ConfigWatcher`

## Fonksiyonlar (7)

- `to_dict()`
- `__init__()`
- `start()`
- `stop()`
- `get_audit_log()`
- `get_status()`
- `force_reload()`

