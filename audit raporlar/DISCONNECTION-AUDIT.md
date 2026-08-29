# BIST-100 Sistem Geneli Veri Akışı Kopuklukları Raporu

**Tarih:** 2026-08-22  
**Kapsam:** Event Bus, Orchestrator, Intelligence Pipeline, Risk Flow, Macro Flow, Learning Flow, API Tutarlılığı

---

## 1. EVENT BUS AUDIT

### 1.1 Publish Edilen Ama Tüketilmeyen Event'ler

#### Kopukluk 1: AGENT_ANALYSIS_COMPLETED — Tüketici Yok
- **Konu:** Orchestrator `AGENT_ANALYSIS_COMPLETED` event'i publish ediyor ama hiçbir servis bu event'i consume etmiyor
- **Üretici:** `services/core/orchestrator.py` (satır ~596)
- **Tüketici:** **YOK** — Ne risk engine, ne learning, ne de intelligence service bu event'i dinliyor
- **Mevcut Durum:** Orchestrator agent analiz sonucunu event bus'a publish ediyor ama event havada kalıyor. Risk engine sadece `DECISION_CREATED` ve `SIGNAL_GENERATED` dinliyor.
- **Öneri:** Risk engine'e `AGENT_ANALYSIS_COMPLETED` handler ekle; agent risk veto mekanizması bu event üzerinden çalışmalı. Learning service'e de bu event'i dinleterek agent tahmin doğruluğu takip edilmeli.
- **Öncelik:** Yüksek

#### Kopukluk 2: PREDICTION_CREATED / OUTCOME_CREATED — Publish Edilmiyor
- **Konu:** Event schema'da tanımlı ama hiçbir yerde publish edilmiyor
- **Üretici:** Olması gereken: `services/learning/integrated_learning.py` veya `services/core/orchestrator.py`
- **Tüketici:** Event schema'da tanımlı, learning service dinlemeli
- **Mevcut Durum:** `IntegratedLearningSystem.record_prediction()` ve `record_outcome()` çalışıyor ama event bus'a bildirim yapmıyor. Outcome tracker bağımsız çalışıyor ama event üretmiyor.
- **Öneri:** `record_prediction()` sonunda `PREDICTION_CREATED`, `record_outcome()` sonunda `OUTCOME_CREATED` event'i publish et. Bu event'ler learning scheduler ve monitoring tarafından tüketilmeli.
- **Öncelik:** Orta

#### Kopukluk 3: DECISION_CREATED — Orchestrator Publish Etmiyor
- **Konu:** Risk engine `DECISION_CREATED` event'ini dinliyor ama orchestrator decision step'inde bu event'i publish etmiyor
- **Üretici:** Olması gereken: `services/core/orchestrator.py` → decision step sonrası
- **Tüketici:** `services/risk/main.py` → `_on_decision()` handler (satır 70)
- **Mevcut Durum:** Orchestrator decision sonucunu `result["decision"]` dict'ine yazıyor ama event bus'a publish etmiyor. Risk engine'in `_on_decision()` handler'ı asla tetiklenmiyor. Risk engine sadece bağımsız servis olarak çalıştığında (async event loop) bu event'i görebilir.
- **Öneri:** Orchestrator'ın `run_pipeline()` methodunda decision step sonrası `DECISION_CREATED` event'i publish et.
- **Öncelik:** Kritik

#### Kopukluk 4: ORDER_PLACED / ORDER_FILLED — Publish Edilmiyor
- **Konu:** Event schema'da tanımlı ama orchestrator veya paper trading tarafından publish edilmiyor
- **Üretici:** Olması gereken: `services/paper_trading/paper_execution.py` veya `services/core/broker.py`
- **Tüketici:** Learning service (outcome tracking), risk engine (P&L tracking)
- **Mevcut Durum:** Paper trading modülü var ama order events üretmiyor. Learning service'in `_outcome_tracking_loop()` DB'den prediction okuyor ama order events'i almıyor.
- **Öneri:** Paper execution modülüne order fill sonrası `ORDER_FILLED` event publish ekle.
- **Öncelik:** Yüksek

