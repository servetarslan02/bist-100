# learning/super_intelligence

**Dosya:** `services/learning/super_intelligence.py`
**Satır:** 621

## Açıklama

ALPHA BIST — Super Intelligence Engine v3.0

SÜPER AKILLI, TAM OTOMATİK, KENDİ KENDİNİ YÖNETEN SİSTEM

Özellikler:
- Self-healing: Hata olduğunda kendi kendini onarır
- Auto-retrain: Model performansı düştüğünde otomatik yeniden eğitir
- A/B testing: Yeni model vs eski model karşılaştırması
- Drift detection: Veri dağılımı değiştiğinde alarm
- Meta-learning: Hangi model ne zaman daha iyi performans gösteriyor öğrenir
- Auto-hyperparameter tuning: Optimal parametreleri kendi bulur
- Cascade failu

## Sınıflar (4)

- `SystemHealth`
- `ModelVersion`
- `ABTestResult`
- `SuperIntelligenceEngine`

## Fonksiyonlar (21)

- `__init__()`
- `detect_and_heal()`
- `execute_healing()`
- `check_retrain_needed()`
- `auto_retrain()`
- `detect_drift()`
- `update_baseline()`
- `_start_ab_test()`
- `evaluate_ab_test()`
- `record_performance()`
- `get_best_model_for_regime()`
- `get_health_status()`
- `update_module_status()`
- `daily_cycle()`
- `_calculate_recent_metrics()`
- `_generate_version_id()`
- `_trigger_retrain()`
- `_trigger_data_refresh()`
- `_restart_module()`
- `_retry_with_backoff()`
- `_activate_fallback()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `ml/ranking_model`

