# 🧠 Learning System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:** Aerospike Model Drift (2025), Databricks MLOps Workflow, QuantInsti Walk-Forward (2025), Quant Beckman CPCV (2025), Frouros Drift Library, arXiv Shadow Before Swap (2026), IBM Model Drift, MLflow Model Registry, SentientConcepts PSI Guide (2025)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Entegrasyon Noktaları](#3-entegrasyon-noktaları)
4. [Genel Mimari Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 Drift Detection — En İyi Uygulama (Aerospike 2025, SentientConcepts 2025, Frouros)

**3 Tür Drift ve Tespit Yöntemleri:**

| Drift Türü | Tanım | Tespit Yöntemi | Eşik |
|------------|-------|----------------|------|
| **Data Drift** | Feature dağılımı değişti | PSI, KS test, Jensen-Shannon | PSI > 0.2 uyarı, > 0.5 kritik |
| **Concept Drift** | Feature-target ilişki değişti | DDM, EDDM, ADWIN, Page-Hinkley | Accuracy drop > %10 |
| **Prediction Drift** | Model çıktı dağılımı değişti | Output distribution monitoring | KL divergence > 0.1 |

**Kütüphane Önerisi:** `frouros` (IFCA, GitHub) — ADWIN, KSWIN, DDM, EDDM, Page-Hinkley dahil. Production-ready Python kütüphanesi.

**PSI Hesaplama (Sektör Standardı):**
```python
# 10 binlik (decile) kullan
# PSI = Σ (actual_% - expected_%) × ln(actual_% / expected_%)
# < 0.1: stabil, 0.1-0.2: dikkat, > 0.2: drift, > 0.5: kritik
```

### 1.2 Walk-Forward Validation — En İyi Uygulama (QuantInsti 2025, Quant Beckman 2025)

**Purged K-Fold Cross-Validation (Marcos López de Prado):**
- Train/test arasına **purge gap** ekle (look-ahead bias önleme)
- Test sonrası **embargo** ekle (information leakage önleme)
- Expanding window: her adımda daha fazla veri
- **Combinatorial Purged CV (CPCV):** Daha fazla test seti, daha robust sonuç

**Parametreler (Finans İçin Önerilen):**
- Purge: 5 gün (train/test arası boşluk)
- Embargo: 5 gün (test sonrası boşluk)
- Train window: 252 gün (1 yıl)
- Test window: 21 gün (1 ay)
- Step: 21 gün (her adımda ilerleme)

**Not:** `services/ml/walk_forward.py` mevcut ama **learning modülüyle entegre değil**. Entegrasyon kritik.

### 1.3 Calibration — En İyi Uygulama (arXiv, MUSE 2026)

**Calibration Curve:**
- Model %90 confidence veriyor → Gerçekten %90 mı gerçekleşiyor?
- Overconfident model → fazla risk → büyük kayıp
- Underconfident model → fırsat kaçırma

**Metrikler:**
- **Brier Score:** `mean((confidence - outcome)²)` — düşük = iyi
- **Expected Calibration Error (ECE):** Bins bazlı miscalibration ölçümü
- **Reliability Diagram:** Görsel calibration analizi

**Uygulama:**
- Haftalık calibration check
- Otomatik confidence adjustment (Platt scaling veya isotonic regression)
- Regime-specific calibration (her rejimde farklı)

### 1.4 Champion-Challenger — En İyi Uygulama (Databricks, CalibreOS 2026)

**Pipeline:**
```
TRAIN → VALIDATE → BACKTEST → WALK-FORWARD → SHADOW → CANARY → CHAMPION → MONITOR
```

**Shadow Deployment:**
- Yeni model eski modelle paralel çalışır
- Sonuçları kaydedilir ama uygulanmaz
- Minimum 21 gün observation
- Statistical significance test (Welch's t-test, p < 0.05)

**Canary Deployment:**
- Yeni modelle küçük pozisyonlar (%10-20)
- Performans monitor et
- Başarılıysa kademeli artır

**Otomatik Karar:**
- Challenger Sharpe > Champion Sharpe + %10 → PROMOTE
- Challenger Sharpe < Champion Sharpe → REJECT
- Belirsiz → Extended shadow period

### 1.5 Feature Importance Tracking — En İyi Uygulama (SHAP, Interpretable ML 2026)

**SHAP (SHapley Additive exPlanations):**
- TreeSHAP: LightGBM için optimal (O(n·log(n)))
- Global importance: tüm veri seti üzerinde
- Local importance: tek tahmin için
- Interaction effects: feature çiftleri arası etkileşim

**Tracking Stratejisi:**
- Günlük SHAP hesaplama (son N günün verisiyle)
- Haftalık trend analizi (artan/azalan importance)
- Regime-specific importance (her rejimde farklı feature'lar önemli)
- Feature selection: importance < eşik → çıkar

### 1.6 Meta-Learning — En İyi Uygulama (arXiv Agentic Trading 2026)

**Regime-Specific Model Selection:**
- Her rejim için farklı model eğit
- Rejim değişince model seçimi
- Dynamic ensemble weights (rejime göre ağırlık)

**Factor-Based Attribution:**
- Momentum, Value, Quality, Macro katkısı ayrı ayrı ölç
- Hangi factor hangi rejimde katkı sağlıyor?
- Factor rotation tespiti

---

## 2. Mevcut Sistem Analizi

### 2.1 Modül Özeti (7 dosya, 2,309 satır)

| Modül | Satır | Sınıf | Ne Yapıyor | Durum |
|-------|-------|-------|------------|-------|
| `super_intelligence.py` | 621 | 4 | Self-healing, auto-retrain, A/B test, drift, meta-learning | ✅ En kapsamlı ama eksikler var |
| `continuous_learning.py` | 386 | 3 | Günlük pipeline, drift check, retrain kararı | ✅ İyi |
| `main.py` | 346 | 1 | Learning service, training loop, outcome tracking | ✅ İyi |
| `integrated_learning.py` | 329 | 2 | Prediction/outcome tracking, regime accuracy | ✅ İyi |
| `attribution.py` | 274 | 2 | İşlem atfedilmesi (neden kazandı/kaybetti) | ⚠️ Basitleştirilmiş hesaplamalar |
| `outcome_tracker.py` | 181 | 1 | Otomatik outcome takibi | ✅ İyi |
| `learning_loop.py` | 172 | 2 | Otonom öğrenme döngüsü, model decay | ✅ İyi |

### 2.2 Mevcut Özellikler — Güçlü ve Zayıf Yönler

| Özellik | Var mı? | Kalite | Detay |
|---------|---------|--------|-------|
| Prediction tracking | ✅ | İyi | `integrated_learning.py` — kayıt, outcome eşleme |
| Outcome tracking | ✅ | İyi | `outcome_tracker.py` — otomatik fiyat takibi |
| Regime-based accuracy | ✅ | İyi | Her rejimde ayrı doğruluk |
| Attribution (neden kazandı/kaybetti) | ✅ | ⚠️ | Basitleştirilmiş formüller, factor-based değil |
| Drift detection | ✅ | ⚠️ | Sadece Z-score — PSI, KS test, ADWIN yok |
| Auto-retrain | ✅ | ⚠️ | Tetikleme var, gerçek implementasyon eksik |
| A/B test | ✅ | ⚠️ | Yapı var ama statistical test eksik |
| Champion-challenger | ✅ | ⚠️ | Yapı var, otomatik yok |
| Meta-learning | ✅ | ⚠️ | Basit regime-model mapping |
| Self-healing | ✅ | ⚠️ | Yapı var ama gerçek healing yok |
| Health monitoring | ✅ | İyi | `SystemHealth` dataclass, module status |
| Calibration | ❌ | Yok | Brier score, calibration curve yok |
| Walk-forward validation | ⚠️ | Var ama entegre değil | `services/ml/walk_forward.py` mevcut |
| Shadow mode | ❌ | Yok | Yeni model doğrudan production'a alınıyor |
| Feature importance tracking | ⚠️ | Yok | SHAP-based tracking yok |
| Model versioning (detaylı) | ⚠️ | Basit | Version ID var ama registry eksik |
| Performance decay prediction | ❌ | Yok | Decay tespit var ama tahmin yok |
| Confidence adjustment | ❌ | Yok | Overconfidence detection + adjustment yok |

### 2.3 Kritik Eksiklikler

#### Eksik 1: Calibration Yok ❌
**Sorun:** Model %90 confidence veriyor ama gerçekten %90 mı gerçekleşiyor bilinmiyor.
**Etki:** Overconfident model → fazla risk → büyük kayıp.
**Çözüm:** ConfidenceCalibrator — Brier score, calibration curve, overconfidence detection, otomatik confidence adjustment.

#### Eksik 2: Walk-Forward Entegrasyonu Yok ⚠️
**Sorun:** `services/ml/walk_forward.py` mevcut ama learning modülüyle entegre değil.
**Etki:** Model eğitiliyor ama walk-forward ile doğrulanmıyor → overfitting riski.
**Çözüm:** Walk-forward'ı continuous_learning pipeline'ına entegre et.

#### Eksik 3: Shadow Mode Yok ❌
**Sorun:** Yeni model doğrudan production'a alınıyor.
**Etki:** Yeni model kötüyse → tüm portföy etkilenir.
**Çözüm:** ShadowModeManager — paralel çalıştır, sonuçları karşılaştır, otomatik promote/reject.

#### Eksik 4: Drift Detection Basit ⚠️
**Sorun:** Sadece Z-score ile drift tespiti — PSI, KS test, ADWIN, Page-Hinkley yok.
**Etki:** Drift geç tespit edilir.
**Çözüm:** AdvancedDriftDetector — çoklu yöntem, drift type sınıflandırma.

#### Eksik 5: Auto-Retrain Implementasyonu Eksik ⚠️
**Sorun:** Retrain tetikleme var ama gerçek eğitim yok (stub metodlar).
**Etki:** Model güncellenmiyor.
**Çözüm:** Ranking model ile entegre, walk-forward validated, shadow mode'da test edilen auto-retrain.

#### Eksik 6: Feature Importance Tracking Yok ❌
**Sorun:** Hangi feature'ın en önemli olduğu takip edilmiyor.
**Etki:** Gereksiz feature'lar kullanılıyor, önemli olanlar kaçırılıyor.
**Çözüm:** SHAP-based FeatureImportanceTracker — günlük tracking, trend analizi, regime-specific.

#### Eksik 7: Factor-Based Attribution Yok ⚠️
**Sorun:** Sadece basit attribution — momentum, value, quality, macro katkısı ayrı ayrı ölçülmüyor.
**Etki:** Neden kazandı/kaybetti detaylı anlaşılamıyor.
**Çözüm:** Gelişmiş AttributionEngine — factor decomposition, SHAP-based attribution.

#### Eksik 8: Model Registry Eksik ⚠️
**Sorun:** Model versiyonları var ama detaylı registry yok.
**Etki:** Model geçmişi izlenemiyor, rollback yapılamıyor.
**Çözüm:** ModelRegistry — version tracking, metadata, performance history, rollback desteği.

---

## 3. Entegrasyon Noktaları

### 3.1 Mevcut Bağlantılar

```
services/learning/
├── main.py                    → LearningService (async, DB, event bus)
├── continuous_learning.py     → ContinuousLearningPipeline (günlük döngü)
├── super_intelligence.py      → SuperIntelligenceEngine (drift, retrain, A/B)
├── integrated_learning.py     → IntegratedLearningSystem (prediction/outcome)
├── attribution.py             → AttributionEngine (neden kazandı/kaybetti)
├── outcome_tracker.py         → OutcomeTracker (otomatik takip)
└── learning_loop.py           → LearningLoop (model decay)

services/ml/
├── ranking_model.py           → RankingModel (LightGBM LambdaRank)
├── walk_forward.py            → WalkForwardValidation (purge/embargo)
└── lightgbm_trainer.py        → LightGBM trainer

services/core/
├── orchestrator.py            → MasterOrchestrator (pipeline orkestrasyon)
├── event_bus.py               → InternalEventBus (Redis Pub/Sub)
└── config.py                  → Settings (konfigürasyon)
```

### 3.2 Entegrasyon Akışı (Hedef)

```
MEVCUT:
  features → ranking_model → predictions → outcome_tracker → learning_loop

HEDEF:
  features → ranking_model → predictions → outcome_tracker
                                              ↓
                                    calibration_check
                                              ↓
                                    drift_detection (PSI + KS + ADWIN + PH)
                                              ↓
                                    attribution (factor-based)
                                              ↓
                                    feature_importance_tracking (SHAP)
                                              ↓
                                    retrain_decision
                                              ↓
                                    walk_forward_validation
                                              ↓
                                    shadow_mode → champion_challenger
                                              ↓
                                    model_registry_update
                                              ↓
                                    meta_learning_update
                                              ↓
                                    health_monitor → self_healing
```

### 3.3 Event Bus Entegrasyonu

```python
# Yeni event type'ları (services/core/event_schema.py'ya eklenecek)
LEARNING_DRIFT_DETECTED = "learning.drift.detected"
LEARNING_RETRAIN_STARTED = "learning.retrain.started"
LEARNING_RETRAIN_COMPLETED = "learning.retrain.completed"
LEARNING_SHADOW_PROMOTED = "learning.shadow.promoted"
LEARNING_SHADOW_REJECTED = "learning.shadow.rejected"
LEARNING_CALIBRATION_ALERT = "learning.calibration.alert"
LEARNING_FEATURE_DRIFT = "learning.feature.drift"
LEARNING_MODEL_DECAY = "learning.model.decay"
```

### 3.4 Config Entegrasyonu

```python
# services/core/config.py'ya eklenecek
class LearningSettings(BaseModel):
    # Calibration
    calibration_check_interval_days: int = 7
    calibration_brier_threshold: float = 0.25
    calibration_overconfidence_threshold: float = 0.15

    # Drift
    drift_psi_threshold: float = 0.2
    drift_psi_critical: float = 0.5
    drift_ks_p_threshold: float = 0.05
    drift_zscore_threshold: float = 3.0
    drift_check_interval_days: int = 1

    # Retrain
    retrain_sharpe_threshold: float = 0.3
    retrain_winrate_threshold: float = 0.45
    retrain_max_interval_days: int = 14
    retrain_min_samples: int = 500

    # Shadow Mode
    shadow_duration_days: int = 21
    shadow_min_predictions: int = 50
    shadow_promote_threshold_pct: float = 10.0
    shadow_significance_p: float = 0.05

    # Walk-Forward
    wf_train_size: int = 252
    wf_test_size: int = 21
    wf_purge_size: int = 5
    wf_embargo_size: int = 5
    wf_step_size: int = 21

    # Feature Importance
    feature_importance_interval_days: int = 1
    feature_importance_min_threshold: float = 0.001
    feature_importance_trend_window: int = 30

    # Model Registry
    max_model_versions: int = 20
    auto_cleanup_versions: bool = True
```

---

## 4. Genel Mimari Tasarım

### 4.1 Nihai Learning Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ALPHA BIST — LEARNING PIPELINE v2.0              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: PREDICTION & OUTCOME TRACKING (Mevcut)             │   │
│  │  - IntegratedLearningSystem.record_prediction()              │   │
│  │  - OutcomeTracker.check_pending_outcomes()                   │   │
│  │  - Horizon: 1D, 5D, 20D, 60D                                │   │
│  │  - Otomatik fiyat takibi                                     │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: CALIBRATION CHECK (YENİ)                           │   │
│  │  - ConfidenceCalibrator.calibrate()                          │   │
│  │  - Brier score hesaplama                                     │   │
│  │  - Overconfidence detection                                  │   │
│  │  - Otomatik confidence adjustment (Platt scaling)            │   │
│  │  - Regime-specific calibration                               │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: DRIFT DETECTION (Gelişmiş)                         │   │
│  │  - PSI (Population Stability Index)                          │   │
│  │  - KS Test (Kolmogorov-Smirnov)                              │   │
│  │  - ADWIN (Adaptive Windowing)                                │   │
│  │  - Page-Hinkley test                                         │   │
│  │  - Z-score (mevcut)                                          │   │
│  │  - Drift type sınıflandırma                                  │   │
│  │  - Concept drift: performance decay                          │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: ATTRIBUTION (Gelişmiş)                             │   │
│  │  - Factor-based attribution (momentum, value, quality, macro)│   │
│  │  - SHAP-based attribution                                    │   │
│  │  - Residual analysis                                         │   │
│  │  - Dersler (what worked, what failed)                        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 5: FEATURE IMPORTANCE TRACKING (YENİ)                 │   │
│  │  - SHAP-based global importance                              │   │
│  │  - Zaman içinde trend analizi                                │   │
│  │  - Regime-specific importance                                │   │
│  │  - Feature selection önerileri                               │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 6: RETRAIN DECISION (Gelişmiş)                        │   │
│  │  - Sharpe < 0.3 → retrain                                    │   │
│  │  - Win rate < 45% → retrain                                  │   │
│  │  - Drift detected → retrain                                  │   │
│  │  - Max interval exceeded → retrain                           │   │
│  │  - Calibration degraded → retrain                            │   │
│  │  - Manual trigger → retrain                                  │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 7: WALK-FORWARD VALIDATION (Entegrasyon)              │   │
│  │  - Purged K-Fold Cross-Validation                            │   │
│  │  - Rolling window walk-forward                               │   │
│  │  - Out-of-sample test                                        │   │
│  │  - Deflated Sharpe hesaplama                                 │   │
│  │  - Model kabul/red kararı                                    │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 8: SHADOW MODE (YENİ)                                 │   │
│  │  - Yeni model eski modelle paralel çalışır                   │   │
│  │  - Sonuçlar kaydedilir ama uygulanmaz                        │   │
│  │  - Minimum 21 gün observation                                │   │
│  │  - Statistical significance test                             │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 9: CHAMPION-CHALLENGER (Gelişmiş)                     │   │
│  │  - Welch's t-test (p < 0.05)                                 │   │
│  │  - Sharpe comparison                                         │   │
│  │  - IC comparison                                             │   │
│  │  - Automatic promotion/rejection                             │   │
│  │  - Canary deployment (küçük pozisyonlarla test)              │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 10: MODEL REGISTRY (YENİ)                             │   │
│  │  - Version tracking (metadata, metrics, features)            │   │
│  │  - Performance history                                       │   │
│  │  - Rollback desteği                                          │   │
│  │  - Auto-cleanup (eski versiyonlar)                           │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 11: META-LEARNING (Gelişmiş)                          │   │
│  │  - Regime-specific model selection                           │   │
│  │  - Dynamic ensemble weights                                  │   │
│  │  - Factor-based model routing                                │   │
│  │  - Performance decay prediction                              │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 12: HEALTH MONITORING & SELF-HEALING (Gelişmiş)       │   │
│  │  - Real-time health dashboard                                │   │
│  │  - Automated alerting                                        │   │
│  │  - Self-healing: hata → otomatik onarım                     │   │
│  │  - Cascade failure prevention                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Dosya Yapısı (Hedef)

```
services/learning/
├── __init__.py
├── main.py                    # MEVCUT — LearningService (async, DB)
├── continuous_learning.py     # MEVCUT — refactor edilecek
├── super_intelligence.py      # MEVCUT — refactor edilecek
├── integrated_learning.py     # MEVCUT — refactor edilecek
├── attribution.py             # MEVCUT — geliştirilecek
├── outcome_tracker.py         # MEVCUT — korunacak
├── learning_loop.py           # MEVCUT — korunacak
│
├── calibration.py             # YENİ — Phase 2: Confidence calibration
├── drift_detector.py          # YENİ — Phase 3: Gelişmiş drift detection
├── feature_tracker.py         # YENİ — Phase 5: SHAP-based feature tracking
├── shadow_manager.py          # YENİ — Phase 8: Shadow mode
├── champion_challenger.py     # YENİ — Phase 9: Otomatik A/B test
├── model_registry.py          # YENİ — Phase 10: Model versioning
├── meta_learner.py            # YENİ — Phase 11: Regime-specific learning
├── health_monitor.py          # YENİ — Phase 12: Health + self-healing
├── retrain_engine.py          # YENİ — Retrain orchestrator
│
├── config/                    # YENİ — Learning konfigürasyonları
│   ├── __init__.py
│   └── learning_config.py
│
└── utils/                     # YENİ — Yardımcı fonksiyonlar
    ├── __init__.py
    ├── statistical_tests.py   # KS test, t-test, PSI helpers
    └── shap_helpers.py        # SHAP hesaplama yardımcıları
```

---

## 5. Faz Planı

### FAZ 0: Temel Altyapı ve Refactor (1-2 gün)

**Amaç:** Mevcut kodu refactor et, temel altyapıyı hazırla, config entegrasyonu.

#### 0.1 — Learning Config Tanımları
```
Dosya: services/learning/config/learning_config.py
```
- [ ] `LearningSettings` Pydantic model'i oluştur
- [ ] Tüm eşikler (thresholds) config'den okunabilir olmalı
- [ ] Default değerler sektör standardına uygun
- [ ] `services/core/config.py`'ya `LearningSettings` ekle

**Gerekçe:** Mevcut hardcoded eşikler (0.3, 0.45, 3.0 vb.) config'den okunmalı. Tuning kolaylığı.

#### 0.2 — Statistical Test Helpers
```
Dosya: services/learning/utils/statistical_tests.py
```
- [ ] `compute_psi(expected, actual, bins=10)` — PSI hesaplama
- [ ] `ks_test(sample1, sample2)` — Kolmogorov-Smirnov test
- [ ] `welch_t_test(sample1, sample2)` — Welch's t-test
- [ ] `page_hinkley_test(data, threshold)` — Page-Hinkley drift test
- [ ] `adwin_test(data, window_size)` — ADWIN drift test
- [ ] Unit test'ler

**Gerekçe:** Drift detection ve A/B test için temel istatistiksel fonksiyonlar. Tekrar kullanılabilir.

#### 0.3 — Mevcut Kod Refactor
```
Dosya: services/learning/super_intelligence.py, continuous_learning.py
```
- [ ] Hardcoded eşikleri config'den oku
- [ ] `_trigger_retrain()` stub'ını gerçek implementasyona çevir
- [ ] `_trigger_data_refresh()` stub'ını gerçek implementasyona çevir
- [ ] `_restart_module()` stub'ını gerçek implementasyona çevir
- [ ] `_activate_fallback()` stub'ını gerçek implementasyona çevir
- [ ] `daily_cycle()` içinde `recent_metrics` scope hatasını düzelt (line ~290)
- [ ] Test'leri güncelle

**Gerekçe:** Stub metodlar production'da çalışmaz. Scope hatası bug.

**Teslimat:** `pytest tests/test_learning_faz0.py` — tüm testler yeşil

---

### FAZ 1: Calibration System (2-3 gün)

**Amaç:** Model confidence'ının kalibrasyonunu ölç ve otomatik ayarla.

#### 1.1 — Confidence Calibrator
```
Dosya: services/learning/calibration.py
```
```python
class ConfidenceCalibrator:
    """Model confidence kalibrasyonu."""

    def calibrate(
        self,
        predictions: List[Dict],  # {confidence, actual_outcome}
        n_bins: int = 10,
    ) -> CalibrationResult:
        """Calibration curve hesapla."""
        # 1. Confidence'a göre bin'le
        bins = np.linspace(0, 1, n_bins + 1)
        calibration = []

        for i in range(len(bins) - 1):
            mask = (confidences >= bins[i]) & (confidences < bins[i+1])
            if mask.sum() > 0:
                bin_mean_pred = confidences[mask].mean()
                bin_mean_actual = outcomes[mask].mean()
                calibration.append({
                    "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                    "predicted": round(bin_mean_pred, 4),
                    "actual": round(bin_mean_actual, 4),
                    "count": int(mask.sum()),
                    "miscalibration": round(abs(bin_mean_pred - bin_mean_actual), 4),
                })

        # 2. Brier score
        brier = np.mean((confidences - outcomes) ** 2)

        # 3. Expected Calibration Error (ECE)
        ece = sum(c["miscalibration"] * c["count"] for c in calibration) / total

        # 4. Overconfidence tespit
        overconfident = any(c["miscalibration"] > 0.15 for c in calibration)

        # 5. Regime-specific calibration
        regime_calibration = self._calibrate_by_regime(predictions)

        return CalibrationResult(
            brier_score=round(float(brier), 4),
            ece=round(float(ece), 4),
            overconfident=overconfident,
            calibration_bins=calibration,
            regime_calibration=regime_calibration,
            suggested_adjustment=self._suggest_adjustment(calibration),
        )

    def adjust_confidence(
        self,
        raw_confidence: float,
        calibration: CalibrationResult,
    ) -> float:
        """Platt scaling ile confidence ayarla."""
        # Overconfident ise confidence'ı düşür
        if calibration.overconfident:
            adjustment = calibration.suggested_adjustment
            adjusted = raw_confidence + adjustment
            return max(0.0, min(1.0, adjusted))
        return raw_confidence
```

**Özellikler:**
- Brier score hesaplama
- Expected Calibration Error (ECE)
- Overconfidence detection
- Platt scaling ile otomatik confidence adjustment
- Regime-specific calibration (her rejimde farklı)
- Haftalık calibration check (configurable)

#### 1.2 — Calibration Alert
- [ ] Calibration degrade olursa event_bus'a bildir
- [ ] `LEARNING_CALIBRATION_ALERT` event publish
- [ ] Dashboard'da calibration heatmap

**Teslimat:** `pytest tests/test_learning_faz1.py` — calibration curve, Brier score, overconfidence detection

---

### FAZ 2: Gelişmiş Drift Detection (2-3 gün)

**Amaç:** Çoklu yöntemle drift tespiti — PSI, KS test, ADWIN, Page-Hinkley.

#### 2.1 — Advanced Drift Detector
```
Dosya: services/learning/drift_detector.py
```
```python
class AdvancedDriftDetector:
    """Gelişmiş drift tespiti — çoklu yöntem."""

    def detect_all_drift(
        self,
        historical: np.ndarray,
        current: np.ndarray,
        feature_name: str = "",
    ) -> DriftResult:
        """Tüm drift türlerini tespit et."""
        results = {}

        # 1. PSI (Population Stability Index)
        results["psi"] = self._compute_psi(historical, current)

        # 2. KS Test (Kolmogorov-Smirnov)
        from scipy import stats
        ks_stat, ks_p = stats.ks_2samp(historical, current)
        results["ks_statistic"] = round(float(ks_stat), 4)
        results["ks_p_value"] = round(float(ks_p), 4)

        # 3. Z-score (mevcut — iyileştirilecek)
        results["z_score"] = self._compute_zscore(historical, current)

        # 4. Page-Hinkley test
        results["page_hinkley"] = self._page_hinkley_test(historical, current)

        # 5. ADWIN (Adaptive Windowing)
        results["adwin"] = self._adwin_test(historical, current)

        # 6. Concept drift (performance-based)
        results["concept_drift"] = self._detect_concept_drift()

        # Genel drift kararı
        drift_detected = (
            results["psi"] > self.config.drift_psi_threshold or
            results["ks_p_value"] < self.config.drift_ks_p_threshold or
            results["z_score"] > self.config.drift_zscore_threshold or
            results["page_hinkley"]["drift"] or
            results["adwin"]["drift"]
        )

        # Drift type sınıflandırma
        drift_type = self._classify_drift(results)

        return DriftResult(
            drift_detected=drift_detected,
            drift_type=drift_type,
            feature_name=feature_name,
            details=results,
            severity=self._calculate_severity(results),
        )
```

**Drift Type Sınıflandırma:**
| Drift Type | Kosul | Aksiyon |
|------------|-------|---------|
| `MINOR_DRIFT` | PSI 0.1-0.2 | İzle |
| `MAJOR_DATA_DRIFT` | PSI > 0.5 | Acil retrain |
| `SIGNIFICANT_DISTRIBUTION_SHIFT` | KS p < 0.01 | Retrain |
| `GRADUAL_DRIFT` | Page-Hinkley drift | Scheduled retrain |
| `SUDDEN_SHIFT` | ADWIN drift | Acil retrain |
| `EXTREME_OUTLIER` | Z-score > 5 | Veri kalitesi kontrolü |
| `CONCEPT_DRIFT` | Performance decay | Retrain + feature review |

#### 2.2 — Mevcut detect_drift() Refactor
- [ ] `super_intelligence.py`'deki `detect_drift()`'i `AdvancedDriftDetector`'a yönlendir
- [ ] Basit Z-score kaldırılmayacak (backward compatibility), üstüne eklenecek
- [ ] Drift alert'leri event_bus'a publish et

#### 2.3 — Drift Alert Sistemi
```python
# Drift tespit edildiğinde
event_bus.publish("learning.drift.detected", CanonicalEvent(
    event_type="learning.drift.detected",
    payload={
        "drift_type": drift_result.drift_type,
        "severity": drift_result.severity,
        "features": drift_result.affected_features,
        "details": drift_result.details,
    }
))
```

**Teslimat:** `pytest tests/test_learning_faz2.py` — PSI, KS, ADWIN, Page-Hinkley, drift type classification

---

### FAZ 3: Walk-Forward Entegrasyonu (2-3 gün)

**Amaç:** Mevcut `walk_forward.py`'yi learning pipeline'ına entegre et.

#### 3.1 — Walk-Forward Entegrasyonu
```
Dosya: services/learning/retrain_engine.py (içinde)
```
```python
class RetrainEngine:
    """Retrain orchestrator — walk-forward validated."""

    async def retrain_with_validation(
        self,
        features_map: Dict,
        returns: Dict,
        regime: str,
    ) -> RetrainResult:
        """Walk-forward validated retrain."""

        # 1. Walk-forward validation
        from services.ml.walk_forward import wf_validator

        wf_results = wf_validator.evaluate(
            data=training_data,
            model_fn=self._create_model,
            feature_fn=self._extract_features,
        )

        # 2. Aggregate metrics
        agg_metrics = wf_validator.get_aggregated_metrics(wf_results)

        # 3. Model kabul/red kararı
        if agg_metrics["avg_correlation"] < 0.05:
            return RetrainResult(success=False, reason="Walk-forward correlation too low")

        if agg_metrics["avg_direction_accuracy"] < 52:
            return RetrainResult(success=False, reason="Direction accuracy below random")

        # 4. Model eğit (tüm veriyle)
        model_result = self._train_final_model(features_map, returns, regime)

        # 5. Shadow mode'a al
        from services.learning.shadow_manager import shadow_manager
        shadow_manager.start_shadow(
            champion=current_model_version,
            challenger=model_result.version_id,
        )

        return RetrainResult(
            success=True,
            version_id=model_result.version_id,
            wf_metrics=agg_metrics,
            shadow_started=True,
        )
```

#### 3.2 — Deflated Sharpe Hesaplama
- [ ] Multiple testing correction (walk-forward split sayısı)
- [ ] Deflated Sharpe ratio: `SR_adj = SR - std(SR) * z_alpha`
- [ ] Model kabulünde deflated Sharpe kullan

#### 3.3 — Orchestrator Entegrasyonu
- [ ] `ContinuousLearningPipeline._execute_retrain()`'i `RetrainEngine`'a yönlendir
- [ ] Walk-forward başarısızsa retrain yapma
- [ ] Walk-forward başarılıysa shadow mode başlat

**Teslimat:** `pytest tests/test_learning_faz3.py` — walk-forward integration, deflated Sharpe

---

### FAZ 4: Feature Importance Tracking (2-3 gün)

**Amaç:** SHAP-based feature importance tracking — hangi feature ne kadar önemli, trend analizi.

#### 4.1 — Feature Importance Tracker
```
Dosya: services/learning/feature_tracker.py
```
```python
class FeatureImportanceTracker:
    """SHAP-based feature importance tracking."""

    def track(
        self,
        model,
        feature_names: List[str],
        X: np.ndarray,
        date: str,
        regime: str = "UNKNOWN",
    ):
        """Feature importance kaydet."""
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            importance = np.abs(shap_values).mean(axis=0)
        except Exception:
            importance = model.feature_importances_

        for name, imp in zip(feature_names, importance):
            self._history.append({
                "date": date,
                "feature": name,
                "importance": round(float(imp), 6),
                "regime": regime,
            })

    def get_trends(self, top_n: int = 20, window_days: int = 30) -> Dict:
        """Feature importance trendleri."""
        recent = [h for h in self._history
                  if h["date"] > (datetime.now() - timedelta(days=window_days)).isoformat()]

        feature_avg = defaultdict(list)
        for h in recent:
            feature_avg[h["feature"]].append(h["importance"])

        trends = {}
        for feature, values in feature_avg.items():
            if len(values) >= 2:
                trend = "increasing" if values[-1] > values[0] else "decreasing"
            else:
                trend = "stable"
            trends[feature] = {
                "avg_importance": round(np.mean(values), 6),
                "trend": trend,
                "volatility": round(np.std(values), 6),
            }

        return dict(sorted(trends.items(),
                           key=lambda x: x[1]["avg_importance"],
                           reverse=True)[:top_n])

    def get_regime_importance(self, regime: str) -> Dict:
        """Rejim-specific feature importance."""
        regime_data = [h for h in self._history if h["regime"] == regime]
        feature_avg = defaultdict(list)
        for h in regime_data:
            feature_avg[h["feature"]].append(h["importance"])
        return {f: round(np.mean(v), 6) for f, v in feature_avg.items()}

    def suggest_feature_selection(self, min_importance: float = 0.001) -> List[str]:
        """Düşük importance'lı feature'ları öner."""
        trends = self.get_trends(top_n=100)
        return [f for f, v in trends.items()
                if v["avg_importance"] < min_importance and v["trend"] == "decreasing"]
```

#### 4.2 — Ranking Model Entegrasyonu
- [ ] `ranking_model.py`'deki `train()` sonrası `FeatureImportanceTracker.track()` çağır
- [ ] Günlük feature importance hesaplama (son N günün verisiyle)
- [ ] Dashboard'da feature importance trend grafikleri

#### 4.3 — Feature Selection Automation
- [ ] Düşük importance'lı feature'ları otomatik öner
- [ ] Feature removal sonrası walk-forward validation
- [ ] Feature addition denemeleri

**Teslimat:** `pytest tests/test_learning_faz4.py` — SHAP tracking, trend analysis, feature selection

---

### FAZ 5: Shadow Mode ve Champion-Challenger (3-4 gün)

**Amaç:** Yeni modeli güvenli şekilde test et, otomatik promote/reject.

#### 5.1 — Shadow Mode Manager
```
Dosya: services/learning/shadow_manager.py
```
```python
class ShadowModeManager:
    """Shadow mode — yeni model eski modelle paralel çalışır."""

    def start_shadow(self, champion: str, challenger: str, duration_days: int = 21):
        """Shadow mode başlat."""
        self._shadow_active = True
        self._champion_id = champion
        self._challenger_id = challenger
        self._start_date = datetime.now(timezone.utc)
        self._duration_days = duration_days
        self._champion_predictions = []
        self._challenger_predictions = []

    def record_prediction(self, ticker: str, features: Dict):
        """Her iki modelden prediction kaydet."""
        champion_pred = self._predict_with_model(self._champion_id, features)
        challenger_pred = self._predict_with_model(self._challenger_id, features)

        self._champion_predictions.append({
            "ticker": ticker, "prediction": champion_pred,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._challenger_predictions.append({
            "ticker": ticker, "prediction": challenger_pred,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def evaluate(self, actual_returns: Dict[str, float]) -> ShadowResult:
        """Shadow mode sonuçlarını değerlendir."""
        champion_metrics = self._calculate_metrics(self._champion_predictions, actual_returns)
        challenger_metrics = self._calculate_metrics(self._challenger_predictions, actual_returns)

        # Statistical significance test
        from scipy import stats
        t_stat, p_value = stats.ttest_ind(
            champion_metrics["returns"],
            challenger_metrics["returns"],
            equal_var=False,
        )

        improvement = ((challenger_metrics["sharpe"] - champion_metrics["sharpe"])
                       / max(abs(champion_metrics["sharpe"]), 0.001) * 100)

        # Karar
        if improvement > self.config.shadow_promote_threshold_pct and p_value < self.config.shadow_significance_p:
            recommendation = "PROMOTE"
        elif improvement < -self.config.shadow_promote_threshold_pct:
            recommendation = "REJECT"
        else:
            recommendation = "EXTEND"  # Daha fazla gözlem

        return ShadowResult(
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            improvement_pct=round(improvement, 2),
            p_value=round(p_value, 4),
            significant=p_value < self.config.shadow_significance_p,
            recommendation=recommendation,
            days_elapsed=(datetime.now(timezone.utc) - self._start_date).days,
        )
```

#### 5.2 — Champion-Challenger Engine
```
Dosya: services/learning/champion_challenger.py
```
```python
class ChampionChallengerEngine:
    """Otomatik champion-challenger yönetimi."""

    def promote(self, challenger_id: str):
        """Challenger'ı yeni champion yap."""
        # Eski champion'ı archive'le
        self._archive_champion()
        # Yeni champion'ı aktif yap
        self._set_champion(challenger_id)
        # Event publish
        event_bus.publish("learning.shadow.promoted", ...)

    def reject(self, challenger_id: str):
        """Challenger'ı reddet."""
        self._archive_challenger(challenger_id)
        event_bus.publish("learning.shadow.rejected", ...)

    def canary_deploy(self, challenger_id: str, allocation_pct: float = 0.1):
        """Canary deployment — küçük pozisyonlarla test."""
        # %10 pozisyonla challenger'ı kullan
        # Performans monitor et
        # Başarılıysa kademeli artır
```

#### 5.3 — Orchestrator Entegrasyonu
- [ ] Retrain sonrası otomatik shadow mode başlat
- [ ] Shadow mode sonucuna göre promote/reject
- [ ] Canary deployment (opsiyonel — daha sonraki faz)

**Teslimat:** `pytest tests/test_learning_faz5.py` — shadow mode, champion-challenger, promote/reject

---

### FAZ 6: Model Registry (2-3 gün)

**Amaç:** Model versiyonlarını detaylı takip et, rollback desteği.

#### 6.1 — Model Registry
```
Dosya: services/learning/model_registry.py
```
```python
class ModelRegistry:
    """Model versiyon kayıt defteri."""

    def register(
        self,
        model_id: str,
        version: str,
        metrics: Dict,
        features: List[str],
        hyperparameters: Dict,
        training_data_info: Dict,
        status: str = "CANDIDATE",
    ) -> ModelRecord:
        """Yeni model versiyonu kaydet."""
        record = ModelRecord(
            model_id=model_id,
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            metrics=metrics,
            features=features,
            hyperparameters=hyperparameters,
            training_data_info=training_data_info,
            status=status,  # CANDIDATE, SHADOW, CHAMPION, RETIRED
            performance_history=[],
        )
        self._records.append(record)
        self._persist()
        return record

    def promote_to_champion(self, version: str):
        """Versiyonu champion yap."""
        # Mevcut champion'ı retired yap
        for r in self._records:
            if r.status == "CHAMPION":
                r.status = "RETIRED"
                r.retired_at = datetime.now(timezone.utc).isoformat()
        # Yeni champion
        record = self._get_version(version)
        record.status = "CHAMPION"

    def rollback(self, to_version: str):
        """Önceki versiyona geri dön."""
        record = self._get_version(to_version)
        if record:
            self.promote_to_champion(to_version)

    def get_champion(self) -> Optional[ModelRecord]:
        """Mevcut champion model."""
        for r in self._records:
            if r.status == "CHAMPION":
                return r
        return None

    def get_performance_history(self, version: str) -> List[Dict]:
        """Model performans geçmişi."""
        record = self._get_version(version)
        return record.performance_history if record else []

    def cleanup_old_versions(self, keep_last: int = 20):
        """Eski versiyonları temizle."""
        # Champion ve son N versiyonu tut, diğerlerini sil
```

#### 6.2 — Database Entegrasyonu
- [ ] PostgreSQL'de `model_versions` tablosu (zaten var — genişletilecek)
- [ ] Model metadata, metrics, features saklama
- [ ] Performance history tracking

#### 6.3 — API Entegrasyonu
- [ ] `GET /api/learning/models` — tüm model versiyonları
- [ ] `GET /api/learning/models/{version}` — detay
- [ ] `POST /api/learning/models/{version}/rollback` — rollback

**Teslimat:** `pytest tests/test_learning_faz6.py` — register, promote, rollback, cleanup

---

### FAZ 7: Meta-Learning Enhancement (2-3 gün)

**Amaç:** Rejim-specific model selection, dynamic ensemble weights.

#### 7.1 — Meta Learner
```
Dosya: services/learning/meta_learner.py
```
```python
class MetaLearner:
    """Rejim-specific model selection ve ensemble optimization."""

    def select_best_model(self, regime: str) -> Optional[str]:
        """Rejim için en iyi modeli seç."""
        regime_performance = self._get_regime_performance(regime)
        if not regime_performance:
            return None

        best_model = max(regime_performance.items(), key=lambda x: np.mean(x[1]))
        return best_model[0]

    def calculate_ensemble_weights(
        self,
        models: List[str],
        regime: str,
    ) -> Dict[str, float]:
        """Dynamic ensemble weights — rejime göre."""
        weights = {}
        total_score = 0

        for model in models:
            performance = self._get_model_regime_performance(model, regime)
            # Sharpe-based weighting
            avg_sharpe = np.mean(performance[-10:]) if performance else 0
            score = max(avg_sharpe, 0.01)  # Negatif ağırlık önleme
            weights[model] = score
            total_score += score

        # Normalize
        return {m: round(w / total_score, 4) for m, w in weights.items()}

    def predict_decay(self, model_version: str) -> Dict:
        """Model decay prediction — ne zaman retrain gerekli?"""
        history = self._get_performance_history(model_version)
        if len(history) < 30:
            return {"decay_predicted": False, "reason": "Insufficient data"}

        # Trend analizi
        sharpes = [h["sharpe"] for h in history[-60:]]
        trend = np.polyfit(range(len(sharpes)), sharpes, 1)[0]

        # Decay prediction
        if trend < -0.001:  # Negatif trend
            current_sharpe = sharpes[-1]
            days_to_threshold = max(0, (current_sharpe - 0.3) / abs(trend))
            return {
                "decay_predicted": True,
                "trend": round(trend, 6),
                "current_sharpe": round(current_sharpe, 4),
                "estimated_days_to_retrain": int(days_to_threshold),
            }

        return {"decay_predicted": False, "trend": round(trend, 6)}

    def record_regime_performance(
        self,
        model_version: str,
        regime: str,
        metrics: Dict,
    ):
        """Rejim bazlı performans kaydet."""
        self._regime_model_performance[regime][model_version].append(metrics)
```

#### 7.2 — Ensemble Entegrasyonu
- [ ] Birden fazla model varsa dynamic ensemble
- [ ] Rejim değişince ağırlıkları güncelle
- [ ] Ensemble prediction: weighted average

#### 7.3 — Decay Prediction
- [ ] Performans trend analizi
- [ ] Tahmini retrain zamanı
- [ ] Proaktif retrain tetikleme

**Teslimat:** `pytest tests/test_learning_faz7.py` — model selection, ensemble weights, decay prediction

---

### FAZ 8: Gelişmiş Attribution (2-3 gün)

**Amaç:** Factor-based attribution — hangi faktör ne kadar katkı sağladı.

#### 8.1 — Gelişmiş Attribution Engine
```
Dosya: services/learning/attribution.py (refactor)
```
```python
class AdvancedAttributionEngine:
    """Factor-based trade attribution."""

    def attribute(
        self,
        ticker: str,
        entry_date: datetime,
        exit_date: datetime,
        entry_price: float,
        exit_price: float,
        expected_return: float,
        features_at_entry: Dict,
        features_at_exit: Dict,
        shap_values: Optional[np.ndarray] = None,
        regime: str = "UNKNOWN",
    ) -> AdvancedTradeAttribution:
        """SHAP-based factor attribution."""

        actual_return = (exit_price / entry_price - 1) * 100

        # 1. Factor decomposition
        factors = {
            "momentum": self._calc_momentum_factor(features_at_entry, features_at_exit),
            "value": self._calc_value_factor(features_at_entry, features_at_exit),
            "quality": self._calc_quality_factor(features_at_entry, features_at_exit),
            "macro": self._calc_macro_factor(features_at_entry, features_at_exit),
            "technical": self._calc_technical_factor(features_at_entry, features_at_exit),
            "sentiment": self._calc_sentiment_factor(features_at_entry, features_at_exit),
        }

        # 2. SHAP-based attribution (varsa)
        if shap_values is not None:
            shap_attribution = self._shap_attribution(shap_values, feature_names)
        else:
            shap_attribution = None

        # 3. Residual
        attributed_sum = sum(factors.values())
        residual = actual_return - attributed_sum

        # 4. Dersler
        lessons = self._extract_advanced_lessons(
            actual_return, expected_return, factors, regime
        )

        return AdvancedTradeAttribution(
            ticker=ticker,
            actual_return=round(actual_return, 2),
            expected_return=round(expected_return, 2),
            factors={k: round(v, 2) for k, v in factors.items()},
            residual=round(residual, 2),
            shap_attribution=shap_attribution,
            regime=regime,
            lessons=lessons,
        )
```

#### 8.2 — SHAP Entegrasyonu
- [ ] Her trade sonrası SHAP values hesapla
- [ ] Factor decomposition ile birleştir
- [ ] Dashboard'da factor contribution grafikleri

**Teslimat:** `pytest tests/test_learning_faz8.py` — factor attribution, SHAP integration

---

### FAZ 9: Health Monitoring & Self-Healing (2-3 gün)

**Amaç:** Sistem sağlığını izle, hataları otomatik onar.

#### 9.1 — Health Monitor
```
Dosya: services/learning/health_monitor.py
```
```python
class LearningHealthMonitor:
    """Learning system sağlık izleme."""

    def check_health(self) -> HealthReport:
        """Tüm modüllerin sağlık durumunu kontrol et."""
        checks = {
            "prediction_tracking": self._check_prediction_tracking(),
            "outcome_tracking": self._check_outcome_tracking(),
            "calibration": self._check_calibration(),
            "drift_detection": self._check_drift_detection(),
            "model_performance": self._check_model_performance(),
            "feature_pipeline": self._check_feature_pipeline(),
            "database": self._check_database(),
        }

        critical = [k for k, v in checks.items() if v["status"] == "CRITICAL"]
        warnings = [k for k, v in checks.items() if v["status"] == "WARNING"]

        overall = "CRITICAL" if critical else ("WARNING" if warnings else "HEALTHY")

        return HealthReport(
            overall_status=overall,
            module_status=checks,
            critical_modules=critical,
            warning_modules=warnings,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def auto_heal(self, health_report: HealthReport):
        """Otomatik onarım."""
        for module, status in health_report.module_status.items():
            if status["status"] == "CRITICAL":
                healing_action = self._determine_healing_action(module, status)
                self._execute_healing(healing_action)
```

#### 9.2 — Self-Healing Actions
| Modül Sorunu | Healing Aksiyon |
|-------------|-----------------|
| Outcome tracking stuck | Price fetcher restart |
| Calibration degraded | Confidence adjustment |
| Drift detected | Retrain trigger |
| Model performance drop | Fallback to rule-based |
| Database connection lost | Retry with backoff |
| Feature pipeline error | Data refresh |

#### 9.3 — Dashboard Entegrasyonu
- [ ] Health status endpoint: `GET /api/learning/health`
- [ ] Grafana dashboard: module status, performance metrics
- [ ] Alert: critical durumda notification

**Teslimat:** `pytest tests/test_learning_faz9.py` — health check, auto-heal

---

### FAZ 10: Test, Kalibrasyon ve Production Hazırlığı (3-4 gün)

**Amaç:** Sistemi production-ready yap.

#### 10.1 — Kapsamlı Test Suite
```
Dosya: tests/test_learning_system.py (genişletme)
```
- [ ] Unit test'ler: her modül için
- [ ] Integration test'ler: pipeline akışı
- [ ] Drift detection test'leri: bilinen drift'leri tespit et
- [ ] Calibration test'leri: overconfident/underconfident detection
- [ ] Shadow mode test'leri: promote/reject senaryoları
- [ ] Walk-forward test'leri: purge/embargo doğruluğu
- [ ] Edge case test'leri: yetersiz veri, tüm modüller başarısız
- [ ] Performance test'leri: pipeline süresi

#### 10.2 — Backtest Entegrasyonu
- [ ] Learning pipeline kararlarını backtest engine'e ekle
- [ ] Calibrated vs non-calibrated performans karşılaştırması
- [ ] Shadow mode kararlarının geriye dönük analizi

#### 10.3 — Paper Trading
- [ ] Learning pipeline'ı paper trading modunda çalıştır
- [ ] Gerçek zamanlı calibration check
- [ ] Drift detection alert'leri

#### 10.4 — Monitoring & Alerting
- [ ] Prometheus metrics: calibration_brier, drift_psi, retrain_count
- [ ] Alert: calibration degrade, drift detected, retrain triggered
- [ ] Dashboard: learning pipeline durumu

#### 10.5 — Dokümantasyon
- [ ] Learning system README güncelle
- [ ] Her modül için docstring
- [ ] Architecture diagram
- [ ] Runbook: troubleshooting

**Teslimat:** `pytest tests/test_learning_faz10.py` — tüm testler yeşil, backtest raporu

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam pipeline)
         ├─────────────┤
         │ Integration  │  ← 15 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 60+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 0 | test_learning_faz0.py | 10 | Config loading, refactor validation |
| 1 | test_learning_faz1.py | 12 | Brier score, overconfidence detection |
| 2 | test_learning_faz2.py | 15 | PSI, KS test, drift type classification |
| 3 | test_learning_faz3.py | 10 | Walk-forward integration, deflated Sharpe |
| 4 | test_learning_faz4.py | 10 | SHAP tracking, trend analysis |
| 5 | test_learning_faz5.py | 12 | Shadow mode, promote/reject |
| 6 | test_learning_faz6.py | 10 | Register, promote, rollback |
| 7 | test_learning_faz7.py | 10 | Model selection, ensemble weights |
| 8 | test_learning_faz8.py | 8 | Factor attribution, SHAP |
| 9 | test_learning_faz9.py | 8 | Health check, auto-heal |
| 10 | test_learning_faz10.py | 15 | E2E, backtest, performance |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| Walk-forward overfitting | Orta | Yüksek | CPCV, deflated Sharpe, purge+embargo |
| Shadow mode çok uzun sürer | Orta | Orta | Configurable duration, minimum prediction count |
| SHAP hesaplama yavaş | Yüksek | Orta | Sampling, caching, periyodik hesaplama |
| Drift false positive | Orta | Yüksek | Çoklu yöntem cross-check, severity scoring |
| Calibration yetersiz veri | Yüksek | Orta | Minimum sample requirement, regime pooling |
| Auto-retrain kötü model üretir | Orta | Kritik | Walk-forward gate, shadow mode gate |
| Model registry şişmesi | Düşük | Orta | Auto-cleanup, configurable max versions |
| Concept drift tespit gecikmesi | Orta | Yüksek | Performance-based monitoring, daily check |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 0** | 1-2 gün | Yok | Config, helpers, refactor |
| **Faz 1** | 2-3 gün | Faz 0 | Calibration system |
| **Faz 2** | 2-3 gün | Faz 0 | Gelişmiş drift detection |
| **Faz 3** | 2-3 gün | Faz 0 | Walk-forward entegrasyonu |
| **Faz 4** | 2-3 gün | Faz 0 | Feature importance tracking |
| **Faz 5** | 3-4 gün | Faz 1+2+3 | Shadow mode + champion-challenger |
| **Faz 6** | 2-3 gün | Faz 5 | Model registry |
| **Faz 7** | 2-3 gün | Faz 5+6 | Meta-learning enhancement |
| **Faz 8** | 2-3 gün | Faz 4 | Gelişmiş attribution |
| **Faz 9** | 2-3 gün | Faz 1-8 | Health monitoring + self-healing |
| **Faz 10** | 3-4 gün | Faz 1-9 | Test, kalibrasyon, production |
| **TOPLAM** | **22-31 gün** | | |

**Not:** Faz 1, 2, 3, 4 paralel geliştirilebilir (bağımsız). Faz 5, 6, 7 sıralı (bağımlı). Bu durumda toplam süre **18-25 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **Walk-forward gate** — Retrain sonrası walk-forward validation zorunlu. Başarısızsa shadow mode'a geçilmez.
2. **Shadow mode zorunlu** — Yeni model doğrudan production'a alınamaz. Minimum 21 gün observation.
3. **Calibration-first** — Confidence calibration her pipeline çalışmasında kontrol edilir.
4. **Drift çoklu yöntem** — Tek yöntemle drift kararı verilmez. En az 2 yöntem hemfikir olmalı.
5. **NO_TRADE default** — Belirsizlik varsa model değişikliği yok (CGX prensibi).
6. **Config-driven** — Tüm eşikler config'den okunur, hardcoded değil.
7. **Backtest-first** — Her faz için backtest kanıtı gerekli.
8. **SHAP-based** — Feature importance ve attribution SHAP ile yapılır (model-agnostic).
9. **Event-driven** — Tüm önemli olaylar event_bus'a publish edilir.
10. **Graceful degradation** — Bir modül çökse diğerleri çalışmaya devam eder.

---

## 📚 Referanslar

1. Aerospike Model Drift (2025) — https://aerospike.com/blog/model-drift-machine-learning/
2. Databricks MLOps Workflow — https://docs.databricks.com/aws/en/machine-learning/mlops/mlops-workflow
3. QuantInsti Walk-Forward (2025) — https://blog.quantinsti.com/walk-forward-optimization-introduction/
4. Quant Beckman CPCV (2025) — https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross
5. Frouros Drift Library — https://github.com/IFCA-Advanced-Computing/frouros
6. SentientConcepts PSI Guide (2025) — https://www.sentientconcepts.com/post/data-drift-detection
7. IBM Model Drift — https://www.ibm.com/think/topics/data-drift-in-machine-learning
8. arXiv Shadow Before Swap (2026) — Shadow deployment best practices
9. CalibreOS ML System Design (2026) — https://www.calibreos.com/learn/mlsd
10. Interpretable ML SHAP (2026) — https://wires.onlinelibrary.wiley.com/doi/10.1002/widm.70075