#### Kopukluk 5: KILL_SWITCH_TRIGGERED — Tetikleme Mekanizması Yok
- **Konu:** Event tanımlı ama hiçbir kill switch mekanizması bu event'i üretmiyor
- **Üretici:** Olması gereken: `services/core/risk_gate.py` veya `services/risk/drawdown_response.py`
- **Tüketici:** Tüm servisler (trading durdurma)
- **Mevcut Durum:** Drawdown response sistemi var (`drawdown_response.py`) ama `KILL_SWITCH_TRIGGERED` event'i publish etmiyor. Sadece internal state değiştiriyor.
- **Öneri:** Drawdown response'un `EMERGENCY` seviyesinde `KILL_SWITCH_TRIGGERED` event publish et. Tüm trading servisleri bu event'i dinlemeli.
- **Öncelik:** Kritik

#### Kopukluk 6: Market State Event'leri — Tüketici Eksik
- **Konu:** `BREADTH_ALERT`, `LIQUIDITY_ALERT`, `ANOMALY_CLUSTER`, `SENTIMENT_SHIFT`, `MULTI_TF_DIVERGENCE`, `REGIME_TRANSITION` — market_state servisi publish ediyor ama tüketen yok
- **Üretici:** `services/market_state/main.py` → `_publish_events()` (satır 514+)
- **Tüketici:** **YOK** — Orchestrator, risk engine, intelligence service bu event'leri dinlemiyor
- **Mevcut Durum:** Market state engine kapsamlı event'ler üretiyor ama hiçbir downstream servis bunları tüketmiyor. Orchestrator market state'i doğrudan fonksiyon çağrısıyla almıyor.
- **Öneri:** Orchestrator ve risk engine bu event'leri dinlemeli. `REGIME_TRANSITION` event'i orchestrator'ın regime step'ini tetiklemeli.
- **Öncelik:** Yüksek

### 1.2 Event Bus Altyapı Sorunları

#### Kopukluk 7: Orchestrator Sync Çalışıyor — Event Bus Kullanamıyor
- **Konu:** Orchestrator `run_pipeline()` senkron method ama event bus asenkron
- **Üretici:** `services/core/orchestrator.py`
- **Tüketici:** Event bus (`services/core/event_bus.py`)
- **Mevcut Durum:** Orchestrator sync context'te çalışıyor. Agent event publish denemesi `asyncio.get_event_loop().create_task()` ile yapılıyor ama bu yaklaşım güvenilir değil. Decision, risk, learning event'leri hiç publish edilmiyor.
- **Öneri:** Orchestrator'ı async'e çevir veya sync→async bridge kullanarak event publish'leri garantile.
- **Öncelik:** Yüksek

---

## 2. ORCHESTRATOR AUDIT

### 2.1 Forecasting Step — Çalışmıyor

#### Kopukluk 8: Forecasting Step Boş
- **Konu:** Orchestrator'ın forecasting step'i gerçek hesaplama yapmıyor
- **Üretici:** `services/intelligence/forecasting.py` → `ForecastingEngine`
- **Tüketici:** Orchestrator → `result["forecast"]`
- **Mevcut Durum:** Orchestrator sadece `forecast = {"horizons": [1, 5, 20]}` yazıyor (satır ~460). `ForecastingEngine.compute_forecasts()` çağrılmıyor. Forecast sonuçları sonraki step'lerde (signal fusion, decision) kullanılmıyor.
- **Öneri:** `fe.compute_forecasts(ticker, features, historical_returns)` çağrısını ekle ve forecast sonucunu signal fusion'a besle.
- **Öncelik:** Yüksek

### 2.2 Monte Carlo Step — Çalışmıyor

#### Kopukluk 9: Monte Carlo Step Boş
- **Konu:** Orchestrator'ın monte_carlo step'i gerçek simülasyon yapmıyor
- **Üretici:** `services/intelligence/monte_carlo.py` → `MonteCarloEngine`
- **Tüketici:** Orchestrator → `result["monte_carlo"]`
- **Mevcut Durum:** Orchestrator sadece `monte_carlo = {"simulated": True}` yazıyor (satır ~470). `MonteCarloEngine.simulate_price_paths()` çağrılmıyor. MC sonuçları risk check'e aktarılmıyor.
- **Öneri:** MC simülasyonunu çalıştır, `var_95`, `prob_positive`, `expected_return` sonuçlarını risk gate ve decision engine'e besle.
- **Öncelik:** Yüksek

