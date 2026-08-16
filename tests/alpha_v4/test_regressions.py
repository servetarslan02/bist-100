from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.company_memory import CompanyMemory, CompanySnapshot
from alpha_v4.contracts import CanonicalEvent, EvidenceRef, RawBar, ValidationStatus
from alpha_v4.data_quality import masked_log_returns, validate_raw_bar

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _evidence():
    return EvidenceRef(
        source_id="kap",
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=1),
        locator="kap://regression",
    )


def test_canonical_event_nested_payload_order_does_not_change_id():
    base = {
        "event_type": "contract_award",
        "source_id": "kap",
        "source_timestamp": T0,
        "ingest_timestamp": T0 + timedelta(minutes=1),
        "effective_timestamp": T0,
        "entities": ("TEST",),
        "evidence": (_evidence(),),
    }
    first = CanonicalEvent(
        **base,
        payload={"terms": {"currency": "TRY", "value": 100}, "flags": ["a", "b"]},
    )
    second = CanonicalEvent(
        **base,
        payload={"flags": ["a", "b"], "terms": {"value": 100, "currency": "TRY"}},
    )

    assert first.event_id == second.event_id


def test_canonical_event_rejects_non_json_payload():
    with pytest.raises(ValueError, match="JSON-serializable"):
        CanonicalEvent(
            event_type="bad",
            source_id="kap",
            source_timestamp=T0,
            ingest_timestamp=T0 + timedelta(minutes=1),
            effective_timestamp=T0,
            entities=("TEST",),
            payload={"bad": {1, 2, 3}},
            evidence=(_evidence(),),
        )


def test_old_historical_bars_are_valid_for_lookback_even_when_current_freshness_is_short():
    bars = []
    for day in range(20):
        timestamp = T0 - timedelta(days=19 - day)
        close = 100.0 + day
        bars.append(
            RawBar(
                ticker="TEST",
                timestamp=timestamp,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=100_000,
                source_id="provider",
                observed_at=timestamp + timedelta(minutes=1),
                is_tradable=True,
            )
        )

    returns = masked_log_returns(
        bars,
        decision_time=T0 + timedelta(hours=1),
        freshness_limit=timedelta(days=2),
    )

    assert returns[0] is None
    assert all(value is not None for value in returns[1:])


def test_serving_freshness_still_marks_old_latest_observation_stale():
    old = RawBar(
        ticker="TEST",
        timestamp=T0 - timedelta(days=10),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=100_000,
        source_id="provider",
        observed_at=T0 - timedelta(days=10),
        is_tradable=True,
    )

    validation = validate_raw_bar(
        old,
        decision_time=T0,
        freshness_limit=timedelta(days=2),
        enforce_freshness=True,
    )

    assert validation.status is ValidationStatus.STALE


def test_company_memory_does_not_apply_future_effective_fact_early():
    memory = CompanyMemory(
        [
            CompanySnapshot(
                company_id="TEST",
                effective_at=T0,
                known_at=T0,
                values={"capacity": 100},
                source_event_ids=("e1",),
            ),
            CompanySnapshot(
                company_id="TEST",
                effective_at=T0 + timedelta(days=30),
                known_at=T0 + timedelta(days=1),
                values={"capacity": 200},
                source_event_ids=("e2",),
            ),
        ]
    )

    before_effective = memory.as_of("TEST", T0 + timedelta(days=10))
    after_effective = memory.as_of("TEST", T0 + timedelta(days=31))

    assert before_effective is not None
    assert before_effective.values["capacity"] == 100
    assert after_effective is not None
    assert after_effective.values["capacity"] == 200
