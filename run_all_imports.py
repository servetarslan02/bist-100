#!/usr/bin/env python3
"""ALPHA BIST — 104 modül import testi."""
import sys, importlib, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

ALL_MODULES = [
    "services.core.market_calendar","services.core.data_quality","services.core.tradability_mask",
    "services.core.reconciliation","services.core.pit_store","services.core.streaming_anomaly",
    "services.core.circuit_breaker","services.core.security","services.core.audit_log",
    "services.core.decision_engine","services.core.infrastructure","services.core.event_bus",
    "services.core.observability","services.core.recovery","services.core.state_recovery",
    "services.core.config","services.core.models","services.core.event_schema",
    "services.core.logging","services.core.database","services.core.database_dev",
    "services.ingestion.providers.yfinance_provider","services.ingestion.providers.kap_provider",
    "services.ingestion.providers.news_provider","services.ingestion.providers.social_provider",
    "services.ingestion.providers.tcmb_provider","services.ingestion.providers.fundamental_provider",
    "services.ingestion.corporate_actions","services.ingestion.providers.data_validator",
    "services.ingestion.providers.bist_provider","services.ingestion.providers.bist_stream",
    "services.ingestion.providers.macro_provider","services.ingestion.providers.matriks_provider",
    "services.ingestion.providers.news_credibility","services.ingestion.providers.provider_manager",
    "services.ingestion.providers.realtime_provider","services.ingestion.realtime",
    "services.ingestion.bist_universe","services.ingestion.universe_enhancements",
    "services.ingestion.main",
    "services.features.seven_motors","services.features.fundamental","services.features.sentiment",
    "services.features.cross_sectional","services.features.macro","services.features.bar_engine",
    "services.features.calculator","services.features.discovery","services.features.extended_indicators",
    "services.features.incremental_state","services.features.store","services.features.main",
    "services.intelligence.regime","services.intelligence.factor_engine",
    "services.intelligence.kap_extractor","services.intelligence.valuation.engine",
    "services.intelligence.forecasting","services.intelligence.probability",
    "services.intelligence.world_state","services.intelligence.monte_carlo",
    "services.intelligence.scenario","services.intelligence.signal_fusion",
    "services.intelligence.knowledge_graph","services.intelligence.research_memory",
    "services.intelligence.evidence_engine","services.intelligence.analysis_engines",
    "services.intelligence.impact_engine","services.intelligence.macro_sensitivity",
    "services.intelligence.news_pipeline","services.intelligence.spec_engine",
    "services.intelligence.trade_planner","services.intelligence.main",
    "services.risk.enhanced_risk","services.risk.position_sizing","services.risk.main",
    "services.risk.reconciliation","services.portfolio.main","services.portfolio.enhancements",
    "services.learning.integrated_learning","services.learning.outcome_tracker",
    "services.learning.attribution","services.learning.learning_loop","services.learning.main",
    "services.labels.generator","services.ml.ranking_model",
    "services.backtest.engine","services.backtest.walk_forward","services.backtest.enhanced_walk_forward",
    "services.agents.agent_system",
    "services.scanner.alpha_engine","services.scanner.alpha_scanner","services.scanner.event_queue",
    "services.scanner.event_scanner","services.scanner.live_scanner","services.scanner.opportunity_engine",
    "services.scanner.tiered_scanner","services.scheduler.daily_report","services.scheduler.main",
    "services.simulation.execution_simulator","services.simulation.main",
    "services.api.main","services.api.server","services.api.websocket","services.market_state.main",
]

def main():
    passed = failed = 0
    start = time.time()
    for mod in ALL_MODULES:
        try:
            importlib.import_module(mod); print(f"  ✅ {mod}"); passed += 1
        except Exception as e:
            print(f"  ❌ {mod}: {e}"); failed += 1
    elapsed = time.time() - start
    print(f"\n{'='*60}\nSONUÇ: {passed} başarılı, {failed} başarısız ({elapsed:.1f}s)\n{'='*60}")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
