"""
ALPHA BIST — Execution Simulator v1.0

Gercekci sanal islem:
- Order lifecycle (CREATED → FILLED)
- Slippage model (volatility, spread, liquidity, order size)
- Transaction cost model (commission, BSMV)
- Partial fill destegi

FAZ 10: Order & Execution Simulator
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import structlog

logger = structlog.get_logger()


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class Order:
    """Emir."""
    order_id: str
    portfolio_id: int
    instrument_id: int
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float = 0.0          # Limit emir fiyati
    stop_price: float = 0.0     # Stop fiyati
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    source: str = "DECISION"
    decision_id: str = ""
    risk_id: str = ""
    notes: str = ""


@dataclass
class Fill:
    """Dolum."""
    fill_id: str
    order_id: str
    instrument_id: int
    ticker: str
    side: OrderSide
    quantity: int
    price: float
    commission: float
    slippage: float
    filled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionSimulator:
    """Sanal execution motoru.

    Gercek broker yerine simulasyon.
    """

    # Komisyon oranlari (BIST)
    BROKER_COMMISSION_RATE = 0.0003   # %0.03
    EXCHANGE_FEE_RATE = 0.000056      # %0.0056
    BSMV_RATE = 0.05                  # BSMV (komisyon uzerinden %5)
    MIN_COMMISSION = 1.0              # Minimum 1 TL

    def execute_order(
        self,
        order: Order,
        market_price: float,
        bid: float = 0,
        ask: float = 0,
        avg_volume: int = 1000000,
        volatility: float = 0.25,
        spread_pct: float = 0.1,
    ) -> Order:
        """Emri simule et.

        Hata yonetimi: Herhangi bir hata durumunda order FAILED olarak isaretlenir.
        """
        try:
            return self._execute_order_internal(order, market_price, bid, ask, avg_volume, volatility, spread_pct)
        except Exception as e:
            logger.error("Order execution failed", order_id=order.order_id, error=str(e))
            order.status = OrderStatus.FAILED
            order.notes = f"Execution error: {e}"
            return order

    def _execute_order_internal(
        self,
        order: Order,
        market_price: float,
        bid: float = 0,
        ask: float = 0,
        avg_volume: int = 1000000,
        volatility: float = 0.25,
        spread_pct: float = 0.1,
    ) -> Order:
        """Emri simule et (internal)."""
        # Status guncelle
        order.status = OrderStatus.SUBMITTED

        # Slippage hesapla
        slippage = self._compute_slippage(
            order.quantity, avg_volume, volatility, spread_pct, order.side
        )

        # Uygulanacak fiyat
        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BUY:
                fill_price = market_price * (1 + slippage)
            else:
                fill_price = market_price * (1 - slippage)
        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                fill_price = min(order.price, market_price * (1 + slippage))
                if order.price < market_price * (1 - spread_pct / 100):
                    order.status = OrderStatus.REJECTED
                    order.notes = "Limit price too far from market"
                    return order
            else:
                fill_price = max(order.price, market_price * (1 - slippage))
                if order.price > market_price * (1 + spread_pct / 100):
                    order.status = OrderStatus.REJECTED
                    order.notes = "Limit price too far from market"
                    return order
        else:
            fill_price = market_price

        # Komisyon hesapla
        amount = order.quantity * fill_price
        commission = self._compute_commission(amount)

        # Partial fill kontrolu
        fill_qty = order.quantity
        if avg_volume > 0:
            # Gunluk hacmin %10'undan fazlasini alamaz
            max_qty = int(avg_volume * 0.1)
            if order.quantity > max_qty:
                fill_qty = max_qty
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.FILLED

        # Guncelle
        order.filled_quantity = fill_qty
        order.avg_fill_price = round(fill_price, 4)
        order.commission = round(commission, 2)
        order.slippage = round(slippage * 100, 4)  # Yuzde olarak
        order.filled_at = datetime.now(timezone.utc)

        logger.info("Order executed",
                    order_id=order.order_id,
                    ticker=order.ticker,
                    side=order.side.value,
                    qty=fill_qty,
                    price=fill_price,
                    commission=commission,
                    slippage=order.slippage)

        return order

    def _compute_slippage(
        self,
        order_size: int,
        avg_volume: int,
        volatility: float,
        spread_pct: float,
        side: OrderSide,
    ) -> float:
        """Slippage hesapla.

        Slippage = base_slippage + volume_impact

        Buyuk ve kucuk emirler ayni slippage almamali.
        """
        # Base slippage (spread'in yarisi)
        base_slippage = (spread_pct / 100) / 2

        # Volume impact
        if avg_volume > 0:
            participation_rate = order_size / avg_volume
            # Katilim orani arttikca slippage artar
            volume_impact = participation_rate * volatility * 0.5
        else:
            volume_impact = 0.001  # Default

        total_slippage = base_slippage + volume_impact

        # Maksimum slippage siniri (%5)
        return min(total_slippage, 0.05)

    def _compute_commission(self, amount: float) -> float:
        """Komisyon hesapla (BIST yapisi)."""
        broker_fee = amount * self.BROKER_COMMISSION_RATE
        exchange_fee = amount * self.EXCHANGE_FEE_RATE
        base_commission = broker_fee + exchange_fee
        bsmv = base_commission * self.BSMV_RATE
        total = base_commission + bsmv
        return max(total, self.MIN_COMMISSION)

    def create_fill(self, order: Order) -> Fill:
        """Fill olustur."""
        import hashlib
        fill_id = hashlib.sha256(
            f"{order.order_id}-{order.filled_quantity}-{order.avg_fill_price}".encode()
        ).hexdigest()[:16]

        return Fill(
            fill_id=fill_id,
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            ticker=order.ticker,
            side=order.side,
            quantity=order.filled_quantity,
            price=order.avg_fill_price,
            commission=order.commission,
            slippage=order.slippage,
            filled_at=order.filled_at or datetime.now(timezone.utc),
        )


# Singleton
execution_simulator = ExecutionSimulator()