### 2.3 Macro Verisi Decision Engine'e Aktarılmıyor

#### Kopukluk 10: Macro Pipeline Sonuçları DecisionInput'a Yazılamıyor
- **Konu:** Orchestrator macro analiz yapıyor ama sonuçları DecisionInput'a aktarmıyor
- **Üretici:** `run_full_pipeline()` → macro pipeline (satır ~777)
- **Tüketici:** `DecisionEngine.decide()` → `DecisionInput.macro_regime/macro_stance/macro_confidence/macro_impact`
- **Mevcut Durum:** `run_full_pipeline()` macro regime detection çalıştırıyor ve `macro_analysis` dict'ine yazıyor. Ama `run_pipeline()` (tek hisse) bu verileri hiç üretmiyor. DecisionInput'un `macro_regime`, `macro_stance`, `macro_confidence`, `macro_impact` alanları hep default değerlerde (UNKNOWN, 0.0, 0.0, 0.0) kalıyor. Decision engine'in `_macro_score()` methodu boş çalışıyor.
- **Öneri:** `run_pipeline()` içinde macro modülleri çalıştır ve sonuçları DecisionInput'a aktar. `run_full_pipeline()` içinde de per-ticker DecisionInput'a macro verilerini ekle.
- **Öncelik:** Kritik

### 2.4 Learning Sistemi Pipeline'a Bağlı Değil

#### Kopukluk 11: Orchestrator Learning Modüllerini Kullanmıyor
- **Konu:** Orchestrator initialize'da learning modüllerini yüklüyor ama pipeline'da hiç kullanmıyor
- **Üretici:** `services/core/orchestrator.py` → initialize (satır 266-279)
- **Tüketici:** `IntegratedLearningSystem`, `OutcomeTracker`
- **Mevcut Durum:** Orchestrator `_services["outcome_tracker"]` ve `_services["learning"]` olarak yüklüyor ama `run_pipeline()` ve `run_full_pipeline()`'da bu servisleri hiç çağırmıyor. Pipeline sonuçları (tahmin, karar, outcome) learning system'a aktarılmıyor.
- **Öneri:** Pipeline sonunda `learning.record_prediction()` çağrısı ekle. Outcome tracking için pipeline sonuçlarını learning system'a besle.
- **Öncelik:** Yüksek

### 2.5 PipelineReport Eksiklikleri

#### Kopukluk 12: PipelineReport.learning_status Hiç Doldurulmuyor
- **Konu:** `PipelineReport` dataclass'ında `learning_status` var ama `run_full_pipeline()` bu alanı hiç doldurmuyor
- **Üretici:** `services/core/orchestrator.py` → `PipelineReport` (satır 31)
- **Tüketici:** API endpoint'leri, raporlama
- **Mevcut Durum:** `learning_status` hep boş dict `{}` olarak kalıyor.
- **Öneri:** `run_full_pipeline()` sonunda learning status'u doldur.
- **Öncelik:** Düşük

---

## 3. INTELLIGENCE PIPELINE AUDIT

### 3.1 IntelligencePipeline Orchestrator Tarafından Kullanılmıyor

#### Kopukluk 13: IntelligencePipeline — Kullanılmayan Parallel Yapı
- **Konu:** `IntelligencePipeline` ve `IntelligenceOutput` tanımlı ama orchestrator bunları hiç kullanmıyor
- **Üretici:** `services/intelligence/pipeline.py` → `intelligence_pipeline` singleton
- **Tüketici:** **YOK** — Orchestrator servisleri doğrudan çağırıyor
- **Mevcut Durum:** Orchestrator her intelligence modülünü ayrı ayrı `_services.get()` ile çağıyor. `IntelligencePipeline.run()` methodu 17 modülü organize şekilde çalıştırıyor ama orchestrator bunu hiç çağırmıyor. `IntelligenceOutput` dataclass'ı zengin bir çıktı yapısı sunuyor ama hiç kullanılmıyor.
- **Öneri:** Orchestrator'ın intelligence step'ini `intelligence_pipeline.run()` ile değiştir. Bu, modül bağlantılarını otomatik hale getirir.
- **Öncelik:** Orta

### 3.2 Signal Fusion — Hardcoded Sinyaller

