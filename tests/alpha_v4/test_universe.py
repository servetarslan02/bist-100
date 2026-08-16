from datetime import datetime, timedelta, timezone

from alpha_v4.universe import InstrumentVersion, UniverseMembershipVersion, UniverseStore


UTC = timezone.utc
T0 = datetime(2020, 1, 1, tzinfo=UTC)


def test_ticker_change_is_point_in_time(tmp_path):
    store = UniverseStore(tmp_path / "universe.sqlite3")
    store.append_instrument(
        InstrumentVersion(
            instrument_id="inst-1",
            company_id="co-1",
            symbol="OLD",
            effective_from=T0,
            known_at=T0,
            listed_at=T0,
            delisted_at=None,
            sector="X",
            source_event_id="e-old",
        )
    )
    store.append_instrument(
        InstrumentVersion(
            instrument_id="inst-1",
            company_id="co-1",
            symbol="NEW",
            effective_from=T0 + timedelta(days=365),
            known_at=T0 + timedelta(days=365),
            listed_at=T0,
            delisted_at=None,
            sector="X",
            source_event_id="e-new",
        )
    )

    before = store.instruments_as_of(T0 + timedelta(days=100))
    after = store.instruments_as_of(T0 + timedelta(days=400))

    assert [item.symbol for item in before] == ["OLD"]
    assert [item.symbol for item in after] == ["NEW"]


def test_future_known_revision_does_not_rewrite_history(tmp_path):
    store = UniverseStore(tmp_path / "universe.sqlite3")
    store.append_instrument(
        InstrumentVersion(
            instrument_id="inst-1",
            company_id="co-1",
            symbol="AAA",
            effective_from=T0,
            known_at=T0,
            listed_at=T0,
            delisted_at=None,
            sector="OLD_SECTOR",
            source_event_id="e1",
        )
    )
    store.append_instrument(
        InstrumentVersion(
            instrument_id="inst-1",
            company_id="co-1",
            symbol="AAA",
            effective_from=T0,
            known_at=T0 + timedelta(days=100),
            listed_at=T0,
            delisted_at=None,
            sector="CORRECTED_SECTOR",
            source_event_id="e2",
        )
    )

    historical = store.instruments_as_of(T0 + timedelta(days=50))
    later = store.instruments_as_of(T0 + timedelta(days=150))

    assert historical[0].sector == "OLD_SECTOR"
    assert later[0].sector == "CORRECTED_SECTOR"


def test_delisted_security_exits_active_universe(tmp_path):
    store = UniverseStore(tmp_path / "universe.sqlite3")
    delist = T0 + timedelta(days=200)
    store.append_instrument(
        InstrumentVersion(
            instrument_id="inst-1",
            company_id="co-1",
            symbol="AAA",
            effective_from=T0,
            known_at=T0,
            listed_at=T0,
            delisted_at=delist,
            sector=None,
            source_event_id="e1",
        )
    )

    assert len(store.instruments_as_of(T0 + timedelta(days=100))) == 1
    assert len(store.instruments_as_of(T0 + timedelta(days=250))) == 0


def test_no_hidden_business_level_universe_cap(tmp_path):
    store = UniverseStore(tmp_path / "universe.sqlite3")
    for idx in range(650):
        store.append_instrument(
            InstrumentVersion(
                instrument_id=f"inst-{idx:04d}",
                company_id=f"co-{idx:04d}",
                symbol=f"S{idx:04d}",
                effective_from=T0,
                known_at=T0,
                listed_at=T0,
                delisted_at=None,
                sector=None,
                source_event_id=f"e-{idx:04d}",
            )
        )

    snapshot = store.instruments_as_of(T0 + timedelta(days=1))

    assert len(snapshot) == 650


def test_historical_index_membership_is_time_aware(tmp_path):
    store = UniverseStore(tmp_path / "universe.sqlite3")
    store.append_membership(
        UniverseMembershipVersion(
            universe_name="BIST100",
            instrument_id="inst-a",
            effective_from=T0,
            effective_to=T0 + timedelta(days=180),
            known_at=T0,
            source_event_id="m1",
        )
    )
    store.append_membership(
        UniverseMembershipVersion(
            universe_name="BIST100",
            instrument_id="inst-b",
            effective_from=T0 + timedelta(days=180),
            effective_to=None,
            known_at=T0 + timedelta(days=170),
            source_event_id="m2",
        )
    )

    assert store.members_as_of("BIST100", T0 + timedelta(days=100)) == ("inst-a",)
    assert store.members_as_of("BIST100", T0 + timedelta(days=200)) == ("inst-b",)
