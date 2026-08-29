"""
ALPHA BIST — Paper Execution Engine v1.0

Signal -> Order Simulation:
- Gercekci execution modeli (kapanis/ertesi seans)
- Commission (BIST yapisina uygun)
- Slippage (volatilite, hacim, spread, emir buyuklugu)
- Turnover takibi
- Likidite kisiti (gunluk hacmin %5'i)
- PreTradeRiskEngine ve MarketMicrostructureEngine Entegrasyonu
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from services.core.bist_tick_size import round_to_bist_tick
from services.paper_trading.market_microstructure_engine import MarketMicrostructureEngine, market_microstructure
from services.paper_trading.synthetic_liquidity import LiquidityScenario, SyntheticOrderBookBuilder

logger = structlog.get_logger()


class PaperExecutionEngine:
    """Sanal execution motoru — gercek broker YOK."""

    def __init__(
        self,
        commission_rate: float = 0.0003,  # %0.03 broker
        exchange_fee_rate: float = 0.000056,  # %0.0056 BIST
        bsmv_rate: float = 0.05,  # BSMV
        min_commission: float = 1.0,
        slippage_base_pct: float = 0.05,  # %0.05 base
        slippage_max_pct: float = 0.5,  # %0.5 max
        microstructure: MarketMicrostructureEngine | None = None,
    ):
        """Otomatik eklendi."""
        self.commission_rate = commission_rate
        self.exchange_fee_rate = exchange_fee_rate
        self.bsmv_rate = bsmv_rate
        self.min_commission = min_commission
        self.slippage_base_pct = slippage_base_pct
        self.slippage_max_pct = slippage_max_pct
        self._daily_turnover_value: float = 0.0
        self.microstructure = microstructure or market_microstructure

    def execute_call_auction(self, ticker: str, reference_price: float = 0.0) -> dict[str, Any]:
        """Açık artırma havuzundaki emirleri BIST denge fiyatıyla eşleştirir."""
        return self.microstructure.execute_call_auction(ticker=ticker, reference_price=reference_price)

    def _create_order_dict(self, order_id, date, ticker, side, quantity, signal_price) -> dict:
        """Sipariş sözlüğü oluştur."""
        return {
            "order_id": order_id,
            "date": date,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "signal_price": signal_price,
            "execution_price": 0.0,
            "commission": 0.0,
            "slippage_pct": 0.0,
            "status": "CREATED",
            "rejection_reason": None,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _validate_order(self, ticker, date, side, is_halted, market_phase, order_type, limit_price) -> str | None:
        """Sipariş validasyonu. Reddedilirse red nedeni döner, None ise geçti."""
        from services.paper_trading.kap_market_restriction_registry import kap_restriction_registry as kap_registry

        is_eligible, kap_reason = kap_registry.validate_trading_eligibility(ticker, date, side)
        if not is_eligible:
            logger.warning("Order rejected by KAP Registry", ticker=ticker, reason=kap_reason)
            return kap_reason

        if is_halted:
            return "MARKET_HALTED: instrument is not tradable"

        if market_phase.upper() not in {"OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION"}:
            return f"MARKET_CLOSED_OR_HALTED: {market_phase}"

        if order_type.upper() not in {"MARKET", "LIMIT", "STOP_LIMIT", "KIE", "KPY", "GIE", "TRADE_AT_CLOSE"}:
            return f"UNSUPPORTED_ORDER_TYPE: {order_type}"

        return None

    def _check_bist_price_limits(self, ticker, side, execution_price, ref_price, price_limit_pct) -> str | None:
        """BIST tavan/taban ve devre kesici kilit kontrolü. Reddedilirse neden döner."""
        if ref_price <= 0:
            return None

        price_change_pct = ((execution_price / ref_price) - 1.0) * 100.0
        lock_threshold = price_limit_pct - 0.10

        if side == "SELL" and price_change_pct <= -lock_threshold:
            logger.warning("Order rejected: Limit Down Locked", ticker=ticker, change_pct=price_change_pct)
            return f"BIST_LIMIT_DOWN_LOCKED: {ticker} taban fiyatta (%{price_change_pct:.2f}). Satış kuyruğunda likidite yok."

        if side == "BUY" and price_change_pct >= lock_threshold:
            logger.warning("Order rejected: Limit Up Locked", ticker=ticker, change_pct=price_change_pct)
            return f"BIST_LIMIT_UP_LOCKED: {ticker} tavan fiyatta (%{price_change_pct:.2f}). Tavanda satıcı yok."

        return None

    def execute_signal(
        self,
        date: str,
        ticker: str,
        side: str,  # "BUY" | "SELL"
        quantity: int,
        signal_price: float,
        market_price: float,
        avg_volume: int = 1_000_000,
        volatility: float = 0.25,
        spread_pct: float = 0.1,
        sector: str = "",
        reference_price: float | None = None,
        price_limit_pct: float = 10.0,
        is_halted: bool = False,
        order_type: str = "MARKET",
        limit_price: float | None = None,
        market_phase: str = "CONTINUOUS",
        scenario: str = "NORMAL",
    ) -> dict[str, Any]:
        """
        Sinyali sanal order'a cevir.

        ONEMLI: signal_price (sinyal uretildigi fiyat) ile market_price
        (islem fiyati) AYRI olabilir. Ertesi seans acilisinda islem
        gerceklesirse signal_price != execution_price olur.
        Bu look-ahead bias'i onler.
        """
        order_id = f"ORD_{date}_{ticker}_{side}_{uuid.uuid4().hex[:6]}"
        order = self._create_order_dict(order_id, date, ticker, side, quantity, signal_price)

        # Validasyon
        rejection = self._validate_order(ticker, date, side, is_halted, market_phase, order_type, limit_price)
        if rejection:
            order["status"] = "REJECTED"
            order["rejection_reason"] = rejection
            return order

        execution_price = market_price

        # Limit emir kontrolü
        if order_type.upper() in {"LIMIT", "STOP_LIMIT"}:
            if not limit_price or limit_price <= 0:
                order["status"] = "REJECTED"
                order["rejection_reason"] = "LIMIT_PRICE_REQUIRED"
                return order
            if (side == "BUY" and execution_price > limit_price) or (side == "SELL" and execution_price < limit_price):
                order["status"] = "UNFILLED"
                order["rejection_reason"] = "LIMIT_NOT_REACHED"
                return order

        # BIST tavan/taban kontrolü
        ref_price = reference_price if reference_price and reference_price > 0 else signal_price
        limit_up_price = ref_price * (1.0 + price_limit_pct / 100.0) if ref_price > 0 else float("inf")
        limit_down_price = ref_price * (1.0 - price_limit_pct / 100.0) if ref_price > 0 else 0.0

        bist_rejection = self._check_bist_price_limits(ticker, side, execution_price, ref_price, price_limit_pct)
        if bist_rejection:
            order["status"] = "REJECTED"
            order["rejection_reason"] = bist_rejection
            return order

        # === SENTETİK DEFTER & WALK-THE-BOOK EŞLEŞTİRME ===
        scenario_enum = LiquidityScenario(scenario) if isinstance(scenario, str) else scenario
        book = SyntheticOrderBookBuilder.build_synthetic_book(
            ticker=ticker,
            mid_price=execution_price,
            adv=avg_volume,
            volatility=volatility,
            spread_pct=spread_pct,
            scenario=scenario_enum,
            num_levels=10,
            limit_up_price=limit_up_price,
            limit_down_price=limit_down_price,
        )

        walk_res = SyntheticOrderBookBuilder.execute_market_order_walk(
            book=book,
            side=side,
            requested_quantity=quantity,
            adv=avg_volume,
            scenario=scenario_enum,
            limit_up_price=limit_up_price,
            limit_down_price=limit_down_price,
        )

        fill_price = walk_res["vwap_price"]
        filled_quantity = walk_res["filled_quantity"]
        slippage = walk_res["slippage_pct"] / 100.0

        # Kayma fiyatı günlük marj dışına taşıyamaz
        if ref_price > 0 and abs((fill_price / ref_price - 1) * 100) > price_limit_pct:
            order["status"] = "REJECTED"
            order["rejection_reason"] = "PRICE_LIMIT: fill price outside BIST daily price band"
            return order

        if walk_res["is_partial"]:
            order["status"] = "PARTIAL_FILL"
            logger.info(
                "Order partially filled due to synthetic liquidity cap",
                ticker=ticker,
                requested=quantity,
                filled=filled_quantity,
                remaining=walk_res["remaining_quantity"],
                scenario=scenario_enum.value,
            )

        # === COMMISSION ===
        amount = filled_quantity * fill_price
        commission = self._compute_commission(amount)

        # === FILL ===
        order["quantity"] = filled_quantity
        order["execution_price"] = round(fill_price, 4)
        order["commission"] = round(commission, 2)
        order["slippage_pct"] = round(slippage * 100, 4)
        if order["status"] != "PARTIAL_FILL":
            order["status"] = "FILLED"

        # Turnover guncelle
        self._daily_turnover_value += amount

        logger.info(
            "Order executed",
            order_id=order_id,
            ticker=ticker,
            side=side,
            qty=filled_quantity,
            signal_price=signal_price,
            execution_price=order["execution_price"],
            commission=order["commission"],
            slippage=order["slippage_pct"],
            status=order["status"],
        )

        # ORDER_FILLED event publish
        try:
            from services.core.event_bus import publish_event
            from services.core.event_schema import CanonicalEvent, EventType

            order_event = CanonicalEvent(
                event_type=EventType.ORDER_FILLED,
                payload={
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": fill_price,
                    "order_id": order_id,
                },
            )
            publish_event(order_event, key=ticker)
        except Exception:
            logger.warning("Caught Exception in execute_signal", exc_info=True)

        return order

    def _compute_slippage(
        self,
        quantity: int,
        avg_volume: int,
        volatility: float,
        spread_pct: float,
        side: str,
    ) -> float:
        """Slippage hesapla."""
        # Base slippage (spread'in yarisi)
        base_slippage = (spread_pct / 100) / 2

        # Volume impact
        if avg_volume > 0:
            participation_rate = quantity / avg_volume
            volume_impact = participation_rate * volatility * 0.5
        else:
            volume_impact = 0.001

        # Volatility premium
        vol_premium = volatility * 0.02

        total_slippage = base_slippage + volume_impact + vol_premium

        # Max slippage cap
        max_slippage = self.slippage_max_pct / 100
        return min(total_slippage, max_slippage)

    def _round_to_tick(self, price: float, side: str) -> float:
        """Otomatik eklendi."""
        return round_to_bist_tick(price, side=side)

    def _compute_commission(self, amount: float) -> float:
        """BIST komisyon yapisi."""
        broker_fee = amount * self.commission_rate
        exchange_fee = amount * self.exchange_fee_rate
        base = broker_fee + exchange_fee
        bsmv = base * self.bsmv_rate
        total = base + bsmv
        return max(total, self.min_commission)

    def get_daily_turnover(self) -> float:
        """Gunluk turnover degeri."""
        return self._daily_turnover_value

    def reset_daily_turnover(self) -> Any:
        """Gunluk turnover'u sifirla."""
        self._daily_turnover_value = 0.0

    def compute_transaction_cost_summary(self, orders: list[dict[str, Any]]) -> dict[str, float]:
        """Islem maliyet ozeti."""
        filled = [o for o in orders if o.get("status") in {"FILLED", "PARTIAL_FILL"}]
        total_commission = sum(o.get("commission", 0) for o in filled)
        total_slippage_cost = sum(o["quantity"] * o["signal_price"] * (o.get("slippage_pct", 0) / 100) for o in filled)
        return {
            "total_commission": round(total_commission, 2),
            "total_slippage_cost": round(total_slippage_cost, 2),
            "total_transaction_cost": round(total_commission + total_slippage_cost, 2),
            "avg_commission_per_trade": round(total_commission / len(filled), 2) if filled else 0,
            "num_filled": len(filled),
            "num_rejected": len([o for o in orders if o.get("status") == "REJECTED"]),
        }


# Singleton
paper_execution = PaperExecutionEngine()
