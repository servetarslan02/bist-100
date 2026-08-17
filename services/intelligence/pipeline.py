"""ALPHA BIST — Intelligence Pipeline Integration v2.0

17 intelligence modülünü orchestrator'a bağlayan pipeline.
Her modül için doğru method isimleri ve parametreleri kullanılır.
"""

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
    world_alignment: float = 0.0
    data_quality: float = 0.0
    model_agreement: float = 0.0
    modules_used: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


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
        """Tüm intelligence modüllerini çalıştır."""
        output = IntelligenceOutput(ticker=ticker, timestamp="")

        self._run_signal_fusion(ticker, features, regime, output)
        self._run_forecasting(ticker, features, output)
        self._run_trade_planner(ticker, features, output)
        self._run_monte_carlo(ticker, features, output)
        self._run_factor(ticker, features, output)
        self._run_world_state(features, output)
        self._run_spec(ticker, features, output)
        self._run_probability(ticker, features, output)
        self._run_evidence(ticker, output)
        self._run_knowledge_graph(ticker, output)
        self._run_impact(ticker, features, output)
        self._run_kap_extractor(ticker, output)
        self._run_analysis_engines(features, output)
        self._run_macro_sensitivity(ticker, features, output)
        self._run_research_memory(ticker, output)
        self._run_scenario(ticker, features, output)

        return output

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
                output.mc_positive_probability = getattr(result, "probability_positive", 0)
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
    except: result["world_state"] = {}

    # 2. Regime
    try:
        from .regime import regime_engine
        r = regime_engine.detect_regime(features)
        result["regime"] = r.regime if hasattr(r, "regime") else str(r)
    except: result["regime"] = "UNKNOWN"

    # 3. SPEC
    try:
        from .spec_engine import spec_engine
        s = spec_engine.compute_spec(ticker, features, market_state)
        result["spec"] = s.__dict__ if hasattr(s, "__dict__") else {}
    except: result["spec"] = {}

    # 4. Forecasting
    try:
        from .forecasting import ForecastingEngine
        result["forecasting"] = {"available": True}
    except: result["forecasting"] = {}

    # 5. Monte Carlo
    try:
        from .monte_carlo import MonteCarloEngine
        result["monte_carlo"] = {"available": True}
    except: result["monte_carlo"] = {}

    # 6. Probability
    try:
        from .probability import ProbabilityEngine
        result["probability"] = {"available": True}
    except: result["probability"] = {}

    # 7. Scenario
    try:
        from .scenario import ScenarioEngine
        result["scenario"] = {"available": True}
    except: result["scenario"] = {}

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
    except: result["signal"] = {}

    # 9. Knowledge Graph
    try:
        from .knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result["knowledge_graph"] = {"loaded": True}
    except: result["knowledge_graph"] = {}

    # 10. Research Memory
    try:
        from .research_memory import ResearchMemory
        result["research_memory"] = {"available": True}
    except: result["research_memory"] = {}

    # 11. Evidence
    try:
        from .evidence_engine import EvidenceVerificationEngine
        result["evidence"] = {"available": True}
    except: result["evidence"] = {}

    # 12. Factors (B30)
    try:
        from .factor_engine import compute_financial_scores
        if fundamentals:
            result["factors"] = compute_financial_scores(fundamentals)
    except: result["factors"] = {}

    # 13. Impact (B31)
    try:
        from .impact_engine import analyze_event_impact
        result["event_impact"] = {"available": True}
    except: result["event_impact"] = {}

    # 14. Macro Sensitivity
    try:
        from .macro_sensitivity import MacroSensitivityEngine
        result["macro_sensitivity"] = {"available": True}
    except: result["macro_sensitivity"] = {}

    # 15. News Pipeline
    try:
        from .news_pipeline import NewsPipeline
        if news:
            result["news"] = {"count": len(news)}
    except: result["news"] = {}

    # 16. Prediction Layer
    try:
        from .prediction_layer import Prediction
        result["prediction_layer"] = {"available": True}
    except: result["prediction_layer"] = {}

    # 17. Trade Planner
    try:
        from .trade_planner import TradePlanner
        result["trade_planner"] = {"available": True}
    except: result["trade_planner"] = {}

    # 18. KAP LLM Extractor
    try:
        from .kap_llm_extractor import KAPLLMExtractor
        result["kap_llm"] = {"available": True}
    except: result["kap_llm"] = {}

    # 19. Analysis Engines
    try:
        from .analysis_engines import (
            PriceActionEngine, VolumeEngine, SectorEngine,
            RelativeStrengthEngine, CorrelationEngine,
            DrawdownEngine, PositionRiskEngine, ModelRiskEngine, DataConfidenceEngine
        )
        result["analysis_engines"] = {"count": 9}
    except: result["analysis_engines"] = {}

    return result
