# core/data_quality

**Dosya:** `services/core/data_quality.py`
**Satır:** 231

## Açıklama

ALPHA BIST — Data Quality & Tradability Mask v1.0

ROADMAP v3.0: Mask-First Design
- Devre kesici, tavan/taban, halt edilmiş fiyatlar maskelenir
- Hiçbir feature hesaplaması mask=0 olan fiyatı görmez
- Bu tek başına +0.44 Sharpe katkısı (Du 2026)

KURAL: Execute edilemeyen fiyat kullanma!

## Sınıflar (5)

- `TradabilityMask`
- `DataQualityEngine`
- `QualityIssue`
- `QualityReport`
- `DataQualityChecker`

## Fonksiyonlar (12)

- `to_dict()`
- `__init__()`
- `check_tradability()`
- `apply_mask()`
- `get_mask()`
- `get_untradable_count()`
- `get_mask_stats()`
- `_get_reasons_breakdown()`
- `__post_init__()`
- `to_dict()`
- `to_dict()`
- `full_quality_check()`

