# Modül Bağımlılık Sırası

**Amaç:** Hangi modül önce düzeltilmeli, hangisi sonra.
**Kural:** Bir modül ancak bağımlılıkları tamamlandıktan sonra düzeltilebilir.

---

## Bağımlılık Ağacı

```
Seviye 0: Temel (bağımlılık yok)
├── core/config.py
├── core/database.py
├── core/database_dev.py
├── core/logging.py
├── core/models.py
├── core/event_schema.py
└── core/event_bus.py

Seviye 1: Core servisler (Seviye 0'a bağlı)
├── core/security.py          ← config
├── core/audit_log.py         ← database
├── core/observability.py     ← database, config
├── core/circuit_breaker.py   ← config
├── core/data_quality.py      ← models
├── core/tradability_mask.py  ← models
├── core/recovery.py          ← database, event_bus
└── core/state_recovery.py    ← database

Seviye 2: Veri katmanı (Seviye 1'e bağlı)
├── ingestion/bist_universe.py      ← config
├── ingestion/providers/yfinance    ← config
├── ingestion/providers/kap         ← config
├── ingestion/providers/news        ← config
├── ingestion/providers/social      ← config
├── ingestion/providers/tcmb        ← config
├── ingestion/providers/macro       ← config
├── ingestion/providers/fundamental ← config
├── ingestion/corporate_actions.py  ← models
└── ingestion/main.py               ← tüm providers

Seviye 3: Feature katmanı (Seviye 2'ye bağlı)
├── features/calculator.py          ← ingestion, data_quality
├── features/technical_features.py  ← calculator
├── features/fundamental.py         ← ingestion
├── features/sentiment.py           ← ingestion, alternative
├── features/macro.py               ← ingestion, macro providers
├── features/cross_sectional.py     ← calculator
├── features/store.py               ← calculator
└── features/feature_selector.py    ← calculator

Seviye 4: Intelligence katmanı (Seviye 3'e bağlı)
├── intelligence/regime.py          ← features
├── intelligence/world_state.py     ← features, macro
├── intelligence/forecasting.py     ← features
├── intelligence/probability.py     ← features
├── intelligence/monte_carlo.py     ← features
├── intelligence/scenario.py        ← features, macro
├── intelligence/spec_engine.py     ← features, regime
├── intelligence/signal_fusion.py   ← features, regime, spec
├── intelligence/evidence_engine.py ← features
├── intelligence/knowledge_graph.py ← features
├── intelligence/research_memory.py ← features
├── intelligence/impact_engine.py   ← features, event_study
├── intelligence/factor_engine.py   ← features, factors
├ intelligence/macro_sensitivity.py ← features, macro
├── intelligence/news_pipeline.py   ← ingestion
├── intelligence/kap_extractor.py   ← ingestion
├── intelligence/kap_llm_extractor.py ← ingestion
├── intelligence/analysis_engines.py ← features
├── intelligence/trade_planner.py   ← features, intelligence
├── intelligence/prediction_layer.py ← features
└── intelligence/pipeline.py        ← tüm intelligence

Seviye 5: ML katmanı (Seviye 3'e bağlı)
├── ml/ranking_model.py       ← features
├── ml/lightgbm_trainer.py    ← features
├── ml/xgboost_model.py       ← features
├── ml/lstm_model.py          ← features
├── ml/transformer_model.py   ← features
├── ml/ensemble.py            ← tüm modeller
├── ml/model_comparator.py    ← tüm modeller
├── ml/training_validator.py  ← features
├── ml/ranker.py              ← features
├── ml/walk_forward.py        ← features, modeller
├── ml/adjusted_loss.py       ← features
├── ml/finrl_bist.py          ← features
├── ml/fingpt.py              ← features
├── ml/hybrid_model.py        ← fingpt, rl_agent
└── ml/rl_agent.py            ← finrl_bist

Seviye 6: Decision katmanı (Seviye 4+5'e bağlı)
├── core/decision_engine.py   ← intelligence, ml
├── core/risk_gate.py         ← decision, BIST kuralları
├── core/compliance.py        ← BIST kuralları
├── core/short_selling.py     ← BIST kuralları
├── core/halt_monitor.py      ← BIST kuralları
├── core/gross_settlement.py  ← BIST kuralları
├── core/viop_monitor.py      ← BIST kuralları
├── core/price_limits.py      ← BIST kuralları
├── core/fee_calculator.py    ← BIST kuralları
└── core/manipulation_detector.py ← BIST kuralları

Seviye 7: Risk katmanı (Seviye 6'ya bağlı)
├── risk/enhanced_risk.py     ← decision, portfolio
├── risk/position_sizing.py   ← decision, risk
├── risk/calibration.py       ← risk
├── risk/covariance.py        ← risk
├── risk/reconciliation.py    ← portfolio
└── risk/main.py              ← tüm risk

Seviye 8: Portfolio katmanı (Seviye 7'ye bağlı)
├── portfolio/portfolio_manager.py ← risk, decision
├── portfolio/enhancements.py      ← portfolio_manager
└── portfolio/main.py              ← tüm portfolio

Seviye 9: Simulation katmanı (Seviye 8'e bağlı)
├── simulation/execution_simulator.py ← portfolio
└── simulation/main.py                ← execution_simulator

Seviye 10: Backtest katmanı (Seviye 3+5+8'e bağlı)
├── backtest/engine.py              ← features, portfolio
├── backtest/engine_v4.py           ← features, portfolio, ml
├── backtest/walk_forward.py        ← features, ml
├── backtest/enhanced_walk_forward.py ← features, ml
├── backtest/walk_forward_runner.py ← features, ml
├── backtest/portfolio_sim.py       ← portfolio
├── backtest/canonical_adapter.py   ← features
└── backtest/persistence.py         ← database

Seviye 11: Learning katmanı (Seviye 8+10'a bağlı)
├── learning/outcome_tracker.py     ← portfolio, backtest
├── learning/attribution.py         ← portfolio
├── learning/learning_loop.py       ← outcome_tracker
├── learning/integrated_learning.py ← tüm learning
├── learning/continuous_learning.py ← learning
└── learning/super_intelligence.py  ← learning

Seviye 12: Scanner katmanı (Seviye 4+5+11'e bağlı)
├── scanner/opportunity_engine.py ← intelligence, ml
├── scanner/alpha_engine.py       ← intelligence
├── scanner/alpha_scanner.py      ← intelligence
├── scanner/event_scanner.py      ← intelligence, event_bus
├── scanner/live_scanner.py       ← intelligence
├── scanner/tiered_scanner.py     ← intelligence, ml
├── scanner/event_queue.py        ← event_bus
└── scanner/backtest_runner.py    ← backtest

Seviye 13: Agent katmanı (Seviye 4+12'ye bağlı)
├── agents/agent_system.py ← intelligence, scanner

Seviye 14: Orkestrasyon (tüm seviyelere bağlı)
├── core/orchestrator.py   ← tüm servisler
├── scheduler/main.py      ← scanner, learning
├── scheduler/production_scheduler.py ← tüm servisler
├── scheduler/daily_report.py ← tüm servisler
└── api/main.py + server.py + websocket.py ← tüm servisler
```

