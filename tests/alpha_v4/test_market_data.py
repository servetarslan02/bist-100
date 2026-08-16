from datetime import datetime, timedelta, timezone

from alpha_v4.contracts import RawBar
from alpha_v4.market_data import RawBarStore


UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _bar(timestamp, observed_at, close, *, high=None, low=None, source_id="p1"):
    return RawBar(
        ticker="AAA",
        timestamp=timestamp,
        open=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=100_000,
        source_id=source_id,
        observed_at=observed_at,
        is_tradable=True,
    )


def test_late_correction_does_not_rewrite_earlier_decision_view(tmp_path):
    store = RawBarStore(tmp_path / "market.sqlite3")
    bar_time = T0
    original = _bar(bar_time, T0 + timedelta(minutes=1), 100.0)
    corrected = _bar(bar_time, T0 + timedelta(hours=2), 110.0)
    store.append(original)
    store.append(corrected)

    early_view = store.bars_as_of("AAA", T0 + timedelta(minutes=30))
    late_view = store.bars_as_of("AAA", T0 + timedelta(hours=3))

    assert early_view[0].close == 100.0
    assert late_view[0].close == 110.0


def test_future_timestamp_is_not_visible(tmp_path):
    store = RawBarStore(tmp_path / "market.sqlite3")
    store.append(_bar(T0 + timedelta(days=1), T0, 100.0))

    assert store.bars_as_of("AAA", T0 + timedelta(hours=1)) == ()


def test_invalid_middle_bar_cannot_contaminate_masked_returns(tmp_path):
    store = RawBarStore(tmp_path / "market.sqlite3")
    store.append(_bar(T0, T0 + timedelta(seconds=1), 100.0))
    store.append(
        RawBar(
            ticker="AAA",
            timestamp=T0 + timedelta(days=1),
            open=101.0,
            high=100.0,
            low=99.0,
            close=100.0,
            volume=100_000,
            source_id="p1",
            observed_at=T0 + timedelta(days=1, seconds=1),
            is_tradable=True,
        )
    )
    store.append(_bar(T0 + timedelta(days=2), T0 + timedelta(days=2, seconds=1), 103.0))

    result = store.masked_returns_as_of(
        "AAA",
        T0 + timedelta(days=2, minutes=1),
        freshness_limit=timedelta(days=10),
    )

    assert result == [None, None, None]


def test_store_is_restart_safe(tmp_path):
    db = tmp_path / "market.sqlite3"
    RawBarStore(db).append(_bar(T0, T0 + timedelta(seconds=1), 100.0))

    restarted = RawBarStore(db)
    bars = restarted.bars_as_of("AAA", T0 + timedelta(hours=1))

    assert len(bars) == 1
    assert bars[0].close == 100.0
