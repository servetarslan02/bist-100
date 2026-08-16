from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.performance import EquityPoint, summarize_performance

UTC = timezone.utc
T0 = datetime(2025, 1, 1, tzinfo=UTC)


def point(days, equity):
    return EquityPoint(timestamp=T0 + timedelta(days=days), equity=equity)


def test_total_return_and_cagr_are_not_the_same_metric():
    summary = summarize_performance(
        [point(0, 100.0), point(365, 121.0), point(730, 144.0)],
        periods_per_year=1,
    )

    assert summary.total_return == pytest.approx(0.44)
    assert summary.cagr == pytest.approx(0.20, rel=0.01)
    assert summary.total_return != pytest.approx(summary.cagr)


def test_max_drawdown_tracks_peak_and_trough_times():
    summary = summarize_performance(
        [
            point(0, 100.0),
            point(1, 120.0),
            point(2, 90.0),
            point(3, 95.0),
            point(4, 130.0),
        ],
        periods_per_year=252,
    )

    assert summary.max_drawdown == pytest.approx(0.25)
    assert summary.max_drawdown_start == T0 + timedelta(days=1)
    assert summary.max_drawdown_end == T0 + timedelta(days=2)


def test_volatility_and_sharpe_require_enough_observations():
    summary = summarize_performance(
        [point(0, 100.0), point(1, 101.0)],
        periods_per_year=252,
    )

    assert summary.annualized_volatility is None
    assert summary.sharpe is None
    assert summary.sortino is None


def test_flat_identical_returns_do_not_fabricate_infinite_sharpe():
    summary = summarize_performance(
        [point(0, 100.0), point(1, 101.0), point(2, 102.01), point(3, 103.0301)],
        periods_per_year=252,
    )

    # Floating arithmetic may leave an extremely tiny standard deviation; any finite
    # numerical value is acceptable, but we never emit infinity.
    assert summary.sharpe is None or abs(summary.sharpe) < 1e16


def test_sortino_is_available_when_downside_returns_exist():
    summary = summarize_performance(
        [point(0, 100), point(1, 110), point(2, 100), point(3, 115), point(4, 105)],
        periods_per_year=252,
    )

    assert summary.sortino is not None
    assert summary.annualized_volatility is not None


def test_duplicate_timestamps_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        summarize_performance(
            [
                EquityPoint(T0, 100),
                EquityPoint(T0, 101),
            ],
            periods_per_year=252,
        )
