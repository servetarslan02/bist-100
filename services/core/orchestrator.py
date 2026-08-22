"""
ALPHA BIST — Master Orchestrator v1.0

Tüm servisleri tek bir pipeline'da birleştiren ana orkestratör.
start.py tarafından çağrılır.

Akış:
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING
"""

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

# Sync-to-async bridge: background event loop for event publishing
_bg_loop = None
_bg_thread = None

def _get_bg_loop():
    """Get or create a background asyncio event loop for sync→async bridge."""
    global _bg_loop, _bg_thread
    if _bg_loop is None or _bg_loop.is_closed():
        _bg_loop = asyncio.new_event_loop()
        _bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
        _bg_thread.start()
    return _bg_loop

def _publish_event_async(event, key="default"):
    """Publish event from sync context via background loop."""
    try:
        from services.core.event_bus import publish_event
        loop = _get_bg_loop()
        asyncio.run_coroutine_threadsafe(publish_event(event, key=key), loop)
    except Exception:
        pass

logger = structlog.get_logger()


@dataclass
class PipelineReport:
    """run_full_pipeline() çıktısı — çoklu-hisse batch çalıştırma raporu."""
    date: str
    results: Dict[str, Any] = field(default_factory=dict)
    system_health: Dict[str, Any] = field(default_factory=dict)
    agent_results: Dict[str, Any] = field(default_factory=dict)
    top_opportunities: List[Dict] = field(default_factory=list)
    regime: str = "UNKNOWN"
    macro_analysis: Dict[str, Any] = field(default_factory=dict)
    portfolio_recommendation: Dict[str, Any] = field(default_factory=dict)
    learning_status: Dict[str, Any] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)


