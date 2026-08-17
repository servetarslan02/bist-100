# ml/walk_forward

**Dosya:** `services/ml/walk_forward.py`
**Satır:** 196

## Açıklama

ALPHA BIST — Walk-Forward Validation v1.0

ROADMAP v3.0: 
- Purge: Train/test arasına boşluk (look-ahead bias önleme)
- Embargo: Test sonrası boşluk (information leakage önleme)
- Expanding window: Her adımda daha fazla veri

KURAL: Gelecekten bilgi sızdırma!

## Sınıflar (2)

- `WFResult`
- `WalkForwardValidation`

## Fonksiyonlar (5)

- `__init__()`
- `generate_splits()`
- `evaluate()`
- `_calculate_metrics()`
- `get_aggregated_metrics()`

