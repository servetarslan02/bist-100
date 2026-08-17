# Test Beklentileri

**Amaç:** Her modül için hangi testlerin geçmesi gerektiği.
**Kural:** Bir modül ancak tüm testleri geçtikten sonra "tamam" sayılır.

---

## Mevcut Test Durumu

| Test Dosyası | Modül | Durum |
|-------------|-------|-------|
| test_bist_rules.py | core (BIST kuralları) | ✅ 30/30 |
| test_feature_eng.py | features | ✅ 9/9 |
| test_bolum25_32.py | ml, factors, event_study, viop, macro, alternative | ✅ 36/36 |
| test_backtest_v4.py | backtest | ✅ Mevcut |
| test_backtest_performance.py | backtest | ✅ Mevcut |
| test_backtest_data_parity.py | backtest | ✅ Mevcut |
| test_canonical_backtest.py | backtest | ✅ Mevcut |
| test_walkforward_canonical.py | backtest | ✅ Mevcut |
| test_faz4_backtest.py | backtest | ✅ Mevcut |
| test_backtest_v5_upgrade.py | backtest | ✅ Mevcut |

**Toplam:** 83 test dosyası, 75+ test geçiyor.

---

## Her Modül İçin Test Gereksinimleri

### Seviye 0: Core Temel

| Modül | Test | Beklenen |
|-------|------|----------|
| config.py | Config yükleme | Settings doğru yükleniyor |
| database.py | DB bağlantısı | PostgreSQL/SQLite bağlantısı kuruluyor |
| event_bus.py | Event publish/subscribe | Event'ler doğru yayınlanıyor ve alınıyor |
| models.py | Model oluşturma | CanonicalEvent, vb. doğru oluşturuluyor |

### Seviye 1: Core Servisler

| Modül | Test | Beklenen |
|-------|------|----------|
| security.py | Yetkilendirme | RBAC doğru çalışıyor |
| data_quality.py | Veri kalitesi | Hatalı veri tespit ediliyor |
| circuit_breaker.py | Circuit breaker | CLOSED→OPEN→HALF_OPEN geçişleri doğru |
| audit_log.py | Audit logging | Olaylar doğru kaydediliyor |

### Seviye 2: Veri Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| bist_universe.py | Universe yükleme | BIST hisseleri doğru yükleniyor |
| yfinance_provider.py | OHLCV çekme | Fiyat verisi doğru geliyor |
| kap_provider.py | KAP çekme | KAP açıklamaları doğru geliyor |
| data_validator.py | Veri doğrulama | Hatalı veri tespit ediliyor |

### Seviye 3: Feature Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| calculator.py | Feature hesaplama | 63+ feature doğru hesaplanıyor |
| technical_features.py | Teknik göstergeler | RSI, MACD, ATR doğru hesaplanıyor |
| cross_sectional.py | Cross-sectional | Sektör bazlı sıralama doğru |
| feature_selector.py | Feature selection | Korelasyon filtreleme çalışıyor |

### Seviye 4: Intelligence Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| regime.py | Rejim tespiti | 11 rejim doğru tespit ediliyor |
| spec_engine.py | SPEC skor | 6 threshold aktif kullanılıyor |
| signal_fusion.py | Sinyal birleştirme | Rejime göre ağırlık değişiyor |
| monte_carlo.py | Monte Carlo | Simülasyon sonuçları makul |
| probability.py | Olasılık | Dağılım doğru hesaplanıyor |
| scenario.py | Senaryo analizi | Şok etkileri doğru hesaplanıyor |
| trade_planner.py | İşlem planı | Entry/stop/target doğru |
| world_state.py | World state | Factor bazlı decay çalışıyor |
| forecasting.py | Tahmin | Multi-horizon tahmin çalışıyor |
| evidence_engine.py | Kanıt doğrulama | Hallucination tespit ediliyor |
| knowledge_graph.py | Bilgi grafiği | Entity/relation doğru |
| research_memory.py | Araştırma hafızası | Lineage tracking çalışıyor |
| factor_engine.py | Faktör motoru | Fama-French doğru hesaplanıyor |
| impact_engine.py | Etki motoru | Event impact doğru hesaplanıyor |
| macro_sensitivity.py | Makro duyarlılık | Sektör hassasiyeti doğru |
| news_pipeline.py | Haber pipeline | Entity extraction çalışıyor |
| kap_extractor.py | KAP çıkarma | KAP parsing doğru |
| kap_llm_extractor.py | KAP LLM | LLM analiz çalışıyor |
| analysis_engines.py | Analiz motorları | 11 motor çalışıyor |
| prediction_layer.py | Tahmin katmanı | Prediction doğru |
| pipeline.py | Pipeline | 19 motor entegre |

