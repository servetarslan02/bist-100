"""
ALPHA BIST — Unified Market Microstructure & Execution Engine

Borsa İstanbul Kurumsal Piyasa Mikro-Yapısı ve Eşleşme Motoru:
- Seans Durum Makinesi Entegrasyonu
- Emir Öncesi Çok Katmanlı Risk Denetimleri
- L2 Price-Time Priority (FIFO) Sürekli Müzayede
- Tek Fiyat Açık Artırması (Call Auction Equilibrium Matching)
- Kapanış Fiyatından İşlemler (Trade at Close)
- BIST Fiyat Adımları, Komisyon ve Slippage Modeli
"""

import time as _time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog

from services.core.bist_tick_size import round_to_bist_tick
from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm
from services.paper_trading.pre_trade_risk import pre_trade_risk_engine
from services.paper_trading.synthetic_liquidity import (
    LiquidityScenario,
    SyntheticOrderBookBuilder,
)
from services.simulation.auction_engine import AuctionOrder, call_auction_engine
from services.simulation.order_book import OrderBook

logger = structlog.get_logger()


class MarketMicrostructureEngine:
    """Kurumsal BIST Mikro-Yapı ve Eşleşme Motoru."""

    def __init__(
        self,
        commission_rate: float = 0.0003,      # %0.03 aracı kurum
        exchange_fee_rate: float = 0.000056,  # %0.0056 BIST borsa payı
        bsmv_rate: float = 0.05,              # BSMV %5
        min_commission: float = 1.0,
        slippage_base_pct: float = 0.05,
        slippage_max_pct: float = 0.5,
    ):
        self.commission_rate = commission_rate
        self.exchange_fee_rate = exchange_fee_rate
        self.bsmv_rate = bsmv_rate
        self.min_commission = min_commission
        self.slippage_base_pct = slippage_base_pct
        self.slippage_max_pct = slippage_max_pct

        # Ticker bazlı emir defterleri (L2 Order Book)
        self._books: dict[str, OrderBook] = {}
        # Açık artırma emir toplama havuzları
        self._auction_pools: dict[str, list[AuctionOrder]] = defaultdict(list)
        # Günlük ciro takibi
        self._daily_turnover: float = 0.0

    def get_or_create_book(self, ticker: str) -> OrderBook:
        if ticker not in self._books:
            self._books[ticker] = OrderBook(ticker=ticker, tick_size=0.01)
        return self._books[ticker]

    def process_order(
        self,
        date: str,
        ticker: str,
        side: str,                  # "BUY" | "SELL" | "SHORT"
        quantity: int,
        order_type: str = "MARKET", # "MARKET" | "LIMIT" | "TRADE_AT_CLOSE"
        price: float = 0.0,
        reference_price: float = 0.0,
        portfolio_cash: float = float("inf"),
        market_phase: BISTMarketPhase | None = None,
        avg_volume: int = 1_000_000,
        volatility: float = 0.25,
        spread_pct: float = 0.1,
        scenario: LiquidityScenario = LiquidityScenario.NORMAL,
    ) -> dict[str, Any]:
        """BIST kurallarına göre emri doğrular, seans durumuna göre deftere veya açık artırmaya iletir."""
        current_phase = market_phase or bist_session_fsm.get_phase(ticker=ticker)
        order_id = f"ORD_{date}_{ticker}_{side}_{uuid.uuid4().hex[:6]}"

        # Fiyat adımına yuvarla
        exec_price = round_to_bist_tick(price, side=side) if price > 0 else reference_price

        order_record = {
            "order_id": order_id,
            "date": date,
            "ticker": ticker,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "filled_quantity": 0,
            "limit_price": exec_price,
            "execution_price": 0.0,
            "commission": 0.0,
            "slippage_pct": 0.0,
            "market_phase": current_phase.value,
            "status": "CREATED",
            "rejection_reason": None,
            "created_at": datetime.now(UTC).isoformat(),
        }

        # 1. EMİR ÖNCESİ RİSK DENETİMİ (Pre-Trade Risk Engine)
        risk_result = pre_trade_risk_engine.validate_order(
            ticker=ticker,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=exec_price,
            reference_price=reference_price,
            market_phase=current_phase,
            portfolio_cash=portfolio_cash,
        )

        if not risk_result.is_valid:
            order_record["status"] = "REJECTED"
            order_record["rejection_reason"] = f"{risk_result.rejection_code}: {risk_result.rejection_reason}"
            logger.warning("Order rejected by PreTradeRiskEngine", ticker=ticker, reason=order_record["rejection_reason"])
            return order_record

        # 2. SEANS FAZINA GÖRE İŞLEME ALMA
        # A) Açık Artırma Emir Toplama Fazları
        if current_phase in {BISTMarketPhase.OPENING_AUCTION_COLLECTION, BISTMarketPhase.CLOSING_AUCTION_COLLECTION, BISTMarketPhase.CIRCUIT_BREAKER_AUCTION}:
            auc_order = AuctionOrder(
                order_id=order_id,
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=exec_price,
                is_market=(order_type == "MARKET"),
                timestamp=_time.time(),
            )
            self._auction_pools[ticker].append(auc_order)
            order_record["status"] = "PENDING_AUCTION"
            logger.info("Order queued for Call Auction", ticker=ticker, side=side, qty=quantity, phase=current_phase.value)
            return order_record

        # B) Sürekli Müzayede (CONTINUOUS_AUCTION)
        elif current_phase == BISTMarketPhase.CONTINUOUS_AUCTION:
            # 5-10 Kademeli Deterministik Sentetik Emir Defteri Üret (Walk-the-Book)
            scenario_enum = LiquidityScenario(scenario) if isinstance(scenario, str) else scenario
            book = SyntheticOrderBookBuilder.build_synthetic_book(
                ticker=ticker,
                mid_price=exec_price,
                adv=avg_volume,
                volatility=volatility,
                spread_pct=spread_pct,
                scenario=scenario_enum,
                num_levels=10,
            )

            # Defter üzerinde kademe tüketerek eşleştir
            walk_result = SyntheticOrderBookBuilder.execute_market_order_walk(
                book=book,
                side=side,
                requested_quantity=quantity,
                adv=avg_volume,
                scenario=scenario_enum,
            )

            filled_qty = walk_result["filled_quantity"]
            fill_price = walk_result["vwap_price"]
            slippage_pct = walk_result["slippage_pct"]

            amount = filled_qty * fill_price
            commission = self._compute_commission(amount)

            order_record["quantity"] = filled_qty
            order_record["filled_quantity"] = filled_qty
            order_record["remaining_quantity"] = walk_result["remaining_quantity"]
            order_record["execution_price"] = fill_price
            order_record["commission"] = round(commission, 2)
            order_record["slippage_pct"] = round(slippage_pct, 4)
            order_record["levels_consumed"] = walk_result["levels_consumed"]
            order_record["scenario"] = scenario_enum.value
            order_record["status"] = "PARTIAL_FILL" if walk_result["is_partial"] else "FILLED"

            self._daily_turnover += amount
            logger.info("Continuous Auction Order Executed (Walk-the-Book)",
                        ticker=ticker, side=side, fill_price=fill_price, qty=filled_qty,
                        slippage=slippage_pct, levels=walk_result["levels_consumed"],
                        scenario=scenario_enum.value)
            return order_record

        # C) Kapanış Fiyatından İşlemler (CLOSING_PRICE_TRADING)
        elif current_phase == BISTMarketPhase.CLOSING_PRICE_TRADING:
            amount = quantity * exec_price
            commission = self._compute_commission(amount)
            order_record["quantity"] = quantity
            order_record["execution_price"] = exec_price
            order_record["commission"] = round(commission, 2)
            order_record["status"] = "FILLED"
            self._daily_turnover += amount
            logger.info("Trade-at-Close Order Executed", ticker=ticker, fill_price=exec_price, qty=quantity)
            return order_record

        return order_record

    def execute_call_auction(self, ticker: str, reference_price: float) -> dict[str, Any]:
        """Açık artırma havuzundaki emirleri tek denge fiyatından eşleştirir."""
        orders = self._auction_pools.pop(ticker, [])
        if not orders:
            return {"matched_volume": 0, "equilibrium_price": reference_price, "trades": []}

        result = call_auction_engine.calculate_equilibrium(orders, reference_price)
        logger.info("Call Auction Finished", ticker=ticker, eq_price=result.equilibrium_price, matched_vol=result.matched_volume)
        return {
            "equilibrium_price": result.equilibrium_price,
            "matched_volume": result.matched_volume,
            "matched_trades": result.matched_trades,
            "imbalance_volume": result.imbalance_volume,
            "imbalance_side": result.imbalance_side,
        }

    def _compute_slippage(self, quantity: int, avg_volume: int, volatility: float, spread_pct: float) -> float:
        base_slippage = (spread_pct / 100.0) / 2.0
        volume_impact = (quantity / avg_volume * volatility * 0.5) if avg_volume > 0 else 0.001
        vol_premium = volatility * 0.02
        total = base_slippage + volume_impact + vol_premium
        return min(total, self.slippage_max_pct / 100.0)

    def _compute_commission(self, amount: float) -> float:
        broker = amount * self.commission_rate
        exchange = amount * self.exchange_fee_rate
        base = broker + exchange
        bsmv = base * self.bsmv_rate
        return max(base + bsmv, self.min_commission)


market_microstructure = MarketMicrostructureEngine()
