from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.contracts import CanonicalEvent, EvidenceRef
from alpha_v4.reaction import classify_reaction
from alpha_v4.source_registry import SourceKind, SourceRecord, SourceRegistry
from alpha_v4.storage import AppendOnlyEventStore, DuplicateEventError

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _event(ingest_delay_minutes: int = 2) -> CanonicalEvent:
    evidence = EvidenceRef(
        source_id="kap",
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=ingest_delay_minutes),
        locator=f"kap://event/{ingest_delay_minutes}",
        evidence_text="contract signed",
    )
    return CanonicalEvent(
        event_type="contract_award",
        source_id="kap",
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=ingest_delay_minutes),
        effective_timestamp=T0,
        entities=("TEST",),
        payload={"value": ingest_delay_minutes * 1000},
        evidence=(evidence,),
    )


def test_event_store_survives_restart(tmp_path):
    database = tmp_path / "events.sqlite3"
    first = AppendOnlyEventStore(database)
    event = _event()
    first.append(event)
    assert first.count() == 1

    restarted = AppendOnlyEventStore(database)
    loaded = restarted.get(event.event_id)

    assert restarted.count() == 1
    assert loaded == event


def test_event_store_is_append_only_by_event_id(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "events.sqlite3")
    event = _event()
    store.append(event)

    with pytest.raises(DuplicateEventError):
        store.append(event)

    assert store.count() == 1


def test_event_store_point_in_time_query_excludes_late_ingest(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "events.sqlite3")
    early = _event(2)
    late = _event(20)
    store.append(early)
    store.append(late)

    known = store.list_known_at(T0 + timedelta(minutes=10))

    assert [event.event_id for event in known] == [early.event_id]


def test_positive_raw_return_can_still_be_negative_relative_reaction():
    reaction = classify_reaction(
        asset_return=0.002,
        benchmark_return=0.020,
        sector_return=0.030,
        expected_direction="POSITIVE",
    )

    assert reaction.asset_return > 0
    assert reaction.benchmark_relative < 0
    assert reaction.sector_relative < 0
    assert reaction.interpretation == "good_news_sold_or_rejected"


def test_bad_news_can_be_absorbed_by_market():
    reaction = classify_reaction(
        asset_return=0.010,
        benchmark_return=0.0,
        sector_return=0.002,
        expected_direction="NEGATIVE",
    )

    assert reaction.interpretation == "bad_news_absorbed"


def test_source_reliability_is_measured_not_invented():
    registry = SourceRegistry(
        [
            SourceRecord(
                source_id="kap",
                kind=SourceKind.KAP,
                owner="KAP",
                access_method="official",
                timezone_name="Europe/Istanbul",
                freshness_limit=timedelta(minutes=5),
            )
        ]
    )

    assert registry.get("kap").measured_reliability is None
    registry.record_success("kap")
    registry.record_success("kap")
    registry.record_failure("kap")
    registry.record_contradiction("kap")

    assert registry.get("kap").measured_reliability == pytest.approx(0.5)


def test_source_registry_rejects_duplicate_identity():
    record = SourceRecord(
        source_id="kap",
        kind=SourceKind.KAP,
        owner="KAP",
        access_method="official",
        timezone_name="Europe/Istanbul",
        freshness_limit=timedelta(minutes=5),
    )
    registry = SourceRegistry([record])

    with pytest.raises(ValueError):
        registry.register(record)
