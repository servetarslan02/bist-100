"""ALPHA BIST — Market State Engine v2.0 (Main Entry Point)

Tüm bileşenleri orkestre eden ana servis:
- MarketBreadthEngine: 7 breadth göstergesi
- ComponentStateEngine: 8 bileşen state
- EnsembleRegimeDetector: 3 yöntem ensemble
- RegimeTransitionTracker: Geçiş takibi
- RiskAppetiteEngine: 6 faktörlü risk appetite
- MultiTimeframeEngine: Çoklu zaman ufku
- MarketStateFormatter: Standart output

v2.0 Değişiklikleri:
- Canonical regime detection (tek kaynak)
- Breadth engine (7 gösterge)
- Ensemble regime (HMM + Skor + GMM)
- Liquidity + Sentiment state
- Transition tracking
- Multi-timeframe
- 6 faktörlü risk appetite
"""

import asyncio
from datetime import UTC, datetime

import numpy as np
import orjson
import structlog

from ..core.config import settings
from ..core.database import (
    ch_insert,
    close_databases,
    init_databases,
    redis_set,
)
from ..core.event_bus import (
    EventConsumer,
    ensure_topics,
    publish_event,
)
from ..core.event_schema import CanonicalEvent, EventType
from ..core.logging import setup_logging

# Market State v2.0 modülleri
from .breadth_engine import BreadthResult, MarketBreadthEngine
from .component_states import ComponentStateEngine, ComponentStates
from .ensemble_regime import EnsembleRegimeDetector, EnsembleResult
from .monitoring import market_state_monitor
from .multi_timeframe import MultiTimeframeEngine, MultiTimeframeResult
from .output_formatter import MarketStateFormatter, MarketStateOutput
from .risk_appetite import RiskAppetiteEngine
from .transition_tracker import RegimeTransitionTracker

logger = structlog.get_logger()


