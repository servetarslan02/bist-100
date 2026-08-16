"""Explicit paper-execution simulation for ALPHA v4.

No real orders are sent. The simulator refuses to invent fills when quotes or liquidity
inputs are unavailable and makes every cost assumption explicit/versionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ExecutionPolicy:
    policy_version: str
    commission_bps: float
    base_slippage_bps: float
    max_volume_participation: float
    minimum_notional: float = 0.0

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.commission_bps < 0 or self.base_slippage_bps < 0:
            raise ValueError("cost assumptions cannot be negative")
        if not 0 < self.max_volume_participation <= 1:
            raise ValueError("max_volume_participation must be in (0, 1]")
        if self.minimum_notional < 0:
            raise ValueError("minimum_notional cannot be negative")


@dataclass(frozen=True)
class MarketExecutionState:
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    available_volume: Optional[float]
    data_integrity_ok: bool


@dataclass(frozen=True)
class SimulatedFill:
    status: str
    requested_quantity: float
    filled_quantity: float
    fill_price: Optional[float]
    commission: float
    spread_cost: float
    slippage_cost: float
    reasons: Tuple[str, ...]
    policy_version: str


class ExecutionSimulator:
    def __init__(self, policy: ExecutionPolicy):
        self.policy = policy

    def simulate_market_order(
        self,
        *,
        side: str,
        requested_quantity: float,
        market: MarketExecutionState,
    ) -> SimulatedFill:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")

        if not market.data_integrity_ok:
            return self._no_fill(requested_quantity, "market_data_integrity_failed")
        if market.bid is None or market.ask is None:
            return self._no_fill(requested_quantity, "missing_bid_ask")
        if market.available_volume is None:
            return self._no_fill(requested_quantity, "missing_liquidity")
        if market.bid <= 0 or market.ask <= 0 or market.ask < market.bid:
            return self._no_fill(requested_quantity, "invalid_quote")
        if market.available_volume <= 0:
            return self._no_fill(requested_quantity, "no_available_volume")

        max_fill = market.available_volume * self.policy.max_volume_participation
        filled_quantity = min(requested_quantity, max_fill)
        if filled_quantity <= 0:
            return self._no_fill(requested_quantity, "participation_capacity_zero")

        mid = (market.bid + market.ask) / 2.0
        touch = market.ask if side == "BUY" else market.bid
        slippage_rate = self.policy.base_slippage_bps / 10_000.0
        fill_price = touch * (1 + slippage_rate if side == "BUY" else 1 - slippage_rate)
        fill_notional = filled_quantity * fill_price

        if fill_notional < self.policy.minimum_notional:
            return self._no_fill(requested_quantity, "below_minimum_notional")

        commission = fill_notional * self.policy.commission_bps / 10_000.0
        spread_per_unit = abs(touch - mid)
        spread_cost = spread_per_unit * filled_quantity
        slippage_cost = abs(fill_price - touch) * filled_quantity
        status = "FILLED" if filled_quantity >= requested_quantity - 1e-12 else "PARTIAL_FILL"

        return SimulatedFill(
            status=status,
            requested_quantity=requested_quantity,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            commission=commission,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            reasons=(),
            policy_version=self.policy.policy_version,
        )

    def _no_fill(self, requested_quantity: float, reason: str) -> SimulatedFill:
        return SimulatedFill(
            status="NO_FILL",
            requested_quantity=requested_quantity,
            filled_quantity=0.0,
            fill_price=None,
            commission=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            reasons=(reason,),
            policy_version=self.policy.policy_version,
        )
