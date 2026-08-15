# Uygulama Planı v4 — Bölüm 1-8 (Güncellenmiş)

## Durum Özeti

| Kategori | Durum |
|----------|-------|
| Toplam modül | **104** (düzeltildi: 87 değildi) |
| Bölüm 1-8 ile ilişkili | ~60 modül |
| Planlanan | ~40 modül |
| **EKSİK** | **43 modül** |
| Test dosyaları | ❌ Hiç yok |
| Entegrasyon testleri | ❌ Yapılmamış |

---

## AŞAMA 1: Tüm 104 Modülü Doğrula

### Katman 1: Core (17 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 1.1 | Market Calendar | `core/market_calendar.py` | 1 | ✅ |
| 1.2 | Data Quality Gate | `core/data_quality.py` | 2 | ✅ |
| 1.3 | Tradability Mask | `core/tradability_mask.py` | 2 | ✅ |
| 1.4 | Cross-Source Reconciliation | `core/reconciliation.py` | 1-2 | ✅ |
| 1.5 | PIT Store | `core/pit_store.py` | 1-2 | ✅ |
| 1.6 | Streaming Anomaly | `core/streaming_anomaly.py` | 1-3 | ✅ |
| 1.7 | Circuit Breaker | `core/circuit_breaker.py` | 21 | ✅ |
| 1.8 | Security (RBAC) | `core/security.py` | 19 | ✅ |
| 1.9 | Audit Log | `core/audit_log.py` | 19,22 | ✅ |
| 1.10 | Decision Engine | `core/decision_engine.py` | 12 | ✅ |
| 1.11 | Infrastructure | `core/infrastructure.py` | 20 | ✅ |
| 1.12 | Event Bus | `core/event_bus.py` | 20 | ✅ |
| 1.13 | Observability | `core/observability.py` | 22 | ✅ |
| 1.14 | Recovery | `core/recovery.py` | 21 | ✅ |
| 1.15 | State Recovery | `core/state_recovery.py` | 21 | ✅ |
| 1.16 | **Config** | `core/config.py` | - | ❌ Planlanmamış |
| 1.17 | **Models** | `core/models.py` | - | ❌ Planlanmamış |
| 1.18 | **Event Schema** | `core/event_schema.py` | - | ❌ Planlanmamış |
| 1.19 | **Logging** | `core/logging.py` | - | ❌ Planlanmamış |
| 1.20 | **Database** | `core/database.py` | - | ❌ Planlanmamış |
| 1.21 | **Database Dev** | `core/database_dev.py` | - | ❌ Planlanmamış |

**Eksik açıklamaları:**
- `config.py`: Sistem konfigürasyonu (env, settings)
- `models.py`: Veri modelleri (dataclass, schema)
- `event_schema.py`: Event şema tanımları
- `logging.py`: Log yapılandırması (structlog)
- `database.py`: ClickHouse bağlantısı
- `database_dev.py`: SQLite dev veritabanı

---

### Katman 2: Data Providers (15 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 2.1 | yfinance Provider | `ingestion/providers/yfinance_provider.py` | 1 | ✅ |
| 2.2 | KAP Provider | `ingestion/providers/kap_provider.py` | 1,6 | ✅ |
| 2.3 | News Provider | `ingestion/providers/news_provider.py` | 1,6 | ✅ |
| 2.4 | Social Provider | `ingestion/providers/social_provider.py` | 1,6 | ✅ |
| 2.5 | TCMB Provider | `ingestion/providers/tcmb_provider.py` | 1 | ✅ |
| 2.6 | Fundamental Provider | `ingestion/providers/fundamental_provider.py` | 1,5 | ✅ |
| 2.7 | Corporate Actions | `ingestion/corporate_actions.py` | 1 | ✅ |
| 2.8 | Data Validator | `ingestion/providers/data_validator.py` | 2 | ✅ |
| 2.9 | **BIST Provider** | `ingestion/providers/bist_provider.py` | - | ❌ |
| 2.10 | **BIST Stream** | `ingestion/providers/bist_stream.py` | - | ❌ |
| 2.11 | **Macro Provider** | `ingestion/providers/macro_provider.py` | - | ❌ |
| 2.12 | **Matriks Provider** | `ingestion/providers/matriks_provider.py` | - | ❌ |
| 2.13 | **News Credibility** | `ingestion/providers/news_credibility.py` | - | ❌ |
| 2.14 | **Provider Manager** | `ingestion/providers/provider_manager.py` | - | ❌ |
| 2.15 | **Realtime Provider** | `ingestion/providers/realtime_provider.py` | - | ❌ |
| 2.16 | **Realtime** | `ingestion/realtime.py` | - | ❌ |
| 2.17 | **BIST Universe** | `ingestion/bist_universe.py` | - | ❌ |
| 2.18 | **Universe Enhancements** | `ingestion/universe_enhancements.py` | 4 | ✅ |
| 2.19 | **Ingestion Main** | `ingestion/main.py` | - | ❌ |

