"""
ALPHA BIST — Paper Execution Engine v1.0

Signal -> Order Simulation:
- Gercekci execution modeli (kapanis/ertesi seans)
- Commission (BIST yapisina uygun)
- Slippage (volatilite, hacim, spread, emir buyuklugu)
- Turnover takibi
- Likidite kisiti (gunluk hacmin %10'u)
- Ayni fiyat uzerinden signal uretip islem gerceklestirme; look-ahead bias YOK.

Mevcut services.backtest.engine.BacktestEngine'den farkli:
- O gunluk, ertesi seans execution
- Persistent order kaydi
- BIST komisyon yapisi
"""

import uuid
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog

logger = structlog.get_logger()


class PaperExecutionEngine:
    """Sanal execution motoru — gercek broker YOK."""

    def __init__(
        self,
        commission_rate: float = 0.0003,      # %0.03 broker
        exchange_fee_rate: float = 0.000056,  # %0.0056 BIST
        bsmv_rate: float = 0.05,              # BSMV
        min_commission: float = 1.0,
        slippage_base_pct: float = 0.05,      # %0.05 base
        slippage_max_pct: float = 0.5,        # %0.5 max
    ):
        self.commission_rate = commission_rate
        self.exchange_fee_rate = exchange_fee_rate
        self.bsmv_rate = bsmv_rate
        self.min_commission = min_commission
        self.slippage_base_pct = slippage_base_pct
        self.slippage_max_pct = slippage_max_pct
        self._daily_turnover_value: float = 0.0

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
        reference_price: Optional[float] = None,
        price_limit_pct: float = 10.0,
        is_halted: bool = False,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        market_phase: str = "CONTINUOUS",
    ) -> Dict[str, Any]:
        """
        Sinyali sanal order'a cevir.

        ONEMLI: signal_price (sinyal uretildigi fiyat) ile market_price
        (islem fiyati) AYRI olabilir. Ertesi seans acilisinda islem
        gerceklesirse signal_price != execution_price olur.
        Bu look-ahead bias'i onler.
        """
        order_id = f"ORD_{date}_{ticker}_{side}_{uuid.uuid4().hex[:6]}"

        order = {
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
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if is_halted:
            order["status"] = "REJECTED"
            order["rejection_reason"] = "MARKET_HALTED: instrument is not tradable"
            return order

        market_phase = market_phase.upper()
        if market_phase not in {"OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION"}:
            order["status"] = "REJECTED"
            order["rejection_reason"] = f"MARKET_CLOSED_OR_HALTED: {market_phase}"
            return order

        order_type = order_type.upper()
        if order_type not in {"MARKET", "LIMIT", "STOP_LIMIT"}:
            order["status"] = "REJECTED"
            order["rejection_reason"] = f"UNSUPPORTED_ORDER_TYPE: {order_type}"
            return order

        # === EXECUTION PRICE ===
        execution_price = market_price

        # Limit emir yalnızca limit fiyatı piyasa tarafından karşılanmışsa
        # gerçekleşir; aksi halde sırada bekler (bu sade motorda fill yoktur).
        if order_type in {"LIMIT", "STOP_LIMIT"}:
            if not limit_price or limit_price <= 0:
                order["status"] = "REJECTED"
                order["rejection_reason"] = "LIMIT_PRICE_REQUIRED"
                return order
            if (side == "BUY" and execution_price > limit_price) or (side == "SELL" and execution_price < limit_price):
                order["status"] = "UNFILLED"
                order["rejection_reason"] = "LIMIT_NOT_REACHED"
                return order

        # === BIST TAVAN / TABAN & DEVRE KESİCİ KİLİT KONTROLÜ ===
        # BIST fiyat marjı sinyal fiyatına değil, önceki seansın baz/referans
        # fiyatına göre kontrol edilir.
        ref_price = reference_price if reference_price and reference_price > 0 else signal_price
        if ref_price > 0:
            price_change_pct = ((execution_price / ref_price) - 1.0) * 100.0

            # Taban Kilidi Kontrolü: Hisse tabana kilitliyse (-%9.95 ve altı), satış likiditesi sıfırdır, satış emri gerçekleşmez!
            lock_threshold = price_limit_pct - 0.10
            if side == "SELL" and price_change_pct <= -lock_threshold:
                order["status"] = "REJECTED"
                order["rejection_reason"] = f"BIST_LIMIT_DOWN_LOCKED: {ticker} taban fiyatta (%{price_change_pct:.2f}). Satış kuyruğunda likidite yok, işlem gerçekleşmedi."
                logger.warning("Order rejected: Limit Down Locked", ticker=ticker, change_pct=price_change_pct)
                return order

            # Tavan Kilidi Kontrolü: Hisse tavana kilitliyse (+%9.95 ve üstü), satıcı yoktur, alış emri gerçekleşmez!
            if side == "BUY" and price_change_pct >= lock_threshold:
                order["status"] = "REJECTED"
                order["rejection_reason"] = f"BIST_LIMIT_UP_LOCKED: {ticker} tavan fiyatta (%{price_change_pct:.2f}). Tavanda satıcı yok, alış emri gerçekleşmedi."
                logger.warning("Order rejected: Limit Up Locked", ticker=ticker, change_pct=price_change_pct)
                return order

        # === SLIPPAGE ===
        slippage = self._compute_slippage(
            quantity=quantity,
            avg_volume=avg_volume,
            volatility=volatility,
            spread_pct=spread_pct,
            side=side,
        )

        if side == "BUY":
            fill_price = execution_price * (1 + slippage)
        else:
            fill_price = execution_price * (1 - slippage)
        fill_price = self._round_to_tick(fill_price, side)

        # Kayma fiyatı günlük marj dışına taşıyamaz; o fiyat seviyesinde işlem
        # gerçekleşmiş varsaymak yerine emir reddedilir.
        if ref_price > 0 and abs((fill_price / ref_price - 1) * 100) > price_limit_pct:
            order["status"] = "REJECTED"
            order["rejection_reason"] = "PRICE_LIMIT: fill price outside BIST daily price band"
            return order

        # === LİKİDİTE VE KISMİ DOLUM (PARTIAL FILL) MODELİ ===
        # BIST piyasa yapıcı kuralı: Tek barda ortalama hacmin en fazla %5'i kadar aktif dolum yapılabilir
        filled_quantity = quantity
        if avg_volume > 0:
            max_participate_qty = max(1, int(avg_volume * 0.05))
            if quantity > max_participate_qty:
                filled_quantity = max_participate_qty
                order["status"] = "PARTIAL_FILL"
                logger.info("Order partially filled due to liquidity participation cap",
                            ticker=ticker, requested=quantity, filled=filled_quantity)

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

        logger.info("Order executed",
                   order_id=order_id, ticker=ticker, side=side,
                   qty=filled_quantity, signal_price=signal_price,
                   execution_price=order["execution_price"],
                   commission=order["commission"],
                   slippage=order["slippage_pct"],
                   status=order["status"])

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
        except Exception as e:
            pass

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

    @staticmethod
    def _tick_size(price: float) -> float:
        """BIST pay fiyat adımları."""
        if price < 20:
            return 0.01
        if price < 50:
            return 0.02
        if price < 100:
            return 0.05
        if price < 250:
            return 0.10
        if price < 500:
            return 0.25
        if price < 1000:
            return 0.50
        if price < 2500:
            return 1.00
        return 2.50

    def _round_to_tick(self, price: float, side: str) -> float:
        tick = self._tick_size(price)
        units = math.ceil(price / tick) if side == "BUY" else math.floor(price / tick)
        return round(units * tick, 4)

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

    def reset_daily_turnover(self):
        """Gunluk turnover'u sifirla."""
        self._daily_turnover_value = 0.0

    def compute_transaction_cost_summary(self, orders: List[Dict[str, Any]]) -> Dict[str, float]:
        """Islem maliyet ozeti."""
        filled = [o for o in orders if o.get("status") in {"FILLED", "PARTIAL_FILL"}]
        total_commission = sum(o.get("commission", 0) for o in filled)
        total_slippage_cost = sum(
            o["quantity"] * o["signal_price"] * (o.get("slippage_pct", 0) / 100)
            for o in filled
        )
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
