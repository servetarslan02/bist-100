from datetime import datetime, timedelta, timezone

from alpha_v4.company_memory import CompanyMemory, CompanySnapshot
from alpha_v4.event_threads import EventStage, EventThreadTracker, ThreadEvent


UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_company_memory_never_uses_future_known_snapshot():
    memory = CompanyMemory(
        [
            CompanySnapshot(
                company_id="TEST",
                effective_at=T0 - timedelta(days=30),
                known_at=T0,
                values={"ttm_revenue": 1_000},
                source_event_ids=("old",),
            ),
            CompanySnapshot(
                company_id="TEST",
                effective_at=T0 - timedelta(days=1),
                known_at=T0 + timedelta(hours=2),
                values={"ttm_revenue": 2_000},
                source_event_ids=("new",),
            ),
        ]
    )

    before_publication = memory.as_of("TEST", T0 + timedelta(hours=1))
    after_publication = memory.as_of("TEST", T0 + timedelta(hours=3))

    assert before_publication is not None
    assert before_publication.values["ttm_revenue"] == 1_000
    assert after_publication is not None
    assert after_publication.values["ttm_revenue"] == 2_000


def test_company_snapshot_requires_provenance():
    try:
        CompanySnapshot(
            company_id="TEST",
            effective_at=T0,
            known_at=T0,
            values={"ttm_revenue": 1_000},
            source_event_ids=(),
        )
    except ValueError as exc:
        assert "source_event_ids" in str(exc)
    else:
        raise AssertionError("snapshot without provenance should fail")


def test_event_thread_tracks_lifecycle_instead_of_double_counting():
    tracker = EventThreadTracker()
    tender = ThreadEvent(
        event_id="e1",
        company_id="TEST",
        project_key="project-alpha",
        event_type="tender_win",
        stage=EventStage.TENDER_WIN,
    )
    contract = ThreadEvent(
        event_id="e2",
        company_id="TEST",
        project_key="project-alpha",
        event_type="contract_award",
        stage=EventStage.SIGNED_CONTRACT,
    )

    first = tracker.append(tender)
    second = tracker.append(contract)
    duplicate = tracker.append(contract)

    assert first.classification == "new_thread"
    assert second.classification == "stage_advance"
    assert second.event_ids == ("e1", "e2")
    assert duplicate.classification == "duplicate_event"
    assert duplicate.event_ids == ("e1", "e2")


def test_event_thread_keeps_different_projects_separate():
    tracker = EventThreadTracker()
    a = tracker.append(
        ThreadEvent(
            event_id="a",
            company_id="TEST",
            project_key="project-a",
            event_type="contract_award",
            stage=EventStage.SIGNED_CONTRACT,
        )
    )
    b = tracker.append(
        ThreadEvent(
            event_id="b",
            company_id="TEST",
            project_key="project-b",
            event_type="contract_award",
            stage=EventStage.SIGNED_CONTRACT,
        )
    )

    assert a.thread_id != b.thread_id
