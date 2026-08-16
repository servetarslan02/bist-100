from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.relations import RelationStore, RelationVersion

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_relation_requires_evidence():
    with pytest.raises(ValueError, match="evidence"):
        RelationVersion(
            source_entity="company:A",
            relation="SUPPLIES",
            target_entity="company:B",
            effective_from=T0,
            known_at=T0,
            source_event_ids=(),
        )


def test_future_known_supplier_relation_does_not_leak_into_past(tmp_path):
    store = RelationStore(tmp_path / "relations.sqlite3")
    store.append(
        RelationVersion(
            source_entity="company:A",
            relation="SUPPLIES",
            target_entity="company:B",
            effective_from=T0,
            known_at=T0 + timedelta(days=30),
            source_event_ids=("event-1",),
        )
    )

    assert store.outgoing_as_of("company:A", T0 + timedelta(days=10)) == ()
    later = store.outgoing_as_of("company:A", T0 + timedelta(days=31))
    assert len(later) == 1
    assert later[0].target_entity == "company:B"


def test_future_effective_relation_does_not_activate_early_even_if_announced(tmp_path):
    store = RelationStore(tmp_path / "relations.sqlite3")
    store.append(
        RelationVersion(
            source_entity="company:A",
            relation="CUSTOMER_OF",
            target_entity="company:C",
            effective_from=T0 + timedelta(days=60),
            known_at=T0 + timedelta(days=5),
            source_event_ids=("event-2",),
        )
    )

    assert store.outgoing_as_of("company:A", T0 + timedelta(days=30)) == ()
    assert len(store.outgoing_as_of("company:A", T0 + timedelta(days=61))) == 1


def test_relation_correction_is_bitemporal_and_restart_safe(tmp_path):
    db = tmp_path / "relations.sqlite3"
    store = RelationStore(db)
    store.append(
        RelationVersion(
            source_entity="company:A",
            relation="EXPOSED_TO",
            target_entity="commodity:oil",
            effective_from=T0,
            known_at=T0,
            source_event_ids=("old",),
        )
    )
    store.append(
        RelationVersion(
            source_entity="company:A",
            relation="EXPOSED_TO",
            target_entity="commodity:oil",
            effective_from=T0,
            effective_to=T0 + timedelta(days=100),
            known_at=T0 + timedelta(days=20),
            source_event_ids=("correction",),
        )
    )

    before_correction = RelationStore(db).outgoing_as_of(
        "company:A", T0 + timedelta(days=10)
    )
    after_correction = RelationStore(db).outgoing_as_of(
        "company:A", T0 + timedelta(days=30)
    )
    after_end = RelationStore(db).outgoing_as_of("company:A", T0 + timedelta(days=101))

    assert len(before_correction) == 1
    assert before_correction[0].effective_to is None
    assert len(after_correction) == 1
    assert after_correction[0].effective_to == T0 + timedelta(days=100)
    assert after_end == ()
