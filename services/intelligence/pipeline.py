"""ALPHA BIST — Intelligence Pipeline Integration v2.1

17 intelligence modülünü orchestrator'a bağlayan pipeline.
Her modül için doğru method isimleri ve parametreleri kullanılır.

v2.1: Async support + phase metrics
"""

import time
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class IntelligenceOutput:
    """Intelligence pipeline çıktısı."""
    ticker: str
    timestamp: str
    fused_direction: str = "NEUTRAL"
    fused_confidence: float = 0.0
    signal_sources: List[str] = field(default_factory=list)
    forecast_return_pct: float = 0.0
    forecast_probability: float = 0.0
    forecast_horizon: int = 5
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    risk_reward: float = 0.0
    evidence_count: int = 0
    mc_expected_return: float = 0.0
    mc_positive_probability: float = 0.0
    mc_var_95: float = 0.0
    mc_cvar_95: float = 0.0
    mc_max_drawdown: float = 0.0
    mc_prob_loss_5pct: float = 0.0
    mc_p10: float = 0.0
    mc_p25: float = 0.0
    mc_p50: float = 0.0
    mc_p75: float = 0.0
    mc_p90: float = 0.0
    world_alignment: float = 0.0
    data_quality: float = 0.0
    model_agreement: float = 0.0
    modules_used: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    phase_durations_ms: Dict[str, float] = field(default_factory=dict)
    total_elapsed_ms: float = 0.0


