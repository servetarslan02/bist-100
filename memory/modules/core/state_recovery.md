# core/state_recovery

**Dosya:** `services/core/state_recovery.py`
**Satır:** 216

## Açıklama

ALPHA BIST — State Recovery v2.0

P0-7 düzeltmesi:
- Snapshot + Event Log approach (60 günlük veriyi yeniden çekme YOK)
- Recovery deterministic olmalı
- Snapshot → events after snapshot → replay → state validation
- Consistency check sonrası current state

## Sınıflar (1)

- `StateRecovery`

## Fonksiyonlar (4)

- `__init__()`
- `get_state()`
- `get_all_states()`
- `get_recovery_errors()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `features/calculator`