**Eksik açıklamaları:**
- `bist_provider.py`: BIST'ten doğrudan veri çekme
- `bist_stream.py`: BIST streaming veri
- `macro_provider.py`: Makro veri sağlayıcı
- `matriks_provider.py`: Matriks veri entegrasyonu
- `news_credibility.py`: Haber kaynak güvenilirliği
- `provider_manager.py`: Provider'ları yöneten orkestratör
- `realtime_provider.py`: Gerçek zamanlı veri sağlayıcı
- `realtime.py`: Gerçek zamanlı veri işleme
- `bist_universe.py`: BIST hisse evreni tanımı
- `main.py`: Ingestion ana modül

---

### Katman 3: Features (12 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 3.1 | Seven Motors | `features/seven_motors.py` | 3-4 | ✅ |
| 3.2 | Fundamental Features | `features/fundamental.py` | 5 | ✅ |
| 3.3 | Sentiment Features | `features/sentiment.py` | 6 | ✅ |
| 3.4 | Cross-Sectional | `features/cross_sectional.py` | 3 | ✅ |
| 3.5 | Macro Features | `features/macro.py` | 3 | ✅ |
| 3.6 | **Bar Engine** | `features/bar_engine.py` | - | ❌ |
| 3.7 | **Calculator** | `features/calculator.py` | - | ❌ |
| 3.8 | **Discovery** | `features/discovery.py` | - | ❌ |
| 3.9 | **Extended Indicators** | `features/extended_indicators.py` | - | ❌ |
| 3.10 | **Incremental State** | `features/incremental_state.py` | - | ❌ |
| 3.11 | **Store** | `features/store.py` | - | ❌ |
| 3.12 | **Features Main** | `features/main.py` | - | ❌ |

**Eksik açıklamaları:**
- `bar_engine.py`: OHLCV bar oluşturma (time-based, tick-based, volume-based)
- `calculator.py`: Feature hesaplama orkestratörü (63+ feature)
- `discovery.py`: Hisse keşfi ve tarama
- `extended_indicators.py`: Ek teknik göstergeler (Ichimoku, Fibonacci, vb.)
- `incremental_state.py`: Artımlı feature güncelleme
- `store.py`: Feature store (saklama/okuma)
- `main.py`: Features ana modül

---