### Seviye 5: ML Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| ranking_model.py | Ranking model | Eğitim ve tahmin çalışıyor |
| lightgbm_trainer.py | LightGBM | Eğitim, NDCG, multi-horizon |
| xgboost_model.py | XGBoost | Eğitim ve tahmin |
| lstm_model.py | LSTM | Eğitim ve tahmin |
| transformer_model.py | Transformer | Eğitim ve tahmin |
| ensemble.py | Ensemble | Ağırlıklı tahmin |
| model_comparator.py | Model karşılaştırma | Karşılaştırma doğru |
| training_validator.py | Eğitim doğrulama | Leakage detection |
| walk_forward.py | Walk-forward | Fold'lar doğru bölünüyor |
| adjusted_loss.py | Adjusted loss | Yanlış yön cezası |

### Seviye 6: Decision Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| decision_engine.py | Karar motoru | HOLD/ LONG/SHORT doğru |
| risk_gate.py | Risk kapısı | 9 check doğru çalışıyor |
| compliance.py | SPK uyumluluk | %5/%10 eşik doğru |
| short_selling.py | Açığa satış | BIST-30, uptick rule doğru |
| halt_monitor.py | Durdurma | Halt kontrolü doğru |
| price_limits.py | Fiyat limitleri | ±%10 limit doğru |
| fee_calculator.py | Komisyon | BIST komisyon yapısı doğru |
| gross_settlement.py | Brüt takas | Brüt takas kontrolü doğru |
| viop_monitor.py | VIOP monitor | Teminat kontrolü doğru |

### Seviye 7: Risk Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| enhanced_risk.py | Gelişmiş risk | Ledoit-Wolf, Kelly, rebalance |
| position_sizing.py | Pozisyon boyutu | Kelly, volatility targeting |
| calibration.py | Kalibrasyon | Platt scaling doğru |
| covariance.py | Kovaryans | Ledoit-Wolf shrinkage doğru |
| reconciliation.py | Uzlaştırma | Ledger vs DB tutarlı |

### Seviye 8: Portfolio Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| portfolio_manager.py | Portföy yönetimi | open/close/reduce, P&L, invariant |
| enhancements.py | Geliştirmeler | Tax, dividend, benchmark |
| main.py | Portfolio service | Atomic operations, lock |

### Seviye 9: Simulation Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| execution_simulator.py | Execution | Order lifecycle, slippage, commission |
| main.py | Simulation engine | Monte Carlo, scenario, stress test |

### Seviye 10: Backtest Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| engine.py | Basit backtest | Sonuçlar makul |
| engine_v4.py | Gelişmiş backtest | Canonical scoring, fast mode |
| walk_forward.py | Walk-forward | Fold'lar, metrics, deflated sharpe |
| enhanced_walk_forward.py | Purge/embargo | Precision@K, IC, hit rate |
| walk_forward_runner.py | WF runner | Fold backtest, aggregation |
| portfolio_sim.py | Portföy sim | Trade, position, equity, invariant |
| canonical_adapter.py | Canonical adapter | Scoring doğru |
| persistence.py | Saklama | Save/load doğru |

### Seviye 11: Learning Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| outcome_tracker.py | Outcome takibi | Tahmin-gerçek eşleşme |
| attribution.py | Attribution | Faktör katkısı doğru |
| learning_loop.py | Öğrenme döngüsü | Döngü çalışıyor |
| integrated_learning.py | Entegre öğrenme | Tüm learning entegre |
| continuous_learning.py | Sürekli öğrenme | Drift detection |
| super_intelligence.py | Süper zekâ | Self-healing |

### Seviye 12: Scanner Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| opportunity_engine.py | Fırsat motoru | 10 bileşenli skor |
| alpha_engine.py | Alpha motoru | Tick processing |
| alpha_scanner.py | Alpha scanner | Breakout, volume |
| event_scanner.py | Event scanner | KAP/haber/macro tepki |
| live_scanner.py | Live scanner | Gerçek zamanlı |
| tiered_scanner.py | Tiered scanner | 6 katmanlı tarama |
| event_queue.py | Event queue | Öncelikli kuyruk |
| backtest_runner.py | Backtest runner | Scanner backtest |

### Seviye 13: Agent Katmanı

| Modül | Test | Beklenen |
|-------|------|----------|
| agent_system.py | Agent sistemi | 10 rol, tool erişimi, validation, fallback |

### Seviye 14: Orkestrasyon

| Modül | Test | Beklenen |
|-------|------|----------|
| orchestrator.py | Orkestratör | 35 servis entegre |
| scheduler/main.py | Scheduler | Market-aware scheduling |
| api/main.py | API | Endpoint'ler çalışıyor |
| api/server.py | Dashboard | HTML sayfalar yükleniyor |
| api/websocket.py | WebSocket | Bağlantı kuruluyor |

---

## Test Çalıştırma

```bash
# Tüm testler
python3 -m pytest tests/ -v

# Sadece BIST kuralları
python3 -m pytest tests/test_bist_rules.py -v

# Sadece feature engineering
python3 -m pytest tests/test_feature_eng.py -v

# Sadece backtest
python3 -m pytest tests/test_backtest*.py -v

# Import testi (160+ modül)
python3 run_all_imports.py
```
