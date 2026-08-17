# Uygulama Planı v4 — Bölüm 1-8 (Güncellenmiş)

## Durum Özeti

| Kategori | Durum |
|----------|-------|
| Toplam mevcut modül | **104** (doğrulandı, HEPSİ MEVCUT) |
| Bölüm 1-8 ile ilişkili | 61 modül (✅ ile işaretli) |
| Bölüm 1-8 ile ilişkisiz | 43 modül (mevcut ama bölümde yok) |
| Yeni yazılacak (B23-32) | **49 modül** |
| Test dosyaları | ❌ Hiç yok |
| Entegrasyon testleri | ❌ Yapılmamış |

---

## AŞAMA 1: Tüm 104 Modülü Doğrula

### Katman 1: Core (21 modül)

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
| 1.16 | **Config** | `core/config.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |
| 1.17 | **Models** | `core/models.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |
| 1.18 | **Event Schema** | `core/event_schema.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |
| 1.19 | **Logging** | `core/logging.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |
| 1.20 | **Database** | `core/database.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |
| 1.21 | **Database Dev** | `core/database_dev.py` | - | ⚠️ Mevcut, bölümde kapsanmamış |

**Eksik açıklamaları:**
- `config.py`: Sistem konfigürasyonu (env, settings)
- `models.py`: Veri modelleri (dataclass, schema)
- `event_schema.py`: Event şema tanımları
- `logging.py`: Log yapılandırması (structlog)
- `database.py`: ClickHouse bağlantısı
- `database_dev.py`: SQLite dev veritabanı

---

### Katman 2: Data Providers (19 modül)

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
| 2.9 | **BIST Provider** | `ingestion/providers/bist_provider.py` | - | ⚠️ Mevcut |
| 2.10 | **BIST Stream** | `ingestion/providers/bist_stream.py` | - | ⚠️ Mevcut |
| 2.11 | **Macro Provider** | `ingestion/providers/macro_provider.py` | - | ⚠️ Mevcut |
| 2.12 | **Matriks Provider** | `ingestion/providers/matriks_provider.py` | - | ⚠️ Mevcut |
| 2.13 | **News Credibility** | `ingestion/providers/news_credibility.py` | - | ⚠️ Mevcut |
| 2.14 | **Provider Manager** | `ingestion/providers/provider_manager.py` | - | ⚠️ Mevcut |
| 2.15 | **Realtime Provider** | `ingestion/providers/realtime_provider.py` | - | ⚠️ Mevcut |
| 2.16 | **Realtime** | `ingestion/realtime.py` | - | ⚠️ Mevcut |
| 2.17 | **BIST Universe** | `ingestion/bist_universe.py` | - | ⚠️ Mevcut |
| 2.18 | **Universe Enhancements** | `ingestion/universe_enhancements.py` | 4 | ✅ |
| 2.19 | **Ingestion Main** | `ingestion/main.py` | - | ⚠️ Mevcut |

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
| 3.6 | **Bar Engine** | `features/bar_engine.py` | - | ⚠️ Mevcut |
| 3.7 | **Calculator** | `features/calculator.py` | - | ⚠️ Mevcut |
| 3.8 | **Discovery** | `features/discovery.py` | - | ⚠️ Mevcut |
| 3.9 | **Extended Indicators** | `features/extended_indicators.py` | - | ⚠️ Mevcut |
| 3.10 | **Incremental State** | `features/incremental_state.py` | - | ⚠️ Mevcut |
| 3.11 | **Store** | `features/store.py` | - | ⚠️ Mevcut |
| 3.12 | **Features Main** | `features/main.py` | - | ⚠️ Mevcut |

**Eksik açıklamaları:**
- `bar_engine.py`: OHLCV bar oluşturma (time-based, tick-based, volume-based)
- `calculator.py`: Feature hesaplama orkestratörü (63+ feature)
- `discovery.py`: Hisse keşfi ve tarama
- `extended_indicators.py`: Ek teknik göstergeler (Ichimoku, Fibonacci, vb.)
- `incremental_state.py`: Artımlı feature güncelleme
- `store.py`: Feature store (saklama/okuma)
- `main.py`: Features ana modül

---

### Katman 4: Intelligence (20 modül)

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
| 4.14 | **Analysis Engines** | `intelligence/analysis_engines.py` | - | ⚠️ Mevcut |
| 4.15 | **Impact Engine** | `intelligence/impact_engine.py` | - | ⚠️ Mevcut |
| 4.16 | **Macro Sensitivity** | `intelligence/macro_sensitivity.py` | - | ⚠️ Mevcut |
| 4.17 | **News Pipeline** | `intelligence/news_pipeline.py` | - | ⚠️ Mevcut |
| 4.18 | **Spec Engine** | `intelligence/spec_engine.py` | - | ⚠️ Mevcut |
| 4.19 | **Trade Planner** | `intelligence/trade_planner.py` | - | ⚠️ Mevcut |
| 4.20 | **Intelligence Main** | `intelligence/main.py` | - | ⚠️ Mevcut |

**Eksik açıklamaları:**
- `analysis_engines.py`: Çoklu analiz motoru orkestratörü
- `impact_engine.py`: Olay etki analizi
- `macro_sensitivity.py`: Makro duyarlılık analizi
- `news_pipeline.py`: Haber işleme hattı
- `spec_engine.py`: Hisse spesifikasyon motoru
- `trade_planner.py`: İşlem planlayıcı
- `main.py`: Intelligence ana modül

---

### Katman 5: Risk & Portfolio (6 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 5.1 | Enhanced Risk | `risk/enhanced_risk.py` | 10-11 | ✅ |
| 5.2 | Position Sizing | `risk/position_sizing.py` | 10 | ✅ |
| 5.3 | Portfolio Main | `portfolio/main.py` | 11 | ✅ |
| 5.4 | **Portfolio Enhancements** | `portfolio/enhancements.py` | 1 | ⚠️ Mevcut, bölümde kapsanmamış |
| 5.5 | **Risk Main** | `risk/main.py` | - | ⚠️ Mevcut |
| 5.6 | **Risk Reconciliation** | `risk/reconciliation.py` | - | ⚠️ Mevcut |

**Eksik açıklamaları:**
- `portfolio/enhancements.py`: Multi-currency, FX impact (Bölüm 1'de var ama planda eksik)
- `risk/main.py`: Risk ana modül
- `risk/reconciliation.py`: Risk uzlaştırma

---

### Katman 6: Learning (6 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 6.1 | Integrated Learning | `learning/integrated_learning.py` | 15 | ✅ |
| 6.2 | Outcome Tracker | `learning/outcome_tracker.py` | 15 | ✅ |
| 6.3 | **Attribution** | `learning/attribution.py` | - | ⚠️ Mevcut |
| 6.4 | **Learning Loop** | `learning/learning_loop.py` | - | ⚠️ Mevcut |
| 6.5 | **Learning Main** | `learning/main.py` | - | ⚠️ Mevcut |
| 6.6 | **Label Generator** | `labels/generator.py` | - | ⚠️ Mevcut |

---

### Katman 7: ML (1 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 7.1 | Ranking Model | `ml/ranking_model.py` | 4 | ✅ |
| 7.2 | **ML Main** | - | - | ⚠️ Mevcut Yok |

---

### Katman 7b: Backtest (3 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 7b.1 | Backtest Engine | `backtest/engine.py` | 13 | ✅ |
| 7b.2 | Walk-Forward | `backtest/walk_forward.py` | 13 | ✅ |
| 7b.3 | Enhanced Walk-Forward | `backtest/enhanced_walk_forward.py` | 13 | ✅ |

---

### Katman 7c: Agents (1 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 7c.1 | Agent System | `agents/agent_system.py` | 16 | ✅ |

---

### Katman 8: Scanner (7 modül) — Mevcut, bölümde kapsanmamış

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

### Katman 9: Scheduler (2 modül) — Mevcut, bölümde kapsanmamış

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 9.1 | **Daily Report** | `scheduler/daily_report.py` | Günlük rapor |
| 9.2 | **Scheduler Main** | `scheduler/main.py` | Zamanlayıcı |

---

### Katman 10: Simulation (2 modül)

| # | Modül | Dosya | Bölüm | Durum |
|---|-------|-------|-------|-------|
| 10.1 | Execution Simulator | `simulation/execution_simulator.py` | 14 | ✅ |
| 10.2 | **Simulation Main** | `simulation/main.py` | - | ⚠️ Mevcut |

---

### Katman 11: API (3 modül) — Mevcut, bölümde kapsanmamış

| # | Modül | Dosya | Açıklama |
|---|-------|-------|----------|
| 11.1 | **API Main** | `api/main.py` | FastAPI endpoint'leri |
| 11.2 | **API Server** | `api/server.py` | HTTP sunucu |
| 11.3 | **WebSocket** | `api/websocket.py` | Gerçek zamanlı WebSocket |

---

### Katman 12: Market State (1 modül) — Mevcut, bölümde kapsanmamış

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

### Test dosyaları (104 modül + 5 entegrasyon = 109 test):

```
tests/
├── test_core/                    # 21 modül
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
│   ├── test_database_dev.py
│   ├── test_event_schema.py
│   ├── test_logging.py
│   ├── test_recovery.py
│   └── test_state_recovery.py
├── test_ingestion/               # 19 modül
│   ├── test_providers.py
│   ├── test_bist_provider.py
│   ├── test_bist_stream.py
│   ├── test_kap_provider.py
│   ├── test_news_provider.py
│   ├── test_news_credibility.py
│   ├── test_provider_manager.py
│   ├── test_universe.py
│   ├── test_universe_enhancements.py
│   ├── test_bist_universe.py
│   ├── test_corporate_actions.py
│   ├── test_data_validator.py
│   ├── test_fundamental_provider.py
│   ├── test_macro_provider.py
│   ├── test_matriks_provider.py
│   ├── test_realtime.py
│   ├── test_realtime_provider.py
│   ├── test_social_provider.py
│   ├── test_tcmb_provider.py
│   ├── test_yfinance_provider.py
│   └── test_ingestion_main.py
├── test_features/                # 12 modül
│   ├── test_seven_motors.py
│   ├── test_fundamental.py
│   ├── test_sentiment.py
│   ├── test_cross_sectional.py
│   ├── test_bar_engine.py
│   ├── test_calculator.py
│   ├── test_discovery.py
│   ├── test_extended_indicators.py
│   ├── test_incremental_state.py
│   ├── test_macro.py
│   ├── test_store.py
│   └── test_features_main.py
├── test_intelligence/            # 20 modül
│   ├── test_regime.py
│   ├── test_factor_engine.py
│   ├── test_valuation.py
│   ├── test_valuation_engine.py
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
│   ├── test_kap_extractor.py
│   ├── test_macro_sensitivity.py
│   ├── test_news_pipeline.py
│   ├── test_spec_engine.py
│   ├── test_trade_planner.py
│   └── test_intelligence_main.py
├── test_risk/                    # 4 modül
│   ├── test_enhanced_risk.py
│   ├── test_position_sizing.py
│   ├── test_risk_main.py
│   └── test_risk_reconciliation.py
├── test_portfolio/               # 2 modül
│   ├── test_portfolio_main.py
│   └── test_enhancements.py
├── test_learning/                # 6 modül
│   ├── test_integrated_learning.py
│   ├── test_outcome_tracker.py
│   ├── test_attribution.py
│   ├── test_learning_loop.py
│   ├── test_learning_main.py
│   └── test_learning_service.py
├── test_labels/                  # 1 modül
│   └── test_generator.py
├── test_ml/                      # 1 modül
│   └── test_ranking_model.py
├── test_backtest/                # 3 modül
│   ├── test_backtest_engine.py
│   ├── test_walk_forward.py
│   └── test_enhanced_walk_forward.py
├── test_agents/                  # 1 modül
│   └── test_agent_system.py
├── test_scanner/                 # 7 modül
│   ├── test_alpha_engine.py
│   ├── test_alpha_scanner.py
│   ├── test_event_queue.py
│   ├── test_event_scanner.py
│   ├── test_live_scanner.py
│   ├── test_opportunity_engine.py
│   └── test_tiered_scanner.py
├── test_scheduler/               # 2 modül
│   ├── test_daily_report.py
│   └── test_scheduler_main.py
├── test_simulation/              # 2 modül
│   ├── test_execution_simulator.py
│   └── test_simulation_main.py
├── test_api/                     # 3 modül
│   ├── test_api_main.py
│   ├── test_api_server.py
│   └── test_websocket.py
├── test_market_state/            # 1 modül
│   └── test_market_state_main.py
└── test_integration/             # 5 entegrasyon
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
- [ ] 104 test dosyası yazıl (her modül için 1 test)
- [ ] `pytest` ile tüm testler geçiyor
- [ ] `run_system.py` sorunsuz çalışıyor

