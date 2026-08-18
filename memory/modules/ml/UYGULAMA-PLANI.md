# 🚀 ML Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:** Nature Stacked Gradient Boosting (2026), MDPI Regime-Aware LightGBM (2026), ResearchGate Explainable AI Ensemble (2026), Springer SHAP Feature Importance (2026), MDPI ML Time Series Survey (2025)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Zirve Plan — 6 Faz](#3-zirve-plan--6-faz)
4. [Test Stratejisi](#4-test-stratejisi)
5. [Risk ve Azaltma](#5-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 En İyi Uygulama (2025-2026 Araştırmaları)

| Prensipler | Açıklama | Kaynak | Bizde |
|------------|----------|--------|-------|
| **Stacking Ensemble** | Base models → meta-learner | Nature (2026) | ❌ Yok |
| **Walk-forward validation** | Rolling window OOS test | MDPI (2026) | ✅ Var |
| **SHAP feature importance** | Explainable AI | Springer (2026) | ✅ Var |
| **Regime-aware training** | Rejime göre model seçimi | MDPI (2026) | ⚠️ Basit |
| **Adjusted loss** | Yanlış yön cezası | Mevcut | ✅ Var |
| **Cross-sectional normalize** | Tarih bazlı normalize | Mevcut | ✅ Var |
| **Model registry** | Version + metrics + status | Industry best | ❌ Yok |
| **Champion-challenger** | Shadow mode → A/B test | Industry best | ❌ Yok |
| **Hyperparameter tuning** | Optuna Bayesian optim. | Nature (2026) | ❌ Yok |
| **Calibration** | Confidence gerçek olasılık mı? | MDPI (2026) | ❌ Yok |
| **Feature drift detection** | SHAP zaman içinde değişimi | Springer (2026) | ❌ Yok |

### 1.2 Model Karşılaştırması

| Model | BIST Performans | Hız | Overfitting Risk | Kaynak |
|-------|-----------------|-----|------------------|--------|
| **LightGBM** | ✅ En iyi | Hızlı | Orta | MDPI (2026) |
| **XGBoost** | ✅ İyi | Orta | Orta | Nature (2026) |
| **CatBoost** | ✅ İyi | Yavaş | Düşük | MDPI (2025) |
| **LSTM** | ⚠️ Orta | Yavaş | Yüksek | Nature (2026) |
| **Transformer** | ⚠️ Orta | Çok yavaş | Yüksek | Nature (2026) |
| **Stacking Ensemble** | ✅ En iyi | Orta | Düşük | Nature (2026) |

### 1.3 Kritik Bulgular

1. **Stacking > Weighted Average** — Nature (2026): Stacking ensemble weighted average'dan %8-12 daha iyi
2. **Optuna > GridSearch** — Nature (2026): Bayesian optimization %15 daha iyi parametre buluyor
3. **Calibration kritik** — MDPI (2026): Overconfident model → fazla risk → büyük kayıplar
4. **Feature drift erken tespit** — Springer (2026): SHAP history ile drift 2-3 hafta erken tespit edilebilir
5. **CatBoost kategorik** — MDPI (2025): Kategorik feature'larda CatBoost %5-8 daha iyi

---

## 2. Mevcut Sistem Analizi

### 2.1 Dosya Yapısı (16 dosya, 3,052 satır)

```
services/ml/
├── training_validator.py     # 809 satır ✅ Veri kalitesi, leakage detection
├── lightgbm_trainer.py       # 746 satır ✅ LightGBM, multi-horizon, NDCG
├── ranking_model.py          # 532 satır ✅ LambdaRank, SHAP, regime-aware
├── ranker.py                 # 238 satır ✅ Learning-to-rank
├── walk_forward.py           # 196 satır ✅ Walk-forward validation
├── adjusted_loss.py          # 111 satır ✅ Yanlış yön cezası
├── cross_sectional/          # 227 satır ✅ Cross-sectional normalization
├── lstm_model.py             #  61 satır ⚠️ Basit PyTorch
├── finrl_bist.py             #  53 satır ⚠️ Basit environment
├── transformer_model.py      #  52 satır ⚠️ Basit PyTorch
├── model_comparator.py       #  42 satır ⚠️ Sadece accuracy/F1
├── ensemble.py               #  37 satır ⚠️ Sadece ağırlıklı ortalama
├── xgboost_model.py          #  32 satır ⚠️ Placeholder
├── fingpt.py                 #  21 satır ⚠️ Kelime tabanlı sentiment
├── hybrid_model.py           #  17 satır ⚠️ Placeholder
├── qlib_integration.py       #  16 satır ⚠️ Placeholder
└── rl_agent.py               #  16 satır ⚠️ Placeholder
```

### 2.2 Güçlü Yönler ✅

- LightGBM trainer çok iyi (multi-horizon, NDCG, purge gap)
- Walk-forward validation sağlam
- Adjusted loss (yanlış yön cezası) iyi
- Cross-sectional normalization iyi
- Training data validation (leakage detection) iyi
- Rule-based fallback var
- Regime-based weights var

### 2.3 Kritik Eksiklikler ❌

1. **CatBoost yok** — kategorik feature handling eksik
2. **Model registry yok** — version tracking yok
3. **Champion-challenger yok** — yeni model doğrudan production
4. **Hyperparameter tuning yok** — manuel parametre
5. **Ensemble basit** — sadece ağırlıklı ortalama, stacking yok
6. **Calibration yok** — overconfident model riski
7. **Feature drift detection yok** — SHAP history yok
8. **Model monitoring yok** — performans takibi yok

---

## 3. Zirve Plan — 6 Faz

### FAZ 1: CatBoost + XGBoost geliştirme (1-2 gün)

**Amaç:** Gradient boosting ailesini tamamla.

#### 1.1 — CatBoost Model
```
Dosya: services/ml/catboost_model.py (YENİ)
```
- [ ] `CatBoostModel` class — train, predict, feature_importance
- [ ] Kategorik feature desteği
- [ ] Early stopping
- [ ] Adjusted loss entegrasyonu

#### 1.2 — XGBoost Model geliştirme
```
Dosya: services/ml/xgboost_model.py (GÜNCELLE)
```
- [ ] Multi-horizon prediction
- [ ] Feature importance (SHAP)
- [ ] Walk-forward entegrasyonu
- [ ] Adjusted loss

**Teslimat:** `pytest tests/test_ml_faz1.py` — CatBoost + XGBoost çalışır

---

### FAZ 2: Stacking Ensemble (2-3 gün)

**Amaç:** Weighted average'den stacking'e geçiş.

#### 2.1 — Stacking Ensemble
```
Dosya: services/ml/stacking_ensemble.py (YENİ)
```
- [ ] Base models: LightGBM, XGBoost, CatBoost
- [ ] Meta-learner: Ridge regression (Nature 2026)
- [ ] Cross-validated stacking (data leakage önleme)
- [ ] Regime-based dynamic weights
- [ ] Model agreement confidence

#### 2.2 — Model Comparator geliştirme
```
Dosya: services/ml/model_comparator.py (GÜNCELLE)
```
- [ ] IC (Information Coefficient)
- [ ] Precision@K
- [ ] Hit rate (yön doğruluğu)
- [ ] Sharpe ratio
- [ ] Max drawdown
- [ ] Calibration score

**Teslimat:** `pytest tests/test_ml_faz2.py` — stacking ensemble çalışır

---

### FAZ 3: Model Registry + Champion-Challenger (2-3 gün)

**Amaç:** Model lifecycle yönetimi.

#### 3.1 — Model Registry
```
Dosya: services/ml/model_registry.py (YENİ)
```
- [ ] Version tracking (v1, v2, v3, ...)
- [ ] Metrics storage (accuracy, IC, Sharpe)
- [ ] Status management (CANDIDATE → CHAMPION → RETIRED)
- [ ] Lineage (training data hash, features, hyperparams)
- [ ] Model serialization (pickle/joblib)

#### 3.2 — Champion-Challenger
```
Dosya: services/ml/champion_challenger.py (YENİ)
```
- [ ] Shadow mode (paralel çalıştır, sonuçları kaydet)
- [ ] A/B test (istatistiksel karşılaştırma)
- [ ] Auto-promote (challenger daha iyiysa champion yap)
- [ ] Auto-reject (challenger kötüyse reddet)
- [ ] Rollback capability

**Teslimat:** `pytest tests/test_ml_faz3.py` — registry + champion-challenger

---

### FAZ 4: Hyperparameter Tuning + Calibration (2-3 gün)

**Amaç:** Optimal parametreler bul, confidence'ı kalibre et.

#### 4.1 — Hyperparameter Tuner
```
Dosya: services/ml/hyperparameter_tuner.py (YENİ)
```
- [ ] Optuna entegrasyonu (Bayesian optimization)
- [ ] IC-based objective function
- [ ] Regime-specific tuning
- [ ] Cross-validation ile tuning
- [ ] Trial history + best params storage

#### 4.2 — Model Calibration
```
Dosya: services/ml/calibration.py (YENİ)
```
- [ ] Calibration curve (beklenen vs gerçek doğruluk)
- [ ] Brier score
- [ ] Platt scaling (sigmoid calibration)
- [ ] Isotonic regression calibration
- [ ] Overconfidence detection

**Teslimat:** `pytest tests/test_ml_faz4.py` — tuning + calibration

---

### FAZ 5: Feature Drift + Model Monitoring (2-3 gün)

**Amaç:** Model ve feature değişimini takip et.

#### 5.1 — Feature Drift Detector
```
Dosya: services/ml/feature_drift.py (YENİ)
```
- [ ] SHAP history tracking (her eğitim sonrası SHAP kaydet)
- [ ] Feature importance trend analizi
- [ ] PSI (Population Stability Index) hesaplama
- [ ] Drift alert (aniden değişen feature'lar)

#### 5.2 — Model Monitor
```
Dosya: services/ml/model_monitor.py (YENİ)
```
- [ ] Performance tracking (IC, Sharpe, win rate zaman içinde)
- [ ] Prediction drift detection
- [ ] Model decay detection (performans düşüşü)
- [ ] Auto-retrain trigger
- [ ] Monitoring dashboard data

**Teslimat:** `pytest tests/test_ml_faz5.py` — drift detection + monitoring

---

### FAZ 6: Backtest Entegrasyonu + Final Test (2-3 gün)

**Amaç:** Tüm sistemi backtest ile doğrula.

#### 6.1 — ML Backtest Integration
```
Dosya: services/ml/ml_backtest.py (YENİ)
```
- [ ] Model predictions → backtest engine
- [ ] Ensemble vs single model karşılaştırması
- [ ] Regime-based performans analizi
- [ ] Transaction cost dahil backtest

#### 6.2 — Final Integration Test
- [ ] End-to-end pipeline test
- [ ] CatBoost + LightGBM + XGBoost → Stacking → Registry
- [ ] Walk-forward + calibration + drift detection
- [ ] Champion-challenger lifecycle test

**Teslimat:** `pytest tests/test_ml_faz6.py` — end-to-end backtest

---

## 4. Test Stratejisi

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 1 | test_ml_faz1.py | 10 | CatBoost train + predict |
| 2 | test_ml_faz2.py | 12 | Stacking > weighted average |
| 3 | test_ml_faz3.py | 10 | Champion promote/reject |
| 4 | test_ml_faz4.py | 10 | Optuna best params + calibration |
| 5 | test_ml_faz5.py | 10 | Drift detection |
| 6 | test_ml_faz6.py | 15 | End-to-end backtest |

---

## 5. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| CatBoost kurulumu zor | Orta | Orta | try/except, pip install |
| Stacking overfitting | Orta | Yüksek | Cross-validated stacking |
| Optuna yavaş | Yüksek | Orta | n_trials limit, early stopping |
| Feature drift false positive | Orta | Orta | Eşik ayarı, çoklu metrik |
| Champion-challenger loops | Düşük | Yüksek | Max iteration limit |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 1** | 1-2 gün | Yok | CatBoost + XGBoost |
| **Faz 2** | 2-3 gün | Faz 1 | Stacking Ensemble |
| **Faz 3** | 2-3 gün | Faz 2 | Model Registry |
| **Faz 4** | 2-3 gün | Faz 3 | Tuning + Calibration |
| **Faz 5** | 2-3 gün | Faz 4 | Drift + Monitoring |
| **Faz 6** | 2-3 gün | Faz 5 | Backtest + Final |
| **TOPLAM** | **11-17 gün** | | |

---

## 📚 Referanslar

1. Nature Stacked Gradient Boosting (2026) — Stacking ensemble
2. MDPI Regime-Aware LightGBM (2026) — Regime-based training
3. ResearchGate Explainable AI Ensemble (2026) — SHAP + ensemble
4. Springer SHAP Feature Importance (2026) — Feature drift
5. MDPI ML Time Series Survey (2025) — Best practices
