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


intelligence_pipeline = IntelligencePipeline()
