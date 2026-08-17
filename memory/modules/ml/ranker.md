# ml/ranker

**Dosya:** `services/ml/ranker.py`
**Satır:** 238

## Açıklama

ALPHA BIST — Learning-to-Rank Model v1.0

ROADMAP v3.0: Regresyon değil sıralama!
- LightGBM Ranker kullan (LGBMRanker)
- Her gün hisseleri sırala, en üsttekini al
- Bu tek başına +0.44 Sharpe katkısı

KURAL: En iyi hisseyi bul, fiyat tahmini yapma!

## Sınıflar (1)

- `LearningToRankModel`

## Fonksiyonlar (6)

- `__init__()`
- `prepare_training_data()`
- `train()`
- `rank()`
- `_fallback_rank()`
- `get_feature_importance()`

