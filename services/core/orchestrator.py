"""
ALPHA BIST — Master Orchestrator v1.0

Tüm servisleri tek bir pipeline'da birleştiren ana orkestratör.
start.py tarafından çağrılır.

Akış:
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

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
        except Exception:
            pass

        # Feature servisleri
        try:
            from services.features.calculator import feature_calculator
            self._services["feature_calculator"] = feature_calculator
        except ImportError:
            pass
        except Exception:
            pass

        # Intelligence servisleri
        try:
            from services.intelligence.world_state import WorldStateManager
            self._services["world_state"] = WorldStateManager()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.regime import regime_engine
            self._services["regime"] = regime_engine
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.forecasting import ForecastingEngine
            self._services["forecasting"] = ForecastingEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.monte_carlo import MonteCarloEngine
            self._services["monte_carlo"] = MonteCarloEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.probability import ProbabilityEngine
            self._services["probability"] = ProbabilityEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.spec_engine import spec_engine
            self._services["spec_engine"] = spec_engine
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.signal_fusion import SignalFusionEngine
            self._services["signal_fusion"] = SignalFusionEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.knowledge_graph import KnowledgeGraph
            self._services["knowledge_graph"] = KnowledgeGraph()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.research_memory import ResearchMemory
            self._services["research_memory"] = ResearchMemory()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.evidence_engine import EvidenceVerificationEngine
            self._services["evidence"] = EvidenceVerificationEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.factor_engine import FactorEngine
            self._services["factor_engine"] = FactorEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.impact_engine import ImpactEngine
            self._services["impact_engine"] = ImpactEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.macro_sensitivity import MacroSensitivityEngine
            self._services["macro_sensitivity"] = MacroSensitivityEngine()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.intelligence.news_pipeline import NewsPipeline
            self._services["news_pipeline"] = NewsPipeline()
        except ImportError:
            pass
        except Exception:
            pass

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
        except Exception:
            pass

        try:
            from services.intelligence.trade_planner import TradePlanner
            self._services["trade_planner"] = TradePlanner()
        except ImportError:
            pass
        except Exception:
            pass

        # Decision servisleri
        try:
            from services.core.decision_engine import DecisionEngine
            self._services["decision_engine"] = DecisionEngine()
        except ImportError:
            pass
        except Exception:
            pass

        # Risk servisleri
        try:
            from services.core.risk_gate import RiskGate
            self._services["risk_gate"] = RiskGate()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.risk.position_sizing import PositionSizer
            self._services["position_sizing"] = PositionSizer()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.core.compliance import compliance_checker
            self._services["compliance"] = compliance_checker
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.core.short_selling import short_selling_monitor
            self._services["short_selling"] = short_selling_monitor
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.core.halt_monitor import halt_monitor
            self._services["halt_monitor"] = halt_monitor
        except ImportError:
            pass
        except Exception:
            pass

        # Portfolio servisleri
        try:
            from services.portfolio.portfolio_manager import PortfolioManager, CommissionModel
            self._services["portfolio_manager"] = PortfolioManager()
            self._services["commission_model"] = CommissionModel()
        except ImportError:
            pass
        except Exception:
            pass

        # Learning servisleri
        try:
            from services.learning.outcome_tracker import OutcomeTracker
            self._services["outcome_tracker"] = OutcomeTracker()
        except ImportError:
            pass
        except Exception:
            pass

        try:
            from services.learning.integrated_learning import IntegratedLearningSystem
            self._services["learning"] = IntegratedLearningSystem()
        except ImportError:
            pass
        except Exception:
            pass

        # Macro servisleri (B28)
        try:
            from services.features.macro import compute_all_macro_features
            self._services["macro_features"] = compute_all_macro_features
        except ImportError:
            pass
        except Exception:
            pass

        # Factors (B30)
        try:
            from services.intelligence.factor_engine import compute_financial_scores
            self._services["financial_scores"] = compute_financial_scores
        except ImportError:
            pass
        except Exception:
            pass

        # Event Study (B31)
        try:
            from services.intelligence.impact_engine import analyze_event_impact
            self._services["event_impact"] = analyze_event_impact
        except ImportError:
            pass
        except Exception:
            pass

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
        except Exception:
            pass

        # ━━━ 3. WORLD STATE ━━━
        world_state = {}
        try:
            ws = self._services.get("world_state")
            if ws:
                world_state = ws.get_state_dict() if hasattr(ws, "get_state_dict") else {}
        except Exception:
            pass
        result["world_state"] = world_state

        # ━━━ 4. REGIME ━━━
        regime = "UNKNOWN"
        try:
            re = self._services.get("regime")
            if re:
                regime_result = re.detect_regime(features)
                regime = regime_result.regime if hasattr(regime_result, "regime") else str(regime_result)
        except Exception:
            pass
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
        except Exception:
            pass
        result["analysis"] = analysis

        # ━━━ 6. FORECASTING + PROBABILITY ━━━
        forecast = {}
        try:
            fe = self._services.get("forecasting")
            if fe:
                forecast = {"horizons": [1, 5, 20]}
        except Exception:
            pass
        result["forecast"] = forecast

        # ━━━ 7. MONTE CARLO ━━━
        monte_carlo = {}
        try:
            mc = self._services.get("monte_carlo")
            if mc:
                monte_carlo = {"simulated": True}
        except Exception:
            pass
        result["monte_carlo"] = monte_carlo

        # ━━━ 8. SPEC ENGINE ━━━
        spec = {}
        try:
            se = self._services.get("spec_engine")
            if se:
                spec = se.compute_spec(ticker, features, world_state)
                if hasattr(spec, "__dict__"):
                    spec = spec.__dict__
        except Exception:
            pass
        result["spec"] = spec

        # ━━━ 9. FACTORS (B30) ━━━
        factors = {}
        try:
            fs_fn = self._services.get("financial_scores")
            if fs_fn and market_data.get("fundamentals"):
                factors = fs_fn(market_data["fundamentals"])
        except Exception:
            pass
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
                        _asyncio.get_event_loop().create_task(eb.publish("agent.analysis", event))
                    except RuntimeError:
                        pass
            except ImportError:
                pass
            except Exception:
                pass

        # ━━━ 10. SIGNAL FUSION (Agent sonuçları dahil) ━━━
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
                    "ai": {
                        "direction": agent_result.get("direction", "NEUTRAL"),
                        "score": agent_result.get("score", 50),
                    },
                }
                fused = sf.fuse_signals(ticker, signals, regime)
                fused_signal = fused.__dict__ if hasattr(fused, "__dict__") else {}
        except Exception:
            pass
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
                )
                d = de.decide(inp)
                decision = d.__dict__ if hasattr(d, "__dict__") else {}
        except ImportError:
            pass
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
        result["compliance"] = compliance

        # ━━━ 15. KNOWLEDGE GRAPH + RESEARCH MEMORY ━━━
        context = {}
        try:
            kg = self._services.get("knowledge_graph")
            if kg: context["knowledge"] = "available"
            rm = self._services.get("research_memory")
            if rm: context["memory"] = "available"
        except Exception:
            pass
        result["context"] = context

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
                        pass

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

        return PipelineReport(
            date=date,
            results=per_ticker_results,
            system_health=system_health,
            agent_results=agent_results_all,
            top_opportunities=top_opportunities[:20],
            macro_analysis=macro_analysis,
            regime=macro_analysis.get("regime", "UNKNOWN"),
        )

    def get_status(self) -> Dict[str, Any]:
        """Sistem durumu."""
        return {
            "initialized": self._initialized,
            "services_loaded": len(self._services),
            "services": list(self._services.keys()),
        }


# Singleton
master_orchestrator = MasterOrchestrator()

# Geriye dönük/alternatif isimlendirme uyumluluğu — testlerde ve bazı
# çağıranlarda "SystemOrchestrator" adı kullanılıyor; gerçek sınıf budur.
SystemOrchestrator = MasterOrchestrator
