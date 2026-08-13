"""ALPHA BIST - Risk Engine Service"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_execute,
    redis_get, redis_set, redis_hgetall,
)
from ..core.event_bus import (
    ensure_topics, AlphaEvent, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class RiskEngine:
    """Independent risk management engine. Operates ABOVE the AI layer."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._risk_limits: Dict[str, float] = {}
        self._portfolio_state: Dict[str, Any] = {}

    async def start(self):
        """Start the risk engine."""
        setup_logging()
        logger.info("Starting Risk Engine")

        await init_databases()
        ensure_topics()
        await self._load_risk_limits()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="risk-engine",
            topics=["decision.created", "order.placed", "signal.generated", "market_state.changed"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.DECISION_CREATED, self._on_decision)
        self._consumer.on(EventType.SIGNAL_GENERATED, self._on_signal)

        logger.info("Risk Engine started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the risk engine."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Risk Engine stopped")

    async def _load_risk_limits(self):
        """Load risk limits from database."""
        try:
            rows = await pg_fetch("""
                SELECT config_key, config_value FROM system_config
                WHERE config_key LIKE 'risk.%'
            """)
            for row in rows:
                key = row["config_key"].replace("risk.", "")
                value = row["config_value"]
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except:
                        pass
                self._risk_limits[key] = float(value) if value else 0

            logger.info("Risk limits loaded", limits=self._risk_limits)

        except Exception as e:
            logger.warning("Failed to load risk limits, using defaults", error=str(e))
            self._risk_limits = {
                "max_position_pct": 10.0,
                "max_sector_pct": 30.0,
                "max_drawdown_pct": 15.0,
                "daily_loss_limit_pct": 5.0,
                "max_correlation": 0.8,
            }

    async def _on_decision(self, event: CanonicalEvent):
        """Evaluate a trading decision against risk limits."""
        try:
            ticker = event.data.get("ticker")
            action = event.data.get("action")  # BUY/SELL
            amount = event.data.get("amount", 0)
            portfolio_id = event.data.get("portfolio_id")

            logger.info("Evaluating decision", ticker=ticker, action=action, amount=amount)

            # Risk checks
            checks = []

            # 1. Position size limit
            check = await self._check_position_limit(ticker, amount, portfolio_id)
            checks.append(check)

            # 2. Sector concentration
            check = await self._check_sector_concentration(ticker, portfolio_id)
            checks.append(check)

            # 3. Daily loss limit
            check = await self._check_daily_loss(portfolio_id)
            checks.append(check)

            # 4. Drawdown limit
            check = await self._check_drawdown(portfolio_id)
            checks.append(check)

            # Determine overall result
            all_passed = all(c["passed"] for c in checks)
            blocking_checks = [c for c in checks if not c["passed"] and c["severity"] == "BLOCK"]

            result = {
                "ticker": ticker,
                "action": action,
                "approved": all_passed and len(blocking_checks) == 0,
                "checks": checks,
                "timestamp": datetime.utcnow().isoformat(),
            }

            if not result["approved"]:
                # Publish risk alert
                alert_event = CanonicalEvent(
                    event_type=EventType.RISK_ALERT,
                    source="risk-engine",
                    data={
                        "ticker": ticker,
                        "action": action,
                        "reason": f"Blocked by: {', '.join(c['name'] for c in blocking_checks)}",
                        "checks": checks,
                    },
                )
                publish_event(alert_event, key=ticker)
                logger.warning("Decision BLOCKED by risk", ticker=ticker, checks=blocking_checks)

            # Store result
            await redis_set(f"risk_check:{ticker}", json.dumps(result), ex=300)

        except Exception as e:
            logger.error("Risk evaluation error", error=str(e))

    async def _on_signal(self, event: CanonicalEvent):
        """Evaluate signal risk."""
        try:
            ticker = event.data.get("ticker")
            score = event.data.get("score", 0)
            risk_level = event.data.get("risk_level", "MEDIUM")

            # Check if risk level is acceptable
            if risk_level == "CRITICAL":
                alert_event = CanonicalEvent(
                    event_type=EventType.RISK_ALERT,
                    source="risk-engine",
                    data={
                        "ticker": ticker,
                        "alert_type": "CRITICAL_RISK_SIGNAL",
                        "message": f"Signal generated with CRITICAL risk level: {ticker}",
                    },
                )
                publish_event(alert_event, key=ticker)

        except Exception as e:
            logger.error("Signal risk check error", error=str(e))

    async def _check_position_limit(self, ticker: str, amount: float, portfolio_id: int) -> Dict[str, Any]:
        """Check if position size exceeds limit."""
        limit = self._risk_limits.get("max_position_pct", 10.0)

        # Get portfolio value
        portfolio = await pg_fetchrow("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio:
            return {"name": "position_limit", "passed": True, "severity": "WARN"}

        portfolio_value = float(portfolio["current_capital"])
        position_pct = (amount / portfolio_value * 100) if portfolio_value > 0 else 0

        passed = position_pct <= limit

        return {
            "name": "position_limit",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Position: {position_pct:.1f}% (limit: {limit}%)",
        }

    async def _check_sector_concentration(self, ticker: str, portfolio_id: int) -> Dict[str, Any]:
        """Check sector concentration limit."""
        limit = self._risk_limits.get("max_sector_pct", 30.0)

        # Get sector for ticker
        sector = await pg_fetchval("""
            SELECT s.code FROM instruments i
            JOIN companies c ON i.company_id = c.id
            JOIN sectors s ON c.sector_id = s.id
            WHERE i.symbol = $1
        """, ticker)

        if not sector:
            return {"name": "sector_concentration", "passed": True, "severity": "WARN"}

        # Get sector exposure
        sector_exposure = await pg_fetchval("""
            SELECT COALESCE(SUM(p.market_value), 0)
            FROM positions p
            JOIN instruments i ON p.instrument_id = i.id
            JOIN companies c ON i.company_id = c.id
            JOIN sectors s ON c.sector_id = s.id
            WHERE p.portfolio_id = $1 AND s.code = $2 AND p.status = 'OPEN'
        """, portfolio_id, sector)

        portfolio_value = await pg_fetchval("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio_value:
            return {"name": "sector_concentration", "passed": True, "severity": "WARN"}

        concentration = (float(sector_exposure) / float(portfolio_value) * 100) if portfolio_value > 0 else 0
        passed = concentration <= limit

        return {
            "name": "sector_concentration",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Sector {sector}: {concentration:.1f}% (limit: {limit}%)",
        }

    async def _check_daily_loss(self, portfolio_id: int) -> Dict[str, Any]:
        """Check daily loss limit."""
        limit = self._risk_limits.get("daily_loss_limit_pct", 5.0)

        # Get today's P&L
        daily_pnl = await pg_fetchval("""
            SELECT COALESCE(SUM(filled_quantity * avg_fill_price * CASE WHEN side = 'SELL' THEN 1 ELSE -1 END), 0)
            FROM orders
            WHERE portfolio_id = $1
            AND status = 'FILLED'
            AND DATE(filled_at) = CURRENT_DATE
        """, portfolio_id)

        portfolio_value = await pg_fetchval("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio_value:
            return {"name": "daily_loss", "passed": True, "severity": "WARN"}

        loss_pct = abs(float(daily_pnl) / float(portfolio_value) * 100) if float(daily_pnl) < 0 else 0
        passed = loss_pct <= limit

        return {
            "name": "daily_loss",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Daily loss: {loss_pct:.1f}% (limit: {limit}%)",
        }

    async def _check_drawdown(self, portfolio_id: int) -> Dict[str, Any]:
        """Check maximum drawdown limit."""
        limit = self._risk_limits.get("max_drawdown_pct", 15.0)

        portfolio = await pg_fetchrow("""
            SELECT initial_capital, current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio:
            return {"name": "drawdown", "passed": True, "severity": "WARN"}

        initial = float(portfolio["initial_capital"])
        current = float(portfolio["current_capital"])
        drawdown = ((initial - current) / initial * 100) if initial > 0 else 0

        passed = drawdown <= limit

        return {
            "name": "drawdown",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Drawdown: {drawdown:.1f}% (limit: {limit}%)",
        }


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the risk engine."""
    engine = RiskEngine()
    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()
    except Exception as e:
        logger.error("Risk Engine crashed", error=str(e))
        await engine.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
