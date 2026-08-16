from datetime import datetime, timedelta, timezone

from alpha_v4.state import StateSnapshot, StateStore

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_state_snapshot_is_point_in_time_and_restart_safe(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = StateStore(db)
    old = StateSnapshot(
        state_type="CompanyState",
        entity_id="TEST",
        effective_at=T0,
        known_at=T0,
        payload={"backlog": 100},
        source_event_ids=("e1",),
    )
    future_known = StateSnapshot(
        state_type="CompanyState",
        entity_id="TEST",
        effective_at=T0,
        known_at=T0 + timedelta(hours=2),
        payload={"backlog": 200},
        source_event_ids=("e2",),
    )
    store.append(old)
    store.append(future_known)

    historical = StateStore(db).as_of("CompanyState", "TEST", T0 + timedelta(hours=1))
    later = StateStore(db).as_of("CompanyState", "TEST", T0 + timedelta(hours=3))

    assert historical is not None
    assert historical.payload["backlog"] == 100
    assert later is not None
    assert later.payload["backlog"] == 200


def test_state_snapshot_requires_provenance():
    try:
        StateSnapshot(
            state_type="MarketState",
            entity_id="BIST",
            effective_at=T0,
            known_at=T0,
            payload={"regime": "UNKNOWN"},
            source_event_ids=(),
        )
    except ValueError as exc:
        assert "source_event_ids" in str(exc)
    else:
        raise AssertionError("state without provenance should fail")


def test_snapshot_id_is_deterministic():
    kwargs = {
        "state_type": "MarketState",
        "entity_id": "BIST",
        "effective_at": T0,
        "known_at": T0,
        "payload": {"breadth": 0.55, "regime": "RANGE"},
        "source_event_ids": ("e1", "e2"),
    }
    assert StateSnapshot(**kwargs).snapshot_id == StateSnapshot(**kwargs).snapshot_id