class MarketStateService:
    """Market State Engine v2.0 — tüm bileşenleri orkestre eder.

    Pipeline:
    1. Data inputs (ticks, features, macro, news)
    2. Market Breadth Engine (7 gösterge)
    3. Component States (8 state)
    4. Ensemble Regime Detection (3 yöntem)
    5. Transition Tracking
    6. Risk Appetite (6 faktör)
    7. Multi-Timeframe
    8. Output (MarketStateOutput)
    9. Event publish (market_state.changed)
    """

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None

        # Instrument states
        self._instrument_states: dict[int, dict] = {}
        self._ticker_map: dict[str, int] = {}

        # v2.0 Engines
        self._breadth_engine = MarketBreadthEngine(
            mcclellan_short_ema=settings.breadth_mcclellan_ema_short,
            mcclellan_long_ema=settings.breadth_mcclellan_ema_long,
            thrust_threshold=settings.breadth_thrust_threshold,
            volume_min=settings.breadth_liquidity_volume_min,
        )
        self._component_engine = ComponentStateEngine()
        self._ensemble_detector = EnsembleRegimeDetector(
            score_weight=settings.regime_score_weight,
            hmm_weight=settings.regime_hmm_weight,
            gmm_weight=settings.regime_gmm_weight,
            rolling_window=settings.regime_rolling_window,
        )
        self._transition_tracker = RegimeTransitionTracker(
            stability_window=settings.regime_transition_stability_window,
        )
        self._risk_appetite = RiskAppetiteEngine(
            breadth_weight=settings.risk_appetite_breadth_weight,
            momentum_weight=settings.risk_appetite_momentum_weight,
            volatility_weight=settings.risk_appetite_volatility_weight,
            rsi_weight=settings.risk_appetite_rsi_weight,
            sentiment_weight=settings.risk_appetite_sentiment_weight,
            macro_weight=settings.risk_appetite_macro_weight,
        )
        self._multi_tf = MultiTimeframeEngine()
        self._formatter = MarketStateFormatter()

        # State
        self._current_regime: str = "UNKNOWN"
        self._last_update: datetime | None = None
        self._last_market_state: MarketStateOutput | None = None

        # HMM returns/volatility history
        self._returns_history: list[float] = []
        self._volatility_history: list[float] = []

        # World state (macro)
        self._world_state: dict[str, float] = {}

        # News sentiment
        self._news_sentiment: float = 0.0
        self._social_sentiment: float = 0.0

    async def start(self):
        """Start the market state service."""
        setup_logging()
        logger.info("Starting Market State Engine v2.0")

        await init_databases()
        ensure_topics()

        # Load instrument map
        await self._load_instruments()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="market-state-v2",
            topics=[
                "feature.updated", "market.tick",
                "world_state.changed", "news.event",
            ],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.FEATURE_UPDATED, self._on_feature_update)
        self._consumer.on(EventType.MARKET_TICK, self._on_tick)
        self._consumer.on(EventType.WORLD_STATE_CHANGED, self._on_world_state)
        self._consumer.on(EventType.NEWS_EVENT, self._on_news)

        logger.info(
            "Market State Engine v2.0 started",
            instruments=len(self._ticker_map),
            engines=["breadth", "component", "ensemble", "transition", "risk_appetite", "multi_tf"],
        )
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the market state service."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Market State Engine v2.0 stopped")

    # API getter methods
    def get_current_state(self) -> MarketStateOutput | None:
        """Mevcut market state döndür (API için)."""
        return self._last_market_state

    def get_breadth(self) -> BreadthResult | None:
        """Son breadth sonucu döndür (API için)."""
        states = list(self._instrument_states.values())
        if not states:
            return None
        return self._breadth_engine.compute(states)

    def get_ensemble_regime(self) -> EnsembleResult | None:
        """Son ensemble regime sonucu döndür (API için)."""
        if not self._instrument_states:
            return None
        states = list(self._instrument_states.values())
        features = self._build_feature_dict(
            self._breadth_engine.compute(states),
            self._component_engine.compute_all(states),
        )
        returns = np.array(self._returns_history) if self._returns_history else None
        volatility = np.array(self._volatility_history) if self._volatility_history else None
        return self._ensemble_detector.detect(features, returns, volatility)

    def get_transition_tracker(self) -> RegimeTransitionTracker | None:
        """Transition tracker'ı döndür (API için)."""
        return self._transition_tracker

    def get_multi_timeframe(self) -> MultiTimeframeResult | None:
        """Son multi-timeframe sonucu döndür (API için)."""
        if not self._instrument_states:
            return None
        states = list(self._instrument_states.values())
        features = self._build_feature_dict(
            self._breadth_engine.compute(states),
            self._component_engine.compute_all(states),
        )
        daily_data = {"instruments": states, "features": features}
        return self._multi_tf.compute_all_timeframes({"daily": daily_data})

    async def _load_instruments(self):
        """Load instrument mapping — BIST universe."""
        try:
            from ..ingestion.bist_universe import bist_universe
            tickers = bist_universe.get_tickers()
        except Exception as e:
            logger.error("Failed to load BIST universe", error=str(e))
            tickers = []

        for i, ticker in enumerate(tickers):
            self._ticker_map[ticker] = i + 1
            self._instrument_states[i + 1] = {
                "ticker": ticker,
                "price": 0,
                "previous_price": 0,
                "volume": 0,
                "change_pct": 0,
                "rsi": 50,
                "momentum": 0,
                "volatility": 0,
                "volume_zscore": 0,
                "anomaly_score": 0,
                "spread": 0,
            }

        logger.info("Instruments loaded", count=len(self._ticker_map))

    async def _on_tick(self, event: CanonicalEvent):
        """Handle tick events."""
        try:
            ticker = event.data.get("ticker")
            price = event.data.get("price", 0)
            volume = event.data.get("volume", 0)

            if not ticker or not price:
                return

            instrument_id = self._ticker_map.get(ticker)
            if not instrument_id:
                return

            state = self._instrument_states.get(instrument_id)
            if not state:
                return

            state["previous_price"] = state["price"]
            state["price"] = price
            state["volume"] = volume
            state["last_update"] = event.timestamp.isoformat()

            if state["previous_price"] > 0:
                state["change_pct"] = (price / state["previous_price"] - 1) * 100

            # Returns history (HMM için)
            if state["previous_price"] > 0:
                ret = (price / state["previous_price"]) - 1
                self._returns_history.append(ret)
                if len(self._returns_history) > 500:
                    self._returns_history = self._returns_history[-500:]

        except Exception as e:
            logger.error("Tick processing error", error=str(e))

    async def _on_feature_update(self, event: CanonicalEvent):
        """Handle feature updates."""
        try:
            ticker = event.data.get("ticker")
            features = event.data.get("features", {})

            if not ticker or not features:
                return

            instrument_id = self._ticker_map.get(ticker)
            if not instrument_id:
                return

            if instrument_id in self._instrument_states:
                self._instrument_states[instrument_id].update({
                    "rsi": features.get("rsi_14", 50),
                    "momentum": features.get("momentum_20d", 0),
                    "volatility": features.get("realized_vol_20d", 0),
                    "volume_zscore": features.get("volume_zscore", 0),
                    "anomaly_score": features.get("anomaly_score", 0),
                    "spread": features.get("spread", 0),
                })

                # Volatility history (HMM için)
                vol = features.get("realized_vol_20d", 0)
                if vol:
                    self._volatility_history.append(vol)
                    if len(self._volatility_history) > 500:
                        self._volatility_history = self._volatility_history[-500:]

            # Recompute periodically
            now = datetime.now(UTC)
            if self._last_update is None or (now - self._last_update).seconds > 30:
                await self._compute_market_state()
                self._last_update = now

        except Exception as e:
            logger.error("Feature update processing error", error=str(e))

    async def _on_world_state(self, event: CanonicalEvent):
        """Handle world state changes."""
        self._world_state = event.data.get("world_state", {})

    async def _on_news(self, event: CanonicalEvent):
        """Handle news events for sentiment."""
        sentiment = event.data.get("sentiment", 0)
        if sentiment:
            # Exponential moving average
            alpha = 0.3
            self._news_sentiment = alpha * sentiment + (1 - alpha) * self._news_sentiment

    async def _compute_market_state(self):
        """Ana hesaplama pipeline — tüm bileşenler."""
        if not self._instrument_states:
            return

        try:
            states = list(self._instrument_states.values())

            # 1. Market Breadth (döviz izolasyonu ile)
            fx_momentum = self._world_state.get("usd_strength", 0.5) * 10 - 5  # Normalize: 0-1 → -5..+5
            breadth = self._breadth_engine.compute(states, fx_momentum=fx_momentum)

            # 2. Component States (fear/greed + market depth ile)
            components = self._component_engine.compute_all(
                instrument_states=states,
                vix_level=self._world_state.get("vix_level"),
                news_sentiment=self._news_sentiment,
                social_sentiment=self._social_sentiment,
                world_state=self._world_state,
            )

            # 3. Ensemble Regime Detection
            features = self._build_feature_dict(breadth, components)
            returns = np.array(self._returns_history) if self._returns_history else None
            volatility = np.array(self._volatility_history) if self._volatility_history else None

            ensemble = self._ensemble_detector.detect(features, returns, volatility)

            # 4. Transition Tracking
            self._transition_tracker.record(ensemble.regime, ensemble.confidence)
            transition_stats = self._transition_tracker.get_stats()

            # 5. Risk Appetite
            risk_appetite = self._risk_appetite.compute(
                breadth_pct=breadth.pct_advancing,
                momentum=components.avg_momentum,
                volatility=components.avg_volatility,
                rsi=components.avg_rsi,
                sentiment_score=components.sentiment_score,
                macro_score=components.macro_score,
            )
            risk_appetite_detail = self._risk_appetite.compute_detailed(
                breadth_pct=breadth.pct_advancing,
                momentum=components.avg_momentum,
                volatility=components.avg_volatility,
                rsi=components.avg_rsi,
                sentiment_score=components.sentiment_score,
                macro_score=components.macro_score,
            )
            risk_appetite_state = risk_appetite_detail.get("state", "NEUTRAL")

            # 6. Multi-Timeframe (daily + weekly)
            weekly_instruments = self._compute_weekly_aggregate(states)
            daily_data = {"instruments": states, "features": features}
            weekly_data = {"instruments": weekly_instruments, "features": features}
            multi_tf = self._multi_tf.compute_all_timeframes({
                "daily": daily_data,
                "weekly": weekly_data,
            })

            # 7. Format output
            market_state = self._formatter.format(
                breadth=breadth,
                components=components,
                ensemble=ensemble,
                transition=transition_stats,
                risk_appetite=risk_appetite,
                risk_appetite_state=risk_appetite_state,
                multi_tf=multi_tf,
            )

            self._last_market_state = market_state

            # 8. Store in Redis
            await redis_set(
                "market_state",
                orjson.dumps(market_state.to_dict(), default=str).decode(),
                ex=60,
            )

            # 9. Store in ClickHouse
            try:
                ch_insert("market_states", [[
                    datetime.now(UTC),
                    ensemble.regime,
                    float(ensemble.confidence),
                    float(components.avg_momentum),
                    float(breadth.pct_advancing),
                    float(components.avg_volatility),
                    components.liquidity_state,
                    float(risk_appetite),
                    market_state.to_dict(),
                ]], column_names=[
                    "timestamp", "regime", "regime_confidence", "trend_score",
                    "breadth_pct", "volatility_regime", "liquidity_level",
                    "risk_appetite", "details",
                ])
            except Exception as e:
                logger.debug("ClickHouse insert failed", error=str(e))

            # 10. Publish events
            await self._publish_events(ensemble, breadth, components, transition_stats)

            # 10.5 Transition alerts
            transition_alerts = self._transition_tracker.check_alerts()
            for alert in transition_alerts:
                logger.warning("transition_alert", **alert)

            # 11. Monitoring update
            try:
                market_state_monitor.update(
                    regime=ensemble.regime,
                    confidence=ensemble.confidence,
                    consensus=ensemble.consensus,
                    stability=transition_stats.stability_score,
                    transition_count=transition_stats.total_transitions,
                    breadth_pct=breadth.pct_advancing,
                    mcclellan=breadth.mcclellan_osc,
                    trin=breadth.trin,
                    thrust=breadth.breadth_thrust,
                    risk_appetite=risk_appetite,
                    alert_count=len(transition_alerts),
                    critical_alerts=sum(1 for a in transition_alerts if a.get("severity") == "WARNING"),
                )
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="main.py:443")

            logger.info(
                "Market state computed",
                regime=ensemble.regime,
                confidence=round(ensemble.confidence, 3),
                breadth=round(breadth.pct_advancing, 1),
                risk_appetite=round(risk_appetite, 3),
                stability=round(transition_stats.stability_score, 3),
            )

            # Prometheus metrics
            try:
                from services.core.observability import prometheus_metrics
                prometheus_metrics.set_gauge("market_state_regime", 1, {"regime": ensemble.regime})
                prometheus_metrics.set_gauge("market_state_regime_confidence", ensemble.confidence)
                prometheus_metrics.set_gauge("market_state_breadth_pct", breadth.pct_advancing)
                prometheus_metrics.set_gauge("market_state_mcclellan", breadth.mcclellan_osc)
                prometheus_metrics.set_gauge("market_state_trin", breadth.trin)
                prometheus_metrics.set_gauge("market_state_risk_appetite", risk_appetite)
                prometheus_metrics.set_gauge("market_state_stability", transition_stats.stability_score)
                prometheus_metrics.set_gauge("market_state_anomaly_count", components.anomaly_count)
                prometheus_metrics.set_gauge("market_state_momentum", components.avg_momentum)
                prometheus_metrics.set_gauge("market_state_volatility", components.avg_volatility)
                prometheus_metrics.set_gauge("market_state_rsi", components.avg_rsi)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="main.py:469")

        except Exception as e:
            logger.error("Market state computation error", error=str(e), exc_info=True)

    def _build_feature_dict(
        self,
        breadth: BreadthResult,
        components: ComponentStates,
    ) -> dict[str, float]:
        """Regime engine için feature dict oluştur."""
        return {
            "breadth_pct": breadth.pct_advancing,
            "momentum_avg": components.avg_momentum,
            "volatility_avg": components.avg_volatility,
            "rsi_avg": components.avg_rsi,
            "risk_appetite": 0.5,  # Will be computed later
            "usdtry_momentum": self._world_state.get("usd_strength", 0.5) * 10,
            "vix_level": self._world_state.get("vix_level", 20),
            "global_momentum": self._world_state.get("global_risk_appetite", 0.5) * 10,
        }

    def _compute_weekly_aggregate(self, daily_states: list[dict]) -> list[dict]:
        """Günlük verilerden haftalık aggregate üret.

        Her hisse için haftalık ortalama change_pct ve momentum hesaplar.
        Basitleştirilmiş: mevcut daily veriyi haftalık gibi kullanır.
        Gerçek implementasyonda haftalık bar verisi gerekli.
        """
        # Şimdilik daily veriyi haftalık olarak kullan
        # Gerçek implementasyonda: haftalık OHLCV aggregation
        return [
            {
                "ticker": s.get("ticker", ""),
                "change_pct": s.get("change_pct", 0),
                "momentum": s.get("momentum", 0),
                "volatility": s.get("volatility", 0),
                "volume": s.get("volume", 0),
            }
            for s in daily_states
        ]

    async def _publish_events(
        self,
        ensemble: EnsembleResult,
        breadth: BreadthResult,
        components: ComponentStates,
        transition,
    ):
        """Event bus'a event publish et."""
        # Regime change
        if ensemble.regime != self._current_regime:
            old_regime = self._current_regime
            self._current_regime = ensemble.regime

            event = CanonicalEvent(
                event_type=EventType.MARKET_STATE_CHANGED,
                source="market-state-v2",
                data={
                    "old_regime": old_regime,
                    "new_regime": ensemble.regime,
                    "confidence": ensemble.confidence,
                    "consensus": ensemble.consensus,
                    "market_state": self._last_market_state.to_dict() if self._last_market_state else {},
                },
            )
            publish_event(event, key="market")

            # Regime transition event
            transition_event = CanonicalEvent(
                event_type=EventType.REGIME_TRANSITION,
                source="market-state-v2",
                data={
                    "from_regime": old_regime,
                    "to_regime": ensemble.regime,
                    "confidence": ensemble.confidence,
                    "stability": transition.stability_score,
                    "duration_days": transition.current_duration_days,
                },
            )
            publish_event(transition_event, key="regime")

        # Breadth alert
        if breadth.alert_level in ("ALERT", "CRITICAL"):
            alert_event = CanonicalEvent(
                event_type=EventType.BREADTH_ALERT,
                source="market-state-v2",
                data={
                    "alert_level": breadth.alert_level,
                    "breadth_state": breadth.breadth_state,
                    "pct_advancing": breadth.pct_advancing,
                    "mcclellan": breadth.mcclellan_osc,
                    "trin": breadth.trin,
                },
            )
            publish_event(alert_event, key="breadth")

        # Liquidity alert
        if components.liquidity_state == "TIGHT":
            liq_event = CanonicalEvent(
                event_type=EventType.LIQUIDITY_ALERT,
                source="market-state-v2",
                data={
                    "liquidity_state": components.liquidity_state,
                    "avg_spread": components.avg_spread,
                },
            )
            publish_event(liq_event, key="liquidity")

        # Anomaly cluster
        if components.anomaly_count > 5:
            anomaly_event = CanonicalEvent(
                event_type=EventType.ANOMALY_CLUSTER,
                source="market-state-v2",
                data={
                    "anomaly_count": components.anomaly_count,
                    "anomaly_severity": components.anomaly_severity,
                },
            )
            publish_event(anomaly_event, key="anomaly")

        # Sentiment shift
        if abs(components.sentiment_score) > 0.5:
            sentiment_event = CanonicalEvent(
                event_type=EventType.SENTIMENT_SHIFT,
                source="market-state-v2",
                data={
                    "sentiment_state": components.sentiment_state,
                    "sentiment_score": components.sentiment_score,
                    "news_sentiment": self._news_sentiment,
                    "social_sentiment": self._social_sentiment,
                },
            )
            publish_event(sentiment_event, key="sentiment")

        # Multi-TF divergence
        if self._last_market_state and self._last_market_state.multi_tf_divergences:
            divergence_event = CanonicalEvent(
                event_type=EventType.MULTI_TF_DIVERGENCE,
                source="market-state-v2",
                data={
                    "divergences": self._last_market_state.multi_tf_divergences,
                    "alignment": self._last_market_state.multi_tf_alignment,
                },
            )
            publish_event(divergence_event, key="multi_tf")


# =====================================================
# Health Check HTTP Server
# =====================================================

async def _health_server(port: int = 8080):
    """Lightweight health check HTTP server for Docker healthcheck."""
    from aiohttp import web

    async def health_handler(request):
        return web.json_response({"status": "healthy", "service": "market_state"})

    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Health server started", port=port)


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the market state service."""
    await _health_server()
    service = MarketStateService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Market State Engine v2.0 crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
