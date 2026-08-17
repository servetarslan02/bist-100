# backtest/walk_forward

**Dosya:** `services/backtest/walk_forward.py`
**Satır:** 436

## Açıklama

ALPHA BIST — Walk-Forward Validation v3.0

ROADMAP v3.0 FAZ 1, 4:
- Purge: train sonu → test başı arası gap (5 gün)
- Embargo: test sonu → bir sonraki train arası gap (5 gün)
- Data leakage koruması (KESİN)
- Precision@K, IC, Deflated Sharpe metrikleri

KURAL: Gelecek veriyi train'de kullanmak = ölüm.

## Sınıflar (3)

- `WalkForwardFold`
- `WalkForwardResult`
- `WalkForwardEngine`

## Fonksiyonlar (7)

- `__init__()`
- `create_folds()`
- `run_walk_forward()`
- `_calculate_fold_metrics()`
- `_deflated_sharpe()`
- `_aggregate_results()`
- `_empty_result()`

