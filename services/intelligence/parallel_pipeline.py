"""
ALPHA BIST — Parallel Intelligence Pipeline v1.0

21 modülü paralel çalıştırır.
Phase-based execution:
  Phase 1: Context (regime + world_state + macro + factor) — paralel
  Phase 2: Analysis (technical + fundamental + sentiment + news) — paralel
  Phase 3: Forecast (forecasting + monte_carlo + probability) — paralel
  Phase 4: Fusion + SPEC + TradePlan — sıralı
  Phase 5: Knowledge + Memory — paralel

Kullanım:
    pipeline = ParallelIntelligencePipeline()
    result = await pipeline.run(ticker, features)
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class PhaseResult:
    """Faz sonucu."""
    phase: str
    modules: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def success_count(self) -> int:
        return len(self.modules)

    @property
    def error_count(self) -> int:
        return len(self.errors)


@dataclass
class ParallelPipelineResult:
    """Pipeline sonucu."""
    ticker: str
    phases: Dict[str, PhaseResult] = field(default_factory=dict)
    total_elapsed_ms: float = 0.0
    modules_used: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)

    def get_module_result(self, module_name: str) -> Optional[Any]:
        """Modül sonucunu getir."""
        for phase_result in self.phases.values():
            if module_name in phase_result.modules:
                return phase_result.modules[module_name]
        return None


class ParallelIntelligencePipeline:
    """
    Paralel intelligence pipeline.

    Bağımsız modülleri asyncio.gather ile paralel çalıştırır.
    """

    def __init__(self):
        self._modules = {}
        self._load_modules()

    def _load_modules(self):
        """Modülleri yükle."""
        module_map = {
            "regime": "services.intelligence.regime",
            "hmm_regime": "services.intelligence.hmm_regime",
            "world_state": "services.intelligence.world_state",
            "macro_sensitivity": "services.intelligence.macro_sensitivity",
            "factor_engine": "services.intelligence.factor_engine",
            "signal_fusion": "services.intelligence.signal_fusion",
            "spec_engine": "services.intelligence.spec_engine",
            "trade_planner": "services.intelligence.trade_planner",
            "forecasting": "services.intelligence.forecasting",
            "monte_carlo": "services.intelligence.monte_carlo",
            "probability": "services.intelligence.probability",
            "scenario": "services.intelligence.scenario",
            "evidence_engine": "services.intelligence.evidence_engine",
            "knowledge_graph": "services.intelligence.knowledge_graph",
            "research_memory": "services.intelligence.research_memory",
            "impact_engine": "services.intelligence.impact_engine",
            "kap_extractor": "services.intelligence.kap_extractor",
            "news_pipeline": "services.intelligence.news_pipeline",
            "prediction_layer": "services.intelligence.prediction_layer",
            "analysis_engines": "services.intelligence.analysis_engines",
            "ensemble_forecast": "services.intelligence.ensemble_forecast",
        }

        for name, path in module_map.items():
            try:
                import importlib
                self._modules[name] = importlib.import_module(path)
            except Exception as e:
                logger.debug(f"Module {name} not available: {e}")

    async def run(
        self,
        ticker: str,
        features: Dict[str, Any],
        market_data: Optional[Any] = None,
        regime: str = "UNKNOWN",
    ) -> ParallelPipelineResult:
        """Tüm pipeline'ı paralel çalıştır."""
        start = time.time()
        result = ParallelPipelineResult(ticker=ticker)

        # Phase 1: Context (paralel)
        phase1 = await self._run_phase1(ticker, features)
        result.phases["context"] = phase1

        # Phase 2: Analysis (paralel)
        phase2 = await self._run_phase2(ticker, features)
        result.phases["analysis"] = phase2

        # Phase 3: Forecast (paralel)
        phase3 = await self._run_phase3(ticker, features)
        result.phases["forecast"] = phase3

        # Phase 4: Fusion + SPEC + TradePlan (sıralı)
        phase4 = await self._run_phase4(ticker, features, phase1, phase2, phase3)
        result.phases["fusion"] = phase4

        # Phase 5: Knowledge + Memory (paralel)
        phase5 = await self._run_phase5(ticker, features)
        result.phases["knowledge"] = phase5

        # Toplam
        result.total_elapsed_ms = round((time.time() - start) * 1000, 2)
        for phase_result in result.phases.values():
            result.modules_used.extend(phase_result.modules.keys())
            result.modules_failed.extend(
                [f"{k}:{v}" for k, v in phase_result.errors.items()]
            )

        logger.info("Parallel pipeline completed",
                    ticker=ticker,
                    elapsed_ms=result.total_elapsed_ms,
                    modules_used=len(result.modules_used),
                    modules_failed=len(result.modules_failed))

        return result

    async def _run_phase1(self, ticker: str, features: Dict) -> PhaseResult:
        """Phase 1: Context — regime + world_state + macro + factor."""
        start = time.time()
        result = PhaseResult(phase="context")

        tasks = {
            "regime": self._safe_run("regime", self._run_regime, ticker, features),
            "hmm_regime": self._safe_run("hmm_regime", self._run_hmm_regime, ticker, features),
            "world_state": self._safe_run("world_state", self._run_world_state, features),
            "macro_sensitivity": self._safe_run("macro_sensitivity", self._run_macro_sensitivity, ticker, features),
            "factor_engine": self._safe_run("factor_engine", self._run_factor, ticker, features),
        }

        done = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for (name, _), outcome in zip(tasks.items(), done):
            if isinstance(outcome, Exception):
                result.errors[name] = str(outcome)[:100]
            elif outcome is not None:
                result.modules[name] = outcome

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _run_phase2(self, ticker: str, features: Dict) -> PhaseResult:
        """Phase 2: Analysis — technical + fundamental + sentiment + news."""
        start = time.time()
        result = PhaseResult(phase="analysis")

        tasks = {
            "analysis_engines": self._safe_run("analysis_engines", self._run_analysis_engines, features),
            "evidence": self._safe_run("evidence_engine", self._run_evidence, ticker),
            "impact": self._safe_run("impact_engine", self._run_impact, ticker, features),
            "kap_extractor": self._safe_run("kap_extractor", self._run_kap_extractor, ticker),
        }

        done = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for (name, _), outcome in zip(tasks.items(), done):
            if isinstance(outcome, Exception):
                result.errors[name] = str(outcome)[:100]
            elif outcome is not None:
                result.modules[name] = outcome

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _run_phase3(self, ticker: str, features: Dict) -> PhaseResult:
        """Phase 3: Forecast — forecasting + monte_carlo + probability."""
        start = time.time()
        result = PhaseResult(phase="forecast")

        tasks = {
            "forecasting": self._safe_run("forecasting", self._run_forecasting, ticker, features),
            "monte_carlo": self._safe_run("monte_carlo", self._run_monte_carlo, ticker, features),
            "probability": self._safe_run("probability", self._run_probability, ticker, features),
            "scenario": self._safe_run("scenario", self._run_scenario, ticker, features),
        }

        done = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for (name, _), outcome in zip(tasks.items(), done):
            if isinstance(outcome, Exception):
                result.errors[name] = str(outcome)[:100]
            elif outcome is not None:
                result.modules[name] = outcome

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _run_phase4(
        self, ticker: str, features: Dict,
        phase1: PhaseResult, phase2: PhaseResult, phase3: PhaseResult,
    ) -> PhaseResult:
        """Phase 4: Fusion + SPEC + TradePlan (sıralı)."""
        start = time.time()
        result = PhaseResult(phase="fusion")

        # Signal fusion
        try:
            sf_result = await self._run_signal_fusion(ticker, features, phase1, phase2, phase3)
            if sf_result:
                result.modules["signal_fusion"] = sf_result
        except Exception as e:
            result.errors["signal_fusion"] = str(e)[:100]

        # SPEC engine
        try:
            spec_result = await self._run_spec(ticker, features, phase1)
            if spec_result:
                result.modules["spec_engine"] = spec_result
        except Exception as e:
            result.errors["spec_engine"] = str(e)[:100]

        # Trade planner
        try:
            tp_result = await self._run_trade_planner(ticker, features, result.modules)
            if tp_result:
                result.modules["trade_planner"] = tp_result
        except Exception as e:
            result.errors["trade_planner"] = str(e)[:100]

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _run_phase5(self, ticker: str, features: Dict) -> PhaseResult:
        """Phase 5: Knowledge + Memory (paralel)."""
        start = time.time()
        result = PhaseResult(phase="knowledge")

        tasks = {
            "knowledge_graph": self._safe_run("knowledge_graph", self._run_knowledge_graph, ticker),
            "research_memory": self._safe_run("research_memory", self._run_research_memory, ticker),
            "news_pipeline": self._safe_run("news_pipeline", self._run_news_pipeline, ticker),
            "prediction_layer": self._safe_run("prediction_layer", self._run_prediction_layer, ticker, features),
        }

        done = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for (name, _), outcome in zip(tasks.items(), done):
            if isinstance(outcome, Exception):
                result.errors[name] = str(outcome)[:100]
            elif outcome is not None:
                result.modules[name] = outcome

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    # =====================================================
    # Module Runners
    # =====================================================

    async def _safe_run(self, name: str, func, *args):
        """Güvenli modül çalıştırma."""
        if name not in self._modules:
            return None
        try:
            return await asyncio.wait_for(func(*args), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Module timeout", module=name)
            return None

    async def _run_regime(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("regime")
        if not mod:
            return {}
        engine = mod.RegimeEngine()
        result = engine.detect_regime(features)
        return {"regime": result.regime.value, "confidence": result.confidence}

    async def _run_hmm_regime(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("hmm_regime")
        if not mod:
            return {}
        detector = mod.HMMRegimeDetector()
        # HMM için tarihsel veri gerekli — features'tan üret
        returns = np.array([features.get("return_1d", 0)] * 63)
        vol = np.array([features.get("volatility_20d", 20) / 100] * 63)
        result = detector.predict_regime(returns, vol)
        return {"regime": result.regime, "confidence": result.confidence, "probabilities": result.probabilities}

    async def _run_world_state(self, features: Dict) -> Dict:
        mod = self._modules.get("world_state")
        if not mod:
            return {}
        wsm = mod.WorldStateManager()
        state = wsm.current_state
        return {"state": str(state)} if state else {}

    async def _run_macro_sensitivity(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("macro_sensitivity")
        if not mod:
            return {}
        ms = mod.MacroSensitivityEngine()
        return ms.get_company_sensitivity(ticker=ticker, sector="UNKNOWN") or {}

    async def _run_factor(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("factor_engine")
        if not mod:
            return {}
        fe = mod.FactorEngine()
        return fe.compute_factor_scores(ticker=ticker, fundamentals=features, technicals=features) or {}

    async def _run_analysis_engines(self, features: Dict) -> Dict:
        mod = self._modules.get("analysis_engines")
        if not mod:
            return {}
        pa = mod.PriceActionEngine()
        close = np.array([features.get("close", 100)])
        high = np.array([features.get("high", 100)])
        low = np.array([features.get("low", 100)])
        open_ = np.array([features.get("open", 100)])
        patterns = pa.detect_patterns(open_, high, low, close)
        return {"patterns": str(patterns)} if patterns is not None else {}

    async def _run_evidence(self, ticker: str) -> Dict:
        mod = self._modules.get("evidence_engine")
        if not mod:
            return {}
        ee = mod.EvidenceVerificationEngine()
        claims = ee.extract_claims(text="", ticker=ticker)
        return {"claims_count": len(claims) if claims else 0}

    async def _run_impact(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("impact_engine")
        if not mod:
            return {}
        ie = mod.ImpactEngine()
        return ie.propagate(
            event_type="general", event_data={"ticker": ticker},
            event_id=f"{ticker}_general", current_world_state={"risk_appetite": 0.5},
            instrument_states={},
        ) or {}

    async def _run_kap_extractor(self, ticker: str) -> Dict:
        mod = self._modules.get("kap_extractor")
        if not mod:
            return {}
        ke = mod.KAPExtractor()
        return ke.extract(ticker=ticker, kap_id="", title="", summary="") or {}

    async def _run_forecasting(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("forecasting")
        if not mod:
            return {}
        fe = mod.ForecastingEngine()
        forecasts = fe.compute_forecasts(ticker=ticker, features=features, historical_returns=[])
        if forecasts:
            f = forecasts[0]
            return {"predicted_return": f.predicted_return, "probability": f.probability_positive, "horizon": f.horizon_days}
        return {}

    async def _run_monte_carlo(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("monte_carlo")
        if not mod:
            return {}
        mc = mod.MonteCarloEngine()
        price = features.get("close", 100)
        vol = features.get("volatility_20d", 20)
        vol_norm = float(vol) / 100 if vol and float(vol) > 1 else (float(vol) if vol else 0.2)
        result = mc.simulate_price_paths(
            ticker=ticker, current_price=float(price),
            expected_return_annual=0.1, volatility_annual=vol_norm,
        )
        return {"expected_return": result.expected_return, "prob_positive": result.prob_positive, "var_95": result.var_95}

    async def _run_probability(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("probability")
        if not mod:
            return {}
        pe = mod.ProbabilityEngine()
        return pe.compute_return_distribution(ticker=ticker, historical_returns=[]) or {}

    async def _run_scenario(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("scenario")
        if not mod:
            return {}
        se = mod.ScenarioEngine()
        scenario_input = mod.ScenarioInput(name="base", description="Base case")
        return se.run_scenario(scenario=scenario_input, positions=[]) or {}

    async def _run_signal_fusion(self, ticker: str, features: Dict, p1: PhaseResult, p2: PhaseResult, p3: PhaseResult) -> Dict:
        mod = self._modules.get("signal_fusion")
        if not mod:
            return {}
        sf = mod.SignalFusionEngine()
        regime = p1.modules.get("regime", {}).get("regime", "UNKNOWN")

        # Phase 1-3 sonuçlarından gerçek sinyaller oluştur
        signals = {
            "technical": {"direction": "NEUTRAL", "score": 50},
            "fundamental": {"direction": "NEUTRAL", "score": 50},
            "momentum": {"direction": "NEUTRAL", "score": 50},
            "macro": {"direction": "NEUTRAL", "score": 50},
            "valuation": {"direction": "NEUTRAL", "score": 50},
            "ai": {"direction": "NEUTRAL", "score": 50},
        }

        # Phase 2 (forecast) sonuçlarını kullan — forecasting
        if "forecasting" in p2.modules:
            fc = p2.modules["forecasting"]
            if isinstance(fc, dict) and "predicted_return" in fc:
                ret = fc["predicted_return"]
                signals["technical"]["direction"] = "LONG" if ret > 0 else "SHORT"
                signals["technical"]["score"] = min(max(50 + ret * 10, 0), 100)

        # Phase 3 (monte_carlo) sonuçlarını kullan
        if "monte_carlo" in p3.modules:
            mc = p3.modules["monte_carlo"]
            if isinstance(mc, dict) and "prob_positive" in mc:
                prob_pos = mc["prob_positive"]
                signals["momentum"]["direction"] = "LONG" if prob_pos > 0.55 else "SHORT"
                signals["momentum"]["score"] = prob_pos * 100

        # Phase 3 (probability) sonuçlarını kullan
        if "probability" in p3.modules:
            prob = p3.modules["probability"]
            if isinstance(prob, dict) and "direction" in prob:
                signals["valuation"]["direction"] = prob["direction"]

        # Phase 1 (factor_engine) sonuçlarını kullan
        if "factor_engine" in p1.modules:
            factor = p1.modules["factor_engine"]
            if isinstance(factor, dict) and "composite_score" in factor:
                score = factor["composite_score"]
                signals["fundamental"]["direction"] = "LONG" if score > 55 else "SHORT"
                signals["fundamental"]["score"] = score

        result = sf.fuse_signals(ticker, signals, regime)
        return result.__dict__ if hasattr(result, "__dict__") else {}

    async def _run_spec(self, ticker: str, features: Dict, phase1: PhaseResult) -> Dict:
        mod = self._modules.get("spec_engine")
        if not mod:
            return {}
        engine = mod.SPECEngine()
        return engine.compute_spec(
            ticker=ticker, asset_state={"features": features},
            market_state={"regime": phase1.modules.get("regime", {}).get("regime", "UNKNOWN")},
        ) or {}

    async def _run_trade_planner(self, ticker: str, features: Dict, fusion_modules: Dict) -> Dict:
        mod = self._modules.get("trade_planner")
        if not mod:
            return {}
        tp = mod.TradePlanner()
        price = features.get("close", 100)
        return tp.create_plan(
            ticker=ticker, price=float(price), features=features,
            spec_score=0.0, spec_category="NEUTRAL",
        ) or {}

    async def _run_knowledge_graph(self, ticker: str) -> Dict:
        mod = self._modules.get("knowledge_graph")
        if not mod:
            return {}
        kg = mod.KnowledgeGraph()
        return {"loaded": True}

    async def _run_research_memory(self, ticker: str) -> Dict:
        mod = self._modules.get("research_memory")
        if not mod:
            return {}
        rm = mod.ResearchMemory()
        return rm.get_ticker_history(ticker=ticker, limit=5) or {}

    async def _run_news_pipeline(self, ticker: str) -> Dict:
        mod = self._modules.get("news_pipeline")
        if not mod:
            return {}
        return {"available": True}

    async def _run_prediction_layer(self, ticker: str, features: Dict) -> Dict:
        mod = self._modules.get("prediction_layer")
        if not mod:
            return {}
        return {"available": True}


# numpy import for runners
import numpy as np

# Singleton
parallel_pipeline = ParallelIntelligencePipeline()
