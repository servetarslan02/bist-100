# ingestion/universe_enhancements

**Dosya:** `services/ingestion/universe_enhancements.py`
**Satır:** 204

## Açıklama

ALPHA BIST — BIST Universe Enhancements v1.0

- Likidite skoru
- Market cap bilgisi
- Listing status
- Survivorship bias koruması
- Cross-source reconciliation
- Outlier detection

## Sınıflar (5)

- `InstrumentInfo`
- `UniverseEnhancements`
- `CrossSourceReconciliation`
- `OutlierDetector`
- `SurvivorshipBiasProtection`

## Fonksiyonlar (10)

- `compute_liquidity_score()`
- `classify_listing_status()`
- `reconcile_price()`
- `detect_zscore_outliers()`
- `detect_iqr_outliers()`
- `__init__()`
- `mark_delisted()`
- `is_delisted()`
- `get_active_universe()`
- `get_delisted()`

