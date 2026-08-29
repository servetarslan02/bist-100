"""ALPHA BIST — Broker Abstraction v1.0

Broker-independent order interface.
Paper broker dahil — gerçek broker henüz bağlanmadı.
"""

import functools
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.broker")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class OrderSide(Enum):
    """Otomatik eklendi."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Otomatik eklendi."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """Otomatik eklendi."""
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
        """Otomatik eklendi."""
        logger.warning("submit_order is not implemented")
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        """Otomatik eklendi."""
        logger.warning("cancel_order is not implemented")
        raise NotImplementedError

    def get_order_status(self, order_id: str) -> Order | None:
        """Otomatik eklendi."""
        logger.warning("get_order_status is not implemented")
        raise NotImplementedError

    def get_positions(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        logger.warning("get_positions is not implemented")
        raise NotImplementedError

    def is_connected(self) -> bool:
        """Otomatik eklendi."""
        logger.warning("is_connected is not implemented")
        raise NotImplementedError


class PaperBroker(BrokerInterface):
    """Paper broker — simülasyon, gerçek emir yok."""

    def __init__(self, initial_capital: float = 1_000_000, slippage_bps: float = 5.0):
        """Otomatik eklendi."""
        self._capital = initial_capital
        self._positions: dict[str, dict] = {}
        self._orders: dict[str, Order] = {}
        self._idempotency_keys: dict[str, str] = {}
        self._slippage_bps = slippage_bps  # basis points (5 bps = %0.05)

    @otel_trace("broker.submit_order")
    def submit_order(self, order: Order) -> Order:
        """Otomatik eklendi."""
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

    @otel_trace("broker.cancel_order")
    def cancel_order(self, order_id: str) -> bool:
        """Otomatik eklendi."""
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.SUBMITTED.value:
            order.status = OrderStatus.CANCELLED.value
            return True
        return False

    @otel_trace("broker.get_order_status")
    def get_order_status(self, order_id: str) -> Order | None:
        """Otomatik eklendi."""
        return self._orders.get(order_id)

    @otel_trace("broker.get_positions")
    def get_positions(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return dict(self._positions)

    def is_connected(self) -> bool:
        """Otomatik eklendi."""
        return True


# Singleton
paper_broker = PaperBroker()
