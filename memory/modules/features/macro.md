# features/macro

**Dosya:** `services/features/macro.py`
**Satır:** 281

## Açıklama

ALPHA BIST — Macro Feature Engine v1.0

Makro verilerden feature üretir:
- USD/TRY z-score, momentum, percentile, regime
- Faiz (TCMB policy rate, differential)
- Enflasyon (CPI, PPI, trend)
- VIX normalize
- Emtia (petrol, altın)
- Global risk appetite

FAZ 2.3: Macro Features

## Sınıflar (1)

- `MacroFeatureEngine`

## Fonksiyonlar (9)

- `__init__()`
- `update_history()`
- `compute_currency_features()`
- `compute_rate_features()`
- `compute_inflation_features()`
- `compute_vix_features()`
- `compute_commodity_features()`
- `compute_global_features()`
- `compute_all_macro_features()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `macro/tcmb`
- `macro/credit`
- `macro/current_account`
- `macro/fx`
- `macro/inflation`
- `macro/cds`

