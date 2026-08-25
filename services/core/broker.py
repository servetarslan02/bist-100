"""ALPHA BIST — Broker Abstraction v1.0

Broker-independent order interface.
Paper broker dahil — gerçek broker henüz bağlanmadı.
"""

import uuid
import time
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    order_id: str
    ticker: str
    side: str
    quantity: int
    price: float
    status: str = OrderStatus.PENDING.value
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    reject_reason: str = ""
    created_at: float = field(default_factory=time.time)
    idempotency_key: str = ""


class BrokerInterface:
    """Broker abstraction interface."""

    def submit_order(self, order: Order) -> Order:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def get_order_status(self, order_id: str) -> Optional[Order]:
        raise NotImplementedError

    def get_positions(self) -> Dict[str, Any]:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


class PaperBroker(BrokerInterface):
    """Paper broker — simülasyon, gerçek emir yok."""

    def __init__(self, initial_capital: float = 1_000_000):
        self._capital = initial_capital
        self._positions: Dict[str, Dict] = {}
        self._orders: Dict[str, Order] = {}
        self._idempotency_keys: Dict[str, str] = {}

    def submit_order(self, order: Order) -> Order:
        # Idempotency kontrolü
        if order.idempotency_key:
            existing_id = self._idempotency_keys.get(order.idempotency_key)
            if existing_id and existing_id in self._orders:
                existing = self._orders[existing_id]
                if existing.status in (OrderStatus.SUBMITTED.value, OrderStatus.FILLED.value):
                    logger.info("Duplicate order blocked", existing_id=existing_id)
                    return existing

        order.order_id = order.order_id or str(uuid.uuid4())[:12]
        order.status = OrderStatus.SUBMITTED.value

        # Basit fill simülasyonu
        if order.side == OrderSide.BUY.value:
            cost = order.quantity * order.price
            if cost > self._capital:
                order.status = OrderStatus.REJECTED.value
                order.reject_reason = "Insufficient capital"
            else:
                self._capital -= cost
                order.status = OrderStatus.FILLED.value
                order.filled_quantity = order.quantity
                order.avg_fill_price = order.price
                pos = self._positions.get(order.ticker, {"qty": 0, "avg_cost": 0})
                total_qty = pos["qty"] + order.quantity
                if total_qty > 0:
                    pos["avg_cost"] = (pos["qty"] * pos["avg_cost"] + cost) / total_qty
                pos["qty"] = total_qty
                self._positions[order.ticker] = pos
        elif order.side == OrderSide.SELL.value:
            pos = self._positions.get(order.ticker)
            if not pos or pos["qty"] < order.quantity:
                order.status = OrderStatus.REJECTED.value
                order.reject_reason = "Insufficient position"
            else:
                revenue = order.quantity * order.price
                self._capital += revenue
                pos["qty"] -= order.quantity
                order.status = OrderStatus.FILLED.value
                order.filled_quantity = order.quantity
                order.avg_fill_price = order.price

        self._orders[order.order_id] = order
        if order.idempotency_key:
            self._idempotency_keys[order.idempotency_key] = order.order_id

        logger.info("Paper order", order_id=order.order_id, status=order.status,
                    ticker=order.ticker, side=order.side, qty=order.quantity)
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.SUBMITTED.value:
            order.status = OrderStatus.CANCELLED.value
            return True
        return False

    def get_order_status(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_positions(self) -> Dict[str, Any]:
        return dict(self._positions)

    def is_connected(self) -> bool:
        return True


# Singleton
paper_broker = PaperBroker()