### Katman 4: Intelligence (17 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 4.1 | Regime Engine | `intelligence/regime.py` | 3 | ✅ |
| 4.2 | Factor Engine | `intelligence/factor_engine.py` | 4 | ✅ |
| 4.3 | KAP Extractor | `intelligence/kap_extractor.py` | 6 | ✅ |
| 4.4 | Valuation Engine | `intelligence/valuation/engine.py` | 7 | ✅ |
| 4.5 | Forecasting Engine | `intelligence/forecasting.py` | 8 | ✅ |
| 4.6 | Probability Engine | `intelligence/probability.py` | 8 | ✅ |
| 4.7 | World State Manager | `intelligence/world_state.py` | 1 | ✅ |
| 4.8 | Monte Carlo Engine | `intelligence/monte_carlo.py` | 9 | ✅ |
| 4.9 | Scenario Engine | `intelligence/scenario.py` | 9 | ✅ |
| 4.10 | Signal Fusion | `intelligence/signal_fusion.py` | 12 | ✅ |
| 4.11 | Knowledge Graph | `intelligence/knowledge_graph.py` | 17 | ✅ |
| 4.12 | Research Memory | `intelligence/research_memory.py` | 17 | ✅ |
| 4.13 | Evidence Engine | `intelligence/evidence_engine.py` | 18 | ✅ |
| 4.14 | **Analysis Engines** | `intelligence/analysis_engines.py` | - | ❌ |
| 4.15 | **Impact Engine** | `intelligence/impact_engine.py` | - | ❌ |
| 4.16 | **Macro Sensitivity** | `intelligence/macro_sensitivity.py` | - | ❌ |
| 4.17 | **News Pipeline** | `intelligence/news_pipeline.py` | - | ❌ |
| 4.18 | **Spec Engine** | `intelligence/spec_engine.py` | - | ❌ |
| 4.19 | **Trade Planner** | `intelligence/trade_planner.py` | - | ❌ |
| 4.20 | **Intelligence Main** | `intelligence/main.py` | - | ❌ |

**Eksik açıklamaları:**
- `analysis_engines.py`: Çoklu analiz motoru orkestratörü
- `impact_engine.py`: Olay etki analizi
- `macro_sensitivity.py`: Makro duyarlılık analizi
- `news_pipeline.py`: Haber işleme hattı
- `spec_engine.py`: Hisse spesifikasyon motoru
- `trade_planner.py`: İşlem planlayıcı
- `main.py`: Intelligence ana modül

---

### Katman 5: Risk & Portfolio (5 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 5.1 | Enhanced Risk | `risk/enhanced_risk.py` | 10-11 | ✅ |
| 5.2 | Position Sizing | `risk/position_sizing.py` | 10 | ✅ |
| 5.3 | Portfolio Main | `portfolio/main.py` | 11 | ✅ |
| 5.4 | **Portfolio Enhancements** | `portfolio/enhancements.py` | 1 | ❌ |
| 5.5 | **Risk Main** | `risk/main.py` | - | ❌ |
| 5.6 | **Risk Reconciliation** | `risk/reconciliation.py` | - | ❌ |

