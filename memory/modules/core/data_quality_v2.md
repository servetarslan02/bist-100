# core/data_quality_v2

**Dosya:** `services/core/data_quality_v2.py`
**Satır:** 301

## Açıklama

ALPHA BIST — Data Quality v2.0 [DEPRECATED → data_quality.py'ye birleştirildi]

Gelişmiş veri kalitesi kontrolleri.

Kontroller:
- Duplicate veri tespiti
- Veri gecikmesi (stale data)
- Ani veri kopması (gap detection)
- Anormal hacim tespiti
- Fiyat boşlukları (price gaps)
- Veri tutarlılık kontrolü

Kullanım:
    dq = DataQualityV2()
    report = dq.full_quality_check(df, ticker="THYAO")

## Sınıflar (3)

- `QualityIssue`
- `QualityReport`
- `DataQualityV2`

## Fonksiyonlar (13)

- `to_dict()`
- `to_dict()`
- `__init__()`
- `full_quality_check()`
- `_check_duplicates()`
- `_check_staleness()`
- `_check_gaps()`
- `_check_volume_anomalies()`
- `_check_price_gaps()`
- `_check_ohlc_consistency()`
- `_check_missing_data()`
- `_check_future_dates()`
- `_calculate_score()`

