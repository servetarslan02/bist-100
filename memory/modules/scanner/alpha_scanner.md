# scanner/alpha_scanner

**Dosya:** `services/scanner/alpha_scanner.py`
**Satır:** 422

## Açıklama

ALPHA BIST — Alpha Scanner v1.0

Tek merkezi pipeline:
800 hisse → data → canonical bars → incremental features →
market regime → quant scan → opportunity score → rank → signals

Bu, ALPHA'nın kalbidir.

## Sınıflar (3)

- `SignalType`
- `ScannerResult`
- `AlphaScanner`

## Fonksiyonlar (9)

- `__init__()`
- `scan()`
- `_scan_single()`
- `_calc_breakout()`
- `_calc_volume_acceleration()`
- `_calc_regime_fit()`
- `_calc_opportunity_score()`
- `_generate_signal()`
- `get_summary()`

