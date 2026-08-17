# Sistem Bağlantı Planı — 138 Modülü Pipeline'a Bağlama

**Tarih:** 2026-08-18
**Durum:** BAŞLADI

---

## Problem
160 modülün 138'i kodda var ama başka hiçbir yerden çağrılmıyor. Pipeline'a bağlı değil.

## Çözüm
Tüm modülleri mantıksal akışa bağla:

```
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING
```

---

## Faz 1: Feature Bağlantıları (12 modül)

### 1.1 calculator.py → technical_features, fundamental, sentiment, macro, extended_indicators
- calculator.py zaten var ama technical_features, fundamental, sentiment, macro, extended_indicators'i çağırmıyor
- Çözüm: calculator.py'ye bu modülleri import et ve compute_all_features'a entegre et

### 1.2 features/main.py → calculator, discovery, store, bar_engine, feature_contract, incremental_state, data_adapter
- main.py var ama pipeline'ı çağırmıyor
- Çözüm: main.py'yi gerçek pipeline orchestrator yap

### 1.3 feature_selector → calculator
- calculator.feature_selector'ı çağırmıyor
- Çözüm: calculator'da feature selection opsiyonu ekle

### 1.4 store → calculator
- Feature store calculator'dan bağımsız
- Çözüm: calculator sonucu store'a yazsın

---

## Faz 2: Intelligence Bağlantıları (19 modül)

### 2.1 intelligence/main.py → TÜM intelligence modülleri
- main.py var ama hiçbir motoru çağırmıyor
- Çözüm: main.py'yi gerçek orchestrator yap

### 2.2 intelligence/pipeline.py → world_state, regime, forecasting, probability, monte_carlo, scenario
- pipeline.py var ama modülleri çağırmıyor
- Çözüm: pipeline'ı gerçek akışa bağla

### 2.3 analysis_engines → tek tek motorlar
- analysis_engines.py var ama bağımsız
- Çözüm: pipeline'a entegre et

### 2.4 evidence_engine → kap_extractor, news_pipeline, research_memory
- evidence_engine bağımsız
- Çözüm: intelligence pipeline'a entegre et

### 2.5 factor_engine → piotroski, beneish, altman (B30)
- Entegrasyon yapıldı ama factor_engine çağrılmıyor
- Çözüm: intelligence pipeline'da çağır

### 2.6 impact_engine → event_study (B31)
- Entegrasyon yapıldı ama impact_engine çağrılmıyor
- Çözüm: intelligence pipeline'da çağır

### 2.7 knowledge_graph, research_memory → pipeline
- Bağımsız duruyor
- Çözüm: intelligence pipeline'da kullan

### 2.8 spec_engine → pipeline
- Zayıf bağlı (1 import)
- Çözüm: pipeline'da çağır

### 2.9 macro_sensitivity → features/macro
- Bağımsız
- Çözüm: macro feature hesaplamada kullan

### 2.10 trade_planner → decision
- Bağımsız
- Çözüm: decision engine'a entegre et

### 2.11 kap_llm_extractor → kap_extractor
- Bağımsız
- Çözüm: KAP pipeline'da LLM fallback olarak kullan

---

## Faz 3: Decision Bağlantıları (3 modül)

### 3.1 signal_fusion → intelligence/main.py
- Zayıf bağlı (1 import)
- Çözüm: intelligence pipeline sonucunu signal_fusion'a besle

### 3.2 spec_engine → signal_fusion
- Bağımsız
- Çözüm: signal_fusion'da SPEC skorunu kullan

### 3.3 trade_planner → decision_engine
- Bağımsız
- Çözüm: decision_engine karar sonrası trade planı oluştur

---

## Faz 4: Risk Bağlantıları (4 modül)

### 4.1 enhanced_risk → risk/main.py
- Bağımsız
- Çözüm: risk/main.py enhanced_risk'i çağırsın

### 4.2 reconciliation → portfolio
- Bağımsız
- Çözüm: portfolio periyodik reconciliation çağırsın

### 4.3 calibration → risk
- Bağımsız
- Çözüm: risk motoru calibration'ı kullansın

### 4.4 covariance → enhanced_risk
- Bağımsız
- Çözüm: enhanced_risk covariance'ı kullansın

---

## Faz 5: Portfolio Bağlantıları (3 modül)

### 5.1 portfolio/main.py → enhancements
- Bağımsız
- Çözüm: main.py enhancements'ı çağırsın

### 5.2 enhancements → portfolio
- TaxModel, DividendHandler, BenchmarkEngine, PerformanceAttribution, MultiCurrencyHandler
- Çözüm: portfolio service'de kullan

---

## Faz 6: Learning Bağlantıları (4 modül)

### 6.1 outcome_tracker → learning/main.py
- Bağımsız
- Çözüm: learning service outcome_tracker'ı çağırsın

### 6.2 attribution → learning
- Bağımsız
- Çözüm: learning service attribution'ı kullansın

### 6.3 learning_loop → learning
- Bağımsız
- Çözüm: learning service learning_loop'u başlatsın

### 6.4 continuous_learning → learning
- Zayıf bağlı (1 import)
- Çözüm: learning service'de çağır

---

## Faz 7: ML Bağlantıları (13 modül)

### 7.1 ranking_model → lightgbm_trainer
- ranking_model zaten lightgbm_trainer'ı çağırıyor (4 import) ✅

### 7.2 ensemble, model_comparator, xgboost, lstm, transformer → ranking_model
- Bağımsız
- Çözüm: ranking_model'de ensemble prediction olarak kullan

### 7.3 finrl_bist, fingpt, hybrid_model, rl_agent → ML pipeline
- Bağımsız
- Çözüm: ML orchestrator'da çağır

