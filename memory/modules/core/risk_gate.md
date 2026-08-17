# core/risk_gate

**Dosya:** `services/core/risk_gate.py`
**Satır:** 180

## Açıklama

ALPHA BIST — Risk Gate v1.0

Merkezi risk kontrolü — order gönderilmeden önce.
Fail-safe, fail-closed.

## Sınıflar (2)

- `RiskDecision`
- `RiskGate`

## Fonksiyonlar (5)

- `__post_init__()`
- `__init__()`
- `check_order()`
- `update_daily_pnl()`
- `reset_daily()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/short_selling`
- `core/price_limits`
- `core/halt_monitor`
- `core/compliance`

