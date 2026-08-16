from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.contracts import RawBar
from alpha_v4.labels import compute_forward_log_return_label, cross_sectional_percentile_labels


UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _bar(ticker, day, close, *, invalid=False):
    timestamp = T0 + timedelta(days=day)
    return RawBar(
        ticker=ticker,
        timestamp=timestamp,
        open=close if not invalid else close + 2,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100_000,
        source_id="provider-a",
        observed_at=timestamp + timedelta(minutes=1),
        is_tradable=True,
    )


def test_forward_label_is_not_usable_at_anchor_time():
    label = compute_forward_log_return_label(
        instrument_id="inst-a",
        anchor_bar=_bar("AAA", 0, 100),
        outcome_bar=_bar("AAA", 5, 110),
        horizon_name="5D",
    )

    assert label.status == "VALID"
    assert not label.usable_at(T0)
    assert not label.usable_at(T0 + timedelta(days=4))
    assert label.usable_at(T0 + timedelta(days=5, minutes=2))


def test_invalid_outcome_is_masked_not_imputed():
    label = compute_forward_log_return_label(
        instrument_id="inst-a",
        anchor_bar=_bar("AAA", 0, 100),
        outcome_bar=_bar("AAA", 5, 110, invalid=True),
        horizon_name="5D",
    )

    assert label.status == "MASKED"
    assert label.value is None


def test_cross_sectional_rank_is_relative_and_not_probability():
    labels = [
        compute_forward_log_return_label(
            instrument_id="a",
            anchor_bar=_bar("A", 0, 100),
            outcome_bar=_bar("A", 5, 90),
            horizon_name="5D",
        ),
        compute_forward_log_return_label(
            instrument_id="b",
            anchor_bar=_bar("B", 0, 100),
            outcome_bar=_bar("B", 5, 100),
            horizon_name="5D",
        ),
        compute_forward_log_return_label(
            instrument_id="c",
            anchor_bar=_bar("C", 0, 100),
            outcome_bar=_bar("C", 5, 120),
            horizon_name="5D",
        ),
    ]

    ranks = cross_sectional_percentile_labels(labels)

    assert ranks == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_cross_sectional_rank_rejects_mixed_windows():
    a = compute_forward_log_return_label(
        instrument_id="a",
        anchor_bar=_bar("A", 0, 100),
        outcome_bar=_bar("A", 5, 110),
        horizon_name="5D",
    )
    b = compute_forward_log_return_label(
        instrument_id="b",
        anchor_bar=_bar("B", 1, 100),
        outcome_bar=_bar("B", 6, 110),
        horizon_name="5D",
    )

    with pytest.raises(ValueError, match="share label and time window"):
        cross_sectional_percentile_labels([a, b])
