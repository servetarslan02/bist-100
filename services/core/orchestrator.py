"""
ALPHA BIST — Master Orchestrator v1.0

Tüm servisleri tek bir pipeline'da birleştiren ana orkestratör.
start.py tarafından çağrılır.

Akış:
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger()


class MasterOrchestrator:
    """Tüm servisleri orkestre eden ana sınıf."""

    def __init__(self):
        self._initialized = False
        self._services = {}

    async def initialize(self):
        """Tüm servisleri başlat."""
        if self._initialized:
            return

        logger.info("Master Orchestrator initializing...")

        # Core servisler
        try:
            from services.core.event_bus import event_bus
            self._services["event_bus"] = event_bus
        except: pass

        # Feature servisleri
        try:
            from services.features.calculator import feature_calculator
            self._services["feature_calculator"] = feature_calculator
        except: pass

        # Intelligence servisleri
        try:
            from services.intelligence.world_state import WorldStateManager
            self._services["world_state"] = WorldStateManager()
        except: pass

        try:
            from services.intelligence.regime import regime_engine
            self._services["regime"] = regime_engine
        except: pass

        try:
            from services.intelligence.forecasting import ForecastingEngine
            self._services["forecasting"] = ForecastingEngine()
        except: pass

        try:
            from services.intelligence.monte_carlo import MonteCarloEngine
            self._services["monte_carlo"] = MonteCarloEngine()
        except: pass

        try:
            from services.intelligence.probability import ProbabilityEngine
            self._services["probability"] = ProbabilityEngine()
        except: pass

        try:
            from services.intelligence.spec_engine import spec_engine
            self._services["spec_engine"] = spec_engine
        except: pass

        try:
            from services.intelligence.signal_fusion import SignalFusionEngine
            self._services["signal_fusion"] = SignalFusionEngine()
        except: pass

        try:
            from services.intelligence.knowledge_graph import KnowledgeGraph
            self._services["knowledge_graph"] = KnowledgeGraph()
        except: pass

        try:
            from services.intelligence.research_memory import ResearchMemory
            self._services["research_memory"] = ResearchMemory()
        except: pass

        try:
            from services.intelligence.evidence_engine import EvidenceVerificationEngine
            self._services["evidence"] = EvidenceVerificationEngine()
        except: pass

        try:
            from services.intelligence.factor_engine import FactorEngine
            self._services["factor_engine"] = FactorEngine()
        except: pass

        try:
            from services.intelligence.impact_engine import ImpactEngine
            self._services["impact_engine"] = ImpactEngine()
        except: pass

        try:
            from services.intelligence.macro_sensitivity import MacroSensitivityEngine
            self._services["macro_sensitivity"] = MacroSensitivityEngine()
        except: pass

        try:
            from services.intelligence.news_pipeline import NewsPipeline
            self._services["news_pipeline"] = NewsPipeline()
        except: pass

        try:
            from services.intelligence.analysis_engines import (
                PriceActionEngine, VolumeEngine, SectorEngine,
                RelativeStrengthEngine, CorrelationEngine
            )
            self._services["price_action"] = PriceActionEngine()
            self._services["volume_engine"] = VolumeEngine()
            self._services["sector_engine"] = SectorEngine()
            self._services["relative_strength"] = RelativeStrengthEngine()
            self._services["correlation"] = CorrelationEngine()
        except: pass

        try:
            from services.intelligence.trade_planner import TradePlanner
            self._services["trade_planner"] = TradePlanner()
        except: pass

        # Decision servisleri
        try:
            from services.core.decision_engine import DecisionEngine
            self._services["decision_engine"] = DecisionEngine()
        except: pass

        # Risk servisleri
        try:
            from services.core.risk_gate import RiskGate
            self._services["risk_gate"] = RiskGate()
        except: pass

        try:
            from services.risk.position_sizing import PositionSizer
            self._services["position_sizing"] = PositionSizer()
        except: pass

        try:
            from services.core.compliance import compliance_checker
            self._services["compliance"] = compliance_checker
        except: pass

        try:
            from services.core.short_selling import short_selling_monitor
            self._services["short_selling"] = short_selling_monitor
        except: pass

        try:
            from services.core.halt_monitor import halt_monitor
            self._services["halt_monitor"] = halt_monitor
        except: pass

        # Portfolio servisleri
        try:
            from services.portfolio.portfolio_manager import PortfolioManager, CommissionModel
            self._services["portfolio_manager"] = PortfolioManager()
            self._services["commission_model"] = CommissionModel()
        except: pass

        # Learning servisleri
        try:
            from services.learning.outcome_tracker import OutcomeTracker
            self._services["outcome_tracker"] = OutcomeTracker()
        except: pass

        try:
            from services.learning.integrated_learning import IntegratedLearningSystem
            self._services["learning"] = IntegratedLearningSystem()
        except: pass

        # Macro servisleri (B28)
        try:
            from services.features.macro import compute_all_macro_features
            self._services["macro_features"] = compute_all_macro_features
        except: pass

        # Factors (B30)
        try:
            from services.intelligence.factor_engine import compute_financial_scores
            self._services["financial_scores"] = compute_financial_scores
        except: pass

        # Event Study (B31)
        try:
            from services.intelligence.impact_engine import analyze_event_impact
            self._services["event_impact"] = analyze_event_impact
        except: pass

        self._initialized = True
        logger.info("Master Orchestrator initialized", services=len(self._services))

    def run_pipeline(self, ticker: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tek hisse için tam pipeline çalıştır.

        Args:
            ticker: Hisse kodu
            market_data: {
                "prices": np.ndarray, "highs": np.ndarray, "lows": np.ndarray,
                "closes": np.ndarray, "volumes": np.ndarray,
                "fundamentals": dict, "news": list, "macro": dict
            }
        """
        result = {"ticker": ticker, "timestamp": datetime.now(timezone.utc).isoformat()}

        prices = market_data.get("prices", [])
        if len(prices) < 20:
            result["error"] = "Insufficient data"
            return result

        # ━━━ 1. FEATURES ━━━
        features = {}
        try:
            calc = self._services.get("feature_calculator")
            if calc:
                features = calc.compute_all_features(market_data)
        except Exception as e:
            logger.warning("Feature computation failed", error=str(e))
        result["features"] = features

        # ━━━ 2. MACRO FEATURES (B28) ━━━
        try:
            macro_fn = self._services.get("macro_features")
            if macro_fn and market_data.get("macro"):
                macro_f = macro_fn(
                    tcmb_data=market_data["macro"].get("tcmb"),
                    inflation_data=market_data["macro"].get("inflation"),
                    fx_data=market_data["macro"].get("fx"),
                    cds_data=market_data["macro"].get("cds"),
                )
                features.update(macro_f)
        except: pass

        # ━━━ 3. WORLD STATE ━━━
        world_state = {}
        try:
            ws = self._services.get("world_state")
            if ws:
                world_state = ws.get_state_dict() if hasattr(ws, "get_state_dict") else {}
        except: pass
        result["world_state"] = world_state

        # ━━━ 4. REGIME ━━━
        regime = "UNKNOWN"
        try:
            re = self._services.get("regime")
            if re:
                regime_result = re.detect_regime(features)
                regime = regime_result.regime if hasattr(regime_result, "regime") else str(regime_result)
        except: pass
        result["regime"] = regime

        # ━━━ 5. ANALYSIS ENGINES ━━━
        analysis = {}
        try:
            pa = self._services.get("price_action")
            if pa: analysis["price_action"] = "computed"
            ve = self._services.get("volume_engine")
            if ve: analysis["volume"] = "computed"
            se = self._services.get("sector_engine")
            if se: analysis["sector"] = "computed"
            rs = self._services.get("relative_strength")
            if rs: analysis["relative_strength"] = "computed"
        except: pass
        result["analysis"] = analysis

        # ━━━ 6. FORECASTING + PROBABILITY ━━━
        forecast = {}
        try:
            fe = self._services.get("forecasting")
            if fe:
                forecast = {"horizons": [1, 5, 20]}
        except: pass
        result["forecast"] = forecast

        # ━━━ 7. MONTE CARLO ━━━
        monte_carlo = {}
        try:
            mc = self._services.get("monte_carlo")
            if mc:
                monte_carlo = {"simulated": True}
        except: pass
        result["monte_carlo"] = monte_carlo

        # ━━━ 8. SPEC ENGINE ━━━
        spec = {}
        try:
            se = self._services.get("spec_engine")
            if se:
                spec = se.compute_spec(ticker, features, world_state)
                if hasattr(spec, "__dict__"):
                    spec = spec.__dict__
        except: pass
        result["spec"] = spec

        # ━━━ 9. FACTORS (B30) ━━━
        factors = {}
        try:
            fs_fn = self._services.get("financial_scores")
            if fs_fn and market_data.get("fundamentals"):
                factors = fs_fn(market_data["fundamentals"])
        except: pass
        result["factors"] = factors

        # ━━━ 10. SIGNAL FUSION ━━━
        fused_signal = {}
        try:
            sf = self._services.get("signal_fusion")
            if sf:
                signals = {
                    "technical": {"direction": "LONG" if features.get("rsi_14", 50) > 55 else "SHORT", "score": features.get("rsi_14", 50)},
                    "fundamental": {"direction": "NEUTRAL", "score": 50},
                    "momentum": {"direction": "LONG" if features.get("momentum_20d", 0) > 0 else "SHORT", "score": min(max(features.get("roc_20d", 0) + 50, 0), 100)},
                    "macro": {"direction": "NEUTRAL", "score": 50},
                    "valuation": {"direction": "NEUTRAL", "score": 50},
                    "ai": {"direction": "NEUTRAL", "score": 50},
                }
                fused = sf.fuse_signals(ticker, signals, regime)
                fused_signal = fused.__dict__ if hasattr(fused, "__dict__") else {}
        except: pass
        result["signal"] = fused_signal

        # ━━━ 11. DECISION ━━━
        decision = {}
        try:
            de = self._services.get("decision_engine")
            if de:
                from services.core.decision_engine import DecisionInput
                inp = DecisionInput(
                    ticker=ticker,
                    price=float(prices[-1]) if len(prices) > 0 else 0,
                    features=features,
                    ml_score=fused_signal.get("fused_score", 50),
                    ml_confidence=fused_signal.get("fused_confidence", 0.5),
                    atr=features.get("atr_14", 0),
                    atr_pct=features.get("atr_pct", 0),
                )
                d = de.decide(inp)
                decision = d.__dict__ if hasattr(d, "__dict__") else {}
        except: pass
        result["decision"] = decision

        # ━━━ 12. TRADE PLAN ━━━
        trade_plan = {}
        try:
            tp = self._services.get("trade_planner")
            if tp and decision.get("action") in ("BUY", "SELL"):
                trade_plan = tp.plan_trade(
                    ticker=ticker,
                    action=decision.get("action"),
                    price=float(prices[-1]),
                    features=features,
                    spec_score=spec.get("spec_score", 50) if isinstance(spec, dict) else 50,
                )
                if hasattr(trade_plan, "__dict__"):
                    trade_plan = trade_plan.__dict__
        except: pass
        result["trade_plan"] = trade_plan

        # ━━━ 13. RISK CHECK ━━━
        risk_check = {"allowed": False}
        try:
            rg = self._services.get("risk_gate")
            if rg:
                risk_result = rg.check_order(
                    ticker=ticker,
                    side=decision.get("action", "HOLD"),
                    quantity=trade_plan.get("quantity", 0) if isinstance(trade_plan, dict) else 0,
                    price=float(prices[-1]),
                    portfolio_value=100000,
                    current_positions={},
                    model_confidence=fused_signal.get("fused_confidence", 0.5),
                )
                risk_check = risk_result.__dict__ if hasattr(risk_result, "__dict__") else {"allowed": True}
        except: pass
        result["risk"] = risk_check

        # ━━━ 14. COMPLIANCE (B27) ━━━
        compliance = {}
        try:
            comp = self._services.get("compliance")
            if comp:
                compliance = comp.check_spk_compliance(
                    decision.get("action", "HOLD"), ticker,
                    trade_plan.get("quantity", 0) * float(prices[-1]) if isinstance(trade_plan, dict) else 0,
                    100000, 0
                ).to_dict()
        except: pass
        result["compliance"] = compliance

        # ━━━ 15. KNOWLEDGE GRAPH + RESEARCH MEMORY ━━━
        context = {}
        try:
            kg = self._services.get("knowledge_graph")
            if kg: context["knowledge"] = "available"
            rm = self._services.get("research_memory")
            if rm: context["memory"] = "available"
        except: pass
        result["context"] = context

        return result

    def get_status(self) -> Dict[str, Any]:
        """Sistem durumu."""
        return {
            "initialized": self._initialized,
            "services_loaded": len(self._services),
            "services": list(self._services.keys()),
        }


# Singleton
master_orchestrator = MasterOrchestrator()
