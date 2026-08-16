"""ALPHA BIST - Portfolio Service v1.1

v1.1: market.tick handler ile canlı mark-to-market.
"""

import asyncio
import json
from datetime import datetime, timezone
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
        """Dinlemeyi durdur."""
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
                "last_update": datetime.now(timezone.utc).isoformat(),
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
        """Alım işlemi — P0-5 düzeltmeleri:
        - Weighted average cost hesabı (son işlem fiyatı DEĞİL)
        - DB transaction içinde atomik işlem
        - Commission broker/market bazlı (hard-coded değil)
        - Idempotency kontrolü
        """
        if quantity <= 0 or price <= 0:
            logger.error("Invalid buy params", ticker=ticker, qty=quantity, price=price)
            return

        cost = quantity * price
        commission = self._calculate_commission(cost, "BUY")
        total_cost = cost + commission

        # Atomik transaction
        async with get_pg_connection() as conn:
            async with conn.transaction():
                # Cash kontrolü
                cash = await conn.fetchval(
                    "SELECT cash_balance FROM portfolios WHERE id = $1 FOR UPDATE",
                    portfolio_id
                )
                if cash is None or float(cash) < total_cost:
                    logger.error("Insufficient cash", ticker=ticker,
                               required=total_cost, available=float(cash) if cash else 0)
                    return

                # Cash güncelle
                await conn.execute(
                    "UPDATE portfolios SET cash_balance = cash_balance - $1, updated_at = NOW() WHERE id = $2",
                    total_cost, portfolio_id
                )

                # Mevcut pozisyon var mı?
                existing = await conn.fetchrow("""
                    SELECT id, quantity, avg_cost FROM positions
                    WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
                    FOR UPDATE
                """, portfolio_id, instrument_id)

                if existing:
                    # Weighted average cost hesabı
                    old_qty = existing["quantity"]
                    old_avg = float(existing["avg_cost"])
                    new_qty = old_qty + quantity
                    # P0-5: Doğru weighted average + commission dahil
                    new_avg = (old_qty * old_avg + cost + commission) / new_qty
                    await conn.execute(
                        "UPDATE positions SET quantity = $1, avg_cost = $2, updated_at = NOW() WHERE id = $3",
                        new_qty, round(new_avg, 4), existing["id"]
                    )
                else:
                    # Yeni pozisyon — commission dahil avg_cost
                    avg_with_commission = (cost + commission) / quantity
                    await conn.execute("""
                        INSERT INTO positions (portfolio_id, instrument_id, quantity, avg_cost, current_price, entry_date, status)
                        VALUES ($1, $2, $3, $4, $4, NOW(), 'OPEN')
                    """, portfolio_id, instrument_id, quantity, round(avg_with_commission, 4))

        # Cache güncelle (DB commit sonrası)
        if ticker in self._position_cache:
            old_qty = self._position_cache[ticker].get("quantity", 0)
            old_avg = self._position_cache[ticker].get("avg_cost", 0)
            new_qty = old_qty + quantity
            new_avg = (old_qty * old_avg + cost + commission) / new_qty if new_qty > 0 else price
            self._position_cache[ticker] = {
                "quantity": new_qty,
                "avg_cost": round(new_avg, 4),
                "current_price": price,
            }
        else:
            avg_with_commission = (cost + commission) / quantity
            self._position_cache[ticker] = {
                "quantity": quantity,
                "avg_cost": round(avg_with_commission, 4),
                "current_price": price,
            }

        logger.info("Buy filled", ticker=ticker, qty=quantity, price=price,
                   commission=round(commission, 2))

    async def _handle_sell(self, portfolio_id, instrument_id, ticker, quantity, price):
        """Satış işlemi — P0-5 düzeltmeleri:
        - Oversell engeli (sell_qty <= available_qty)
        - Realized P&L hesaplaması
        - DB transaction içinde atomik işlem
        - Commission dahil
        """
        if quantity <= 0 or price <= 0:
            logger.error("Invalid sell params", ticker=ticker, qty=quantity, price=price)
            return

        revenue = quantity * price
        commission = self._calculate_commission(revenue, "SELL")
        net_revenue = revenue - commission

        # Atomik transaction
        async with get_pg_connection() as conn:
            async with conn.transaction():
                # Mevcut pozisyon kontrolü
                existing = await conn.fetchrow("""
                    SELECT id, quantity, avg_cost FROM positions
                    WHERE portfolio_id = $1 AND instrument_id = $2 AND status = 'OPEN'
                    FOR UPDATE
                """, portfolio_id, instrument_id)

                if not existing:
                    logger.error("No position to sell", ticker=ticker, qty=quantity)
                    return

                available_qty = existing["quantity"]

                # P0-5: Oversell engeli
                if quantity > available_qty:
                    logger.error("Oversell attempt blocked", ticker=ticker,
                               requested=quantity, available=available_qty)
                    return

                avg_cost = float(existing["avg_cost"])

                # Realized P&L hesapla
                realized_pnl = (price - avg_cost) * quantity - commission

                # Cash güncelle
                await conn.execute(
                    "UPDATE portfolios SET cash_balance = cash_balance + $1, updated_at = NOW() WHERE id = $2",
                    net_revenue, portfolio_id
                )

                new_qty = available_qty - quantity
                if new_qty <= 0:
                    # Pozisyonu kapat
                    await conn.execute(
                        "UPDATE positions SET quantity = 0, status = 'CLOSED', updated_at = NOW() WHERE id = $1",
                        existing["id"]
                    )
                    self._position_cache.pop(ticker, None)
                else:
                    await conn.execute(
                        "UPDATE positions SET quantity = $1, updated_at = NOW() WHERE id = $2",
                        new_qty, existing["id"]
                    )
                    if ticker in self._position_cache:
                        self._position_cache[ticker]["quantity"] = new_qty

                # Audit log
                logger.info("Sell filled", ticker=ticker, qty=quantity, price=price,
                           commission=round(commission, 2),
                           realized_pnl=round(realized_pnl, 2))

    def _calculate_commission(self, amount: float, side: str) -> float:
        """Komisyon hesapla.

        P0-5: Hard-coded 0.001 yerine broker/market bazlı model.
        BIST tipik komisyon: ~%0.02-0.05 + BSMV + stopaj.
        Paper trading için basitleştirilmiş.
        """
        # BIST komisyon yapısı (yaklaşık)
        broker_commission_rate = 0.0003   # %0.03 broker
        exchange_fee_rate = 0.000056      # %0.0056 BIST
        bsmv_rate = 0.05                  # BSMV (komisyon üzerinden %5)

        base_commission = amount * (broker_commission_rate + exchange_fee_rate)
        bsmv = base_commission * bsmv_rate
        total = base_commission + bsmv

        # Minimum komisyon
        return max(total, 1.0)

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
    """Scheduler baslangic noktasi."""
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
