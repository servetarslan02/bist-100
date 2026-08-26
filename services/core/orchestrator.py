"""
ALPHA BIST — Master Orchestrator v1.0

Tüm servisleri tek bir pipeline'da birleştiren ana orkestratör.
start.py tarafından çağrılır.

Akış:
INGESTION → FEATURES → INTELLIGENCE → DECISION → RISK → PORTFOLIO → LEARNING
"""

import asyncio
import contextlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
import numpy as np

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
    """Publish event directly (publish_event is synchronous)."""
    try:
        from services.core.event_bus import publish_event
        publish_event(event, key=key)
    except Exception as e:
        logger.debug("event_publish_failed", error=str(e))

logger = structlog.get_logger()


@dataclass
class PipelineReport:
    """run_full_pipeline() çıktısı — çoklu-hisse batch çalıştırma raporu."""
    date: str
    results: dict[str, Any] = field(default_factory=dict)
    system_health: dict[str, Any] = field(default_factory=dict)
    agent_results: dict[str, Any] = field(default_factory=dict)
    top_opportunities: list[dict] = field(default_factory=list)
    regime: str = "UNKNOWN"
    macro_analysis: dict[str, Any] = field(default_factory=dict)
    portfolio_recommendation: dict[str, Any] = field(default_factory=dict)
    learning_status: dict[str, Any] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


