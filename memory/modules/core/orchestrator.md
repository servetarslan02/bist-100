# core/orchestrator

**Dosya:** `services/core/orchestrator.py`
**Satır:** 424

## Açıklama

ALPHA BIST — Master Orchestrator v1.0

Tüm servisleri tek bir pipeline'da birleştiren ana orkestratör.
start.py tarafından çağrılır.

Akış:
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING

## Sınıflar (1)

- `MasterOrchestrator`

## Fonksiyonlar (3)

- `__init__()`
- `run_pipeline()`
- `get_status()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/risk_gate`
- `core/halt_monitor`
- `intelligence/spec_engine`
- `intelligence/news_pipeline`
- `intelligence/probability`
- `intelligence/analysis_engines`
- `intelligence/evidence_engine`
- `core/compliance`
- `intelligence/factor_engine`
- `learning/outcome_tracker`
- `features/calculator`
- `core/event_bus`
- `portfolio/portfolio_manager`
- `intelligence/regime`
- `features/macro`
- `intelligence/world_state`
- `intelligence/macro_sensitivity`
- `intelligence/knowledge_graph`
- `intelligence/forecasting`
- `learning/integrated_learning`
- `core/short_selling`
- `risk/position_sizing`
- `intelligence/research_memory`
- `intelligence/trade_planner`
- `intelligence/monte_carlo`
- `intelligence/impact_engine`
- `intelligence/signal_fusion`
- `core/decision_engine`

