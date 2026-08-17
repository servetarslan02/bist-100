# backtest/canonical_adapter

**Dosya:** `services/backtest/canonical_adapter.py`
**Satır:** 165

## Açıklama

ALPHA BIST — Backtest Canonical Scoring Adapter v2.0

FAZ 4.7: Artık prepare_features_for_inference() kullanır.
Feature parity training ile garanti edilir.

Bu adapter:
- Backtest'teki feature snapshot'tan canonical score üretir
- PIT (Point-in-Time) koruması sağlar
- prepare_features_for_inference() ile CS normalization uygular
- Feature contract'ı zorunlu kılar
- Mevcut backtest API'sini bozmaz

## Sınıflar (1)

- `BacktestCanonicalAdapter`

## Fonksiyonlar (5)

- `__init__()`
- `_lazy_load()`
- `compute_score()`
- `compute_score_and_decision()`
- `enrich_features_for_canonical()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/decision_engine`
- `ml/training_validator`
- `core/canonical_scoring`