class MasterOrchestrator:
    """Tüm servisleri orkestre eden ana sınıf."""

    def __init__(self):
        self._initialized = False
        self._services: dict[str, Any] = {}
        self._simulation_results: dict[str, Any] = {}  # MC simulation cache
        self._thread_pool = None  # Lazy-initialized shared pool

    # Service loading registry: (service_key, module_path, class_or_attr_name, is_class)
    # is_class=True → instantiate; is_class=False → import attribute directly
    _SERVICE_REGISTRY = [
        # Core
        ("event_bus",          "services.core.event_bus",                "event_bus",              False),
        # Features
        ("feature_calculator", "services.features.calculator",           "feature_calculator",     False),
        # Intelligence
        ("world_state",        "services.intelligence.world_state",      "WorldStateManager",      True),
        ("regime",             "services.intelligence.regime",           "regime_engine",          False),
        ("forecasting",        "services.intelligence.forecasting",      "ForecastingEngine",      True),
        ("monte_carlo",        "services.intelligence.monte_carlo",      "MonteCarloEngine",       True),
        ("probability",        "services.intelligence.probability",      "ProbabilityEngine",      True),
        ("spec_engine",        "services.intelligence.spec_engine",      "spec_engine",            False),
        ("signal_fusion",      "services.intelligence.signal_fusion",    "SignalFusionEngine",     True),
        ("knowledge_graph",    "services.intelligence.knowledge_graph",  "KnowledgeGraph",         True),
        ("research_memory",    "services.intelligence.research_memory",  "ResearchMemory",         True),
        ("evidence",           "services.intelligence.evidence_engine",  "EvidenceVerificationEngine", True),
        ("factor_engine",      "services.intelligence.factor_engine",    "FactorEngine",           True),
        ("impact_engine",      "services.intelligence.impact_engine",    "ImpactEngine",           True),
        ("macro_sensitivity",  "services.intelligence.macro_sensitivity","MacroSensitivityEngine", True),
        ("news_pipeline",      "services.intelligence.news_pipeline",    "NewsPipeline",           True),
        ("trade_planner",      "services.intelligence.trade_planner",    "TradePlanner",           True),
        ("llm_agent",          "services.intelligence.llm_agent",        "llm_agent",              False),
        ("agent_pipeline",     "services.agents.agent_pipeline",         "AgentPipelineOrchestrator", True),
        # Decision
        ("decision_engine",    "services.core.decision_engine",          "DecisionEngine",         True),
        # Risk
        ("risk_gate",          "services.core.risk_gate",                "RiskGate",               True),
        ("position_sizing",    "services.risk.position_sizing",          "PositionSizer",          True),
        ("compliance",         "services.core.compliance",               "compliance_checker",     False),
        ("short_selling",      "services.core.short_selling",            "short_selling_monitor",  False),
        ("halt_monitor",       "services.core.halt_monitor",             "halt_monitor",           False),
        # Portfolio
        ("portfolio_manager",  "services.portfolio.portfolio_manager",   "PortfolioManager",       True),
        ("commission_model",   "services.portfolio.portfolio_manager",   "CommissionModel",        True),
        # Learning
        ("outcome_tracker",    "services.learning.outcome_tracker",      "OutcomeTracker",         True),
        ("learning",           "services.learning.integrated_learning",  "IntegratedLearningSystem", True),
        # Macro (B28)
        ("macro_features",     "services.features.macro",                "compute_all_macro_features", False),
        # Factors (B30)
        ("financial_scores",   "services.intelligence.factor_engine",    "compute_financial_scores", False),
        # Event Study (B31)
        ("event_impact",       "services.intelligence.impact_engine",    "analyze_event_impact",   False),
    ]

    # Multi-attribute imports: one module → multiple services
    _MULTI_SERVICE_REGISTRY = [
        ("services.intelligence.analysis_engines", [
            ("price_action",       "PriceActionEngine"),
            ("volume_engine",      "VolumeEngine"),
            ("sector_engine",      "SectorEngine"),
            ("relative_strength",  "RelativeStrengthEngine"),
            ("correlation",        "CorrelationEngine"),
        ]),
    ]

    async def initialize(self):
        """Tüm servisleri başlat."""
        if self._initialized:
            return

        logger.info("Master Orchestrator initializing...")

        # Single-attribute services (registry-driven)
        for key, module_path, attr_name, is_class in self._SERVICE_REGISTRY:
            try:
                module = __import__(module_path, fromlist=[attr_name])
                obj = getattr(module, attr_name)
                self._services[key] = obj() if is_class else obj
            except ImportError as e:
                logger.error("ImportError loading module", module=module_path, attr=attr_name, error=str(e), exc_info=True)
            except Exception as e:
                logger.error("Failed to load module", module=attr_name, error=str(e), exc_info=True)

        # Multi-attribute services
        for module_path, attrs in self._MULTI_SERVICE_REGISTRY:
            try:
                module = __import__(module_path, fromlist=[a[1] for a in attrs])
                for key, cls_name in attrs:
                    self._services[key] = getattr(module, cls_name)()
            except ImportError as e:
                logger.error("ImportError loading module", module=module_path, error=str(e), exc_info=True)
            except Exception as e:
                logger.error("Failed to load module", module=module_path, error=str(e), exc_info=True)

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
                with contextlib.suppress(Exception):
                    await eb.subscribe("market.regime_transition", _on_regime_transition)
        except Exception as e:
            logger.debug("regime_transition_handler_setup_failed", error=str(e))

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
                    except Exception as e:
                        logger.debug("outcome_tracker_add_prediction_failed", error=str(e))
                with contextlib.suppress(Exception):
                    await eb.subscribe("agent.analysis", _on_agent_analysis)
        except Exception as e:
            logger.debug("agent_analysis_handler_setup_failed", error=str(e))

        self._initialized = True
        logger.info("Master Orchestrator initialized", services=len(self._services))

    def _get_thread_pool(self):
        """Shared thread pool for sync→async bridging (lazy init)."""
        if self._thread_pool is None:
            import concurrent.futures
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="orch-async"
            )
        return self._thread_pool

    def _run_agent_async(self, coro):
        """Run an async agent coroutine from sync context."""
        import asyncio as _asyncio
        try:
            _asyncio.get_running_loop()
            return self._get_thread_pool().submit(_asyncio.run, coro).result(timeout=180)
        except RuntimeError:
            return _asyncio.run(coro)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PIPELINE STEPS — run_pipeline'ın parçalara ayrılmış halleri
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _prepare_prices(self, market_data: dict) -> tuple:
        """Fiyat verisini hazırla ve doğrula. Returns (raw_prices, prices, error)."""
        raw_prices = np.asarray(market_data.get("prices", []), dtype=float)
        valid_idx = ~np.isnan(raw_prices) & (raw_prices > 0)
        prices = raw_prices[valid_idx]
        if len(prices) < 20:
            return raw_prices, prices, "Insufficient data"
        return raw_prices, prices, None

    def _compute_features(self, ticker: str, market_data: dict, raw_prices) -> dict:
        """Teknik ve temel özellikleri hesapla."""
        features = {}
        try:
            calc = self._services.get("feature_calculator")
            if calc:
                import pandas as _pd
                ohlcv_df = _pd.DataFrame({
                    "Open": market_data.get("opens", raw_prices),
                    "High": market_data.get("highs", raw_prices),
                    "Low": market_data.get("lows", raw_prices),
                    "Close": market_data.get("closes", raw_prices),
                    "Volume": market_data.get("volumes", [1.0] * len(raw_prices)),
                })
                ohlcv_df = ohlcv_df.dropna(subset=["Close"])
                ohlcv_df = ohlcv_df[ohlcv_df["Close"] > 0]
                features = calc.compute_all_features(ohlcv_df, ticker=ticker)
        except Exception as e:
            logger.warning("Feature computation failed", error=str(e))
        return features

    def _compute_macro_features(self, features: dict, market_data: dict, ticker: str) -> None:
        """Makro özellikleri features sözlüğüne ekle (in-place)."""
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

        try:
            from services.macro.surprise_model import MacroSurpriseModel
            surprise = MacroSurpriseModel()
            if hasattr(surprise, 'compute_surprise') and market_data.get("macro"):
                surprise_result = surprise.compute_surprise(market_data["macro"])
                if surprise_result:
                    features["macro_surprise"] = surprise_result
        except Exception as e:
            logger.debug("macro_surprise_failed", ticker=ticker, error=str(e))

    def _compute_news_sentiment(self, features: dict, market_data: dict, ticker: str) -> None:
        """Haber sentiment özelliklerini features'a ekle (in-place)."""
        try:
            news_pipe = self._services.get("news_pipeline")
            if news_pipe and market_data.get("news"):
                for raw_item in market_data["news"]:
                    processed = news_pipe.process(raw_item)
                    if processed and hasattr(processed, "sentiment"):
                        features["news_sentiment"] = processed.sentiment
                        features["news_importance"] = getattr(processed, "importance", 0.5)
                        if hasattr(processed, "key_insight") and processed.key_insight:
                            features["news_key_insight"] = processed.key_insight
        except Exception as e:
            logger.debug("news_sentiment_failed", ticker=ticker, error=str(e))

    def _compute_world_state(self) -> dict:
        """Küresel piyasa durumunu al."""
        world_state = {}
        try:
            ws = self._services.get("world_state")
            if ws:
                world_state = ws.get_state_dict() if hasattr(ws, "get_state_dict") else {}
        except Exception as e:
            logger.warning("Pipeline step failed", step="world_state", error=str(e))
        return world_state

    def _detect_regime(self, features: dict) -> str:
        """Piyasa rejimini tespit et."""
        regime = "UNKNOWN"
        try:
            re = self._services.get("regime")
            if re:
                regime_result = re.detect_regime(features)
                regime = regime_result.regime if hasattr(regime_result, "regime") else str(regime_result)
        except Exception as e:
            logger.warning("Pipeline step failed", step="regime", error=str(e))
        return regime

    def _run_analysis_engines(self, features: dict) -> dict:
        """Fiyat, hacim, sektör ve göreceli güç analizlerini çalıştır."""
        analysis = {}
        engines = [
            ("price_action", "price_action_analysis_failed"),
            ("volume_engine", "volume_analysis_failed"),
            ("sector_engine", "sector_analysis_failed"),
            ("relative_strength", "relative_strength_analysis_failed"),
        ]
        for service_key, error_label in engines:
            try:
                eng = self._services.get(service_key)
                if eng:
                    analysis[service_key] = eng.analyze(features) if hasattr(eng, 'analyze') else "available"
            except Exception as e:
                logger.debug(error_label, error=str(e))
                analysis[service_key] = "error"
        return analysis

    def _compute_forecast(self, ticker: str, features: dict, prices) -> dict:
        """Tahmin ve olasılık hesapla."""
        forecast = {}
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
            logger.warning("Pipeline step failed", step="forecasting", error=str(e))
        return forecast

    def _run_monte_carlo(self, ticker: str, prices, features: dict) -> dict:
        """Monte Carlo simülasyonu çalıştır."""
        monte_carlo = {}
        try:
            mc = self._services.get("monte_carlo")
            if mc:
                mc_price = float(prices[-1]) if len(prices) > 0 else 100.0
                vol_20d = features.get("volatility_20d", 20)
                if vol_20d is not None and float(vol_20d) > 1:
                    vol_annual = float(vol_20d) / 100.0
                else:
                    vol_annual = float(vol_20d) if vol_20d else 0.20
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
        return monte_carlo

    def _run_intelligence_pipeline(self, ticker: str, features: dict, regime: str) -> dict:
        """Intelligence pipeline çalıştır."""
        try:
            from services.intelligence.pipeline import IntelligencePipeline
            ip = IntelligencePipeline()
            ip_result = ip.run(ticker, features, regime=regime)
            return {
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
            return {}

    def _compute_spec(self, ticker: str, features: dict, world_state: dict) -> dict:
        """Spec motorunu çalıştır."""
        spec = {}
        try:
            se = self._services.get("spec_engine")
            if se:
                spec = se.compute_spec(ticker, features, world_state)
                if hasattr(spec, "__dict__"):
                    spec = spec.__dict__
        except Exception as e:
            logger.warning("Pipeline step failed", step="spec_engine", error=str(e))
        return spec

    def _compute_factors(self, market_data: dict) -> dict:
        """Finansal skorları hesapla."""
        factors = {}
        try:
            fs_fn = self._services.get("financial_scores")
            if fs_fn and market_data.get("fundamentals"):
                factors = fs_fn(market_data["fundamentals"])
        except Exception as e:
            logger.warning("Pipeline step failed", step="factors", error=str(e))
        return factors

    def _run_agent_pipeline(self, ticker: str, features: dict, sector_map: dict, regime: str, prices) -> dict:
        """Agent pipeline çalıştır."""
        agent_result = {}
        try:
            agent_pipe = self._services.get("agent_pipeline")
            if agent_pipe:
                agent_pipeline_result = self._run_agent_async(
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
        return agent_result

    def _publish_agent_event(self, ticker: str, agent_result: dict) -> None:
        """Agent analiz sonucunu event bus'a yayınla."""
        if not agent_result or not agent_result.get("direction"):
            return
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
                with contextlib.suppress(RuntimeError):
                    _publish_event_async(event, key=ticker)
        except ImportError:
            logger.debug("Optional import not available in _publish_agent_event", exc_info=True)
        except Exception as e:
            logger.warning("Agent event publish failed", step="agent_event_publish", error=str(e))

    def _fuse_signals(self, ticker: str, features: dict, regime: str, factors: dict,
                      spec: dict, agent_result: dict, monte_carlo: dict, world_state: dict) -> dict:
        """Sinyalleri füzyonla."""
        fused_signal = {}
        try:
            sf = self._services.get("signal_fusion")
            if not sf:
                return fused_signal

            fund_score = 50.0
            if factors and isinstance(factors, dict):
                fund_score = factors.get("composite_score", factors.get("financial_score", 50))
            elif features.get("fundamental_score"):
                fund_score = float(features["fundamental_score"])
            fund_dir = "LONG" if fund_score > 55 else ("SHORT" if fund_score < 45 else "NEUTRAL")

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

            val_score = 50.0
            if spec and isinstance(spec, dict):
                val_score = spec.get("spec_score", 50)
            elif features.get("pe_ratio"):
                pe = float(features["pe_ratio"])
                val_score = max(0, min(100, 80 - pe * 2))
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
        return fused_signal

    def _make_decision(self, ticker: str, prices, features: dict, fused_signal: dict,
                       agent_result: dict, regime: str, monte_carlo: dict, forecast: dict,
                       spec: dict, world_state: dict) -> dict:
        """Karar motorunu çalıştır."""
        decision = {}
        try:
            de = self._services.get("decision_engine")
            if not de:
                return decision
            from services.core.decision_engine import DecisionInput
            inp = DecisionInput(
                ticker=ticker,
                price=float(prices[-1]) if len(prices) > 0 else 0,
                features=features,
                ml_score=fused_signal.get("fused_score", 50),
                ml_confidence=fused_signal.get("fused_confidence", 0.5),
                atr=features.get("atr_14", 0),
                atr_pct=features.get("atr_pct", 0),
                agent_direction=agent_result.get("direction", "NEUTRAL"),
                agent_confidence=agent_result.get("confidence", 0.0),
                agent_score=agent_result.get("score", 50.0),
                macro_regime=regime,
                macro_stance=1.0 if regime in ("BULL", "RECOVERY") else (-1.0 if regime in ("BEAR", "CRASH") else 0.0),
                macro_confidence=0.7 if regime != "UNKNOWN" else 0.3,
                macro_impact=features.get("macro_cumulative_impact", 0),
                sim_var_95=monte_carlo.get("var_95", 0),
                sim_expected_return=monte_carlo.get("expected_return", 0),
                sim_prob_positive=monte_carlo.get("prob_positive", 0),
                ml_return_5d=forecast.get("predicted_return", 0) if forecast.get("horizon_days", 0) == 5 else 0,
                ml_return_20d=forecast.get("predicted_return", 0) if forecast.get("horizon_days", 0) == 20 else 0,
                spec_score=spec.get("spec_score", 50) if isinstance(spec, dict) else 50,
                world_alignment=world_state.get("global_risk_appetite", 0.5) if isinstance(world_state, dict) else 0.5,
            )
            d = de.decide(inp)
            decision = d.__dict__ if hasattr(d, "__dict__") else {}

            if not decision.get("llm_narrative"):
                try:
                    from services.intelligence.llm_agent import llm_agent
                    decision["llm_narrative"] = llm_agent.generate_decision_narrative(
                        ticker=ticker,
                        decision=decision,
                        features=features,
                        price=float(prices[-1]) if len(prices) > 0 else 0,
                    )
                except Exception as exc:
                    logger.debug("LLM narrative skipped", ticker=ticker, error=str(exc))

            try:
                eb = self._services.get("event_bus")
                if eb and decision.get("action"):
                    from services.core.event_schema import CanonicalEvent
                    from services.core.event_schema import EventType as ET
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
                    with contextlib.suppress(RuntimeError):
                        _publish_event_async(dec_event, key=ticker)
            except Exception as e:
                logger.debug("decision_event_publish_failed", ticker=ticker, error=str(e))
        except ImportError:
            logger.debug("Optional import not available in _make_decision", exc_info=True)
        except Exception as e:
            logger.warning("Pipeline step failed", step="decision", error=str(e))
        return decision

    def _apply_learning_feedback(self, decision: dict, regime: str) -> None:
        """Öğrenme geri bildirimini uygula (in-place)."""
        try:
            ls = self._services.get("learning")
            if ls and hasattr(ls, 'get_regime_accuracy'):
                regime_acc = ls.get_regime_accuracy(regime)
                if regime_acc and regime_acc < 0.4 and decision.get("confidence", 0) > 0:
                    decision["confidence"] = decision["confidence"] * 0.8
                    decision["learning_adjustment"] = f"Low regime accuracy ({regime_acc:.2f})"
        except Exception as e:
            logger.debug("learning_feedback_failed", error=str(e))

    def _create_trade_plan(self, ticker: str, decision: dict, prices, features: dict, spec: dict) -> dict:
        """İşlem planı oluştur."""
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
        return trade_plan

    def _check_risk(self, ticker: str, decision: dict, trade_plan: dict, prices,
                    fused_signal: dict, monte_carlo: dict) -> dict:
        """Risk kontrolü yap."""
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
        return risk_check

    def _check_compliance(self, ticker: str, decision: dict, trade_plan: dict, prices) -> dict:
        """SPK uyumluluk kontrolü."""
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
        return compliance

    def _build_context(self) -> dict:
        """Bilgi grafiği ve araştırma belleği bağlamını oluştur."""
        context = {}
        try:
            kg = self._services.get("knowledge_graph")
            if kg:
                context["knowledge"] = "available"
            rm = self._services.get("research_memory")
            if rm:
                context["memory"] = "available"
        except Exception as e:
            logger.warning("Pipeline step failed", step="knowledge_graph", error=str(e))
        return context

    def _record_prediction(self, ticker: str, decision: dict, features: dict) -> None:
        """Tahmin sonucunu öğrenme sistemine kaydet."""
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
                logger.debug("Prediction recorded", ticker=ticker, action=decision.get("action"))
        except Exception as e:
            logger.debug("Learning prediction recording skipped", error=str(e))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PIPELINE ORKESTRASYONU
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def run_pipeline(self, ticker: str, market_data: dict[str, Any]) -> dict[str, Any]:
        """Tek hisse için tam pipeline çalıştır.

        Args:
            ticker: Hisse kodu
            market_data: {
                "prices": np.ndarray, "highs": np.ndarray, "lows": np.ndarray,
                "closes": np.ndarray, "volumes": np.ndarray,
                "fundamentals": dict, "news": list, "macro": dict
            }
        """
        if not self._initialized:
            try:
                asyncio.run(self.initialize())
            except RuntimeError:
                logger.warning("Runtime error in run_pipeline", exc_info=True)

        result = {"ticker": ticker, "timestamp": datetime.now(UTC).isoformat()}
        sector_map = market_data.get("sector_map", {})

        # 1. Veri hazırlama
        raw_prices, prices, error = self._prepare_prices(market_data)
        if error:
            result["error"] = error
            return result

        # 2. Özellik hesaplama
        features = self._compute_features(ticker, market_data, raw_prices)
        self._compute_macro_features(features, market_data, ticker)
        self._compute_news_sentiment(features, market_data, ticker)
        result["features"] = features

        # 3. Dünya durumu ve rejim
        world_state = self._compute_world_state()
        result["world_state"] = world_state
        regime = self._detect_regime(features)
        result["regime"] = regime

        # 4. Analiz motorları
        result["analysis"] = self._run_analysis_engines(features)

        # 5. Tahmin ve simülasyon
        forecast = self._compute_forecast(ticker, features, prices)
        result["forecast"] = forecast
        monte_carlo = self._run_monte_carlo(ticker, prices, features)
        result["monte_carlo"] = monte_carlo
        result["intelligence_pipeline"] = self._run_intelligence_pipeline(ticker, features, regime)

        # 6. Spec ve faktörler
        spec = self._compute_spec(ticker, features, world_state)
        result["spec"] = spec
        factors = self._compute_factors(market_data)
        result["factors"] = factors

        # 7. Agent pipeline
        agent_result = self._run_agent_pipeline(ticker, features, sector_map, regime, prices)
        result["agent"] = agent_result
        self._publish_agent_event(ticker, agent_result)

        # 8. Sinyal füzyonu ve karar
        fused_signal = self._fuse_signals(ticker, features, regime, factors, spec, agent_result, monte_carlo, world_state)
        result["signal"] = fused_signal
        decision = self._make_decision(ticker, prices, features, fused_signal, agent_result, regime, monte_carlo, forecast, spec, world_state)
        self._apply_learning_feedback(decision, regime)
        result["decision"] = decision

        # 9. İşlem planı ve risk
        trade_plan = self._create_trade_plan(ticker, decision, prices, features, spec)
        result["trade_plan"] = trade_plan
        result["risk"] = self._check_risk(ticker, decision, trade_plan, prices, fused_signal, monte_carlo)
        result["compliance"] = self._check_compliance(ticker, decision, trade_plan, prices)

        # 10. Bağlam ve öğrenme
        result["context"] = self._build_context()
        self._record_prediction(ticker, decision, features)

        return result

    def run_full_pipeline(
        self,
        date: str,
        market_data: dict[str, Any],
        sector_map: dict[str, str] | None = None,
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
        per_ticker_results: dict[str, Any] = {}
        errors: list[str] = []

        # === MACRO PIPELINE (YENİ) ===
        macro_analysis = {}
        try:
            from services.features.macro import macro_feature_engine
            from services.macro import (
                macro_impact_analyzer,
                macro_regime_detector,
            )

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
        except Exception as e:
            logger.debug("macro_factor_decomposition_failed", error=str(e))

        # Macro correlation tracker (audit #21)
        try:
            from services.macro.correlation_tracker import MacroCorrelationTracker
            mct = MacroCorrelationTracker()
            if hasattr(mct, 'get_current_regime'):
                corr_regime = mct.get_current_regime()
                macro_analysis["correlation_regime"] = corr_regime
        except Exception as e:
            logger.debug("macro_correlation_tracker_failed", error=str(e))

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
                        agent_res = self._run_agent_async(
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
        if total == 0 or failed == total:
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
        except Exception as e:
            learning_status = {"status": "unavailable"}
            logger.debug("learning_status_check_failed", error=str(e))

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

    def get_status(self) -> dict[str, Any]:
        """Sistem durumu."""
        return {
            "initialized": self._initialized,
            "services_loaded": len(self._services),
            "services": list(self._services.keys()),
        }

    def export_daily_report_json(self, date: str) -> str:
        """Günlük pipeline raporunu JSON olarak dışa aktar."""
        import orjson as _json
        report = {
            "date": date,
            "status": self.get_status(),
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        return _json.dumps(report, indent=2, ensure_ascii=False)

    def get_pipeline_stats(self) -> dict[str, Any]:
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
