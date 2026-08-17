# learning/outcome_tracker

**Dosya:** `services/learning/outcome_tracker.py`
**Satır:** 181

## Açıklama

ALPHA BIST — Outcome Tracker v1.0

Tahmin sonuçlarını otomatik takip eder:
- Her prediction için bekleme süresi (5 gün default)
- Süre dolduğunda gerçek fiyatı çek
- Outcome kaydet
- Learning system'a bildir

Bu modül learning'in çalışması için KRİTİK.

## Sınıflar (1)

- `OutcomeTracker`

## Fonksiyonlar (5)

- `__init__()`
- `add_prediction()`
- `_calculate_holding_days()`
- `get_pending_count()`
- `get_stats()`