class MasterOrchestrator:
    """Tüm servisleri orkestre eden ana sınıf."""

    def __init__(self):
        self._initialized = False
        self._services = {}
        self._simulation_results: Dict[str, Any] = {}  # MC simulation cache

    async def initialize(self):
        """Tüm servisleri başlat."""
        if self._initialized:
            return

        logger.info("Master Orchestrator initializing...")

        # Core servisler
        try:
            from services.core.event_bus import event_bus
            self._services["event_bus"] = event_bus
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="event_bus", error=str(e))

        # Feature servisleri
        try:
            from services.features.calculator import feature_calculator
            self._services["feature_calculator"] = feature_calculator
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="feature_calculator", error=str(e))

        # Intelligence servisleri
        try:
            from services.intelligence.world_state import WorldStateManager
            self._services["world_state"] = WorldStateManager()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="world_state", error=str(e))

        try:
            from services.intelligence.regime import regime_engine
            self._services["regime"] = regime_engine
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="regime", error=str(e))

        try:
            from services.intelligence.forecasting import ForecastingEngine
            self._services["forecasting"] = ForecastingEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="forecasting", error=str(e))

        try:
            from services.intelligence.monte_carlo import MonteCarloEngine
            self._services["monte_carlo"] = MonteCarloEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="monte_carlo", error=str(e))

        try:
            from services.intelligence.probability import ProbabilityEngine
            self._services["probability"] = ProbabilityEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="probability", error=str(e))

        try:
            from services.intelligence.spec_engine import spec_engine
            self._services["spec_engine"] = spec_engine
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="spec_engine", error=str(e))

        try:
            from services.intelligence.signal_fusion import SignalFusionEngine
            self._services["signal_fusion"] = SignalFusionEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="signal_fusion", error=str(e))

        try:
            from services.intelligence.knowledge_graph import KnowledgeGraph
            self._services["knowledge_graph"] = KnowledgeGraph()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="knowledge_graph", error=str(e))

        try:
            from services.intelligence.research_memory import ResearchMemory
            self._services["research_memory"] = ResearchMemory()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="research_memory", error=str(e))

        try:
            from services.intelligence.evidence_engine import EvidenceVerificationEngine
            self._services["evidence"] = EvidenceVerificationEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="evidence", error=str(e))

        try:
            from services.intelligence.factor_engine import FactorEngine
            self._services["factor_engine"] = FactorEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="factor_engine", error=str(e))

        try:
            from services.intelligence.impact_engine import ImpactEngine
            self._services["impact_engine"] = ImpactEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="impact_engine", error=str(e))

        try:
            from services.intelligence.macro_sensitivity import MacroSensitivityEngine
            self._services["macro_sensitivity"] = MacroSensitivityEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="macro_sensitivity", error=str(e))

        try:
            from services.intelligence.news_pipeline import NewsPipeline
            self._services["news_pipeline"] = NewsPipeline()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="news_pipeline", error=str(e))

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
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="correlation", error=str(e))

        try:
            from services.intelligence.trade_planner import TradePlanner
            self._services["trade_planner"] = TradePlanner()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="trade_planner", error=str(e))

        # Decision servisleri
        try:
            from services.core.decision_engine import DecisionEngine
            self._services["decision_engine"] = DecisionEngine()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="decision_engine", error=str(e))

        # Risk servisleri
        try:
            from services.core.risk_gate import RiskGate
            self._services["risk_gate"] = RiskGate()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="risk_gate", error=str(e))

        try:
            from services.risk.position_sizing import PositionSizer
            self._services["position_sizing"] = PositionSizer()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="position_sizing", error=str(e))

        try:
            from services.core.compliance import compliance_checker
            self._services["compliance"] = compliance_checker
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="compliance", error=str(e))

        try:
            from services.core.short_selling import short_selling_monitor
            self._services["short_selling"] = short_selling_monitor
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="short_selling", error=str(e))

        try:
            from services.core.halt_monitor import halt_monitor
            self._services["halt_monitor"] = halt_monitor
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="halt_monitor", error=str(e))

        # Portfolio servisleri
        try:
            from services.portfolio.portfolio_manager import PortfolioManager, CommissionModel
            self._services["portfolio_manager"] = PortfolioManager()
            self._services["commission_model"] = CommissionModel()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="commission_model", error=str(e))

        # Learning servisleri
        try:
            from services.learning.outcome_tracker import OutcomeTracker
            self._services["outcome_tracker"] = OutcomeTracker()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="outcome_tracker", error=str(e))

        try:
            from services.learning.integrated_learning import IntegratedLearningSystem
            self._services["learning"] = IntegratedLearningSystem()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="learning", error=str(e))

        # Macro servisleri (B28)
        try:
            from services.features.macro import compute_all_macro_features
            self._services["macro_features"] = compute_all_macro_features
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="macro_features", error=str(e))

        # Factors (B30)
        try:
            from services.intelligence.factor_engine import compute_financial_scores
            self._services["financial_scores"] = compute_financial_scores
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="financial_scores", error=str(e))

        # Event Study (B31)
        try:
            from services.intelligence.impact_engine import analyze_event_impact
            self._services["event_impact"] = analyze_event_impact
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Failed to load module", module="event_impact", error=str(e))

        # === AGENT SYSTEM (Nihai Mimari) ===
        try:
            from services.agents.agent_pipeline import AgentPipelineOrchestrator
            self._services["agent_pipeline"] = AgentPipelineOrchestrator(
                enable_debate=True,
                enable_memory=True,
                enable_self_eval=True,
            )
            logger.info("Agent pipeline loaded")
        except Exception as e:
            logger.warning("Agent pipeline not available", error=str(e))

        # SIMULATION_COMPLETED event handler
        try:
            eb = self._services.get("event_bus")
            if eb:
                from services.core.event_schema import EventType
                async def _on_simulation_completed(event):
                    ticker = event.data.get("ticker", "")
                    if ticker:
                        if not hasattr(self, '_simulation_results'):
                            self._simulation_results = {}
                        self._simulation_results[ticker] = event.data.get("result")
                        logger.debug("Simulation result cached", ticker=ticker)
                try:
                    await eb.subscribe(EventType.SIMULATION_COMPLETED, _on_simulation_completed)
                    logger.info("SIMULATION_COMPLETED handler registered")
                except Exception as e:
                    logger.debug("Could not subscribe to SIMULATION_COMPLETED", error=str(e))
        except Exception as e:
            logger.debug("SIMULATION_COMPLETED handler setup skipped", error=str(e))

        # REGIME_TRANSITION handler (audit #6)
        try:
            eb = self._services.get("event_bus")
            if eb:
                from services.core.event_schema import EventType
                async def _on_regime_transition(event):
                    old_regime = event.data.get("old_regime", "")
                    new_regime = event.data.get("new_regime", "")
                    logger.info("Regime transition detected", old=old_regime, new=new_regime)
                    self._last_regime_transition = event.data
                try:
                    await eb.subscribe("market.regime_transition", _on_regime_transition)
                except Exception:
                    pass
        except Exception:
            pass

        # AGENT_ANALYSIS_COMPLETED handler (audit #1)
        try:
            eb = self._services.get("event_bus")
            if eb:
                from services.core.event_schema import EventType
                async def _on_agent_analysis(event):
                    ticker = event.data.get("ticker", "")
                    direction = event.data.get("direction", "")
                    confidence = event.data.get("confidence", 0)
                    try:
                        ot = self._services.get("outcome_tracker")
                        if ot:
                            ot.add_prediction(
                                ticker=ticker,
                                prediction_type="agent_direction",
                                predicted_value=1 if direction == "LONG" else -1,
                                confidence=confidence,
                            )
                    except Exception:
                        pass
                try:
                    await eb.subscribe("agent.analysis", _on_agent_analysis)
                except Exception:
                    pass
        except Exception:
            pass

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

        # sector_map: market_data'dan veya varsayılan olarak
        sector_map = market_data.get("sector_map", {})

        prices = market_data.get("prices", [])
        if len(prices) < 20:
            result["error"] = "Insufficient data"
            return result

        # ━━━ 1. FEATURES ━━━
        features = {}
        try:
            calc = self._services.get("feature_calculator")
            if calc:
                # compute_all_features bir OHLCV DataFrame bekler; market_data
                # burada ayrı numpy dizileri içeren bir sözlük olduğundan
                # önce uygun şekle dönüştürülür (önceki halde bu adım eksikti
                # ve çağrı her zaman sessizce başarısız oluyordu).
                import pandas as _pd
                ohlcv_df = _pd.DataFrame({
                    "Open": market_data.get("opens", prices),
                    "High": market_data.get("highs", prices),
                    "Low": market_data.get("lows", prices),
                    "Close": market_data.get("closes", prices),
                    "Volume": market_data.get("volumes", [1.0] * len(prices)),
                })
                features = calc.compute_all_features(ohlcv_df, ticker=ticker)
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
        except Exception as e:
            logger.warning("Pipeline step failed", step="macro_features", error=str(e))

        # Macro surprise model
        try:
            from services.macro.surprise_model import MacroSurpriseModel
            surprise = MacroSurpriseModel()
            if hasattr(surprise, 'compute_surprise') and market_data.get("macro"):
                surprise_result = surprise.compute_surprise(market_data["macro"])
                if surprise_result:
                    features["macro_surprise"] = surprise_result
        except Exception:
            pass

        # ━━━ 3. WORLD STATE ━━━
        world_state = {}
        try:
            ws = self._services.get("world_state")
            if ws:
                world_state = ws.get_state_dict() if hasattr(ws, "get_state_dict") else {}
        except Exception as e:
            logger.warning("Pipeline step failed", step="world_state", error=str(e))
        result["world_state"] = world_state

        # ━━━ 4. REGIME ━━━
        regime = "UNKNOWN"
        try:
            re = self._services.get("regime")
            if re:
                regime_result = re.detect_regime(features)
                regime = regime_result.regime if hasattr(regime_result, "regime") else str(regime_result)
        except Exception as e:
            logger.warning("Pipeline step failed", step="regime", error=str(e))
        result["regime"] = regime

        # ━━━ 5. ANALYSIS ENGINES ━━━
        analysis = {}
        try:
            pa = self._services.get("price_action")
            if pa:
                try:
                    analysis["price_action"] = pa.analyze(features) if hasattr(pa, 'analyze') else "available"
                except Exception:
                    analysis["price_action"] = "error"
            ve = self._services.get("volume_engine")
            if ve:
                try:
                    analysis["volume"] = ve.analyze(features) if hasattr(ve, 'analyze') else "available"
                except Exception:
                    analysis["volume"] = "error"
            se = self._services.get("sector_engine")
            if se:
                try:
                    analysis["sector"] = se.analyze(features) if hasattr(se, 'analyze') else "available"
                except Exception:
                    analysis["sector"] = "error"
            rs = self._services.get("relative_strength")
            if rs:
                try:
                    analysis["relative_strength"] = rs.analyze(features) if hasattr(rs, 'analyze') else "available"
                except Exception:
                    analysis["relative_strength"] = "error"
        except Exception as e:
            logger.warning("Pipeline step failed", step="analysis_engines", error=str(e))
        result["analysis"] = analysis

        # ━━━ 6. FORECASTING + PROBABILITY ━━━
        forecast = {}
        # Champion/challenger model seçimi (audit #26)
        champion_model = None
        try:
            from services.learning.champion_challenger import ChampionChallengerEngine
            cc = ChampionChallengerEngine()
            champion = cc.get_champion()
            if champion:
                champion_model = champion.model_id
                logger.debug("Champion model selected", model=champion_model)
        except Exception:
            pass

        try:
            fe = self._services.get("forecasting")
            if fe:
                import pandas as _pd
                hist_returns = []
                if len(prices) > 1:
                    _closes = _pd.Series(prices)
                    hist_returns = _closes.pct_change().dropna().tolist()
                forecasts = fe.compute_forecasts(
                    ticker=ticker,
                    features=features,
                    historical_returns=hist_returns,
                )
                if forecasts and isinstance(forecasts, list) and len(forecasts) > 0:
                    f0 = forecasts[0]
                    forecast = {
                        "horizons": [1, 5, 20],
                        "predicted_return": getattr(f0, "predicted_return", 0),
                        "probability_positive": getattr(f0, "probability_positive", 0),
                        "horizon_days": getattr(f0, "horizon_days", 5),
                        "model_name": getattr(f0, "model_name", "unknown"),
                        "forecasts": [
                            {
                                "horizon": getattr(f, "horizon_days", 0),
                                "return": getattr(f, "predicted_return", 0),
                                "prob_pos": getattr(f, "probability_positive", 0),
                            }
                            for f in forecasts[:3]
                        ],
                    }
                else:
                    forecast = {"horizons": [1, 5, 20], "predicted_return": 0, "probability_positive": 0}
        except Exception as e:
            logger.warning("Pipeline step failed", step="forecasting_+_probability", error=str(e))
        result["forecast"] = forecast

        # ━━━ 7. MONTE CARLO ━━━
        monte_carlo = {}
        try:
            mc = self._services.get("monte_carlo")
            if mc:
                # Fiyat ve volatilite bilgilerini topla
                mc_price = float(prices[-1]) if len(prices) > 0 else 100.0
                vol_20d = features.get("volatility_20d", 20)
                # vol_20d yüzde olarak geliyorsa (örn 25.3) float'a çevir
                if vol_20d is not None and float(vol_20d) > 1:
                    vol_annual = float(vol_20d) / 100.0
                else:
                    vol_annual = float(vol_20d) if vol_20d else 0.20
                # Cache'den MC sonucu varsa kullan
                cached_mc = getattr(self, '_simulation_results', {}).get(ticker)
                if cached_mc:
                    mc_result = cached_mc
                else:
                    mc_result = mc.simulate_price_paths(
                        ticker=ticker,
                        current_price=mc_price,
                        expected_return_annual=0.10,
                        volatility_annual=vol_annual,
                        horizon_days=20,
                        num_simulations=10000,
                    )
                if mc_result:
                    monte_carlo = {
                        "simulated": True,
                        "expected_return": getattr(mc_result, "expected_return", 0),
                        "volatility": getattr(mc_result, "volatility", 0),
                        "p10": getattr(mc_result, "p10", 0),
                        "p25": getattr(mc_result, "p25", 0),
                        "p50": getattr(mc_result, "p50", 0),
                        "p75": getattr(mc_result, "p75", 0),
                        "p90": getattr(mc_result, "p90", 0),
                        "prob_positive": getattr(mc_result, "prob_positive", 0),
                        "prob_plus_5pct": getattr(mc_result, "prob_plus_5pct", 0),
                        "prob_plus_10pct": getattr(mc_result, "prob_plus_10pct", 0),
                        "prob_minus_5pct": getattr(mc_result, "prob_minus_5pct", 0),
                        "prob_minus_10pct": getattr(mc_result, "prob_minus_10pct", 0),
                        "var_95": getattr(mc_result, "var_95", 0),
                        "cvar_95": getattr(mc_result, "cvar_95", 0),
                        "max_drawdown_sim": getattr(mc_result, "max_drawdown_sim", 0),
                        "horizon_days": getattr(mc_result, "horizon_days", 20),
                        "num_simulations": getattr(mc_result, "num_simulations", 10000),
                    }
        except Exception as e:
            logger.warning("Pipeline step failed", step="monte_carlo", error=str(e))
        result["monte_carlo"] = monte_carlo

        # ━━━ 7.5. INTELLIGENCE PIPELINE (audit #13) ━━━
        try:
            from services.intelligence.pipeline import IntelligencePipeline
            ip = IntelligencePipeline()
            ip_result = ip.run(ticker, features, regime=regime)
            result["intelligence_pipeline"] = {
                "fused_direction": ip_result.fused_direction,
                "fused_confidence": ip_result.fused_confidence,
                "mc_var_95": ip_result.mc_var_95,
                "mc_cvar_95": ip_result.mc_cvar_95,
                "modules_used": ip_result.modules_used,
                "modules_failed": ip_result.modules_failed,
                "total_elapsed_ms": ip_result.total_elapsed_ms,
            }
        except Exception as e:
            logger.warning("Intelligence pipeline failed", error=str(e))

        # ━━━ 8. SPEC ENGINE ━━━
        spec = {}
        try:
            se = self._services.get("spec_engine")
            if se:
                spec = se.compute_spec(ticker, features, world_state)
                if hasattr(spec, "__dict__"):
                    spec = spec.__dict__
        except Exception as e:
            logger.warning("Pipeline step failed", step="spec_engine", error=str(e))
        result["spec"] = spec

        # ━━━ 9. FACTORS (B30) ━━━
        factors = {}
        try:
            fs_fn = self._services.get("financial_scores")
            if fs_fn and market_data.get("fundamentals"):
                factors = fs_fn(market_data["fundamentals"])
        except Exception as e:
            logger.warning("Pipeline step failed", step="factors_(b30)", error=str(e))
        result["factors"] = factors

        # ━━━ 9.5. AGENT PIPELINE (Nihai Mimari) ━━━
        agent_result = {}
        try:
            agent_pipe = self._services.get("agent_pipeline")
            if agent_pipe:
                import asyncio as _asyncio
                try:
                    loop = _asyncio.get_running_loop()
                    # Zaten bir loop içinde — nested çalıştır
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            _asyncio.run,
                            agent_pipe.run(
                                ticker=ticker,
                                features=features,
                                sector=sector_map.get(ticker, "UNKNOWN"),
                                regime=regime,
                                price=float(prices[-1]) if len(prices) > 0 else 0,
                            )
                        )
                        agent_pipeline_result = future.result(timeout=180)
                except RuntimeError:
                    # Loop yok
                    agent_pipeline_result = _asyncio.run(
                        agent_pipe.run(
                            ticker=ticker,
                            features=features,
                            sector=sector_map.get(ticker, "UNKNOWN"),
                            regime=regime,
                            price=float(prices[-1]) if len(prices) > 0 else 0,
                        )
                    )

                agent_result = {
                    "direction": agent_pipeline_result.direction,
                    "confidence": agent_pipeline_result.confidence,
                    "score": agent_pipeline_result.synthesis.weighted_score,
                    "consensus": agent_pipeline_result.synthesis.consensus_reached,
                    "debate_occurred": agent_pipeline_result.synthesis.debate_occurred,
                    "risk_approved": agent_pipeline_result.synthesis.risk_approved,
                    "reasoning": agent_pipeline_result.synthesis.reasoning[:300],
                    "reasons": agent_pipeline_result.synthesis.reasons[:5],
                    "risks": agent_pipeline_result.synthesis.risks[:5],
                    "duration_ms": agent_pipeline_result.total_duration_ms,
                }
                logger.info("Agent pipeline completed",
                           ticker=ticker,
                           direction=agent_result["direction"],
                           confidence=agent_result["confidence"])
        except Exception as e:
            logger.warning("Agent pipeline failed", ticker=ticker, error=str(e))
        result["agent"] = agent_result

        # Agent event publish
        if agent_result and agent_result.get("direction"):
            try:
                eb = self._services.get("event_bus")
                if eb:
                    from services.core.event_schema import CanonicalEvent, EventType
                    event = CanonicalEvent(
                        event_type=EventType.AGENT_ANALYSIS_COMPLETED,
                        payload={
                            "ticker": ticker,
                            "direction": agent_result.get("direction"),
                            "confidence": agent_result.get("confidence"),
                            "score": agent_result.get("score"),
                            "consensus": agent_result.get("consensus"),
                            "debate_occurred": agent_result.get("debate_occurred"),
                        },
                    )
                    import asyncio as _asyncio
                    try:
                        _publish_event_async(event, key=ticker)
                    except RuntimeError:
                        pass
            except ImportError:
                pass
            except Exception as e:
                logger.warning("Pipeline step failed", step="agent_event_publish", error=str(e))

        # ━━━ 10. SIGNAL FUSION (Agent sonuçları dahil) ━━━
        fused_signal = {}
        try:
            sf = self._services.get("signal_fusion")
            if sf:
                # Fundamental: factor_engine sonucu veya features'dan
                fund_score = 50.0
                if factors and isinstance(factors, dict):
                    fund_score = factors.get("composite_score", factors.get("financial_score", 50))
                elif features.get("fundamental_score"):
                    fund_score = float(features["fundamental_score"])
                fund_dir = "LONG" if fund_score > 55 else ("SHORT" if fund_score < 45 else "NEUTRAL")

                # Macro: regime sonucu veya macro features'dan
                macro_score = 50.0
                macro_dir = "NEUTRAL"
                if features.get("macro_regime_score"):
                    macro_score = float(features["macro_regime_score"])
                elif features.get("macro_cumulative_impact"):
                    impact = float(features["macro_cumulative_impact"])
                    macro_score = min(max(50 + impact * 100, 0), 100)
                if regime in ("BULL", "BULL_VOLATILE", "RECOVERY"):
                    macro_dir = "LONG"
                    macro_score = max(macro_score, 60)
                elif regime in ("BEAR", "BEAR_VOLATILE", "CRASH"):
                    macro_dir = "SHORT"
                    macro_score = min(macro_score, 40)

                # Valuation: spec_engine sonucu veya features'dan
                val_score = 50.0
                if spec and isinstance(spec, dict):
                    val_score = spec.get("spec_score", 50)
                elif features.get("pe_ratio"):
                    pe = float(features["pe_ratio"])
                    val_score = max(0, min(100, 80 - pe * 2))  # Düşük PE = yüksek skor
                val_dir = "LONG" if val_score > 55 else ("SHORT" if val_score < 45 else "NEUTRAL")

                signals = {
                    "technical": {"direction": "LONG" if features.get("rsi_14", 50) > 55 else "SHORT", "score": features.get("rsi_14", 50)},
                    "fundamental": {"direction": fund_dir, "score": fund_score},
                    "momentum": {"direction": "LONG" if features.get("momentum_20d", 0) > 0 else "SHORT", "score": min(max(features.get("roc_20d", 0) + 50, 0), 100)},
                    "macro": {"direction": macro_dir, "score": macro_score},
                    "valuation": {"direction": val_dir, "score": val_score},
                    "ai": {
                        "direction": agent_result.get("direction", "NEUTRAL"),
                        "score": agent_result.get("score", 50),
                    },
                    "monte_carlo": {
                        "direction": "LONG" if monte_carlo.get("prob_positive", 0) > 0.55 else ("SHORT" if monte_carlo.get("prob_positive", 0) < 0.45 else "NEUTRAL"),
                        "score": min(max(monte_carlo.get("expected_return", 0) * 5 + 50, 0), 100) if monte_carlo.get("simulated") else 50,
                    },
                }
                fused = sf.fuse_signals(ticker, signals, regime)
                fused_signal = fused.__dict__ if hasattr(fused, "__dict__") else {}
        except Exception as e:
            logger.warning("Pipeline step failed", step="signal_fusion", error=str(e))
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
                    # Agent sistemi
                    agent_direction=agent_result.get("direction", "NEUTRAL"),
                    agent_confidence=agent_result.get("confidence", 0.0),
                    agent_score=agent_result.get("score", 50.0),
                    # Macro sistemi (audit #10)
                    macro_regime=regime,
                    macro_stance=1.0 if regime in ("BULL", "RECOVERY") else (-1.0 if regime in ("BEAR", "CRASH") else 0.0),
                    macro_confidence=0.7 if regime != "UNKNOWN" else 0.3,
                    macro_impact=features.get("macro_cumulative_impact", 0),
                    # Monte Carlo simülasyon sonuçları
                    sim_var_95=monte_carlo.get("var_95", 0),
                    sim_expected_return=monte_carlo.get("expected_return", 0),
                    sim_prob_positive=monte_carlo.get("prob_positive", 0),
                    # Forecast
                    ml_return_5d=forecast.get("predicted_return", 0) if forecast.get("horizon_days", 0) == 5 else 0,
                    ml_return_20d=forecast.get("predicted_return", 0) if forecast.get("horizon_days", 0) == 20 else 0,
                    # Spec
                    spec_score=spec.get("spec_score", 50) if isinstance(spec, dict) else 50,
                    world_alignment=world_state.get("global_risk_appetite", 0.5) if isinstance(world_state, dict) else 0.5,
                )
                d = de.decide(inp)
                decision = d.__dict__ if hasattr(d, "__dict__") else {}

                # DECISION_CREATED event publish (audit #3)
                try:
                    eb = self._services.get("event_bus")
                    if eb and decision.get("action"):
                        from services.core.event_schema import CanonicalEvent, EventType as ET
                        dec_event = CanonicalEvent(
                            event_type=ET.DECISION_CREATED,
                            payload={
                                "ticker": ticker,
                                "action": decision.get("action"),
                                "direction": decision.get("direction"),
                                "confidence": decision.get("confidence"),
                                "score": decision.get("score"),
                            },
                        )
                        import asyncio as _asyncio
                        try:
                            _publish_event_async(dec_event, key=ticker)
                        except RuntimeError:
                            pass
                except Exception:
                    pass
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Pipeline step failed", step="decision", error=str(e))
        result["decision"] = decision

        # ━━━ 11.5. LEARNING FEEDBACK — Regime Accuracy (audit #25) ━━━
        try:
            ls = self._services.get("learning")
            if ls and hasattr(ls, 'get_regime_accuracy'):
                regime_acc = ls.get_regime_accuracy(regime)
                if regime_acc and regime_acc < 0.4:
                    if decision.get("confidence", 0) > 0:
                        decision["confidence"] = decision["confidence"] * 0.8
                        decision["learning_adjustment"] = f"Low regime accuracy ({regime_acc:.2f})"
        except Exception:
            pass

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
        except Exception as e:
            logger.warning("Pipeline step failed", step="trade_plan", error=str(e))
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
                    mc_var_95=monte_carlo.get("var_95", 0),
                    mc_cvar_95=monte_carlo.get("cvar_95", 0),
                )
                if isinstance(risk_result, dict):
                    risk_check = risk_result
                elif hasattr(risk_result, "__dict__"):
                    risk_check = risk_result.__dict__
                else:
                    risk_check = {"allowed": False, "reason": "Invalid risk result format"}
        except Exception as e:
            logger.warning("Pipeline step failed", step="risk_check", error=str(e))
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
        except Exception as e:
            logger.warning("Pipeline step failed", step="compliance", error=str(e))
        result["compliance"] = compliance

        # ━━━ 15. KNOWLEDGE GRAPH + RESEARCH MEMORY ━━━
        context = {}
        try:
            kg = self._services.get("knowledge_graph")
            if kg: context["knowledge"] = "available"
            rm = self._services.get("research_memory")
            if rm: context["memory"] = "available"
        except Exception as e:
            logger.warning("Pipeline step failed", step="knowledge_graph_+_research_memory", error=str(e))
        result["context"] = context

        # ━━━ 16. LEARNING — Prediction Kaydet (audit #24) ━━━
        try:
            ot = self._services.get("outcome_tracker")
            if ot and decision.get("action") in ("BUY", "SELL"):
                ot.add_prediction(
                    ticker=ticker,
                    prediction_type="direction",
                    predicted_value=1 if decision.get("direction") == "LONG" else -1,
                    confidence=decision.get("confidence", 0.5),
                    features=features,
                    model_version="pipeline_v1",
                )
                output.modules_used.append("outcome_tracker") if hasattr(output, "modules_used") else None
                logger.debug("Prediction recorded", ticker=ticker, action=decision.get("action"))
        except Exception as e:
            logger.debug("Learning prediction recording skipped", error=str(e))

        return result

    def run_full_pipeline(
        self,
        date: str,
        market_data: Dict[str, Any],
        sector_map: Optional[Dict[str, str]] = None,
    ) -> "PipelineReport":
        """Birden fazla hisse için tam pipeline'ı bir tarih için çalıştırır.

        Args:
            date: İşlem tarihi (ISO string)
            market_data: {ticker: OHLCV DataFrame}
            sector_map: {ticker: sektör adı} (opsiyonel)

        Not: Bu metod senkrondur; servisler henüz initialize edilmediyse
        (`await initialize()` çağrılmadıysa) otomatik olarak, mevcut bir
        event loop'a bağımlı olmadan senkron şekilde initialize eder.
        """
        if not self._initialized:
            try:
                asyncio.run(self.initialize())
            except RuntimeError:
                # Zaten çalışan bir event loop içindeysek (nadir, sync
                # context'te olmamalı) — yine de en azından boş servis
                # sözlüğüyle devam et, initialize() daha sonra çağrılabilir.
                logger.warning("initialize() senkron çağrılamadı (aktif event loop mevcut)")

        sector_map = sector_map or {}
        per_ticker_results: Dict[str, Any] = {}
        errors: List[str] = []

        # === MACRO PIPELINE (YENİ) ===
        macro_analysis = {}
        try:
            from services.macro import (
                macro_surprise_model, macro_regime_detector,
                macro_impact_analyzer, macro_stress_test,
                macro_correlation_tracker, macro_factor_decomposition,
            )
            from services.features.macro import macro_feature_engine

            # Macro data (market_data'dan çıkar veya servislerden al)
            macro_data = {}
            for _ticker, _df in market_data.items():
                if hasattr(_df, 'columns') and 'Close' in _df.columns:
                    # Basit macro data çıkarma
                    pass

            # Macro regime detection
            macro_features = macro_feature_engine.compute_all_macro_features(macro_data)
            if macro_features:
                macro_regime = macro_regime_detector.detect_regime(macro_features)
                macro_analysis = {
                    "regime": macro_regime.regime,
                    "regime_confidence": macro_regime.confidence,
                    "regime_description": macro_regime.description,
                    "macro_features": macro_features,
                }
        except Exception as e:
            logger.warning("Macro pipeline failed", error=str(e))

        # Macro factor decomposition (audit #22)
        try:
            from services.macro.factor_decomposition import MacroFactorDecomposition
            mfd = MacroFactorDecomposition()
            if hasattr(mfd, 'decompose'):
                factor_result = mfd.decompose(macro_data)
                macro_analysis["factor_decomposition"] = factor_result
        except Exception:
            pass

        # Macro correlation tracker (audit #21)
        try:
            from services.macro.correlation_tracker import MacroCorrelationTracker
            mct = MacroCorrelationTracker()
            if hasattr(mct, 'get_current_regime'):
                corr_regime = mct.get_current_regime()
                macro_analysis["correlation_regime"] = corr_regime
        except Exception:
            pass

        for ticker, df in market_data.items():
            try:
                calc = self._services.get("feature_calculator")
                features = calc.compute_all_features(df, ticker=ticker) if calc else {}

                # Macro features ekle
                if macro_analysis.get("macro_features"):
                    features.update(macro_analysis["macro_features"])

                # Macro impact (sektör bazlı)
                if macro_analysis.get("regime"):
                    sector = sector_map.get(ticker, "OTHER")
                    try:
                        impact = macro_impact_analyzer.compute_cumulative_impact(ticker, sector)
                        features["macro_cumulative_impact"] = impact.get("cumulative_impact", 0)
                    except Exception as e:
                        logger.debug("Handled exception", error=str(e), context="orchestrator.py:614")

                # Agent pipeline (varsa)
                agent_info = {}
                try:
                    agent_pipe = self._services.get("agent_pipeline")
                    if agent_pipe and features:
                        import asyncio as _asyncio
                        try:
                            loop = _asyncio.get_running_loop()
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                future = pool.submit(
                                    _asyncio.run,
                                    agent_pipe.run(
                                        ticker=ticker,
                                        features=features,
                                        sector=sector_map.get(ticker, "UNKNOWN"),
                                    )
                                )
                                agent_res = future.result(timeout=180)
                        except RuntimeError:
                            agent_res = _asyncio.run(
                                agent_pipe.run(
                                    ticker=ticker,
                                    features=features,
                                    sector=sector_map.get(ticker, "UNKNOWN"),
                                )
                            )
                        agent_info = {
                            "direction": agent_res.direction,
                            "confidence": agent_res.confidence,
                            "score": agent_res.synthesis.weighted_score,
                        }
                except Exception as e:
                    agent_info = {"error": str(e)}

                per_ticker_results[ticker] = {
                    "ticker": ticker,
                    "sector": sector_map.get(ticker, "UNKNOWN"),
                    "features": features,
                    "feature_count": len(features),
                    "agent": agent_info,
                    "error": None,
                }
                if not features:
                    errors.append(f"{ticker}: feature hesaplanamadı (boş sonuç)")
            except Exception as e:
                per_ticker_results[ticker] = {
                    "ticker": ticker, "sector": sector_map.get(ticker, "UNKNOWN"),
                    "features": {}, "feature_count": 0, "error": str(e),
                }
                errors.append(f"{ticker}: {e}")

        total = len(market_data)
        failed = sum(1 for r in per_ticker_results.values() if r["error"] is not None)
        # Sağlık durumu gerçek başarısızlık oranına dayanır — uydurulmuş
        # bir "her zaman HEALTHY" değeri değildir.
        if total == 0:
            status = "CRITICAL"
        elif failed == total:
            status = "CRITICAL"
        elif failed > 0:
            status = "DEGRADED"
        else:
            status = "HEALTHY"

        system_health = {
            "status": status,
            "total_tickers": total,
            "failed_tickers": failed,
            "errors": errors,
        }

        # Agent sonuçlarından top_opportunities oluştur
        top_opportunities = []
        agent_results_all = {}
        for ticker, data in per_ticker_results.items():
            agent = data.get("agent", {})
            if agent and agent.get("direction") in ["LONG", "SHORT"]:
                top_opportunities.append({
                    "ticker": ticker,
                    "direction": agent.get("direction", "NEUTRAL"),
                    "score": agent.get("score", 50),
                    "confidence": agent.get("confidence", 0),
                    "sector": data.get("sector", "UNKNOWN"),
                })
                agent_results_all[ticker] = agent

        # Score'a göre sırala
        top_opportunities.sort(key=lambda x: x["score"], reverse=True)
        for i, opp in enumerate(top_opportunities[:20], 1):
            opp["rank"] = i

        # Learning status (audit #12)
        learning_status = {}
        try:
            ot = self._services.get("outcome_tracker")
            ls = self._services.get("learning")
            learning_status = {
                "outcome_tracker": "active" if ot else "not_loaded",
                "learning_system": "active" if ls else "not_loaded",
                "predictions_recorded": len(getattr(ot, '_predictions', [])) if ot else 0,
            }
        except Exception:
            learning_status = {"status": "unavailable"}

        return PipelineReport(
            date=date,
            results=per_ticker_results,
            system_health=system_health,
            agent_results=agent_results_all,
            top_opportunities=top_opportunities[:20],
            macro_analysis=macro_analysis,
            regime=macro_analysis.get("regime", "UNKNOWN"),
            learning_status=learning_status,
        )

    def get_status(self) -> Dict[str, Any]:
        """Sistem durumu."""
        return {
            "initialized": self._initialized,
            "services_loaded": len(self._services),
            "services": list(self._services.keys()),
        }

    def export_daily_report_json(self, date: str) -> str:
        """Günlük pipeline raporunu JSON olarak dışa aktar."""
        import json as _json
        report = {
            "date": date,
            "status": self.get_status(),
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        return _json.dumps(report, indent=2, ensure_ascii=False)

    def get_pipeline_stats(self) -> Dict[str, Any]:
        """Pipeline istatistiklerini döndür."""
        return {
            "services_count": len(self._services),
            "initialized": self._initialized,
            "services": list(self._services.keys()),
        }


# Singleton
master_orchestrator = MasterOrchestrator()

# Geriye dönük/alternatif isimlendirme uyumluluğu — testlerde ve bazı
# çağıranlarda "SystemOrchestrator" adı kullanılıyor; gerçek sınıf budur.
SystemOrchestrator = MasterOrchestrator

# main.py ve diğer çağıranlar için alias
orchestrator = master_orchestrator
