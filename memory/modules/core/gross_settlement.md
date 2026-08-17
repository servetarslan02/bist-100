# core/gross_settlement

**Dosya:** `services/core/gross_settlement.py`
**Satır:** 77

## Açıklama

ALPHA BIST — Gross Settlement Monitor

Brüt takas kontrolü:
- Brüt takaslı hisselerde açığa satış yasak
- T+0 ödeme (nakit aynı gün)
- SPK tarafından belirlenir

## Sınıflar (2)

- `GrossSettlementStatus`
- `GrossSettlementMonitor`

## Fonksiyonlar (8)

- `__post_init__()`
- `to_dict()`
- `__init__()`
- `set_gross_tickers()`
- `add_gross_ticker()`
- `remove_gross_ticker()`
- `check_gross_settlement()`
- `get_all_gross()`

