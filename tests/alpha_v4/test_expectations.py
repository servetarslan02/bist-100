from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.expectations import (
    NumericExpectation,
    NumericObservation,
    compare_expectation,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def expectation(value, known_minutes=-60):
    return NumericExpectation(
        metric="net_income",
        expected_value=value,
        known_at=T0 + timedelta(minutes=known_minutes),
        source_event_ids=("expectation-source",),
    )


def observation(value):
    return NumericObservation(
        metric="net_income",
        observed_value=value,
        event_time=T0,
        known_at=T0 + timedelta(minutes=1),
        source_event_ids=("financial-report",),
    )


def test_above_expectation_is_measured_relative_to_pre_event_baseline():
    result = compare_expectation(
        expectation(100.0),
        observation(120.0),
        absolute_tolerance=2.0,
    )

    assert result.absolute_surprise == pytest.approx(20.0)
    assert result.relative_surprise == pytest.approx(0.20)
    assert result.classification == "ABOVE_EXPECTATION"


def test_good_absolute_number_can_still_be_below_expectation():
    result = compare_expectation(
        expectation(150.0),
        observation(120.0),
        absolute_tolerance=2.0,
    )

    assert result.observed_value > 0
    assert result.classification == "BELOW_EXPECTATION"


def test_post_event_expectation_is_rejected_as_hindsight():
    late = expectation(100.0, known_minutes=1)

    with pytest.raises(ValueError, match="known before event_time"):
        compare_expectation(late, observation(120.0), absolute_tolerance=1.0)


def test_zero_expected_value_does_not_fake_relative_surprise():
    result = compare_expectation(
        expectation(0.0),
        observation(10.0),
        absolute_tolerance=0.0,
    )

    assert result.absolute_surprise == 10.0
    assert result.relative_surprise is None
    assert result.classification == "ABOVE_EXPECTATION"


def test_tolerance_is_explicit_policy_not_hidden_magic_number():
    tight = compare_expectation(expectation(100.0), observation(101.0), absolute_tolerance=0.5)
    loose = compare_expectation(expectation(100.0), observation(101.0), absolute_tolerance=2.0)

    assert tight.classification == "ABOVE_EXPECTATION"
    assert loose.classification == "IN_LINE"
