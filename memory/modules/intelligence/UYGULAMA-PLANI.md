# 🚀 Intelligence Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:** arXiv Agentic Trading (2026), MDPI Regime-Aware LightGBM (2026), TradingAgents (TauricResearch 2025), ICUQF Monte Carlo Fusion (2026), HMM Gold Market Regimes (Medium 2026), SHAP-Enhanced Gradient Boosting (ACM 2026)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Genel Mimari Tasarım](#3-genel-mimari-tasarım)
4. [Faz Planı](#4-faz-planı)
5. [Test Stratejisi](#5-test-stratejisi)

---

## 1. Araştırma Bulguları

### 1.1 HMM Regime Detection (Medium 2026, MDPI 2026)

**Kaynak:** Medium Kryptera (2026), MDPI Regime-Aware LightGBM (2026)

**Rolling HMM:**
- 252 gün eğitim window'u (1 yıl)
- 4 rejim: Bull, Bear, High-Vol, Low-Vol
- Her 63 günde yeniden eğit (quarterly)
- Return + volatility → 2D feature space
- GaussianHMM, full covariance

**Dersler:**
- ✅ Rolling window şart — tüm veriye fit etmek overfitting
- ✅ 4 rejim yeterli — daha fazlası overfitting riski
- ✅ Return + volatility en iyi feature çifti
- ✅ Regime probability > binary classification
- ⚠️ hmmlearn pip ile kurulmalı

### 1.2 Ensemble Forecasting (ResearchGate 2026, ACM 2026)

**Kaynak:** Explainable AI in Stock Prediction (2026), SHAP-Enhanced GBF (ACM 2026)

**Ensemble Mimarisi:**
- LightGBM + XGBoost + CatBoost → stacking
- SHAP ile feature importance → dynamic weights
- Regime-conditioned model selection
- Model agreement = confidence proxy

**Dersler:**
- ✅ Stacking > simple averaging
- ✅ SHAP feature importance → interpretable weights
- ✅ Regime-specific model selection kritik
- ✅ Model agreement yüksekse confidence yüksek

### 1.3 Confidence Calibration (Wiley 2025)

**Probabilistic AI Forecasting:**
- Brier score → calibration metric
- Calibration curve → overconfidence detection
- Isotonic regression → post-hoc calibration
- Hit rate tracking → per-regime accuracy

---

## 2. Mevcut Sistem Analizi

### 2.1 Kritik Eksiklikler

| # | Sorun | Etki | Öncelik |
|---|-------|------|---------|
| 1 | HMM regime detection yok | Matematiksel rejim tespiti eksik | Yüksek |
| 2 | Pipeline paralel değil | 21 modül sırasıyla → yavaş | Yüksek |
| 3 | Forecasting tek model | Ensemble eksik | Yüksek |
| 4 | Confidence calibration yok | Overconfidence riski | Yüksek |
| 5 | Monte Carlo basit GBM | Jump-diffusion, fat tails yok | Orta |
| 6 | Signal fusion sabit ağırlık | ML-optimized ağırlık yok | Orta |
| 7 | Prediction layer çok basit | Multi-horizon eksik | Orta |
| 8 | Model agreement yok | Cross-model consensus eksik | Orta |

### 2.2 Mevcut Pipeline Akışı

```
MEVCUT (Sıralı):
  features → regime → signal_fusion → spec → trade_planner → output
  (Her modül birbirini bekliyor)

HEDEF (Paralel):
  features → [regime | world_state | macro_sens | factor_engine] (paralel)
           → [technical | fundamental | sentiment | news] (paralel)
           → [forecasting | monte_carlo | probability] (paralel)
           → signal_fusion (tüm sonuçları birleştir)
           → spec_engine → trade_planner → output
```

---

## 3. Genel Mimari Tasarım

### 3.1 Nihai Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                INTELLIGENCE PIPELINE v3.0                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 1: PARALLEL CONTEXT (asyncio.gather)          │   │
│  │  Regime + WorldState + MacroSensitivity + Factor      │   │
│  │  → ContextBundle                                      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 2: PARALLEL ANALYSIS (asyncio.gather)         │   │
│  │  Technical + Fundamental + Sentiment + News/KAP       │   │
│  │  → AnalysisBundle                                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 3: ENSEMBLE FORECAST (asyncio.gather)         │   │
│  │  LightGBM + XGBoost + Heuristic + Monte Carlo        │   │
│  │  → EnsembleForecast (agreement + calibrated conf.)    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 4: SIGNAL FUSION (ML-optimized)               │   │
│  │  Conflict detection + Regime weights + SHAP weights   │   │
│  │  → FusedSignal                                        │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 5: SPEC + TRADE PLANNER                       │   │
│  │  → TradePlan                                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PHASE 6: KNOWLEDGE GRAPH + MEMORY                   │   │
│  │  → IntelligenceOutput                                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Faz Planı

### FAZ 0: HMM Regime Detection (2-3 gün) ✅ BAŞLANACAK

**Amaç:** Matematiksel rejim tespiti ekle.

#### 0.1 — HMM Regime Detector
```
Dosya: services/intelligence/hmm_regime.py
```
- [ ] `HMMRegimeDetector` class
- [ ] `fit(returns, volatility)` — GaussianHMM eğitimi
- [ ] `predict_regime()` → regime + probability
- [ ] `rolling_detect(window=63)` — rolling HMM
- [ ] Regime transition matrix
- [ ] Fallback: hmmlearn yoksa rule-based

#### 0.2 — Regime Engine Entegrasyonu
```
Dosya: services/intelligence/regime.py (değişiklik)
```
- [ ] Mevcut `RegimeEngine` ile HMM sonucunu birleştir
- [ ] Hybrid: HMM probability × rule-based score
- [ ] `detect_regime()` → HMM + rule-based weighted

**Test:** `tests/test_intelligence_faz0.py` — HMM fit/predict/rolling

---

### FAZ 1: Parallel Pipeline (2-3 gün)

**Amaç:** Pipeline'ı paralel çalıştır.

#### 1.1 — Parallel Runner
```
Dosya: services/intelligence/parallel_pipeline.py
```
- [ ] `ParallelIntelligencePipeline` class
- [ ] Phase 1: `asyncio.gather(regime, world_state, macro, factor)`
- [ ] Phase 2: `asyncio.gather(technical, fundamental, sentiment, news)`
- [ ] Phase 3: `asyncio.gather(forecast, monte_carlo, probability)`
- [ ] Phase 4-6: sıralı (birbirine bağımlı)
- [ ] Timeout + partial failure handling

#### 1.2 — Pipeline Refactor
```
Dosya: services/intelligence/pipeline.py (değişiklik)
```
- [ ] `run()` methodunu async yap
- [ ] Parallel phases entegrasyonu
- [ ] Metrics: phase durations

**Test:** `tests/test_intelligence_faz1.py` — paralel çalıştığını doğrula

---

### FAZ 2: Ensemble Forecasting (3-4 gün)

**Amaç:** Çoklu model ensemble forecasting.

#### 2.1 — Ensemble Engine
```
Dosya: services/intelligence/ensemble_forecast.py
```
- [ ] `EnsembleForecaster` class
- [ ] Register models: LightGBM, XGBoost, Heuristic, Statistical
- [ ] Regime-based model weighting
- [ ] Model agreement scoring
- [ ] Confidence calibration

#### 2.2 — ML Signal Fusion
```
Dosya: services/intelligence/ml_signal_fusion.py
```
- [ ] SHAP-based weight optimization
- [ ] Regime-specific weights
- [ ] Conflict detection improvements
- [ ] Self-check mechanism

**Test:** `tests/test_intelligence_faz2.py` — ensemble + ML fusion

---

### FAZ 3: Confidence Calibration (2-3 gün)

**Amaç:** Overconfidence önleme.

#### 3.1 — Confidence Calibrator
```
Dosya: services/intelligence/confidence_calibrator.py
```
- [ ] Calibration curve hesaplama
- [ ] Brier score
- [ ] Overconfidence detection
- [ ] Automatic adjustment
- [ ] Per-regime calibration

**Test:** `tests/test_intelligence_faz3.py` — calibration tests

---

### FAZ 4: Advanced Monte Carlo (2-3 gün)

**Amaç:** Jump-diffusion, fat tails.

#### 4.1 — Enhanced Monte Carlo
```
Dosya: services/intelligence/monte_carlo.py (değişiklik)
```
- [ ] Jump-diffusion model (Merton)
- [ ] Student-t distribution (fat tails)
- [ ] Stochastic volatility (Heston-lite)
- [ ] Correlated paths iyileştirme

**Test:** `tests/test_intelligence_faz4.py` — advanced MC

---

### FAZ 5: Prediction Layer + Test (3-4 gün)

**Amaç:** Multi-horizon prediction, kapsamlı test.

#### 5.1 — Prediction Layer Enhancement
```
Dosya: services/intelligence/prediction_layer.py (değişiklik)
```
- [ ] Multi-horizon support (1d, 5d, 20d, 60d)
- [ ] Ensemble integration
- [ ] Calibration integration

#### 5.2 — Comprehensive Tests
```
Dosya: tests/test_intelligence_system.py
```
- [ ] 100+ test
- [ ] Integration tests
- [ ] Edge cases

---

## 5. Test Stratejisi

| Faz | Test Dosyası | Min Test |
|-----|-------------|----------|
| 0 | test_intelligence_faz0.py | 12 |
| 1 | test_intelligence_faz1.py | 10 |
| 2 | test_intelligence_faz2.py | 15 |
| 3 | test_intelligence_faz3.py | 10 |
| 4 | test_intelligence_faz4.py | 10 |
| 5 | test_intelligence_faz5.py | 15 |
| **TOPLAM** | | **72+** |

---

## 📊 Zaman Özeti

| Faz | Süre | Teslimat |
|-----|------|----------|
| Faz 0 | 2-3 gün | HMM regime detection |
| Faz 1 | 2-3 gün | Parallel pipeline |
| Faz 2 | 3-4 gün | Ensemble forecasting + ML fusion |
| Faz 3 | 2-3 gün | Confidence calibration |
| Faz 4 | 2-3 gün | Advanced Monte Carlo |
| Faz 5 | 3-4 gün | Prediction layer + tests |
| **TOPLAM** | **14-20 gün** | |

**Paralel geliştirme:** Faz 0 + Faz 1 birlikte → toplam **12-16 gün**.
