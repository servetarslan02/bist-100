# features/calculator

**Dosya:** `services/features/calculator.py`
**Satır:** 559

## Açıklama

ALPHA BIST — Feature Calculator v3.0 (Mask-First Design)

ROADMAP v3.0 FAZ 1-2:
- Mask-aware hesaplama (execute edilemeyen fiyatlar görmez)
- Cross-sectional rank features
- Sector relative features
- 7 motor çıktıları ile entegre

KURAL: Mask=0 olan günler feature hesaplamasında KULLANILMAMALI.

## Sınıflar (1)

- `FeatureCalculator`

## Fonksiyonlar (23)

- `__init__()`
- `compute_all_features()`
- `_enforce_scalar_features()`
- `_sma_masked()`
- `_ema_masked()`
- `_roc_masked()`
- `_momentum_masked()`
- `_rsi_masked()`
- `_macd_masked()`
- `_ema_on_array()`
- `_bollinger_masked()`
- `_stochastic_masked()`
- `_atr_masked()`
- `_adx_masked()`
- `_volume_zscore_masked()`
- `_volume_trend_masked()`
- `_obv_masked()`
- `_volatility_masked()`
- `_volume_profile()`
- `_higher_highs_masked()`
- `_lower_lows_masked()`
- `_inside_days_masked()`
- `compute_cross_sectional_features()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `features/sentiment`
- `features/technical_features`
- `features/macro`
- `features/bar_engine`
- `features/store`
- `features/discovery`
- `features/fundamental`
- `features/extended_indicators`
- `features/feature_selector`
- `features/cross_sectional`

