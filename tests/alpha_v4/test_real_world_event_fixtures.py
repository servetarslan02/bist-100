"""Real-world sanity fixtures derived from public KAP disclosures.

Facts are intentionally reduced to non-expressive structured data. These tests verify
that ALPHA's event math/lifecycle logic handles an actual tender sequence rather than
only synthetic toy values.
"""

import pytest

from alpha_v4.event_intelligence import (
    BindingStatus,
    CompanyContext,
    ContractFacts,
    analyze_contract_event,
)
from alpha_v4.event_threads import EventStage, EventThreadTracker, ThreadEvent


def test_kap_tender_company_share_math_matches_disclosed_amount():
    # KAP notification 1622639: total sales-revenue offer 36.661bn TRY,
    # company revenue-share ratio 42%, disclosed company share 15.39762bn TRY.
    facts = ContractFacts(
        headline_value=36_661_000_000,
        company_share=0.42,
        duration_months=None,
        binding_status=BindingStatus.TENDER_WIN,
        currency="TRY",
    )
    company = CompanyContext(
        ticker="EKGYO",
        ttm_revenue=None,
        market_cap=None,
    )

    result = analyze_contract_event(company, facts)

    assert result.attributable_value == pytest.approx(15_397_620_000)
    assert result.execution_probability_prior < 0.85  # lower than signed-contract prior
    assert "gross_margin" in result.key_unknowns
    assert "revenue_recognition_timing" in result.key_unknowns


def test_kap_tender_sessions_form_one_event_thread_not_two_positive_events():
    # KAP 1619017 describes the first/prequalification session of the same
    # Kemerburgaz 3rd-stage project later updated by KAP 1622639 with the second
    # session/highest offer. The lifecycle tracker must keep them together.
    tracker = EventThreadTracker()

    first_session = tracker.append(
        ThreadEvent(
            event_id="kap-1619017",
            company_id="EKGYO",
            project_key="istanbul-eyupsultan-kemerburgaz-3-etap",
            event_type="tender_participation",
            stage=EventStage.TENDER_PARTICIPATION,
        )
    )
    second_session = tracker.append(
        ThreadEvent(
            event_id="kap-1622639",
            company_id="EKGYO",
            project_key="istanbul-eyupsultan-kemerburgaz-3-etap",
            event_type="tender_highest_offer",
            stage=EventStage.TENDER_WIN,
        )
    )

    assert first_session.thread_id == second_session.thread_id
    assert second_session.classification == "stage_advance"
    assert second_session.event_ids == ("kap-1619017", "kap-1622639")