#### Kopukluk 14: Pipeline ve Orchestrator'da Signal Fusion'a Gerçek Sinyaller Gitmiyor
- **Konu:** Signal fusion engine'e gönderilen sinyaller hardcoded/default değerler
- **Üretici:** Orchestrator'ın signal fusion step'i (satır ~505), `IntelligencePipeline._run_signal_fusion()`
- **Tüketici:** `SignalFusionEngine.fuse_signals()`
- **Mevcut Durum:** Orchestrator'da sinyaller şöyle oluşturuluyor:
  ```python
  "technical": {"direction": "LONG" if rsi > 55 else "SHORT", "score": rsi}
  "fundamental": {"direction": "NEUTRAL", "score": 50}  # hardcoded
  "macro": {"direction": "NEUTRAL", "score": 50}  # hardcoded
  "valuation": {"direction": "NEUTRAL", "score": 50}  # hardcoded
  ```
  Intelligence pipeline'da daha da kötü: tüm sinyaller NEUTRAL/0.5.
  Fundamental, macro, valuation sinyalleri hiç gerçek veri kullanmıyor.
- **Öneri:** Her sinyal kaynağını gerçek hesaplama sonuçlarından besle: macro → macro_regime_detector, fundamental → factor_engine, valuation → spec_engine.
- **Öncelik:** Kritik

### 3.3 Parallel Pipeline — Faz Sonuçları Fusion'a Aktarılmıyor

#### Kopukluk 15: Phase 1-3 Sonuçları Phase 4'e Tam Aktarılmıyor
- **Konu:** Parallel pipeline'da phase 1-3 sonuçları phase 4 (fusion) step'ine yeterince beslenmiyor
- **Üretici:** `services/intelligence/parallel_pipeline.py` → `_run_phase4()`
- **Tüketici:** Signal fusion, spec engine, trade planner
- **Mevcut Durum:** `_run_signal_fusion()` methodunda phase 1-3 sonuçları parametre olarak alınıyor ama sadece `regime` bilgisi kullanılıyor. Forecasting, monte_carlo, probability, factor_engine sonuçları signal fusion'a aktarılmıyor. Signal fusion yine hardcoded NEUTRAL sinyaller kullanıyor.
- **Öneri:** Phase 1-3 modül sonuçlarını signal fusion'a gerçek sinyal olarak besle.
- **Öncelik:** Yüksek

---

## 4. RISK FLOW AUDIT

### 4.1 VaR/CVaR Pipeline'a Bağlı Değil

#### Kopukluk 16: VaR/CVaR Hesaplamaları Orchestrator ve Decision Engine'e Bağlı Değil
- **Konu:** Kapsamlı VaR/CVaR modülü var ama orchestrator pipeline'ında hiç kullanılmıyor
- **Üretici:** `services/risk/var_cvar.py` → `VaRCalculator`
- **Tüketici:** Olması gereken: orchestrator, decision engine, risk gate
- **Mevcut Durum:** `VaRCalculator` 3 yöntemle (parametrik, tarihsel, Monte Carlo) VaR/CVaR hesaplıyor, component VaR ve marginal VaR destekliyor. Ama orchestrator'ın risk step'inde sadece `RiskGate.check_order()` çağrılıyor — bu da sadece basit limit kontrolleri yapıyor. VaR/CVaR sonuçları risk gate'e, decision engine'e veya position sizing'e aktarılmıyor.
- **Öneri:** Orchestrator risk step'inde `VaRCalculator.calculate_full_var_report()` çağrısı ekle. VaR sonuçlarını risk gate ve decision engine'e besle.
- **Öncelik:** Yüksek

### 4.2 Stress Test Sonuçları Karar Mekanizmasına Aktarılmıyor

#### Kopukluk 17: Stress Test — Breaking Point Analizi Kullanılmıyor
- **Konu:** Stress test engine kapsamlı ama sonuçları pipeline'da kullanılmıyor
- **Üretici:** `services/risk/stress_test.py` → `StressTestEngine`
- **Tüketici:** Olması gereken: risk gate, decision engine
- **Mevcut Durum:** `StressTestEngine` tarihsel senaryolar (2008, 2020, 2022), hipotetik senaryolar ve breaking point analizi sunuyor. `RiskGate`'in `check_macro_stress()` methodu var ama orchestrator bunu çağırmıyor. `set_macro_stress_result()` methodu risk gate'e stres sonucu besleyebilir ama hiç kullanılmıyor.
- **Öneri:** Orchestrator pipeline'ında stres testi çalıştır ve sonuçlarını `risk_gate.set_macro_stress_result()` ile risk gate'e besle. Breaking point analizini position sizing'de kullan.
- **Öncelik:** Yüksek

