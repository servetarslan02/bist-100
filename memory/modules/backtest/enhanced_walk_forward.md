# backtest/enhanced_walk_forward

**Dosya:** `services/backtest/enhanced_walk_forward.py`
**Satır:** 369

## Açıklama

ALPHA BIST — Enhanced Walk-Forward & Evaluation v1.0

Walk-Forward with purge + embargo:
- Purge: Gap between train end and test start (prevents leakage)
- Embargo: Gap between test end and next train start (prevents leakage)

Evaluation metrics:
- Alpha, Precision@K, IC, Hit Rate, Sharpe, Max DD, Turnover
- Deflated Sharpe Ratio (overfitting detection)

Kaynak: Du (2026), Huang (2026), Oxford (2023)

## Sınıflar (3)

- `WalkForwardFold`
- `WalkForwardResult`
- `PurgeEmbargoWalkForward`

## Fonksiyonlar (12)

- `__init__()`
- `split()`
- `run()`
- `_precision_at_k()`
- `_compute_ic()`
- `_compute_hit_rate()`
- `_compute_top_k_return()`
- `_compute_daily_returns()`
- `_compute_sharpe()`
- `_compute_max_drawdown()`
- `_compute_turnover()`
- `_deflated_sharpe()`

