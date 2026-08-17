# backtest/walk_forward_runner

**Dosya:** `services/backtest/walk_forward_runner.py`
**Satır:** 649

## Açıklama

ALPHA BIST — Walk-Forward Backtest Runner v1.0

BacktestEngineV4 + WalkForwardEngine (purge + embargo) gerçek entegrasyonu.

Güvenceler:
1. POINT-IN-TIME: Her fold için piyasa verisi test_end'e kadar KESİLİR.
   Engine gelecek veriyi fiziksel olarak göremez.
2. PURGE: train_end → test_start arası gap korunur (WalkForwardEngine.create_folds).
3. EMBARGO: test_end → sonraki train arası gap fold metadata'sında korunur.
4. LEAKAGE GUARD: Fold sınırları, trade tarihleri ve equity tarihleri
   çalışma

## Sınıflar (3)

- `FoldBacktestResult`
- `WalkForwardBacktestResult`
- `WalkForwardBacktestRunner`

## Fonksiyonlar (11)

- `to_dict()`
- `to_dict()`
- `__init__()`
- `run()`
- `_train_fold_model()`
- `_get_canonical_feature_names()`
- `_truncate()`
- `_verify_fold()`
- `_aggregate()`
- `_base_run_id()`
- `_empty_result()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/model_persistence`
- `core/canonical_scoring`
- `ml/lightgbm_trainer`
- `ml/training_validator`
- `features/calculator`

