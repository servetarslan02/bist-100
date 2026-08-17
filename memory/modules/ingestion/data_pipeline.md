# ingestion/data_pipeline

**Dosya:** `services/ingestion/data_pipeline.py`
**Satır:** 204

## Açıklama

ALPHA BIST — Data Pipeline with Quality Gate

Ingestion → Data Quality v2 → Feature Engine → Scanner

Özellikler:
- Her veri akışında quality score
- Başarısız veri reddetme + sebep kaydı
- Audit trail
- Pipeline metrics

Kullanım:
    pipeline = DataPipeline()
    result = pipeline.process(market_data)

## Sınıflar (3)

- `PipelineResult`
- `PipelineReport`
- `DataPipeline`

## Fonksiyonlar (8)

- `to_dict()`
- `to_dict()`
- `_count_rejections()`
- `__init__()`
- `process()`
- `_process_single()`
- `_get_primary_rejection_reason()`
- `_add_audit()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/tradability_mask`
- `features/calculator`
- `core/data_quality`