### 4.3 Position Sizing Pipeline'a Bağlı Değil

#### Kopukluk 18: Position Sizing — Orchestrator Tarafından Kullanılmıyor
- **Konu:** `PositionSizer` (Calibrated Kelly + Vol Targeting) var ama orchestrator'da hiç çağrılmıyor
- **Üretici:** `services/risk/position_sizing.py` → `PositionSizer`
- **Tüketici:** Olması gereken: orchestrator → trade plan step'i
- **Mevcut Durum:** Orchestrator'ın trade plan step'i `TradePlanner.plan_trade()` çağrıyor ama `PositionSizer.calculate_position_sizes()` hiç çağrılmıyor. Trade plan'daki position boyutu, Kelly fraction veya volatilite hedeflemesi kullanılmıyor.
- **Öneri:** Trade plan step'inde `PositionSizer` entegre et. Regime ve volatilite bazlı position boyutu hesapla.
- **Öncelik:** Yüksek

### 4.4 Risk Monitoring — Event-Based Uyarı Sistemi Çalışmıyor

#### Kopukluk 19: Risk Monitoring Alert'leri Pipeline'da Üretilmiyor
- **Konu:** `risk/monitoring.py` alert sistemi var ama pipeline'dan gelen metriklerle beslenmiyor
- **Üretici:** `services/risk/monitoring.py` → `RiskMonitor`
- **Tüketici:** API endpoint'leri, kullanıcı bildirimleri
- **Mevcut Durum:** Risk monitoring API'de çalışıyor (`/risk/monitoring`, `/risk/alerts`) ama pipeline'dan üretilen metriklerle (VaR, drawdown, position size) beslenmiyor. Alert kuralları var ama tetiklenme mekanizması pipeline'a bağlı değil.
- **Öneri:** Pipeline risk step'inde monitoring'e metrik snapshot gönder.
- **Öncelik:** Orta

---

## 5. MACRO FLOW AUDIT

### 5.1 Macro Modülleri Orchestrator'a Bağlı Değil

#### Kopukluk 20: Macro Surprise Model — Kullanılmıyor
- **Konu:** `MacroSurpriseModel` (beklenti vs gerçek sürpriz) var ama orchestrator'da hiç çağrılmıyor
- **Üretici:** `services/macro/surprise_model.py`
- **Tüketici:** Olması gereken: orchestrator → macro step, intelligence → macro_sensitivity
- **Mevcut Durum:** Model TCMB faiz, enflasyon, GSYH sürprizlerini hesaplayabiliyor, sector-specific impact ve decay modeli sunuyor. Ama orchestrator'ın macro step'inde sadece `compute_all_macro_features()` çağrılıyor — surprise model hiç kullanılmıyor.
- **Öneri:** Orchestrator macro step'inde surprise model'i entegre et. Sürpriz sonuçlarını features'a ve decision engine'e aktar.
- **Öncelik:** Orta

#### Kopukluk 21: Macro Correlation Tracker — Kullanılmıyor
- **Konu:** `MacroCorrelationTracker` var ama hiç kullanılmıyor
- **Üretici:** `services/macro/correlation_tracker.py`
- **Tüketici:** Olması gereken: risk engine, portfolio optimizer
- **Mevcut Durum:** Makro değişken korelasyon takibi yapabilen modül var ama ne orchestrator ne de risk engine tarafından kullanılıyor.
- **Öneri:** Risk engine'de korelasyon rejim değişikliklerini tespit etmek için kullan.
- **Öncelik:** Düşük