### 7.4 walk_forward → backtest
- Bağımsız
- Çözüm: backtest engine walk_forward'ı kullansın

### 7.5 training_validator → ranking_model
- 3 import var ✅

### 7.6 qlib_integration → framework
- Placeholder — bağlantı yok

---

## Faz 8: Backtest Bağlantıları (4 modül)

### 8.1 engine_v4 → engine
- Bağımsız
- Çözüm: engine_v4'ü varsayılan backtest engine yap

### 8.2 enhanced_walk_forward → walk_forward
- Bağımsız
- Çözüm: walk_forward enhanced sürümü kullansın

### 8.3 portfolio_sim → portfolio
- Bağımsız
- Çözüm: backtest'te portfolio simülasyonu olarak kullan

### 8.4 walk_forward_runner → walk_forward
- Bağımsız
- Çözüm: backtest orchestrator'da çağır

---

## Faz 9: Scanner Bağlantıları (5 modül)

### 9.1 scanner/main.py → alpha_engine, alpha_scanner, event_scanner, live_scanner, opportunity_engine, tiered_scanner
- Hepsi zayıf bağlı (1 import)
- Çözüm: scanner orchestrator'da çağır

### 9.2 backtest_runner → backtest
- Bağımsız
- Çözüm: scanner'da backtest tetikleme olarak kullan

### 9.3 event_queue → event_bus
- Bağımsız
- Çözüm: event_bus'a entegre et

---

## Faz 10: B23-32 Modülleri (38 modül)

### 10.1 Macro (7) → features/macro.py
- Entegrasyon yapıldı ✅ ama features/macro.py çağrılmıyor
- Çözüm: features pipeline'da çağır

### 10.2 Factors (7) → factor_engine
- Entegrasyon yapıldı ✅ ama factor_engine çağrılmıyor
- Çözüm: intelligence pipeline'da çağır

### 10.3 Event Study (7) → impact_engine
- Entegrasyon yapıldı ✅ ama impact_engine çağrılmıyor
- Çözüm: intelligence pipeline'da çağır

### 10.4 VIOP (6) → risk + portfolio
- Bağımsız
- Çözüm: risk motoru VIOP hedging'i önersin

### 10.5 Alternative Data (5) → features
- Bağımsız
- Çözüm: feature pipeline'da alternatif veri olarak kullan

### 10.6 SPK (5) → risk_gate
- manipulation_detector, insider_detector, algo_notification, reporting, tax
- Bağımsız
- Çözüm: risk_gate ve compliance'da kullan

---

## Faz 11: Agents + Scheduler + Simulation + API

### 11.1 agent_system → intelligence pipeline
- Bağımsız (511 satır)
- Çözüm: intelligence orchestrator olarak kullan

### 11.2 scheduler → scanner + learning
- Bağımsız
- Çözüm: scheduler scanner ve learning'i zamanlasın

### 11.3 simulation/main.py → execution_simulator
- Bağımsız
- Çözüm: simulation service'i başlat

### 11.4 api → tüm servisler
- Bağımsız
- Çözüm: API endpoint'lerini servislere bağla

---

## Faz 12: Orchestrator — Ana Pipeline

Tüm servisleri tek bir ana pipeline'da birleştir:

```python
# main.py veya orchestrator.py

def run_full_pipeline(date):
    # 1. VERİ
    ingestion_service.collect_data(date)
    
    # 2. FEATURE
    features = calculator.compute_all_features(data)
    macro_features = compute_all_macro_features(tcmb, inflation, fx, cds)
    features.update(macro_features)
    
    # 3. INTELLIGENCE
    world_state = world_state_manager.update(features)
    regime = regime_engine.detect_regime(features)
    forecasting = forecasting_engine.compute_forecasts(features)
    monte_carlo = monte_carlo_engine.simulate(features)
    probability = probability_engine.compute(features)
    spec = spec_engine.compute_spec(features)
    factors = compute_financial_scores(financials)
    event_impact = analyze_event_impact(ticker, events)
    knowledge = knowledge_graph.propagate_impact(events)
    research = research_memory.get_context(ticker)
    evidence = evidence_engine.verify(claims)
    
    # 4. DECISION
    signal = signal_fusion.fuse_signals(all_signals, regime)
    decision = decision_engine.decide(signal)
    trade_plan = trade_planner.plan(decision)
    
    # 5. RISK
    risk_check = risk_gate.check_order(decision)
    enhanced_risk = enhanced_risk_engine.assess(portfolio, decision)
    compliance = compliance_checker.check(decision)
    
    # 6. PORTFOLIO
    if risk_check.allowed:
        portfolio.execute(decision)
    
    # 7. LEARNING
    outcome_tracker.track(decision, result)
    learning_loop.update()
    attribution.analyze()
```

---

## Uygulama Sırası

| Faz | İçerik | Modül | Öncelik |
|-----|--------|-------|---------|
| 1 | Feature bağlantıları | 12 | 🔴 |
| 2 | Intelligence bağlantıları | 19 | 🔴 |
| 3 | Decision bağlantıları | 3 | 🔴 |
| 4 | Risk bağlantıları | 4 | 🔴 |
| 5 | Portfolio bağlantıları | 3 | 🔴 |
| 6 | Learning bağlantıları | 4 | 🟡 |
| 7 | ML bağlantıları | 13 | 🟡 |
| 8 | Backtest bağlantıları | 4 | 🟡 |
| 9 | Scanner bağlantıları | 5 | 🟡 |
| 10 | B23-32 bağlantıları | 38 | 🟡 |
| 11 | Agents/Scheduler/API | 8 | 🟢 |
| 12 | Orchestrator | 1 | 🔴 |