**Eksik açıklamaları:**
- `portfolio/enhancements.py`: Multi-currency, FX impact (Bölüm 1'de var ama planda eksik)
- `risk/main.py`: Risk ana modül
- `risk/reconciliation.py`: Risk uzlaştırma

---

### Katman 6: Learning (5 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 6.1 | Integrated Learning | `learning/integrated_learning.py` | 15 | ✅ |
| 6.2 | Outcome Tracker | `learning/outcome_tracker.py` | 15 | ✅ |
| 6.3 | **Attribution** | `learning/attribution.py` | - | ❌ |
| 6.4 | **Learning Loop** | `learning/learning_loop.py` | - | ❌ |
| 6.5 | **Learning Main** | `learning/main.py` | - | ❌ |
| 6.6 | **Label Generator** | `labels/generator.py` | - | ❌ |

---

### Katman 7: ML (2 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 7.1 | Ranking Model | `ml/ranking_model.py` | 4 | ✅ |
| 7.2 | **ML Main** | - | - | ❌ Yok |

---

### Katman 8: Scanner (7 modül) — HİÇ PLANLANMAMIŞ

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 8.1 | **Alpha Engine** | `scanner/alpha_engine.py` | Alpha sinyal üretimi |
| 8.2 | **Alpha Scanner** | `scanner/alpha_scanner.py` | Alpha tarama |
| 8.3 | **Event Queue** | `scanner/event_queue.py` | Event kuyruğu |
| 8.4 | **Event Scanner** | `scanner/event_scanner.py` | Event tarama |
| 8.5 | **Live Scanner** | `scanner/live_scanner.py` | Canlı tarama |
| 8.6 | **Opportunity Engine** | `scanner/opportunity_engine.py` | Fırsat motoru |
| 8.7 | **Tiered Scanner** | `scanner/tiered_scanner.py` | Katmanlı tarama |

---

### Katman 9: Scheduler (2 modül) — HİÇ PLANLANMAMIŞ

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 9.1 | **Daily Report** | `scheduler/daily_report.py` | Günlük rapor |
| 9.2 | **Scheduler Main** | `scheduler/main.py` | Zamanlayıcı |

---

### Katman 10: Simulation (2 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 10.1 | Execution Simulator | `simulation/execution_simulator.py` | 14 | ✅ |
| 10.2 | **Simulation Main** | `simulation/main.py` | - | ❌ |

---

### Katman 11: API (3 modül) — HİÇ PLANLANMAMIŞ

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 11.1 | **API Main** | `api/main.py` | FastAPI endpoint'leri |
| 11.2 | **API Server** | `api/server.py` | HTTP sunucu |
| 11.3 | **WebSocket** | `api/websocket.py` | Gerçek zamanlı WebSocket |

---

### Katman 12: Market State (1 modül) — HİÇ PLANLANMAMIŞ

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 12.1 | **Market State Main** | `market_state/main.py` | Market state orkestratörü |

---

## AŞAMA 2: Eksik Modülleri Grupla

### Grup A: Zaten var, sadece planlanmamış (çalışıyor olabilir)
```
core/config.py, core/models.py, core/event_schema.py, core/logging.py,
core/database.py, core/database_dev.py
features/bar_engine.py, features/calculator.py, features/discovery.py,
features/extended_indicators.py, features/incremental_state.py,
features/store.py, features/main.py
ingestion/bist_universe.py, ingestion/realtime.py, ingestion/main.py
ingestion/providers/bist_provider.py, bist_stream.py, macro_provider.py,
matriks_provider.py, news_credibility.py, provider_manager.py,
realtime_provider.py
intelligence/analysis_engines.py, impact_engine.py, macro_sensitivity.py,
news_pipeline.py, spec_engine.py, trade_planner.py, main.py
portfolio/enhancements.py, risk/main.py, risk/reconciliation.py
learning/attribution.py, learning_loop.py, main.py
labels/generator.py
scanner/* (7 dosya)
scheduler/* (2 dosya)
simulation/main.py
api/* (3 dosya)
market_state/main.py
```

### Grup B: Yeni yazılacak (Bölüm 23-32)
```
core/short_selling.py, core/fee_calculator.py, core/price_limits.py,
core/halt_monitor.py, core/compliance.py, core/manipulation_detector.py
features/technical_features.py, features/bist_specific.py
ml/model_comparator.py, ml/finrl_bist.py
factors/piotroski.py, factors/beneish.py, factors/altman.py
event_study/expected_return.py, event_study/abnormal_return.py
viop/options_pricing.py, viop/greeks.py
alternative/web_scraping.py, alternative/social.py, alternative/jobs.py
```

---

## AŞAMA 3: Tam Import Testi (104 modül)

```python
# run_all_imports.py
import importlib
import sys

modules = [
    # Core (17)
    "services.core.market_calendar",
    "services.core.data_quality",
    "services.core.tradability_mask",
    "services.core.reconciliation",
    "services.core.pit_store",
    "services.core.streaming_anomaly",
    "services.core.circuit_breaker",
    "services.core.security",
    "services.core.audit_log",
    "services.core.decision_engine",
    "services.core.infrastructure",
    "services.core.event_bus",
    "services.core.observability",
    "services.core.recovery",
    "services.core.state_recovery",
    "services.core.config",
    "services.core.models",
    # ... 104 modülün tamamı
]

for mod in modules:
    try:
        importlib.import_module(mod)
        print(f"✓ {mod}")
    except Exception as e:
        print(f"✗ {mod}: {e}")
```

---

## AŞAMA 4: Test Yazma (Tüm modüller)

### Test dosyaları (43 yeni + mevcut):

```
tests/
├── test_core/                    # 17 modül
│   ├── test_market_calendar.py
│   ├── test_data_quality.py
│   ├── test_tradability_mask.py
│   ├── test_reconciliation.py
│   ├── test_pit_store.py
│   ├── test_streaming_anomaly.py
│   ├── test_circuit_breaker.py
│   ├── test_security.py
│   ├── test_audit_log.py
│   ├── test_decision_engine.py
│   ├── test_infrastructure.py
│   ├── test_event_bus.py
│   ├── test_observability.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_database.py
│   └── test_logging.py
├── test_ingestion/               # 15 modül
│   ├── test_providers.py
│   ├── test_bist_provider.py
│   ├── test_kap_provider.py
│   ├── test_news_provider.py
│   ├── test_provider_manager.py
│   ├── test_universe.py
│   └── test_realtime.py
├── test_features/                # 12 modül
│   ├── test_seven_motors.py
│   ├── test_fundamental.py
│   ├── test_sentiment.py
│   ├── test_cross_sectional.py
│   ├── test_bar_engine.py
│   ├── test_calculator.py
│   ├── test_discovery.py
│   ├── test_extended_indicators.py
│   └── test_store.py
├── test_intelligence/            # 17 modül
│   ├── test_regime.py
│   ├── test_factor_engine.py
│   ├── test_valuation.py
│   ├── test_forecasting.py
│   ├── test_probability.py
│   ├── test_signal_fusion.py
│   ├── test_monte_carlo.py
│   ├── test_scenario.py
│   ├── test_world_state.py
│   ├── test_knowledge_graph.py
│   ├── test_research_memory.py
│   ├── test_evidence_engine.py
│   ├── test_analysis_engines.py
│   ├── test_impact_engine.py
│   ├── test_news_pipeline.py
│   └── test_trade_planner.py
├── test_risk/                    # 3 modül
│   ├── test_enhanced_risk.py
│   ├── test_position_sizing.py
│   └── test_risk_main.py
├── test_portfolio/               # 2 modül
│   ├── test_portfolio_main.py
│   └── test_enhancements.py
├── test_learning/                # 5 modül
│   ├── test_integrated_learning.py
│   ├── test_outcome_tracker.py
│   ├── test_attribution.py
│   └── test_learning_loop.py
├── test_ml/                      # 1 modül
│   └── test_ranking_model.py
├── test_scanner/                 # 7 modül
│   ├── test_alpha_engine.py
│   ├── test_alpha_scanner.py
│   ├── test_event_scanner.py
│   ├── test_live_scanner.py
│   └── test_opportunity_engine.py
├── test_simulation/              # 2 modül
│   ├── test_execution_simulator.py
│   └── test_simulation_main.py
├── test_api/                     # 3 modül
│   ├── test_api_main.py
│   └── test_websocket.py
└── test_integration/             # Entegrasyon
    ├── test_data_to_feature.py
    ├── test_feature_to_intelligence.py
    ├── test_intelligence_to_risk.py
    ├── test_risk_to_portfolio.py
    └── test_full_pipeline.py
```

---

## AŞAMA 5: Entegrasyon Zincirleri

| # | Zincir | Modüller |
|---|--------|----------|
| E1 | Veri → Kalite | yfinance → data_quality → tradability_mask |
| E2 | Kalite → Feature | pit_store → calculator → seven_motors |
| E3 | Feature → Rejim | cross_sectional → regime → factor_engine |
| E4 | Rejim → Değerleme | regime → valuation → forecasting |
| E5 | Değerleme → Karar | forecasting → signal_fusion → decision_engine |
| E6 | Karar → Risk | decision → enhanced_risk → position_sizing |
| E7 | Risk → Portföy | risk → portfolio → rebalance |
| E8 | Portföy → Backtest | portfolio → backtest → walk_forward |
| E9 | Backtest → Öğrenme | backtest → integrated_learning → outcome_tracker |
| E10 | Öğrenme → Agent | learning → agent_system → knowledge_graph |

---

## Başarı Kriterleri (Güncellenmiş)

- [ ] 104 modülün tamamı import edilebiliyor
- [ ] 12 kod örneği beklenen çıktıyı üretiyor
- [ ] 10 entegrasyon zinciri çalışıyor
- [ ] 43 eksik modül açıklanmış (Grup A: mevcut, Grup B: yeni)
- [ ] 50+ test dosyası yazıl
- [ ] `pytest` ile tüm testler geçiyor
- [ ] `run_system.py` sorunsuz çalışıyor