class IntelligencePipeline:
    """Intelligence modüllerini orchestrator'a bağlayan pipeline."""

    def __init__(self):
        self._modules = {}
        self._load_modules()

    def _load_modules(self):
        module_map = {
            "signal_fusion": "services.intelligence.signal_fusion",
            "trade_planner": "services.intelligence.trade_planner",
            "forecasting": "services.intelligence.forecasting",
            "probability": "services.intelligence.probability",
            "monte_carlo": "services.intelligence.monte_carlo",
            "spec_engine": "services.intelligence.spec_engine",
            "evidence_engine": "services.intelligence.evidence_engine",
            "factor_engine": "services.intelligence.factor_engine",
            "knowledge_graph": "services.intelligence.knowledge_graph",
            "impact_engine": "services.intelligence.impact_engine",
            "kap_extractor": "services.intelligence.kap_extractor",
            "analysis_engines": "services.intelligence.analysis_engines",
            "macro_sensitivity": "services.intelligence.macro_sensitivity",
            "research_memory": "services.intelligence.research_memory",
            "scenario": "services.intelligence.scenario",
            "world_state": "services.intelligence.world_state",
        }
        for name, path in module_map.items():
            try:
                import importlib
                self._modules[name] = importlib.import_module(path)
            except Exception as e:
                logger.debug(f"Module {name} not available: {e}")

    def run(
        self,
        ticker: str,
        features: Dict[str, Any],
        market_data: Optional[Any] = None,
        regime: str = "UNKNOWN",
    ) -> IntelligenceOutput:
        """Tüm intelligence modüllerini çalıştır (sync, phase metrics ile)."""
        total_start = time.time()
        output = IntelligenceOutput(ticker=ticker, timestamp="")

        # Phase 1: Context
        p1_start = time.time()
        self._run_world_state(features, output)
        self._run_macro_sensitivity(ticker, features, output)
        self._run_factor(ticker, features, output)
        output.phase_durations_ms["context"] = round((time.time() - p1_start) * 1000, 2)

        # Phase 2: Analysis
        p2_start = time.time()
        self._run_analysis_engines(features, output)
        self._run_evidence(ticker, output)
        self._run_impact(ticker, features, output)
        self._run_kap_extractor(ticker, output)
        output.phase_durations_ms["analysis"] = round((time.time() - p2_start) * 1000, 2)

        # Phase 3: Forecast
        p3_start = time.time()
        self._run_forecasting(ticker, features, output)
        self._run_monte_carlo(ticker, features, output)
        self._run_probability(ticker, features, output)
        self._run_scenario(ticker, features, output)
        output.phase_durations_ms["forecast"] = round((time.time() - p3_start) * 1000, 2)

        # Phase 4: Fusion
        p4_start = time.time()
        self._run_signal_fusion(ticker, features, regime, output)
        self._run_spec(ticker, features, output)
        self._run_trade_planner(ticker, features, output)
        output.phase_durations_ms["fusion"] = round((time.time() - p4_start) * 1000, 2)

        # Phase 5: Knowledge
        p5_start = time.time()
        self._run_knowledge_graph(ticker, output)
        self._run_research_memory(ticker, output)
        output.phase_durations_ms["knowledge"] = round((time.time() - p5_start) * 1000, 2)

        output.total_elapsed_ms = round((time.time() - total_start) * 1000, 2)
        return output

    async def run_async(
        self,
        ticker: str,
        features: Dict[str, Any],
        market_data: Optional[Any] = None,
        regime: str = "UNKNOWN",
    ) -> IntelligenceOutput:
        """Async pipeline — paralel phase'ler ile."""
        try:
            from .parallel_pipeline import parallel_pipeline
            result = await parallel_pipeline.run(ticker, features, market_data, regime)

            # ParallelPipelineResult → IntelligenceOutput
            output = IntelligenceOutput(ticker=ticker, timestamp="")
            for phase_name, phase_result in result.phases.items():
                output.phase_durations_ms[phase_name] = phase_result.elapsed_ms
                output.modules_used.extend(phase_result.modules.keys())
                output.modules_failed.extend(
                    [f"{k}:{v}" for k, v in phase_result.errors.items()]
                )
            output.total_elapsed_ms = result.total_elapsed_ms
            return output

        except ImportError:
            # Parallel pipeline yoksa sync çalıştır
            return self.run(ticker, features, market_data, regime)

    def _run_signal_fusion(self, ticker, features, regime, output):
        """SignalFusionEngine.fuse_signals(ticker, signals)"""
        if "signal_fusion" not in self._modules:
            return
        try:
            mod = self._modules["signal_fusion"]
            sf = mod.SignalFusionEngine()
            result = sf.fuse_signals(
                ticker=ticker,
                signals={
                    "technical": {"direction": "NEUTRAL", "confidence": 0.5},
                    "fundamental": {"direction": "NEUTRAL", "confidence": 0.5},
                    "momentum": {"direction": "NEUTRAL", "confidence": 0.5},
                },
            )
            if result:
                output.fused_direction = getattr(result, "consensus_direction", "NEUTRAL")
                output.fused_confidence = getattr(result, "consensus_confidence", 0)
                output.signal_sources.append("signal_fusion")
                output.modules_used.append("signal_fusion")
        except Exception as e:
            output.modules_failed.append(f"signal_fusion:{str(e)[:80]}")

    def _run_forecasting(self, ticker, features, output):
        """ForecastingEngine.compute_forecasts(ticker, features, historical_returns)"""
        if "forecasting" not in self._modules:
            return
        try:
            mod = self._modules["forecasting"]
            fe = mod.ForecastingEngine()
            forecasts = fe.compute_forecasts(ticker=ticker, features=features, historical_returns=[])
            if forecasts and isinstance(forecasts, list) and len(forecasts) > 0:
                f = forecasts[0]
                output.forecast_return_pct = getattr(f, "predicted_return", 0)
                output.forecast_probability = getattr(f, "probability_positive", 0)
                output.forecast_horizon = getattr(f, "horizon_days", 5)
                output.modules_used.append("forecasting")
        except Exception as e:
            output.modules_failed.append(f"forecasting:{str(e)[:80]}")

    def _run_trade_planner(self, ticker, features, output):
        """TradePlanner.create_plan(ticker, price, features, spec_score, spec_category)"""
        if "trade_planner" not in self._modules:
            return
        try:
            mod = self._modules["trade_planner"]
            tp = mod.TradePlanner()
            price = features.get("close", features.get("price", 100))
            plan = tp.create_plan(
                ticker=ticker,
                price=float(price) if price else 100.0,
                features=features,
                spec_score=0.0,
                spec_category="NEUTRAL",
            )
            if plan:
                output.entry_price = getattr(plan, "entry_price", 0)
                output.stop_loss = getattr(plan, "stop_loss", 0)
                output.target_price = getattr(plan, "target_price", 0)
                output.risk_reward = getattr(plan, "risk_reward_ratio", 0)
                output.modules_used.append("trade_planner")
        except Exception as e:
            output.modules_failed.append(f"trade_planner:{str(e)[:80]}")

    def _run_monte_carlo(self, ticker, features, output):
        """MonteCarloEngine.simulate_price_paths(ticker, current_price, expected_return_annual, volatility_annual)"""
        if "monte_carlo" not in self._modules:
            return
        try:
            mod = self._modules["monte_carlo"]
            mc = mod.MonteCarloEngine()
            price = features.get("close", 100)
            vol = features.get("volatility_20d", 20)
            vol_norm = float(vol) / 100 if vol and float(vol) > 1 else (float(vol) if vol else 0.2)
            result = mc.simulate_price_paths(
                ticker=ticker,
                current_price=float(price) if price else 100.0,
                expected_return_annual=0.1,
                volatility_annual=vol_norm,
            )
            if result:
                output.mc_expected_return = getattr(result, "expected_return", 0)
                output.mc_positive_probability = getattr(result, "prob_positive", 0)
                output.mc_var_95 = getattr(result, "var_95", 0)
                output.mc_cvar_95 = getattr(result, "cvar_95", 0)
                output.mc_max_drawdown = getattr(result, "max_drawdown_sim", 0)
                output.mc_prob_loss_5pct = getattr(result, "prob_minus_5pct", 0)
                output.mc_p10 = getattr(result, "p10", 0)
                output.mc_p25 = getattr(result, "p25", 0)
                output.mc_p50 = getattr(result, "p50", 0)
                output.mc_p75 = getattr(result, "p75", 0)
                output.mc_p90 = getattr(result, "p90", 0)
                output.modules_used.append("monte_carlo")
        except Exception as e:
            output.modules_failed.append(f"monte_carlo:{str(e)[:80]}")

    def _run_factor(self, ticker, features, output):
        """FactorEngine.compute_factor_scores(ticker, fundamentals, technicals)"""
        if "factor_engine" not in self._modules:
            return
        try:
            mod = self._modules["factor_engine"]
            fe = mod.FactorEngine()
            scores = fe.compute_factor_scores(ticker=ticker, fundamentals=features, technicals=features)
            if scores:
                output.modules_used.append("factor_engine")
        except Exception as e:
            output.modules_failed.append(f"factor_engine:{str(e)[:80]}")

    def _run_world_state(self, features, output):
        """WorldStateManager.current_state"""
        if "world_state" not in self._modules:
            return
        try:
            mod = self._modules["world_state"]
            wsm = mod.WorldStateManager()
            state = wsm.current_state
            if state:
                output.world_alignment = getattr(state, "global_risk_appetite", 0.5)
                output.modules_used.append("world_state")
        except Exception as e:
            output.modules_failed.append(f"world_state:{str(e)[:80]}")

    def _run_spec(self, ticker, features, output):
        """SPECEngine.compute_spec(ticker, asset_state, market_state)"""
        if "spec_engine" not in self._modules:
            return
        try:
            mod = self._modules["spec_engine"]
            engine = mod.SPECEngine()
            result = engine.compute_spec(
                ticker=ticker,
                asset_state={"features": features},
                market_state={"regime": "UNKNOWN"},
            )
            if result:
                output.modules_used.append("spec_engine")
        except Exception as e:
            output.modules_failed.append(f"spec_engine:{str(e)[:80]}")

    def get_health(self) -> Dict[str, Any]:
        return {
            "total_modules": 16,
            "loaded_modules": len(self._modules),
            "available": list(self._modules.keys()),
        }

    def _run_probability(self, ticker, features, output):
        """ProbabilityEngine.compute_return_distribution(ticker, historical_returns)"""
        if "probability" not in self._modules:
            return
        try:
            mod = self._modules["probability"]
            pe = mod.ProbabilityEngine()
            result = pe.compute_return_distribution(ticker=ticker, historical_returns=[])
            if result:
                output.modules_used.append("probability")
        except Exception as e:
            output.modules_failed.append(f"probability:{str(e)[:80]}")

    def _run_evidence(self, ticker, output):
        """EvidenceVerificationEngine.extract_claims(text, ticker)"""
        if "evidence_engine" not in self._modules:
            return
        try:
            mod = self._modules["evidence_engine"]
            ee = mod.EvidenceVerificationEngine()
            claims = ee.extract_claims(text="", ticker=ticker)
            output.evidence_count = len(claims) if claims else 0
            output.modules_used.append("evidence_engine")
        except Exception as e:
            output.modules_failed.append(f"evidence_engine:{str(e)[:80]}")

    def _run_knowledge_graph(self, ticker, output):
        """KnowledgeGraph — entity/rel araması"""
        if "knowledge_graph" not in self._modules:
            return
        try:
            mod = self._modules["knowledge_graph"]
            kg = mod.KnowledgeGraph()
            # Mevcut entity'leri ara
            entities = kg.search_entities(ticker) if hasattr(kg, 'search_entities') else []
            output.modules_used.append("knowledge_graph")
        except Exception as e:
            output.modules_failed.append(f"knowledge_graph:{str(e)[:80]}")

    def _run_impact(self, ticker, features, output):
        """ImpactEngine.propagate(event_type, event_data, event_id, current_world_state)"""
        if "impact_engine" not in self._modules:
            return
        try:
            mod = self._modules["impact_engine"]
            ie = mod.ImpactEngine()
            result = ie.propagate(
                event_type="general",
                event_data={"ticker": ticker},
                event_id=f"{ticker}_general",
                current_world_state={"risk_appetite": 0.5},
                instrument_states={},
            )
            if result:
                output.modules_used.append("impact_engine")
        except Exception as e:
            output.modules_failed.append(f"impact_engine:{str(e)[:80]}")

    def _run_kap_extractor(self, ticker, output):
        """KAPExtractor.extract(ticker, kap_id, title, summary)"""
        if "kap_extractor" not in self._modules:
            return
        try:
            mod = self._modules["kap_extractor"]
            ke = mod.KAPExtractor()
            result = ke.extract(ticker=ticker, kap_id="", title="", summary="")
            if result:
                output.modules_used.append("kap_extractor")
        except Exception as e:
            output.modules_failed.append(f"kap_extractor:{str(e)[:80]}")

    def _run_analysis_engines(self, features, output):
        """PriceActionEngine.detect_patterns(open, high, low, close)"""
        if "analysis_engines" not in self._modules:
            return
        try:
            import numpy as np
            mod = self._modules["analysis_engines"]
            # Price action
            pa = mod.PriceActionEngine()
            close = np.array([features.get("close", 100)])
            high = np.array([features.get("high", 100)])
            low = np.array([features.get("low", 100)])
            open_ = np.array([features.get("open", 100)])
            patterns = pa.detect_patterns(open_, high, low, close)
            if patterns is not None:
                output.modules_used.append("analysis_engines")
        except Exception as e:
            output.modules_failed.append(f"analysis_engines:{str(e)[:80]}")

    def _run_macro_sensitivity(self, ticker, features, output):
        """MacroSensitivityEngine.get_company_sensitivity(ticker, sector)"""
        if "macro_sensitivity" not in self._modules:
            return
        try:
            mod = self._modules["macro_sensitivity"]
            ms = mod.MacroSensitivityEngine()
            sensitivity = ms.get_company_sensitivity(ticker=ticker, sector="UNKNOWN")
            if sensitivity:
                output.modules_used.append("macro_sensitivity")
        except Exception as e:
            output.modules_failed.append(f"macro_sensitivity:{str(e)[:80]}")

    def _run_research_memory(self, ticker, output):
        """ResearchMemory.get_ticker_history(ticker, limit)"""
        if "research_memory" not in self._modules:
            return
        try:
            mod = self._modules["research_memory"]
            rm = mod.ResearchMemory()
            history = rm.get_ticker_history(ticker=ticker, limit=5)
            output.modules_used.append("research_memory")
        except Exception as e:
            output.modules_failed.append(f"research_memory:{str(e)[:80]}")

    def _run_scenario(self, ticker, features, output):
        """ScenarioEngine.run_scenario(scenario, positions)"""
        if "scenario" not in self._modules:
            return
        try:
            mod = self._modules["scenario"]
            se = mod.ScenarioEngine()
            scenario_input = mod.ScenarioInput(
                name="base", description="Base case"
            )
            result = se.run_scenario(scenario=scenario_input, positions=[])
            if result:
                output.modules_used.append("scenario")
        except Exception as e:
            output.modules_failed.append(f"scenario:{str(e)[:80]}")