#### Kopukluk 22: Macro Factor Decomposition — Kullanılmıyor
- **Konu:** `MacroFactorDecomposition` var ama hiç kullanılmıyor
- **Üretici:** `services/macro/factor_decomposition.py`
- **Tüketici:** Olması gereken: risk engine, portfolio optimizer
- **Mevcut Durum:** Faktör ayrıştırması yapabilen modül var ama ne orchestrator ne de risk engine tarafından kullanılıyor.
- **Öneri:** Risk raporlamasında faktör bazlı risk ayrıştırması için kullan.
- **Öncelik:** Düşük

### 5.2 Macro API — Hardcoded Sensitivity Değerleri

#### Kopukluk 23: Macro Impact Endpoint — Gerçek Veri Kullanılmıyor
- **Konu:** `/macro/impact/{ticker}` endpoint'i hardcoded sensitivity değerleri döndürüyor
- **Üretici:** `services/api/v1/macro.py` → `macro_impact()` (satır ~109)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** Endpoint her ticker için aynı hardcoded değerleri döndürüyor:
  ```python
  "interest_rate_sensitivity": -0.42,
  "fx_sensitivity": 0.68,
  "inflation_beta": 1.15,
  ```
  `MacroSensitivityEngine` veya `DynamicSensitivityEngine` hiç çağrılmıyor.
- **Öneri:** Endpoint'i `macro_sensitivity_engine.get_company_sensitivity(ticker)` ile besle.
- **Öncelik:** Orta

---

## 6. LEARNING FLOW AUDIT

### 6.1 Outcome Tracker — Pipeline Bağlantısı Yok

#### Kopukluk 24: Outcome Tracker — Tahminler Kaydedilmiyor
- **Konu:** `OutcomeTracker` var ama orchestrator pipeline'ı tahmin kaydetmiyor
- **Üretici:** `services/learning/outcome_tracker.py`
- **Tüketici:** `IntegratedLearningSystem.record_outcome()`
- **Mevcut Durum:** `OutcomeTracker.add_prediction()` methodu var, tahmin eklenince otomatik outcome takibi başlatıyor. Ama orchestrator pipeline'ı bu methodu hiç çağırmıyor. Pipeline sonunda üretilen forecast, signal, decision sonuçları outcome tracker'a aktarılmıyor.
- **Öneri:** Pipeline sonunda `outcome_tracker.add_prediction()` çağrısı ekle. Forecast sonucunu prediction olarak kaydet.
- **Öncelik:** Kritik

### 6.2 Learning Feedback — Decision Engine'e Geri Bağlanmıyor

#### Kopukluk 25: Learning Sistemi → Decision Engine Feedback Döngüsü Kopuk
- **Konu:** Learning sistemi model doğruluklarını takip ediyor ama bu bilgi decision engine'e geri beslenmiyor
- **Üretici:** `services/learning/integrated_learning.py` → regime accuracy, feature importance
- **Tüketici:** Olması gereken: `services/core/decision_engine.py` → confidence ayarlaması
- **Mevcut Durum:** `IntegratedLearningSystem` regime bazlı doğruluk (`_regime_accuracy`), feature importance ve model drift tespiti yapıyor. Ama bu bilgiler decision engine'in `_min_confidence` eşiklerine veya ağırlıklarına yansımıyor. Decision engine statik eşiklerle çalışıyor.
- **Öneri:** Learning sisteminin regime doğruluk skorlarını decision engine'in confidence eşiklerine dinamik olarak besle.
- **Öncelik:** Yüksek

### 6.3 Champion/Challenger — Pipeline Entegrasyonu Yok

#### Kopukluk 26: Champion/Challenger Sistemi Pipeline'da Kullanılmıyor
- **Konu:** `services/learning/champion_challenger.py` var ama pipeline'da model seçimi yapılmıyor
- **Üretici:** `services/learning/champion_challenger.py`
- **Tüketici:** Olması gereken: orchestrator → forecasting step
- **Mevcut Durum:** Champion/challenger sistemi model karşılaştırması yapabiliyor ama orchestrator pipeline'ında hangi modelin kullanılacağı belirlenmiyor. Forecasting step'i tek bir `ForecastingEngine` kullanıyor.
- **Öneri:** Pipeline forecasting step'inde champion modeli dinamik olarak seç.
- **Öncelik:** Düşük

---

## 7. API vs INTERNAL AUDIT

### 7.1 Intelligence API — Hardcoded Fallback Veriler

