"""ALPHA BIST — Broker Abstraction v1.0

Broker-independent order interface.
Paper broker dahil — gerçek broker henüz bağlanmadı.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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

    def get_order_status(self, order_id: str) -> Order | None:
        raise NotImplementedError

    def get_positions(self) -> dict[str, Any]:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


class PaperBroker(BrokerInterface):
    """Paper broker — simülasyon, gerçek emir yok."""

    def __init__(self, initial_capital: float = 1_000_000, slippage_bps: float = 5.0):
        self._capital = initial_capital
        self._positions: dict[str, dict] = {}
        self._orders: dict[str, Order] = {}
        self._idempotency_keys: dict[str, str] = {}
        self._slippage_bps = slippage_bps  # basis points (5 bps = %0.05)

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

        # Fill simülasyonu — slippage dahil
        slippage_mult = (
            1.0 + (self._slippage_bps / 10_000)
            if order.side == OrderSide.BUY.value
            else 1.0 - (self._slippage_bps / 10_000)
        )
        fill_price = round(order.price * slippage_mult, 4)

        if order.side == OrderSide.BUY.value:
            cost = order.quantity * fill_price
            if cost > self._capital:
                order.status = OrderStatus.REJECTED.value
                order.reject_reason = "Insufficient capital"
            else:
                self._capital -= cost
                order.status = OrderStatus.FILLED.value
                order.filled_quantity = order.quantity
                order.avg_fill_price = fill_price
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
                revenue = order.quantity * fill_price
                self._capital += revenue
                pos["qty"] -= order.quantity
                order.status = OrderStatus.FILLED.value
                order.filled_quantity = order.quantity
                order.avg_fill_price = fill_price
                order.avg_fill_price = order.price

        self._orders[order.order_id] = order
        if order.idempotency_key:
            self._idempotency_keys[order.idempotency_key] = order.order_id

        logger.info(
            "Paper order",
            order_id=order.order_id,
            status=order.status,
            ticker=order.ticker,
            side=order.side,
            qty=order.quantity,
        )
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.SUBMITTED.value:
            order.status = OrderStatus.CANCELLED.value
            return True
        return False

    def get_order_status(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_positions(self) -> dict[str, Any]:
        return dict(self._positions)

    def is_connected(self) -> bool:
        return True


# Singleton
paper_broker = PaperBroker()