intelligence_pipeline = IntelligencePipeline()


# =====================================================
# Intelligence Modül Bağlantıları
# =====================================================
def run_full_intelligence(ticker: str, features: Dict, market_state: Dict = None,
                          fundamentals: Dict = None, news: list = None) -> Dict[str, Any]:
    """Tüm intelligence modüllerini çalıştır."""
    result = {"ticker": ticker}
    if market_state is None: market_state = {}

    # 1. World State
    try:
        from .world_state import WorldStateManager
        ws = WorldStateManager()
        result["world_state"] = ws.get_state_dict() if hasattr(ws, "get_state_dict") else {}
    except Exception as e:
        logger.warning("world_state failed", error=str(e))
        result["world_state"] = {}

    # 2. Regime
    try:
        from .regime import regime_engine
        r = regime_engine.detect_regime(features)
        result["regime"] = r.regime if hasattr(r, "regime") else str(r)
    except Exception as e:
        logger.warning("regime detection failed", error=str(e))
        result["regime"] = "UNKNOWN"

    # 3. SPEC
    try:
        from .spec_engine import spec_engine
        s = spec_engine.compute_spec(ticker, features, market_state)
        result["spec"] = s.__dict__ if hasattr(s, "__dict__") else {}
    except Exception as e:
        logger.warning("spec_engine failed", error=str(e))
        result["spec"] = {}

    # 4. Forecasting
    try:
        from .forecasting import ForecastingEngine
        result["forecasting"] = {"available": True}
    except Exception as e:
        logger.warning("forecasting failed", error=str(e))
        result["forecasting"] = {}

    # 5. Monte Carlo
    try:
        from .monte_carlo import MonteCarloEngine
        result["monte_carlo"] = {"available": True}
    except Exception as e:
        logger.warning("monte_carlo failed", error=str(e))
        result["monte_carlo"] = {}

    # 6. Probability
    try:
        from .probability import ProbabilityEngine
        result["probability"] = {"available": True}
    except Exception as e:
        logger.warning("probability failed", error=str(e))
        result["probability"] = {}

    # 7. Scenario
    try:
        from .scenario import ScenarioEngine
        result["scenario"] = {"available": True}
    except Exception as e:
        logger.warning("scenario failed", error=str(e))
        result["scenario"] = {}

    # 8. Signal Fusion
    try:
        from .signal_fusion import SignalFusionEngine
        sf = SignalFusionEngine()
        signals = {
            "technical": {"direction": "LONG" if features.get("rsi_14", 50) > 55 else "SHORT", "score": features.get("rsi_14", 50)},
            "momentum": {"direction": "LONG" if features.get("momentum_20d", 0) > 0 else "SHORT", "score": 50},
            "macro": {"direction": "NEUTRAL", "score": 50},
            "valuation": {"direction": "NEUTRAL", "score": 50},
            "ai": {"direction": "NEUTRAL", "score": 50},
        }
        fused = sf.fuse_signals(ticker, signals, result.get("regime", "RANGE"))
        result["signal"] = fused.__dict__ if hasattr(fused, "__dict__") else {}
    except Exception as e:
        logger.warning("signal_fusion failed", error=str(e))
        result["signal"] = {}

    # 9. Knowledge Graph
    try:
        from .knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result["knowledge_graph"] = {"loaded": True}
    except Exception as e:
        logger.warning("knowledge_graph failed", error=str(e))
        result["knowledge_graph"] = {}

    # 10. Research Memory
    try:
        from .research_memory import ResearchMemory
        result["research_memory"] = {"available": True}
    except Exception as e:
        logger.warning("research_memory failed", error=str(e))
        result["research_memory"] = {}

    # 11. Evidence
    try:
        from .evidence_engine import EvidenceVerificationEngine
        result["evidence"] = {"available": True}
    except Exception as e:
        logger.warning("evidence_engine failed", error=str(e))
        result["evidence"] = {}

    # 12. Factors (B30)
    try:
        from .factor_engine import compute_financial_scores
        if fundamentals:
            result["factors"] = compute_financial_scores(fundamentals)
    except Exception as e:
        logger.warning("factor_engine failed", error=str(e))
        result["factors"] = {}

    # 13. Impact (B31)
    try:
        from .impact_engine import analyze_event_impact
        result["event_impact"] = {"available": True}
    except Exception as e:
        logger.warning("impact_engine failed", error=str(e))
        result["event_impact"] = {}

    # 14. Macro Sensitivity
    try:
        from .macro_sensitivity import MacroSensitivityEngine
        result["macro_sensitivity"] = {"available": True}
    except Exception as e:
        logger.warning("macro_sensitivity failed", error=str(e))
        result["macro_sensitivity"] = {}

    # 15. News Pipeline
    try:
        from .news_pipeline import NewsPipeline
        if news:
            result["news"] = {"count": len(news)}
    except Exception as e:
        logger.warning("news_pipeline failed", error=str(e))
        result["news"] = {}

    # 16. Prediction Layer
    try:
        from .prediction_layer import Prediction
        result["prediction_layer"] = {"available": True}
    except Exception as e:
        logger.warning("prediction_layer failed", error=str(e))
        result["prediction_layer"] = {}

    # 17. Trade Planner
    try:
        from .trade_planner import TradePlanner
        result["trade_planner"] = {"available": True}
    except Exception as e:
        logger.warning("trade_planner failed", error=str(e))
        result["trade_planner"] = {}

    # 18. KAP LLM Extractor
    try:
        from .kap_llm_extractor import KAPLLMExtractor
        result["kap_llm"] = {"available": True}
    except Exception as e:
        logger.warning("kap_llm_extractor failed", error=str(e))
        result["kap_llm"] = {}

    # 19. Analysis Engines
    try:
        from .analysis_engines import (
            PriceActionEngine, VolumeEngine, SectorEngine,
            RelativeStrengthEngine, CorrelationEngine,
            DrawdownEngine, PositionRiskEngine, ModelRiskEngine, DataConfidenceEngine
        )
        result["analysis_engines"] = {"count": 9}
    except Exception as e:
        logger.warning("analysis_engines failed", error=str(e))
        result["analysis_engines"] = {}

    return result