---

## GELİŞTİRME STANDARTLARI

### 1. Modüller Arası İletişim

**Sorun:** Şu an her modül doğrudan diğerini import ediyor. Bu tight coupling sorun yaratır — bir modül değişince diğeri bozulur.

**Çözüm:** İki tür iletişim:

**a) Veri çekme (doğrudan çağrı):**
Bir modül başka bir modülden veri almak istediğinde doğrudan çağırır.
```python
# Intelligence, Features'tan veri çeker (gerekli)
features = feature_calculator.compute_all("THYAO", data)

# Risk, Intelligence'dan tahmin alır (gerekli)
forecast = forecasting_engine.compute_forecasts("THYAO", features, [1, 5])
```

**b) Bildirim (event):**
Bir modül bir olay gerçekleştiğinde event publish eder, dinleyenler tepki verir.
```python
# Veri kalitesi kontrol edildi, diğer modüllere haber ver
event_bus.publish("data.quality.checked", {"ticker": "THYAO", "quality": 95})

# Features modülü event'i dinler, feature hesaplamayı başlatır
event_bus.subscribe("data.quality.checked", features_handler)
```

**Kural:**
- Veri çekme → Doğrudan çağrı ✅ (her zaman)
- Bildirim → Event ✅ (çapraz katman tetikleme)
- Karıştırma: Veri çekmek için event kullanma ❌

