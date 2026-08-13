"""ALPHA BIST - Market State Engine (Main Entry Point)"""

import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, get_pg_pool,
    ch_insert, ch_execute, redis_get, redis_set,
    redis_hgetall, redis_hset,
)
from ..core.event_bus import (
    ensure_topics, AlphaEvent, EventType,
    EventConsumer, publish_event, flush_producer,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class MarketStateService:
    """Computes overall market state and regime detection."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._instrument_states: Dict[int, Dict] = {}  # instrument_id -> state
        self._ticker_map: Dict[str, int] = {}  # ticker -> instrument_id
        self._current_regime: str = "UNKNOWN"
        self._last_update: Optional[datetime] = None

    async def start(self):
        """Start the market state service."""
        setup_logging()
        logger.info("Starting Market State Service")

        await init_databases()
        ensure_topics()

        # Load instrument map
        await self._load_instruments()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="market-state",
            topics=["feature.updated", "market.tick"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.FEATURE_UPDATED, self._on_feature_update)
        self._consumer.on(EventType.MARKET_TICK, self._on_tick)

        logger.info("Market State Service started", instruments=len(self._ticker_map))
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the market state service."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Market State Service stopped")

    async def _load_instruments(self):
        """Load instrument mapping."""
        from ..core.database import pg_fetch

        rows = await pg_fetch("""
            SELECT i.symbol, i.id FROM instruments i WHERE i.active = TRUE
        """)
        self._ticker_map = {row["symbol"]: row["id"] for row in rows}

    async def _on_tick(self, event: AlphaEvent):
        """Handle tick events for real-time state updates."""
        try:
            ticker = event.data.get("ticker")
            price = event.data.get("price", 0)
            volume = event.data.get("volume", 0)

            if not ticker or not price:
                return

            instrument_id = self._ticker_map.get(ticker)
            if not instrument_id:
                return

            # Update instrument state
            if instrument_id not in self._instrument_states:
                self._instrument_states[instrument_id] = {
                    "ticker": ticker,
                    "price": 0,
                    "previous_price": 0,
                    "volume": 0,
                    "change_pct": 0,
                }

            state = self._instrument_states[instrument_id]
            state["previous_price"] = state["price"]
            state["price"] = price
            state["volume"] = volume
            state["last_update"] = event.timestamp.isoformat()

            if state["previous_price"] > 0:
                state["change_pct"] = (price / state["previous_price"] - 1) * 100

        except Exception as e:
            logger.error("Tick processing error", error=str(e))

    async def _on_feature_update(self, event: AlphaEvent):
        """Handle feature updates to recompute market state."""
        try:
            ticker = event.data.get("ticker")
            features = event.data.get("features", {})

            if not ticker or not features:
                return

            instrument_id = self._ticker_map.get(ticker)
            if not instrument_id:
                return

            # Update instrument state with features
            if instrument_id in self._instrument_states:
                self._instrument_states[instrument_id].update({
                    "rsi": features.get("rsi_14", 50),
                    "momentum": features.get("momentum_20d", 0),
                    "volatility": features.get("realized_vol_20d", 0),
                    "volume_zscore": features.get("volume_zscore", 0),
                    "anomaly_score": features.get("anomaly_score", 0),
                })

            # Recompute market state periodically
            now = datetime.utcnow()
            if self._last_update is None or (now - self._last_update).seconds > 30:
                await self._compute_market_state()
                self._last_update = now

        except Exception as e:
            logger.error("Feature update processing error", error=str(e))

    async def _compute_market_state(self):
        """Compute overall market state from all instrument states."""
        if not self._instrument_states:
            return

        try:
            states = list(self._instrument_states.values())

            # Market breadth
            advancing = sum(1 for s in states if s.get("change_pct", 0) > 0)
            declining = sum(1 for s in states if s.get("change_pct", 0) < 0)
            total = len(states)

            breadth_pct = (advancing / total * 100) if total > 0 else 50

            # Average momentum
            momentums = [s.get("momentum", 0) for s in states if s.get("momentum")]
            avg_momentum = np.mean(momentums) if momentums else 0

            # Average volatility
            volatilities = [s.get("volatility", 0) for s in states if s.get("volatility")]
            avg_volatility = np.mean(volatilities) if volatilities else 0

            # Average RSI
            rsis = [s.get("rsi", 50) for s in states if s.get("rsi")]
            avg_rsi = np.mean(rsis) if rsis else 50

            # Anomaly count
            anomaly_count = sum(1 for s in states if s.get("anomaly_score", 0) > 0.7)

            # Regime detection
            regime = self._detect_regime(breadth_pct, avg_momentum, avg_volatility, avg_rsi)

            # Market state
            market_state = {
                "timestamp": datetime.utcnow().isoformat(),
                "regime": regime,
                "breadth_pct": round(breadth_pct, 2),
                "advancing": advancing,
                "declining": declining,
                "total_instruments": total,
                "avg_momentum": round(avg_momentum, 4),
                "avg_volatility": round(avg_volatility, 4),
                "avg_rsi": round(avg_rsi, 2),
                "anomaly_count": anomaly_count,
                "risk_appetite": round(breadth_pct / 100, 4),
            }

            # Store in Redis
            await redis_set("market_state", str(market_state), ex=60)

            # Store in ClickHouse
            ch_insert("market_states", [[
                datetime.utcnow(),
                regime,
                0.8,  # confidence
                float(avg_momentum),
                float(breadth_pct),
                float(avg_volatility),
                "NORMAL",
                float(breadth_pct / 100),
                {},
            ]], column_names=[
                "timestamp", "regime", "regime_confidence", "trend_score",
                "breadth_pct", "volatility_regime", "liquidity_level",
                "risk_appetite", "details",
            ])

            # Publish market state change event
            if regime != self._current_regime:
                old_regime = self._current_regime
                self._current_regime = regime

                event = AlphaEvent(
                    event_type=EventType.MARKET_STATE_CHANGED,
                    source="market-state",
                    data={
                        "old_regime": old_regime,
                        "new_regime": regime,
                        "market_state": market_state,
                    },
                )
                publish_event(event, key="market")
                logger.info("Market regime changed", old=old_regime, new=regime)

        except Exception as e:
            logger.error("Market state computation error", error=str(e))

    def _detect_regime(self, breadth: float, momentum: float, volatility: float, rsi: float) -> str:
        """Detect current market regime."""
        # Panic
        if breadth < 20 and volatility > 0.03:
            return "PANIC"

        # Risk-off
        if breadth < 35:
            return "RISK-OFF"

        # High volatility
        if volatility > 0.025:
            return "HIGH-VOLATILITY"

        # Trending up
        if breadth > 65 and momentum > 0:
            return "TRENDING-UP"

        # Momentum expansion
        if breadth > 70 and rsi > 60:
            return "MOMENTUM-EXPANSION"

        # Trending down
        if breadth < 40 and momentum < 0:
            return "TRENDING-DOWN"

        # Recovery
        if 45 < breadth < 55 and momentum > 0:
            return "RECOVERY"

        # Low volatility
        if volatility < 0.01:
            return "LOW-VOLATILITY"

        # Default
        return "RANGE"


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the market state service."""
    service = MarketStateService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Market State Service crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
