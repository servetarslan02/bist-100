# ML Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 27 |
| Toplam satır | ~9,317 |
| Test sayısı | 25 |
| Model mimarisi | 5 (LightGBM, CatBoost, XGBoost, LSTM, Transformer) |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| ranker.py | ✅ TAM | LGBMRanker, rule-based fallback |
| ranking_model.py | ✅ TAM | LambdaRank + Adjusted-MSE + Rejim |
| lightgbm_trainer.py | ✅ TAM | Date-space purge, multi-horizon |
| catboost_model.py | ✅ TAM | Custom loss, SHAP |
| ensemble.py | ✅ TAM | Ağırlıklı ortalama |
| stacking_ensemble.py | ✅ TAM | Ridge meta-learner |
| champion_challenger.py | ✅ TAM | A/B test, auto-promote |
| calibration.py | ✅ TAM | Brier, ECE, Platt scaling |
| feature_drift.py | ✅ TAM | PSI, SHAP trend |
| model_registry.py | ✅ TAM | Versiyon takibi |
| hyperparameter_tuner.py | ✅ TAM | Optuna Bayesian |
| model_monitor.py | ✅ TAM | Decay detection |
| model_comparator.py | ✅ TAM | IC, Sharpe, Precision@K |
| walk_forward.py | ✅ TAM | Purge + embargo |
| training_validator.py | ✅ TAM | Dataset kalite kontrolü |
| adjusted_loss.py | ✅ TAM | Yanlış yön 11x ceza |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Sentetik veri ile eğitim | P1 | Gerçek BIST verisiyle eğitim tam entegre değil |
| LSTM/Transformer sınırlı | P2 | Deneysel aşamada |
| Feature sayısı | P2 | Cross-sectional normalization sadece temel feature'lara |
| Regime tespiti bağımlılığı | P2 | Yanlış etiket tüm sistemi etkiler |
| SHAP maliyeti | P2 | Büyük dataset'lerde yavaş |
| CatBoost custom loss | P2 | Production'da tam test edilmedi |
| RL deneysel | P2 | rl_agent.py ve finrl_bist.py aktif değil |