**Event tablosu:**

| Publisher | Event | Subscriber | Ne yapar? |
|-----------|-------|------------|----------|
| data_quality | data.quality.checked | features | Feature hesaplamayı başlat |
| regime_engine | regime.detected | risk, portfolio | Rejime göre ağırlık değiştir |
| signal_fusion | signal.generated | decision_engine | Karar sürecini başlat |
| decision_engine | decision.made | risk, portfolio | Risk kontrolü yap |
| risk_engine | risk.checked | portfolio | Pozisyon boyutu ayarla |
| portfolio | portfolio.updated | simulation | Paper trading güncelle |
| learning | model.drift.detected | intelligence | Model yeniden eğit |

### 2. Hata Yönetimi Stratejisi

**Sorun:** Her modül kendi hatasını farklı şekilde handle ediyor. Standart yok.

**Çözüm:** Üç seviyeli hata sınıflandırması:

**Seviye 1 — Kritik (sistem durmalı):**
```python
class CriticalError(Exception):
    """Risk motoru çalışmıyor, veri tabanı çöktü → TÜM İŞLEMLER DURUR"""
    pass
```

**Seviye 2 — Uyarı (fallback kullan):**
```python
class WarningError(Exception):
    """Bir provider başarısız → diğer kaynaktan devam et"""
    pass
```

