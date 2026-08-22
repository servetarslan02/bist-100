# Learning Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 73 |
| Toplam satır | ~18,975 |
| Test sayısı | 30 |
| Katman sayısı | 6 |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| integrated_learning.py | ✅ TAM | Prediction/outcome kaydı |
| continuous_learning.py | ✅ TAM | Günlük pipeline |
| learning_loop.py | ✅ TAM | Ana döngü |
| drift_detector.py | ✅ TAM | PSI, KS, ADWIN, Page-Hinkley |
| champion_challenger.py | ✅ TAM | Promote/reject, canary deploy |
| calibration.py | ✅ TAM | Brier, ECE, Platt scaling |
| attribution.py | ✅ TAM | Macro, flow, momentum, event |
| feature_tracker.py | ✅ TAM | SHAP-based importance |
| health_monitor.py | ✅ TAM | Modül sağlık izleme |
| outcome_tracker.py | ✅ TAM | 5 gün bekle, fiyat çek |
| shadow_manager.py | ✅ TAM | Paralel çalıştırma |
| retrain_engine.py | ✅ TAM | Walk-forward validated |
| model_registry.py | ✅ TAM | Versiyon takibi |
| meta_learner.py | ✅ TAM | Rejim-specific selection |
| super_intelligence.py | ✅ TAM | Self-healing |
| config/learning_config.py | ✅ TAM | Pydantic, env override |
| utils/statistical_tests.py | ✅ TAM | PSI, KS, ADWIN, PH, Welch |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Phase scriptleri araştırma | P2 | Production pipeline parçası değil |
| Super Intelligence karmaşıklık | P2 | Çok fazla sorumluluk taşıyor |
| Outcome takibi asenkron | P2 | Fiyat kaynağı yoksa outcome kaydedilemez |
| Regime bağımlılığı | P2 | Yanlış etiket tüm sistemi etkiler |
| SHAP maliyeti | P2 | Büyük dataset'lerde yavaş |
| Config override sınırlı | P2 | İki seviye nested destek |
| Model memory store | P2 | Henüz tam entegre değil |
| Kurumsal modüller deneysel | P2 | institutional_walkforward vb. |
