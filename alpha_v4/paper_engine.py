"""Governed paper-operation slice for ALPHA v4.

This is virtual execution only. It connects a research/operating decision to the
independent risk gate, tamper-evident audit ledger and persistent paper portfolio.
There is no broker or real-money execution path in this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Tuple

from .audit import AuditLedger
from .paper_ledger import PaperLedger, PaperLedgerError
from .risk import RiskAction, RiskDecision, RiskPolicy, RiskRequest, evaluate_risk


@dataclass(frozen=True)
class PaperDecisionRequest:
    decision_id: str
    account_id: str
    instrument_id: str
    ticker: str
    model_id: str
    price: float
    requested_notional: float
    commission_bps: float
    state_snapshot_ids: Tuple[str, ...]
    feature_refs: Tuple[str, ...]
    risk_request: RiskRequest

    def __post_init__(self) -> None:
        for name in ("decision_id", "account_id", "instrument_id", "ticker", "model_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.price <= 0 or self.requested_notional <= 0:
            raise ValueError("price and requested_notional must be positive")
        if self.commission_bps < 0:
            raise ValueError("commission_bps cannot be negative")
        if not self.state_snapshot_ids or not self.feature_refs:
            raise ValueError("state and feature lineage are required")
        if self.risk_request.instrument_id != self.instrument_id:
            raise ValueError("risk_request instrument mismatch")
        if abs(self.risk_request.requested_notional - self.requested_notional) > 1e-9:
            raise ValueError("risk_request notional mismatch")


@dataclass(frozen=True)
class PaperDecisionResult:
    decision_id: str
    risk_decision_id: str
    risk: RiskDecision
    fill_event_id: str | None
    simulated_quantity: float
    status: str


class PaperEngine:
    def __init__(
        self,
        *,
        ledger: PaperLedger,
        audit: AuditLedger,
        risk_policy: RiskPolicy,
    ):
        self.ledger = ledger
        self.audit = audit
        self.risk_policy = risk_policy

    def submit_buy(
        self,
        request: PaperDecisionRequest,
        *,
        event_time: datetime,
    ) -> PaperDecisionResult:
        """Evaluate and, only when allowed, record a simulated BUY fill."""
        self.audit.append(
            "DECISION_CREATED",
            {
                "decision_id": request.decision_id,
                "account_id": request.account_id,
                "instrument_id": request.instrument_id,
                "ticker": request.ticker,
                "model_id": request.model_id,
                "requested_notional": request.requested_notional,
                "price": request.price,
                "state_snapshot_ids": list(request.state_snapshot_ids),
                "feature_refs": list(request.feature_refs),
                "execution_mode": "PAPER_ONLY",
            },
            created_at=event_time,
        )

        risk = evaluate_risk(request.risk_request, self.risk_policy)
        risk_decision_id = uuid.uuid4().hex
        self.audit.append(
            "RISK_DECISION",
            {
                "decision_id": request.decision_id,
                "risk_decision_id": risk_decision_id,
                "policy_version": risk.policy_version,
                "action": risk.action.value,
                "approved_notional": risk.approved_notional,
                "reasons": list(risk.reasons),
            },
            created_at=event_time,
        )

        if risk.action is RiskAction.NO_TRADE or risk.approved_notional <= 0:
            return PaperDecisionResult(
                decision_id=request.decision_id,
                risk_decision_id=risk_decision_id,
                risk=risk,
                fill_event_id=None,
                simulated_quantity=0.0,
                status="NO_TRADE",
            )

        quantity = risk.approved_notional / request.price
        commission = risk.approved_notional * request.commission_bps / 10_000.0
        try:
            fill_event_id = self.ledger.record_fill(
                request.account_id,
                ticker=request.ticker,
                side="BUY",
                quantity=quantity,
                price=request.price,
                commission=commission,
                event_time=event_time,
                decision_id=request.decision_id,
                risk_decision_id=risk_decision_id,
                model_id=request.model_id,
            )
        except PaperLedgerError as exc:
            self.audit.append(
                "PAPER_FILL_REJECTED",
                {
                    "decision_id": request.decision_id,
                    "risk_decision_id": risk_decision_id,
                    "reason_type": type(exc).__name__,
                    "message": str(exc),
                },
                created_at=event_time,
            )
            return PaperDecisionResult(
                decision_id=request.decision_id,
                risk_decision_id=risk_decision_id,
                risk=risk,
                fill_event_id=None,
                simulated_quantity=0.0,
                status="FILL_REJECTED",
            )

        self.audit.append(
            "PAPER_FILL_RECORDED",
            {
                "decision_id": request.decision_id,
                "risk_decision_id": risk_decision_id,
                "fill_event_id": fill_event_id,
                "ticker": request.ticker,
                "quantity": quantity,
                "price": request.price,
                "commission": commission,
                "simulation_only": True,
            },
            created_at=event_time,
        )
        return PaperDecisionResult(
            decision_id=request.decision_id,
            risk_decision_id=risk_decision_id,
            risk=risk,
            fill_event_id=fill_event_id,
            simulated_quantity=quantity,
            status="PAPER_FILLED",
        )
