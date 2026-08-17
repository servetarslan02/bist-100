"""ALPHA BIST — Intelligence Pipeline Integration v1.0

17 intelligence modülünü orchestrator'a bağlayan pipeline.
Her modül için input/output contract, error handling, PIT safety.
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

    # Signal fusion
    fused_direction: str = "NEUTRAL"
    fused_confidence: float = 0.0
    signal_sources: List[str] = field(default_factory=list)

    # Forecasting
    forecast_return_pct: float = 0.0
    forecast_probability: float = 0.0
    forecast_horizon: int = 5

    # Trade plan
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    risk_reward: float = 0.0

    # Evidence
    evidence_count: int = 0
    evidence_strength: float = 0.0

    # Monte Carlo
    mc_expected_return: float = 0.0
    mc_confidence_interval: float = 0.0
    mc_positive_probability: float = 0.0

    # World state alignment
    world_alignment: float = 0.0

    # Quality
    data_quality: float = 0.0
    model_agreement: float = 0.0

    # Diagnostics
    modules_used: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class IntelligencePipeline:
    """Intelligence modüllerini orchestrator'a bağlayan pipeline.

    Her modül bağımsız çalışır, biri başarısız olursa diğerleri devam eder.
    """

    def __init__(self):
        self._modules = {}
        self._load_modules()

    def _load_modules(self):
        """Modülleri lazy-load et."""
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

        for name, module_path in module_map.items():
            try:
                import importlib
                mod = importlib.import_module(module_path)
                self._modules[name] = mod
            except Exception as e:
                logger.debug(f"Intelligence module {name} not available: {e}")

    def run(
        self,
        ticker: str,
        features: Dict[str, Any],
        market_data: Optional[Any] = None,
        regime: str = "UNKNOWN",
    ) -> IntelligenceOutput:
        """Tüm intelligence modüllerini çalıştır.

        Her modül bağımsız — biri başarısız olursa diğerleri devam eder.
        """
        output = IntelligenceOutput(
            ticker=ticker,
            timestamp="",
        )

        # 1. Signal Fusion
        self._run_signal_fusion(ticker, features, regime, output)

        # 2. Forecasting
        self._run_forecasting(ticker, features, output)

        # 3. Trade Planner
        self._run_trade_planner(ticker, features, output)

        # 4. Monte Carlo
        self._run_monte_carlo(ticker, features, output)

        # 5. Evidence Engine
        self._run_evidence(ticker, features, output)

        # 6. Factor Engine
        self._run_factor(ticker, features, output)

        # 7. World State
        self._run_world_state(features, output)

        # 8. Scenario
        self._run_scenario(ticker, features, output)

        # 9. Macro Sensitivity
        self._run_macro(features, output)

        # Model agreement hesapla
        if output.modules_used:
            directions = []
            if output.fused_direction != "NEUTRAL":
                directions.append(output.fused_direction)
            if output.forecast_return_pct > 1:
                directions.append("UP")
            elif output.forecast_return_pct < -1:
                directions.append("DOWN")
            if directions:
                agreement = directions.count(max(set(directions), key=directions.count)) / len(directions)
                output.model_agreement = round(agreement, 2)

        return output

    def _run_signal_fusion(self, ticker, features, regime, output):
        """Signal fusion çalıştır."""
        if "signal_fusion" not in self._modules:
            return
        try:
            mod = self._modules["signal_fusion"]
            if hasattr(mod, "SignalFusion"):
                sf = mod.SignalFusion()
                result = sf.fuse_signals(
                    ticker=ticker,
                    technical_data=features,
                    regime=regime,
                )
                if result:
                    output.fused_direction = getattr(result, "consensus_direction", "NEUTRAL")
                    output.fused_confidence = getattr(result, "consensus_confidence", 0)
                    output.signal_sources.append("signal_fusion")
                    output.modules_used.append("signal_fusion")
        except Exception as e:
            output.modules_failed.append(f"signal_fusion:{str(e)[:50]}")

    def _run_forecasting(self, ticker, features, output):
        """Forecasting çalıştır."""
        if "forecasting" not in self._modules:
            return
        try:
            mod = self._modules["forecasting"]
            if hasattr(mod, "ForecastingEngine"):
                fe = mod.ForecastingEngine()
                forecast = fe.forecast(ticker=ticker, features=features)
                if forecast:
                    output.forecast_return_pct = getattr(forecast, "predicted_return", 0)
                    output.forecast_probability = getattr(forecast, "probability_positive", 0)
                    output.forecast_horizon = getattr(forecast, "horizon_days", 5)
                    output.modules_used.append("forecasting")
        except Exception as e:
            output.modules_failed.append(f"forecasting:{str(e)[:50]}")

    def _run_trade_planner(self, ticker, features, output):
        """Trade planner çalıştır."""
        if "trade_planner" not in self._modules:
            return
        try:
            mod = self._modules["trade_planner"]
            if hasattr(mod, "TradePlanner"):
                tp = mod.TradePlanner()
                plan = tp.create_plan(
                    ticker=ticker,
                    direction=output.fused_direction,
                    features=features,
                )
                if plan:
                    output.entry_price = getattr(plan, "entry_price", 0)
                    output.stop_loss = getattr(plan, "stop_loss", 0)
                    output.target_price = getattr(plan, "target_price", 0)
                    output.risk_reward = getattr(plan, "risk_reward_ratio", 0)
                    output.modules_used.append("trade_planner")
        except Exception as e:
            output.modules_failed.append(f"trade_planner:{str(e)[:50]}")

    def _run_monte_carlo(self, ticker, features, output):
        """Monte Carlo çalıştır."""
        if "monte_carlo" not in self._modules:
            return
        try:
            mod = self._modules["monte_carlo"]
            if hasattr(mod, "MonteCarloEngine"):
                mc = mod.MonteCarloEngine()
                result = mc.simulate(ticker=ticker, features=features)
                if result:
                    output.mc_expected_return = getattr(result, "expected_return", 0)
                    output.mc_confidence_interval = getattr(result, "confidence_interval_95", 0)
                    output.mc_positive_probability = getattr(result, "probability_positive", 0)
                    output.modules_used.append("monte_carlo")
        except Exception as e:
            output.modules_failed.append(f"monte_carlo:{str(e)[:50]}")

    def _run_evidence(self, ticker, features, output):
        """Evidence engine çalıştır."""
        if "evidence_engine" not in self._modules:
            return
        try:
            mod = self._modules["evidence_engine"]
            if hasattr(mod, "EvidenceEngine"):
                ee = mod.EvidenceEngine()
                evidence = ee.collect_evidence(ticker=ticker, features=features)
                if evidence:
                    output.evidence_count = len(evidence) if isinstance(evidence, list) else 1
                    output.modules_used.append("evidence_engine")
        except Exception as e:
            output.modules_failed.append(f"evidence_engine:{str(e)[:50]}")

    def _run_factor(self, ticker, features, output):
        """Factor engine çalıştır."""
        if "factor_engine" not in self._modules:
            return
        try:
            mod = self._modules["factor_engine"]
            if hasattr(mod, "FactorEngine"):
                fe = mod.FactorEngine()
                factors = fe.compute_factors(ticker=ticker, features=features)
                if factors:
                    output.modules_used.append("factor_engine")
        except Exception as e:
            output.modules_failed.append(f"factor_engine:{str(e)[:50]}")

    def _run_world_state(self, features, output):
        """World state çalıştır."""
        if "world_state" not in self._modules:
            return
        try:
            mod = self._modules["world_state"]
            if hasattr(mod, "WorldStateManager"):
                wsm = mod.WorldStateManager()
                state = wsm.current_state
                if state:
                    output.world_alignment = getattr(state, "global_risk_appetite", 0.5)
                    output.modules_used.append("world_state")
        except Exception as e:
            output.modules_failed.append(f"world_state:{str(e)[:50]}")

    def _run_scenario(self, ticker, features, output):
        """Scenario engine çalıştır."""
        if "scenario" not in self._modules:
            return
        try:
            mod = self._modules["scenario"]
            if hasattr(mod, "ScenarioEngine"):
                se = mod.ScenarioEngine()
                scenarios = se.generate_scenarios(ticker=ticker, features=features)
                if scenarios:
                    output.modules_used.append("scenario")
        except Exception as e:
            output.modules_failed.append(f"scenario:{str(e)[:50]}")

    def _run_macro(self, features, output):
        """Macro sensitivity çalıştır."""
        if "macro_sensitivity" not in self._modules:
            return
        try:
            mod = self._modules["macro_sensitivity"]
            if hasattr(mod, "MacroSensitivityAnalyzer"):
                ms = mod.MacroSensitivityAnalyzer()
                sensitivity = ms.analyze(features=features)
                if sensitivity:
                    output.modules_used.append("macro_sensitivity")
        except Exception as e:
            output.modules_failed.append(f"macro_sensitivity:{str(e)[:50]}")

    def get_health(self) -> Dict[str, Any]:
        """Modül sağlık durumu."""
        return {
            "total_modules": 16,
            "loaded_modules": len(self._modules),
            "available": list(self._modules.keys()),
        }


# Singleton
intelligence_pipeline = IntelligencePipeline()
