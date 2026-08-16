"""Deterministic event-understanding primitives for ALPHA v4.

LLMs may extract these facts later, but the financial interpretation contract remains
structured, evidence-linked and testable. There is intentionally no single
``news_score`` output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


class BindingStatus(str, Enum):
    RUMOR = "rumor"
    INTENTION = "intention"
    MOU = "memorandum_of_understanding"
    TENDER_WIN = "tender_win"
    SIGNED = "signed_contract"
    APPROVED = "regulatory_approved"
    EXECUTING = "execution_started"


_EXECUTION_PRIOR = {
    BindingStatus.RUMOR: 0.10,
    BindingStatus.INTENTION: 0.25,
    BindingStatus.MOU: 0.40,
    BindingStatus.TENDER_WIN: 0.65,
    BindingStatus.SIGNED: 0.85,
    BindingStatus.APPROVED: 0.93,
    BindingStatus.EXECUTING: 0.98,
}


@dataclass(frozen=True)
class CompanyContext:
    ticker: str
    ttm_revenue: Optional[float]
    market_cap: Optional[float]
    backlog: Optional[float] = None
    ebitda: Optional[float] = None
    free_cash_flow: Optional[float] = None
    cash: Optional[float] = None


@dataclass(frozen=True)
class ContractFacts:
    headline_value: Optional[float]
    company_share: Optional[float]
    duration_months: Optional[int]
    binding_status: BindingStatus
    expected_gross_margin: Optional[float] = None
    capex_required: Optional[float] = None
    advance_payment: Optional[float] = None
    currency: Optional[str] = None
    previously_announced: bool = False

    def attributable_value(self) -> Optional[float]:
        if self.headline_value is None:
            return None
        if self.company_share is None:
            return self.headline_value
        if not 0 <= self.company_share <= 1:
            raise ValueError("company_share must be between 0 and 1")
        return self.headline_value * self.company_share


@dataclass(frozen=True)
class ContractInterpretation:
    attributable_value: Optional[float]
    execution_probability_prior: float
    materiality: Dict[str, Optional[float]]
    novelty_state: str
    key_unknowns: Tuple[str, ...]
    cautions: Tuple[str, ...]


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def analyze_contract_event(company: CompanyContext, facts: ContractFacts) -> ContractInterpretation:
    """Interpret contract economics without collapsing them into a sentiment score."""
    value = facts.attributable_value()
    expected_gross_profit = None
    if value is not None and facts.expected_gross_margin is not None:
        if not 0 <= facts.expected_gross_margin <= 1:
            raise ValueError("expected_gross_margin must be between 0 and 1")
        expected_gross_profit = value * facts.expected_gross_margin

    materiality = {
        "revenue_ratio": _safe_ratio(value, company.ttm_revenue),
        "market_cap_ratio": _safe_ratio(value, company.market_cap),
        "backlog_ratio": _safe_ratio(value, company.backlog),
        "gross_profit_to_ebitda": _safe_ratio(expected_gross_profit, company.ebitda),
        "capex_to_cash": _safe_ratio(facts.capex_required, company.cash),
        "advance_to_contract": _safe_ratio(facts.advance_payment, value),
    }

    unknowns = []
    if facts.headline_value is None:
        unknowns.append("contract_value")
    if facts.company_share is None:
        unknowns.append("company_share")
    if facts.duration_months is None:
        unknowns.append("revenue_recognition_timing")
    if facts.expected_gross_margin is None:
        unknowns.append("gross_margin")
    if facts.capex_required is None:
        unknowns.append("capex_requirement")
    if facts.currency is None:
        unknowns.append("currency")

    cautions = []
    if facts.binding_status in {BindingStatus.RUMOR, BindingStatus.INTENTION, BindingStatus.MOU}:
        cautions.append("not_fully_binding")
    if facts.previously_announced:
        cautions.append("potentially_already_known")
    if materiality["capex_to_cash"] is not None and materiality["capex_to_cash"] > 1:
        cautions.append("capex_exceeds_current_cash")

    novelty_state = "previously_known" if facts.previously_announced else "new_information"

    return ContractInterpretation(
        attributable_value=value,
        execution_probability_prior=_EXECUTION_PRIOR[facts.binding_status],
        materiality=materiality,
        novelty_state=novelty_state,
        key_unknowns=tuple(unknowns),
        cautions=tuple(cautions),
    )