**Seviye 3 — Bilgi (logla, devam et):**
```python
class InfoError(Exception):
    """Bir feature hesaplanamadı → None döndür, devam et"""
    pass
```

**Retry politikası:**
Mevcut: `services/core/circuit_breaker.py` → `RetryPolicy` sınıfı zaten var.
```python
from services.core.circuit_breaker import RetryPolicy

retry = RetryPolicy(max_retries=3, base_delay=1.0)
# 1s → 2s → 4s bekleme ile retry
```

**Kural:** Her modül hangi hata seviyesini kullanacağını belirtmeli. Yeni `retry.py` yazma, mevcut `circuit_breaker.py`'deki `RetryPolicy`'yi kullan.

### 3. Konfigürasyon Yönetimi

**Sorun:** config.py var ama tüm modüller nasıl config'e erişecek belli değil.

**Çözüm:** Merkezi config servisi + environment-based override.

```python
# services/core/config.py — mevcut yapı
from services.core.config import get_settings

# Mevcut alanlar:
settings = get_settings()
# settings.tcmb_evds_api_key
# settings.ch_host, settings.ch_port
# settings.alpha_vantage_api_key
# ... (diğer alanlar)

# Yeni eklenmesi gereken alanlar:
# settings.bist_commission_rate = 0.0003
# settings.max_position_pct = 10
# settings.default_risk_limit = 0.02
```

