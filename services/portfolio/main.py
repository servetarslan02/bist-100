"""ALPHA BIST - Portfolio Management Service"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_execute, pg_fetchval,
    redis_get, redis_set,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class PortfolioService:
    """Portfolio management, position tracking, and P&L calculation."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None

    async def start(self):
        """Start the portfolio service."""
        setup_logging()
        logger.info("Starting Portfolio Service")

        await init_databases()
        ensure_topics()

        # Ensure default portfolio exists
        await self._ensure_default_portfolio()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="portfolio",
            topics=["order.filled", "market.tick"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.ORDER_FILLED, self._on_order_filled)

        logger.info("Portfolio Service started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the portfolio service."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Portfolio Service stopped")

    async def _ensure_default_portfolio(self):
        """Create default paper portfolio if it doesn't exist."""
        existing = await pg_fetchval("""
            SELECT id FROM portfolios WHERE name = 'ALPHA Paper Portfolio' LIMIT 1
        """)

        if not existing:
            await pg_execute("""
                INSERT INTO portfolios (name, description, initial_capital, current_capital, cash_balance, is_paper)
                VALUES ('ALPHA Paper Portfolio', 'Default paper trading portfolio', 100000, 100000, 100000, TRUE)
            """)
            logger.info("Default paper portfolio created")

    async def _on_order_filled(self, event: CanonicalEvent):
        """Handle order filled events."""
        try:
            order_id = event.data.get("order_id")
            instrument_id = event.data.get("instrument_id")
            side = event.data.get("side")
            quantity = event.data.get("quantity")
            price = event.data.get("price")
            portfolio_id = event.data.get("portfolio_id")

            if side == "BUY":
                await self._handle_buy(portfolio_id, instrument_id, quantity, price)
            elif side == "SELL":
                await self._handle_sell(portfolio_id, instrument_id, quantity, price)

            # Update portfolio totals
            await self._update_portfolio_totals(portfolio_id)

        except Exception as e:
            logger.error("Order fill handling error", error=str(e))

    async def _handle_buy(self, portfolio_id: int, instrument_id: int, quantity: int, price: float):
        """Handle a buy order fill."""
        cost = quantity * price

        # Deduct from cash
        await pg_execute("""
            UPDATE portfolios SET cash_balance = cash_balance - $1 WHERE id = $2
        """, cost, portfolio_id)

        # Update or create position
        existing = await pg_fetchrow("""
            SELECT id, quantity, avg_cost FROM positions
            WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
        """, portfolio_id, instrument_id)

        if existing:
            # Update existing position
            new_qty = existing["quantity"] + quantity
            new_avg_cost = (existing["quantity"] * existing["avg_cost"] + cost) / new_qty

            await pg_execute("""
                UPDATE positions SET quantity = $1, avg_cost = $2, updated_at = NOW()
                WHERE id = $3
            """, new_qty, new_avg_cost, existing["id"])
        else:
            # Create new position
            await pg_execute("""
                INSERT INTO positions (portfolio_id, instrument_id, quantity, avg_cost, entry_date, status)
                VALUES ($1, $2, $3, $4, NOW(), 'OPEN')
            """, portfolio_id, instrument_id, quantity, price)

        logger.info("Buy filled", instrument_id=instrument_id, quantity=quantity, price=price)

    async def _handle_sell(self, portfolio_id: int, instrument_id: int, quantity: int, price: float):
        """Handle a sell order fill."""
        revenue = quantity * price

        # Add to cash
        await pg_execute("""
            UPDATE portfolios SET cash_balance = cash_balance + $1 WHERE id = $2
        """, revenue, portfolio_id)

        # Update position
        existing = await pg_fetchrow("""
            SELECT id, quantity, avg_cost FROM positions
            WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
        """, portfolio_id, instrument_id)

        if existing:
            new_qty = existing["quantity"] - quantity
            if new_qty <= 0:
                # Close position
                await pg_execute("""
                    UPDATE positions SET quantity = 0, status = 'CLOSED', updated_at = NOW()
                    WHERE id = $1
                """, existing["id"])
            else:
                await pg_execute("""
                    UPDATE positions SET quantity = $1, updated_at = NOW()
                    WHERE id = $2
                """, new_qty, existing["id"])

        logger.info("Sell filled", instrument_id=instrument_id, quantity=quantity, price=price)

    async def _update_portfolio_totals(self, portfolio_id: int):
        """Update portfolio total values."""
        # Get all open positions
        positions = await pg_fetch("""
            SELECT quantity, avg_cost, current_price
            FROM positions
            WHERE portfolio_id = $1 AND status = 'OPEN'
        """, portfolio_id)

        invested = sum(float(p["quantity"]) * float(p.get("current_price") or p["avg_cost"]) for p in positions)
        pnl = sum(float(p["quantity"]) * (float(p.get("current_price") or p["avg_cost"]) - float(p["avg_cost"])) for p in positions)

        portfolio = await pg_fetchrow("""
            SELECT initial_capital, cash_balance FROM portfolios WHERE id = $1
        """, portfolio_id)

        if portfolio:
            total = float(portfolio["cash_balance"]) + invested
            return_pct = (total / float(portfolio["initial_capital"]) - 1) * 100

            await pg_execute("""
                UPDATE portfolios SET
                    invested_value = $1,
                    total_pnl = $2,
                    total_return_pct = $3,
                    current_capital = $4,
                    updated_at = NOW()
                WHERE id = $5
            """, invested, pnl, return_pct, total, portfolio_id)


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the portfolio service."""
    service = PortfolioService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Portfolio Service crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