#### Kopukluk 27: Intelligence Decisions Endpoint — Gerçek Pipeline Kullanılmıyor
- **Konu:** `/intelligence/decisions` endpoint'i gerçek pipeline yerine hardcoded veri döndürüyor
- **Üretici:** `services/api/v1/intelligence.py` → `get_decisions()` (satır ~40)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** Endpoint `alpha_engine.get_latest_results()` deniyor, boşsa hardcoded demo veri döndürüyor:
  ```python
  {"ticker": "THYAO", "action": "BUY", "confidence": 0.88, ...}
  ```
  Gerçek `DecisionEngine` veya orchestrator pipeline hiç çağrılmıyor.
- **Öneri:** Endpoint'i orchestrator'ın `run_pipeline()` sonucuna veya decision engine'e bağla.
- **Öncelik:** Yüksek

#### Kopukluk 28: Intelligence Regime Endpoint — Hardcoded Fallback
- **Konu:** `/intelligence/regime` endpoint'i gerçek regime detection yerine hardcoded veri döndürüyor
- **Üretici:** `services/api/v1/intelligence.py` → `get_market_regime()` (satır ~18)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** `regime_detector.detect_regime()` çağrılıyor ama başarısız olursa hardcoded BULL_MOMENTUM verisi döndürüyor. Regime detection'ın features parametre alması gerekiyor ama çağrılmıyor.
- **Öneri:** Regime detection'a güncel market features besle.
- **Öncelik:** Orta

#### Kopukluk 29: Risk Portfolio Endpoint — 501 Dönüyor
- **Konu:** `/risk/portfolio` endpoint'i `501 Not Implemented` döndürüyor
- **Üretici:** `services/api/v1/risk.py` → `portfolio_risk()` (satır ~130)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** Endpoint `assess_portfolio_risk()` çağırmadan önce `raise HTTPException(501)` fırlatıyor. "Real return history required" mesajı var ama veri kaynağı bağlantısı yapılmamış.
- **Öneri:** Portfolio risk assessment'i gerçek veri kaynağına bağla veya demo veri ile çalıştır.
- **Öncelik:** Orta

#### Kopukluk 30: Learning Performance Matrix — Hardcoded Fallback
- **Konu:** `/learning/performance-matrix` endpoint'i gerçek model metrics yerine hardcoded veri döndürüyor
- **Üretici:** `services/api/v1/learning.py` → `performance_matrix()` (satır ~37)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** `_pipeline.store.get_latest_metrics_all_models()` boşsa hardcoded model metrikleri döndürüyor (LightGBM IC=0.082, CatBoost IC=0.076 vb.). Bu metrikler gerçek değil.
- **Öneri:** Boş durumda "no data available" döndür veya gerçek model eğitimini tetikle.
- **Öncelik:** Düşük

#### Kopukluk 31: Macro Sensitivity Endpoint — Static Değerler
- **Konu:** `/macro/sensitivity/{sector}` endpoint'i static katsayılar döndürüyor
- **Üretici:** `services/api/v1/macro.py` → `sector_sensitivity()` (satır ~117)
- **Tüketici:** API kullanıcıları
- **Mevcut Durum:** Her sektör için hardcoded katsayılar döndürüyor (BANKING: rate=-0.85). `DynamicSensitivityEngine` hiç çağrılmıyor.
- **Öneri:** `macro_sensitivity_engine` ile gerçek dinamik katsayıları hesapla.
- **Öncelik:** Düşük

---

## ÖNCELİK MATRİSİ

### 🔴 Kritik (Hemen Düzeltilmeli)
| # | Kopukluk | Etki |
|---|---------|------|
| 3 | DECISION_CREATED event publish edilmiyor | Risk engine asla decision evaluate edemiyor |
| 5 | KILL_SWITCH_TRIGGERED tetiklenmiyor | Acil durumda trading durdurulamıyor |
| 10 | Macro verisi DecisionInput'a aktarılmıyor | Decision engine macro sinyallerini hiç kullanmıyor |
| 14 | Signal fusion'a hardcoded sinyaller | Tüm sinyal füzyonu anlamsız |
| 24 | Outcome tracker'a tahmin kaydedilmiyor | Learning sistemi hiç outcome göremiyor |

