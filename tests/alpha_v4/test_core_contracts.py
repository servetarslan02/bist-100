from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.contracts import CanonicalEvent, EvidenceRef, RawBar, ValidationStatus
from alpha_v4.data_quality import masked_log_returns, validate_raw_bar
from alpha_v4.event_intelligence import (
    BindingStatus,
    CompanyContext,
    ContractFacts,
    analyze_contract_event,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _bar(**overrides):
    base = dict(
        ticker="TEST",
        timestamp=T0,
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=100_000.0,
        source_id="provider-a",
        observed_at=T0 + timedelta(minutes=1),
        is_tradable=True,
    )
    base.update(overrides)
    return RawBar(**base)


def test_canonical_event_is_point_in_time_and_deterministic():
    evidence = EvidenceRef(
        source_id="kap",
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=2),
        locator="kap://disclosure/123",
        evidence_text="signed contract",
    )
    kwargs = dict(
        event_type="contract_award",
        source_id="kap",
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=2),
        effective_timestamp=T0,
        entities=("TEST",),
        payload={"value": 1000, "currency": "TRY"},
        evidence=(evidence,),
    )
    event_a = CanonicalEvent(**kwargs)
    event_b = CanonicalEvent(**kwargs)

    assert event_a.event_id == event_b.event_id
    assert not event_a.was_known_at(T0 + timedelta(minutes=1))
    assert event_a.was_known_at(T0 + timedelta(minutes=2))


def test_evidence_rejects_impossible_ingest_order():
    with pytest.raises(ValueError):
        EvidenceRef(
            source_id="kap",
            source_timestamp=T0,
            ingest_timestamp=T0 - timedelta(seconds=1),
            locator="kap://bad",
        )


def test_raw_validation_rejects_invalid_ohlc_before_features():
    bad = _bar(low=106.0, high=105.0)
    result = validate_raw_bar(bad, decision_time=T0 + timedelta(minutes=5))

    assert result.status is ValidationStatus.INVALID
    assert not result.usable_for_features
    assert "low_above_high" in result.reasons


def test_raw_validation_rejects_not_yet_known_observation():
    future_observed = _bar(observed_at=T0 + timedelta(hours=1))
    result = validate_raw_bar(future_observed, decision_time=T0 + timedelta(minutes=5))

    assert result.status is ValidationStatus.NOT_YET_KNOWN


def test_masked_returns_do_not_bridge_across_invalid_observation():
    bars = [
        _bar(timestamp=T0, observed_at=T0 + timedelta(seconds=5), close=100.0),
        _bar(
            timestamp=T0 + timedelta(days=1),
            observed_at=T0 + timedelta(days=1, seconds=5),
            open=101.0,
            high=100.0,
            low=99.0,
            close=100.0,
        ),
        _bar(
            timestamp=T0 + timedelta(days=2),
            observed_at=T0 + timedelta(days=2, seconds=5),
            open=102.0,
            high=104.0,
            low=101.0,
            close=103.0,
        ),
    ]

    returns = masked_log_returns(
        bars,
        decision_time=T0 + timedelta(days=2, minutes=1),
        freshness_limit=timedelta(days=10),
    )

    assert returns == [None, None, None]


def test_contract_materiality_is_relative_to_company_scale():
    facts = ContractFacts(
        headline_value=1_000_000_000,
        company_share=1.0,
        duration_months=24,
        binding_status=BindingStatus.SIGNED,
        expected_gross_margin=0.20,
        currency="TRY",
    )
    small = CompanyContext(
        ticker="SMALL",
        ttm_revenue=2_000_000_000,
        market_cap=3_000_000_000,
        backlog=1_000_000_000,
        ebitda=400_000_000,
    )
    large = CompanyContext(
        ticker="LARGE",
        ttm_revenue=100_000_000_000,
        market_cap=200_000_000_000,
        backlog=50_000_000_000,
        ebitda=20_000_000_000,
    )

    small_result = analyze_contract_event(small, facts)
    large_result = analyze_contract_event(large, facts)

    assert small_result.materiality["revenue_ratio"] == pytest.approx(0.5)
    assert large_result.materiality["revenue_ratio"] == pytest.approx(0.01)
    assert small_result.materiality["gross_profit_to_ebitda"] > large_result.materiality["gross_profit_to_ebitda"]


def test_contract_interpretation_does_not_fake_missing_financials():
    company = CompanyContext(ticker="TEST", ttm_revenue=None, market_cap=None)
    facts = ContractFacts(
        headline_value=500_000_000,
        company_share=None,
        duration_months=None,
        binding_status=BindingStatus.MOU,
        previously_announced=True,
    )

    result = analyze_contract_event(company, facts)

    assert result.materiality["revenue_ratio"] is None
    assert result.materiality["market_cap_ratio"] is None
    assert "gross_margin" in result.key_unknowns
    assert "revenue_recognition_timing" in result.key_unknowns
    assert "not_fully_binding" in result.cautions
    assert "potentially_already_known" in result.cautions
    assert result.novelty_state == "previously_known"
    assert result.execution_probability_prior < 0.5


def test_company_share_out_of_range_is_rejected():
    company = CompanyContext(ticker="TEST", ttm_revenue=1_000, market_cap=1_000)
    facts = ContractFacts(
        headline_value=100,
        company_share=1.5,
        duration_months=12,
        binding_status=BindingStatus.SIGNED,
    )

    with pytest.raises(ValueError):
        analyze_contract_event(company, facts)