---

## Düzeltme Sırası

**Kural:** Seviye 0'dan başla, yukarı doğru çık. Her seviyedeki modüller bir sonraki seviye için hazır olmalı.

| Sıra | Seviye | Modül Sayısı | Öncelik |
|------|--------|-------------|---------|
| 1 | Seviye 0 | 7 | 🔴 Kritik |
| 2 | Seviye 1 | 8 | 🔴 Kritik |
| 3 | Seviye 2 | 10 | 🔴 Kritik |
| 4 | Seviye 3 | 8 | 🔴 Kritik |
| 5 | Seviye 4 | 20 | 🔴 Kritik |
| 6 | Seviye 5 | 15 | 🟡 Önemli |
| 7 | Seviye 6 | 10 | 🔴 Kritik |
| 8 | Seviye 7 | 6 | 🔴 Kritik |
| 9 | Seviye 8 | 3 | 🔴 Kritik |
| 10 | Seviye 9 | 2 | 🟡 Önemli |
| 11 | Seviye 10 | 8 | 🟡 Önemli |
| 12 | Seviye 11 | 6 | 🟡 Önemli |
| 13 | Seviye 12 | 8 | 🟡 Önemli |
| 14 | Seviye 13 | 1 | 🟢 İsteğe bağlı |
| 15 | Seviye 14 | 5 | 🟡 Önemli |
