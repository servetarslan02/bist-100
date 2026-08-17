# backtest/engine_v4

**Dosya:** `services/backtest/engine_v4.py`
**Satır:** 1225

## Açıklama

ALPHA BIST — Backtest Engine v4.0 (Institutional Grade)

Tasarım ilkeleri:
1. Finansal doğruluk: v2.0/v3.0 ile aynı sonuçlar
2. Ölçeklenebilirlik: 5000+ hisse
3. Deterministik: aynı veri → aynı sonuç
4. Denetlenebilir: tam audit trail
5. Dayanıklı: restart sonrası recovery

Optimizasyonlar:
- Pre-slice market data (bir kez)
- Batch signal processing
- Feature cache korunuyor
- Quality cache korunuyor
- Portfolio simulator v3.0 (audit + invariant)
- SQLite persistence

## Sınıflar (9)

- `BacktestConfig`
- `BacktestMetrics`
- `BacktestResultV4`
- `FeatureCache`
- `QualityCache`
- `BacktestEngineV4`
- `_FallbackCalculator`
- `_FallbackMask`
- `_FallbackQuality`

## Fonksiyonlar (31)

- `to_dict()`
- `to_dict()`
- `to_dict()`
- `__init__()`
- `get()`
- `set()`
- `clear()`
- `hit_rate()`
- `__init__()`
- `get()`
- `set()`
- `clear()`
- `__init__()`
- `_lazy_load()`
- `run()`
- `_run_legacy()`
- `_run_fast()`
- `_features_fast()`
- `_find_tie_members()`
- `_rescore_tie_members_scalar()`
- `_finalize_run()`
- `_get_features()`
- `_compute_score()`
- `_compute_score_legacy()`
- `_compute_score_canonical()`
- `_enrich_features_for_canonical()`
- `_generate_run_id()`
- `_empty_result()`
- `compute_all_features()`
- `compute_mask()`
- ... ve 1 daha

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/tradability_mask`
- `data/historical_adapter`
- `features/seven_motors`
- `features/panel_engine`
- `core/data_quality`
- `features/calculator`
- `features/cross_sectional`

