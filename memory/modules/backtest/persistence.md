# backtest/persistence

**Dosya:** `services/backtest/persistence.py`
**Satır:** 250

## Açıklama

ALPHA BIST — Backtest Persistence Layer v1.0

SQLite-based persistence for backtest results:
- Run metadata
- Trades
- Equity curve
- Performance metrics

Recovery: restart sonrası eksiksiz veri yükler.

## Sınıflar (1)

- `BacktestPersistence`

## Fonksiyonlar (10)

- `__init__()`
- `_ensure_db()`
- `save_run()`
- `save_trades()`
- `save_equity_curve()`
- `get_run()`
- `get_trades()`
- `get_equity_curve()`
- `list_runs()`
- `delete_run()`

