# features/incremental_state

**Dosya:** `services/features/incremental_state.py`
**Satır:** 353

## Açıklama

ALPHA BIST - Incremental Feature State v1.2

v1.2 Düzeltmeler:
- ATR: completed bar'dan güncellenir, tick'ten değil
- 5m aggregation: zaman bazlı bucket (timestamp bucket)
- Daily bars: doğru aggregation
- return_1d: günlük return (tick-to-tick değil)
- momentum_5d/20d: timeframe bazlı
- MACD signal: gerçek 9-period EMA
- RSI: tek canonical Wilder implementation

## Sınıflar (4)

- `OHLCBar`
- `TimeframeState`
- `IncrementalAssetState`
- `IncrementalStateManager`

## Fonksiyonlar (14)

- `process_tick()`
- `get_all_bars()`
- `get_last_n_bars()`
- `process_tick()`
- `_update_rsi()`
- `_update_ema()`
- `_update_atr_from_bar()`
- `get_incremental_features()`
- `__init__()`
- `get_or_create()`
- `process_tick()`
- `get_state()`
- `get_all_states()`
- `get_features()`

