# core/alert_policy

**Dosya:** `services/core/alert_policy.py`
**Satır:** 806

## Açıklama

ALPHA BIST — Alert Policy Configuration v3.0

Kurumsal operasyon: diff, optimistic locking, webhook, batch silence.

Özellikler:
- Policy diff (eski/yeni/değişen alanlar)
- Optimistic locking (çakışan güncellemeleri engelle)
- Policy change webhook notification
- Batch silence işlemleri (transaction)
- Audit log (her değişiklik)

## Sınıflar (5)

- `PolicyDiff`
- `PolicyAuditEntry`
- `SilenceRule`
- `VersionConflictError`
- `AlertPolicy`

## Fonksiyonlar (44)

- `has_changes()`
- `to_dict()`
- `summary()`
- `to_dict()`
- `is_active()`
- `is_expired()`
- `matches()`
- `to_dict()`
- `_ts_iso()`
- `load()`
- `reload_if_changed()`
- `update()`
- `compute_diff()`
- `_compute_diff()`
- `three_way_diff()`
- `_get_history_version()`
- `acquire_edit_lock()`
- `release_edit_lock()`
- `is_locked()`
- `get_lock_info()`
- `rollback()`
- `set_webhook_urls()`
- `_notify_change()`
- `add_silence()`
- `batch_add_silences()`
- `batch_remove_silences()`
- `remove_silence()`
- `is_silenced()`
- `get_active_silences()`
- `load_silences_from_db()`
- ... ve 14 daha

