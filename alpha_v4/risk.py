"""Independent fail-closed risk gate for ALPHA v4 paper operation.

The gate consumes explicit state; it never asks a model to decide whether its own risk
limits should apply. Unknown integrity states produce NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class RiskAction(str, Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class RiskPolicy:
    policy_version: str
    max_position_fraction: float
    max_sector_fraction: float
    max_gross_exposure_fraction: float
    minimum_liquidity_score: float

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        for name in (
            "max_position_fraction",
            "max_sector_fraction",
            "max_gross_exposure_fraction",
            "minimum_liquidity_score",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class RiskRequest:
    instrument_id: str
    sector_id: Optional[str]
    requested_notional: float
    portfolio_equity: Optional[float]
    current_instrument_notional: Optional[float]
    current_sector_notional: Optional[float]
    current_gross_exposure: Optional[float]
    liquidity_score: Optional[float]
    data_integrity_ok: Optional[bool]
    model_integrity_ok: Optional[bool]
    kill_switch_active: bool = False


@dataclass(frozen=True)
class RiskDecision:
    action: RiskAction
    approved_notional: float
    reasons: Tuple[str, ...]
    policy_version: str


def evaluate_risk(request: RiskRequest, policy: RiskPolicy) -> RiskDecision:
    if request.requested_notional <= 0:
        raise ValueError("requested_notional must be positive")

    reasons = []
    if request.kill_switch_active:
        reasons.append("kill_switch_active")
    if request.data_integrity_ok is not True:
        reasons.append("data_integrity_unresolved")
    if request.model_integrity_ok is not True:
        reasons.append("model_integrity_unresolved")

    required_values = {
        "portfolio_equity": request.portfolio_equity,
        "current_instrument_notional": request.current_instrument_notional,
        "current_sector_notional": request.current_sector_notional,
        "current_gross_exposure": request.current_gross_exposure,
        "liquidity_score": request.liquidity_score,
    }
    unresolved = [name for name, value in required_values.items() if value is None]
    if unresolved:
        reasons.append("missing_risk_state:" + ",".join(sorted(unresolved)))

    if reasons:
        return RiskDecision(
            action=RiskAction.NO_TRADE,
            approved_notional=0.0,
            reasons=tuple(reasons),
            policy_version=policy.policy_version,
        )

    assert request.portfolio_equity is not None
    assert request.current_instrument_notional is not None
    assert request.current_sector_notional is not None
    assert request.current_gross_exposure is not None
    assert request.liquidity_score is not None

    if request.portfolio_equity <= 0:
        return RiskDecision(
            action=RiskAction.NO_TRADE,
            approved_notional=0.0,
            reasons=("non_positive_portfolio_equity",),
            policy_version=policy.policy_version,
        )
    if request.liquidity_score < policy.minimum_liquidity_score:
        return RiskDecision(
            action=RiskAction.NO_TRADE,
            approved_notional=0.0,
            reasons=("liquidity_below_policy",),
            policy_version=policy.policy_version,
        )

    equity = request.portfolio_equity
    position_capacity = max(
        0.0,
        equity * policy.max_position_fraction - request.current_instrument_notional,
    )
    sector_capacity = max(
        0.0,
        equity * policy.max_sector_fraction - request.current_sector_notional,
    )
    gross_capacity = max(
        0.0,
        equity * policy.max_gross_exposure_fraction - request.current_gross_exposure,
    )
    approved = min(request.requested_notional, position_capacity, sector_capacity, gross_capacity)

    if approved <= 0:
        limiting = []
        if position_capacity <= 0:
            limiting.append("position_limit")
        if sector_capacity <= 0:
            limiting.append("sector_limit")
        if gross_capacity <= 0:
            limiting.append("gross_exposure_limit")
        return RiskDecision(
            action=RiskAction.NO_TRADE,
            approved_notional=0.0,
            reasons=tuple(limiting) or ("no_risk_capacity",),
            policy_version=policy.policy_version,
        )

    if approved + 1e-9 < request.requested_notional:
        return RiskDecision(
            action=RiskAction.REDUCE,
            approved_notional=approved,
            reasons=("requested_notional_reduced_to_policy_capacity",),
            policy_version=policy.policy_version,
        )

    return RiskDecision(
        action=RiskAction.APPROVE,
        approved_notional=approved,
        reasons=(),
        policy_version=policy.policy_version,
    )