**Config hiyerarşisi (öncelik sırası):**
```
1. Environment variable (en yüksek öncelik)
2. .env dosyası
3. config.py default değerleri (en düşük öncelik)
```

**Kural:** Hiçbir modül hardcoded değer kullanmamalı. Tüm sabitler config'den gelmeli.

### 4. Veritabanı Şeması Senkronizasyonu

**Sorun:** database.py ve database_dev.py var ama şema tanımları nerede, migration stratejisi yok.

**Çözüm:** SQL migration dosyaları + version tracking.

```
database/
├── init/                    # Mevcut
│   └── 001_schema.sql       # Mevcut (14KB, tablo tanımları)
├── clickhouse/              # Mevcut
└── migrations/              # YENİ eklenecek
    ├── 002_add_features.sql
    └── ...
```

**Migration kuralı:**
```python
# services/core/database.py'ye ekle
def run_migrations(db):
    current_version = get_schema_version(db)
    for migration in get_pending_migrations(current_version):
        db.execute(migration.sql)
        update_schema_version(db, migration.version)
```

**Kural:** Şema değişikliği her zaman migration dosyası ile yapılmalı. Doğrudan ALTER TABLE yasak.

### 5. Test Stratejisi

**Sorun:** 104 test dosyası planladık ama unit test mi, integration test mi, mock mu, gerçek veri mi belli değil.

**Çözüm:** Üç katmanlı test:

**a) Unit test (her modül, mock veri):**
```python
# tests/test_core/test_data_quality.py
def test_check_tick_valid():
    result = data_quality_gate.check_tick("THYAO", 305.25, 100000, datetime.now())
    assert result.passed == True

def test_check_tick_zero_volume():
    result = data_quality_gate.check_tick("THYAO", 305.25, 0, datetime.now())
    assert result.passed == False
```

**b) Integration test (modül arası, mock veri):**
```python
# tests/test_integration/test_data_to_feature.py
def test_data_to_feature_pipeline():
    # Veri çek (mock)
    data = mock_yfinance_data("THYAO")
    # Kalite kontrol
    quality = data_quality_gate.check_tick(...)
    # Feature hesapla
    features = seven_motor_engine.compute_all(...)
    assert len(features) > 40
```

**c) E2E test (gerçek veri, manuel çalıştırma):**
```python
# tests/test_e2e/test_full_pipeline.py
@pytest.mark.slow
def test_full_pipeline_real_data():
    # Gerçek API çağrısı
    data = yfinance_provider.get_ohlcv("THYAO")
    # Tüm zincir
    ...
```

**Coverage hedefi:** %80 (unit + integration)

### 6. Dokümantasyon-Kod Eşleşme Garantisi

**Sorun:** Bölüm dokümantasyonundaki kod örnekleri ile gerçek kod farklı olabilir.

**Çözüm:** Her bölümdeki kod bloğu için otomatik çalıştırma testi.

```python
# tests/test_docs/test_chapter_examples.py
import re
import importlib
import glob

def extract_python_blocks(filepath):
    """Markdown dosyasından python kod bloklarını çıkar."""
    with open(filepath) as f:
        content = f.read()
    return re.findall(r'```python\n(.*?)```', content, re.DOTALL)

def test_chapter_imports():
    """Her bölümdeki import ifadelerinin çalıştığını doğrula."""
    for chapter_file in glob.glob("sistem ve calisma mantiklari/bolumler/bolum-*.md"):
        code_blocks = extract_python_blocks(chapter_file)
        for i, code in enumerate(code_blocks):
            # Sadece import satırlarını kontrol et
            for line in code.split('\n'):
                if line.startswith('from ') or line.startswith('import '):
                    try:
                        exec(line)
                    except Exception as e:
                        print(f"✗ {chapter_file}, blok {i+1}: {line} → {e}")
```

**Kural:**
- Dokümantasyondaki her `from services.X import Y` ifadesi import edilebilir olmalı.
- Kod bloklarındaki örnekler çalıştırılmaz, sadece syntax kontrolü yapılır.
- Hata veren import varsa: modül mü eksik, isim mi yanlış? Düzelt.
