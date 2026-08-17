# ml/lightgbm_trainer

**Dosya:** `services/ml/lightgbm_trainer.py`
**Satır:** 746

## Açıklama

ALPHA BIST — LightGBM Training Pipeline v3.0 (Production-Hardened)

FAZ 4.4 değişiklikleri:
- purge_gap artık SAMPLE-SPACE değil DATE-SPACE'de çalışıyor
- purge_gap = max(forward_horizon, purge_gap_days) gerçek tarih gününde
- Scaler/impute sadece TRAIN split'inden öğrenilir (data leakage yok)
- Multi-horizon target (1d/5d/20d/60d) altyapısı, horizon-aware purge
- Cross-sectional normalization feature contract ile tutarlı
- Model metadata (confidence, metrics) kalıcı field olarak saklanır
- Dete

## Sınıflar (5)

- `MLModelConfig`
- `TrainedModel`
- `MultiHorizonModel`
- `TargetSpec`
- `LightGBMTrainer`

## Fonksiyonlar (25)

- `predict()`
- `predict_batch()`
- `_feature_vector()`
- `save()`
- `load()`
- `primary_model()`
- `predict()`
- `predict_horizon()`
- `get_all_predictions()`
- `available_horizons()`
- `total_train_samples()`
- `train_samples()`
- `train_date_range()`
- `validation_score()`
- `validation_metrics()`
- `confidence_score()`
- `feature_names()`
- `label()`
- `__init__()`
- `train()`
- `_prepare_data()`
- `_compute_impute_values()`
- `_impute()`
- `_compute_groups_from_indices()`
- `_compute_ndcg()`