### 🟡 Yüksek (Sprint İçinde Düzeltilmeli)
| # | Kopukluk | Etki |
|---|---------|------|
| 1 | AGENT_ANALYSIS_COMPLETED tüketici yok | Agent analiz sonuçları havada kalıyor |
| 4 | ORDER_FILLED publish edilmiyor | Outcome tracking çalışamıyor |
| 6 | Market state event'leri tüketici yok | Piyasa durumu değişiklikleri pipeline'a yansımıyor |
| 7 | Orchestrator sync — event bus kullanamıyor | Event-based iletişim kopuk |
| 8 | Forecasting step çalışmıyor | Forecast sonuçları üretilmiyor |
| 9 | Monte Carlo step çalışmıyor | MC sonuçları risk'e aktarılmıyor |
| 11 | Learning pipeline'da kullanılmıyor | Prediction→outcome döngüsü kopuk |
| 13 | IntelligencePipeline kullanılmıyor | 17 modülün organize çalışması sağlanamıyor |
| 15 | Parallel pipeline faz sonuçları aktarılmıyor | Fusion'a gerçek sinyaller gitmiyor |
| 16 | VaR/CVaR pipeline'a bağlı değil | Risk metrikleri karara yansımıyor |
| 17 | Stress test sonuçları kullanılmıyor | Breaking point analizi atlanıyor |
| 18 | Position sizing kullanılmıyor | Kelly fraction ve vol targeting yok |
| 25 | Learning→Decision feedback kopuk | Model doğruluğu karara yansımıyor |
| 27 | Intelligence decisions hardcoded | API gerçek pipeline kullanmıyor |

### 🟢 Orta (Backlog'a Alınmalı)
| # | Kopukluk | Etki |
|---|---------|------|
| 2 | PREDICTION_CREATED/OUTCOME_CREATED publish edilmiyor | Event-based learning tetikleme yok |
| 12 | PipelineReport.learning_status boş | Raporlama eksik |
| 19 | Risk monitoring pipeline'dan beslenmiyor | Alert'ler tetiklenmiyor |
| 20 | Macro surprise model kullanılmıyor | Sürpriz etkileri hesaba katılmıyor |
| 23 | Macro impact endpoint hardcoded | API tutarsız |
| 28 | Regime endpoint hardcoded fallback | API tutarsız |
| 29 | Portfolio risk endpoint 501 | Endpoint çalışmıyor |

### ⚪ Düşük (Nice-to-have)
| # | Kopukluk | Etki |
|---|---------|------|
| 21 | Macro correlation tracker kullanılmıyor | Korelasyon analizi eksik |
| 22 | Macro factor decomposition kullanılmıyor | Faktör analizi eksik |
| 26 | Champion/challenger pipeline'da yok | Model seçimi statik |
| 30 | Learning performance matrix hardcoded | API tutarsız |
| 31 | Macro sensitivity endpoint static | API tutarsız |

---

## MİMARİ ÖNERİ

Bu kopuklukların çoğu aynı kök nedenden kaynaklanıyor: **Orchestrator, servisleri initialize ediyor ama sonuçlarını birbirine bağlamıyor.** Her modül bağımsız çalışıyor ama aralarında veri akışı yok.

### Kısa Vadeli Çözüm (1-2 hafta):
1. Orchestrator'ın `run_pipeline()` methodunda **her step'in çıktısını sonraki step'e aktar** (özellikle macro → decision, forecast → signal fusion, risk → position sizing)
2. **Event publish'leri ekle:** Decision, order, kill switch event'lerini pipeline'dan publish et
3. **Learning entegrasyonu:** Pipeline sonunda prediction kaydet, outcome tracker'ı tetikle

### Orta Vadeli Çözüm (1 ay):
4. Orchestrator'ı async'e çevir, event bus ile tam entegrasyon sağla
5. Intelligence pipeline'ı orchestrator'a entegre et (tek entry point)
6. Risk pipeline'ı zenginleştir: VaR/CVaR + stress test + position sizing zinciri

### Uzun Vadeli Çözüm (2-3 ay):
7. Full event-driven architecture: Her servis event bus üzerinden haberleşsin
8. Learning feedback loop: Model doğrulukları → decision engine confidence ayarlaması
9. API endpoint'lerini gerçek pipeline sonuçlarına bağla, hardcoded fallback'leri kaldır
