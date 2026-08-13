"""ALPHA BIST - Portfolio Service v1.1

v1.1: market.tick handler ile canlı mark-to-market.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_execute, pg_fetchval,
    redis_get, redis_set, redis_hgetall,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class PortfolioService:
    """Portfolio management with live mark-to-market."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._position_cache: Dict[str, Dict] = {}  # ticker -> position data

    async def start(self):
        """Start the portfolio service."""
        setup_logging()
        logger.info("Starting Portfolio Service")

        await init_databases()
        ensure_topics()
        await self._ensure_default_portfolio()
        await self._load_positions()

        self._running = True

        # Event consumer — hem order.fill hem market.tick dinle
        self._consumer = EventConsumer(
            group_id="portfolio",
            topics=["order.filled", "market.tick", "market_state.changed"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.ORDER_FILLED, self._on_order_filled)
        self._consumer.on("market.tick", self._on_market_tick)

        logger.info("Portfolio Service started")
        await self._consumer.consume_loop()

    async def stop(self):
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Portfolio Service stopped")

    async def _ensure_default_portfolio(self):
        existing = await pg_fetchval(
            "SELECT id FROM portfolios WHERE name = 'ALPHA Paper Portfolio' LIMIT 1"
        )
        if not existing:
            await pg_execute("""
                INSERT INTO portfolios (name, description, initial_capital, current_capital, cash_balance, is_paper)
                VALUES ('ALPHA Paper Portfolio', 'Default paper trading portfolio', 100000, 100000, 100000, TRUE)
            """)
            logger.info("Default paper portfolio created")

    async def _load_positions(self):
        """Pozisyonları cache'e yükle."""
        try:
            rows = await pg_fetch("""
                SELECT p.*, i.symbol as ticker
                FROM positions p
                JOIN instruments i ON p.instrument_id = i.id
                WHERE p.status = 'OPEN'
            """)
            for row in rows:
                ticker = row["ticker"]
                self._position_cache[ticker] = {
                    "id": row["id"],
                    "quantity": row["quantity"],
                    "avg_cost": float(row["avg_cost"]),
                    "current_price": float(row.get("current_price") or row["avg_cost"]),
                }
            logger.info("Positions loaded", count=len(self._position_cache))
        except Exception as e:
            logger.warning("Could not load positions", error=str(e))

    # =====================================================
    # Market Tick Handler — CANLI MARK-TO-MARKET
    # =====================================================

    async def _on_market_tick(self, event: CanonicalEvent):
        """
        Her fiyat değişiminde pozisyonları güncelle.
        Bu sayede portfolio her an gerçek değeri gösterir.
        """
        try:
            ticker = event.data.get("ticker")
            price = event.data.get("price", 0)

            if not ticker or not price or ticker not in self._position_cache:
                return

            pos = self._position_cache[ticker]
            pos["current_price"] = price

            # P&L hesapla
            unrealized_pnl = (price - pos["avg_cost"]) * pos["quantity"]
            unrealized_pnl_pct = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0

            # Redis'e yaz (dashboard için)
            await redis_hset(f"position:{ticker}", {
                "current_price": str(price),
                "unrealized_pnl": str(round(unrealized_pnl, 2)),
                "unrealized_pnl_pct": str(round(unrealized_pnl_pct, 2)),
                "last_update": datetime.utcnow().isoformat(),
            })

        except Exception as e:
            logger.error("Mark-to-market error", error=str(e))

    async def _on_order_filled(self, event: CanonicalEvent):
        """İşlem gerçekleştiğinde pozisyon güncelle."""
        try:
            order_id = event.data.get("order_id")
            instrument_id = event.data.get("instrument_id")
            ticker = event.data.get("ticker", "")
            side = event.data.get("side")
            quantity = event.data.get("quantity", 0)
            price = event.data.get("price", 0)
            portfolio_id = event.data.get("portfolio_id", 1)

            if side == "BUY":
                await self._handle_buy(portfolio_id, instrument_id, ticker, quantity, price)
            elif side == "SELL":
                await self._handle_sell(portfolio_id, instrument_id, ticker, quantity, price)

            await self._update_portfolio_totals(portfolio_id)

        except Exception as e:
            logger.error("Order fill handling error", error=str(e))

    async def _handle_buy(self, portfolio_id, instrument_id, ticker, quantity, price):
        cost = quantity * price
        commission = cost * 0.001

        await pg_execute("UPDATE portfolios SET cash_balance = cash_balance - $1 WHERE id = $2", cost + commission, portfolio_id)

        existing = await pg_fetchrow("""
            SELECT id, quantity, avg_cost FROM positions
            WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
        """, portfolio_id, instrument_id)

        if existing:
            new_qty = existing["quantity"] + quantity
            new_avg = (existing["quantity"] * existing["avg_cost"] + cost) / new_qty
            await pg_execute("UPDATE positions SET quantity = $1, avg_cost = $2, updated_at = NOW() WHERE id = $3",
                           new_qty, new_avg, existing["id"])
        else:
            await pg_execute("""
                INSERT INTO positions (portfolio_id, instrument_id, quantity, avg_cost, current_price, entry_date, status)
                VALUES ($1, $2, $3, $4, $4, NOW(), 'OPEN')
            """, portfolio_id, instrument_id, quantity, price)

        # Cache güncelle
        self._position_cache[ticker] = {
            "quantity": quantity if ticker not in self._position_cache else self._position_cache.get(ticker, {}).get("quantity", 0) + quantity,
            "avg_cost": price,
            "current_price": price,
        }

        logger.info("Buy filled", ticker=ticker, qty=quantity, price=price)

    async def _handle_sell(self, portfolio_id, instrument_id, ticker, quantity, price):
        revenue = quantity * price
        commission = revenue * 0.001

        await pg_execute("UPDATE portfolios SET cash_balance = cash_balance + $1 WHERE id = $2", revenue - commission, portfolio_id)

        existing = await pg_fetchrow("""
            SELECT id, quantity FROM positions
            WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
        """, portfolio_id, instrument_id)

        if existing:
            new_qty = existing["quantity"] - quantity
            if new_qty <= 0:
                await pg_execute("UPDATE positions SET quantity = 0, status = 'CLOSED', updated_at = NOW() WHERE id = $1", existing["id"])
                self._position_cache.pop(ticker, None)
            else:
                await pg_execute("UPDATE positions SET quantity = $1, updated_at = NOW() WHERE id = $2", new_qty, existing["id"])
                if ticker in self._position_cache:
                    self._position_cache[ticker]["quantity"] = new_qty

        logger.info("Sell filled", ticker=ticker, qty=quantity, price=price)

    async def _update_portfolio_totals(self, portfolio_id):
        positions = await pg_fetch("""
            SELECT quantity, avg_cost, current_price FROM positions
            WHERE portfolio_id = $1 AND status = 'OPEN'
        """, portfolio_id)

        invested = sum(float(p["quantity"]) * float(p.get("current_price") or p["avg_cost"]) for p in positions)
        pnl = sum(float(p["quantity"]) * (float(p.get("current_price") or p["avg_cost"]) - float(p["avg_cost"])) for p in positions)

        portfolio = await pg_fetchrow("SELECT initial_capital, cash_balance FROM portfolios WHERE id = $1", portfolio_id)
        if portfolio:
            total = float(portfolio["cash_balance"]) + invested
            return_pct = (total / float(portfolio["initial_capital"]) - 1) * 100

            await pg_execute("""
                UPDATE portfolios SET invested_value = $1, total_pnl = $2, total_return_pct = $3, current_capital = $4, updated_at = NOW()
                WHERE id = $5
            """, invested, pnl, return_pct, total, portfolio_id)


async def main():
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
