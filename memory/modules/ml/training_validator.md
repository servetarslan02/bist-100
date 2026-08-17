# ml/training_validator

**Dosya:** `services/ml/training_validator.py`
**Satır:** 809

## Açıklama

ALPHA BIST — Training Dataset Quality Validator

FAZ 4.2: ML training dataset kalite kontrolü.
Her eğitim öncesi çalışır, kalite sorunlarını tespit eder ve düzeltir.

Kontroller:
1. Sample metadata doğruluğu (ticker, feature_date, target_date)
2. Target = T+5 forward return doğrulaması
3. Train/test overlap/leakage tespiti
4. Cross-ticker sample oluşturma doğruluğu
5. NaN/inf/outlier tespiti ve temizleme
6. Feature dağılım analizi
7. Target dağılımı ve sample dengesi
8. Validation metrikleri (MA

## Sınıflar (5)

- `SampleMeta`
- `DataQualityReport`
- `ValidationMetrics`
- `TrainingDatasetValidator`
- `CrossSectionalNormalizer`

## Fonksiyonlar (13)

- `validate_dataset()`
- `_validate_sample_metadata()`
- `_validate_features()`
- `_validate_target_distribution()`
- `_validate_cross_ticker()`
- `_validate_leakage()`
- `_compute_quality_score()`
- `compute_validation_metrics()`
- `_compute_simple_ndcg()`
- `_precision_at_k()`
- `clean_features()`
- `normalize_zscore_by_date()`
- `normalize_rank_by_date()`

