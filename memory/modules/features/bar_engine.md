# features/bar_engine

**Dosya:** `services/features/bar_engine.py`
**Satır:** 213

## Açıklama

ALPHA BIST — Canonical Bar Engine v1.0

Tick → 1m → 5m → 15m → 1h → 1d

Live ve replay aynı engine'i kullanır.
Tek canonical OHLC kaynağı.

## Sınıflar (4)

- `Bar`
- `TimeframeConfig`
- `BarEngine`
- `BarEngineManager`

## Fonksiyonlar (13)

- `to_dict()`
- `__init__()`
- `process_tick()`
- `_get_bar_timestamp()`
- `get_bars()`
- `get_current_bar()`
- `get_all_bars_numpy()`
- `get_latest_complete()`
- `warmup_from_history()`
- `__init__()`
- `get_engine()`
- `process_tick()`
- `get_all_tickers()`

