from datetime import datetime, timedelta, timezone
from math import log

import pytest

from alpha_v4.contracts import RawBar
from alpha_v4.features import FeatureRecord, FeatureStore, compute_log_return_feature
from alpha_v4.market_data import RawBarStore

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _append(store, day, close, *, invalid=False):
    ts = T0 + timedelta(days=day)
    store.append(
        RawBar(
            ticker="AAA",
            timestamp=ts,
            open=close if not invalid else close + 2,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=100_000,
            source_id="provider-a",
            observed_at=ts + timedelta(minutes=1),
            is_tradable=True,
        )
    )


def test_log_return_feature_uses_only_data_known_by_decision_time(tmp_path):
    market = RawBarStore(tmp_path / "market.sqlite3")
    _append(market, 0, 100)
    _append(market, 1, 105)
    _append(market, 2, 120)

    record = compute_log_return_feature(
        market,
        ticker="AAA",
        instrument_id="inst-a",
        decision_time=T0 + timedelta(days=1, minutes=5),
        lookback_bars=1,
    )

    assert record.status == "VALID"
    assert record.value == pytest.approx(log(105 / 100))
    assert record.effective_at == T0 + timedelta(days=1)


def test_invalid_intermediate_bar_masks_feature(tmp_path):
    market = RawBarStore(tmp_path / "market.sqlite3")
    _append(market, 0, 100)
    _append(market, 1, 102, invalid=True)
    _append(market, 2, 104)

    record = compute_log_return_feature(
        market,
        ticker="AAA",
        instrument_id="inst-a",
        decision_time=T0 + timedelta(days=2, minutes=5),
        lookback_bars=2,
    )

    assert record.status == "MASKED"
    assert record.value is None


def test_insufficient_data_does_not_fabricate_source(tmp_path):
    market = RawBarStore(tmp_path / "market.sqlite3")

    record = compute_log_return_feature(
        market,
        ticker="AAA",
        instrument_id="inst-a",
        decision_time=T0,
        lookback_bars=5,
    )

    assert record.status == "INSUFFICIENT_DATA"
    assert record.source_ids == ()
    assert record.input_timestamps == ()


def test_computed_feature_requires_real_provenance():
    with pytest.raises(ValueError, match="provenance"):
        FeatureRecord(
            instrument_id="inst-a",
            feature_id="f@1",
            value=1.0,
            effective_at=T0,
            known_at=T0,
            source_ids=(),
            input_timestamps=(T0,),
            status="VALID",
        )


def test_feature_store_is_point_in_time(tmp_path):
    store = FeatureStore(tmp_path / "features.sqlite3")
    early = FeatureRecord(
        instrument_id="inst-a",
        feature_id="f@1",
        value=1.0,
        effective_at=T0,
        known_at=T0,
        source_ids=("p1",),
        input_timestamps=(T0,),
        status="VALID",
    )
    correction = FeatureRecord(
        instrument_id="inst-a",
        feature_id="f@1",
        value=2.0,
        effective_at=T0,
        known_at=T0 + timedelta(days=1),
        source_ids=("p1",),
        input_timestamps=(T0,),
        status="VALID",
    )
    store.append(early)
    store.append(correction)

    before = store.as_of("inst-a", "f@1", T0 + timedelta(hours=1))
    after = store.as_of("inst-a", "f@1", T0 + timedelta(days=2))

    assert before is not None and before.value == 1.0
    assert after is not None and after.value == 2.0
