from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.research_queue import ResearchQueue, ResearchStatus

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_research_task_requires_trigger_evidence(tmp_path):
    queue = ResearchQueue(tmp_path / "research.sqlite3")

    with pytest.raises(ValueError, match="trigger evidence"):
        queue.create(
            created_at=T0,
            trigger_type="MODEL_DRIFT",
            hypothesis="momentum decay",
            experiment_type="walk_forward",
            trigger_evidence_ids=(),
            priority=80,
        )


def test_priority_batching_does_not_delete_long_tail_tasks(tmp_path):
    db = tmp_path / "research.sqlite3"
    queue = ResearchQueue(db)
    for idx, priority in enumerate((10, 90, 50, 70, 30)):
        queue.create(
            task_id=f"t{idx}",
            created_at=T0 + timedelta(minutes=idx),
            trigger_type="UNEXPLAINED_RESIDUAL",
            hypothesis=f"hypothesis-{idx}",
            experiment_type="feature_research",
            trigger_evidence_ids=(f"e{idx}",),
            priority=priority,
        )

    top_two = ResearchQueue(db).pending(limit=2)
    all_tasks = ResearchQueue(db).pending()

    assert [task.priority for task in top_two] == [90, 70]
    assert len(all_tasks) == 5


def test_completed_research_cannot_self_reopen_or_promote(tmp_path):
    queue = ResearchQueue(tmp_path / "research.sqlite3")
    task = queue.create(
        created_at=T0,
        trigger_type="MODEL_DRIFT",
        hypothesis="regime-specialist may improve stability",
        experiment_type="isolated_challenger_research",
        trigger_evidence_ids=("drift-artifact",),
        priority=90,
    )
    queue.transition(
        task.task_id,
        ResearchStatus.RUNNING,
        transitioned_at=T0 + timedelta(minutes=1),
        reason="worker claimed",
    )
    queue.transition(
        task.task_id,
        ResearchStatus.COMPLETED,
        transitioned_at=T0 + timedelta(minutes=2),
        reason="experiment artifact recorded",
    )

    assert queue.pending() == ()
    with pytest.raises(ValueError, match="invalid research transition"):
        queue.transition(
            task.task_id,
            ResearchStatus.RUNNING,
            transitioned_at=T0 + timedelta(minutes=3),
            reason="self reopen",
        )


def test_research_status_survives_restart(tmp_path):
    db = tmp_path / "research.sqlite3"
    queue = ResearchQueue(db)
    task = queue.create(
        created_at=T0,
        trigger_type="SOURCE_FAILURE",
        hypothesis="secondary source can reduce missingness",
        experiment_type="source_reliability_study",
        trigger_evidence_ids=("source-incident",),
        priority=60,
    )
    queue.transition(
        task.task_id,
        ResearchStatus.BLOCKED,
        transitioned_at=T0 + timedelta(minutes=1),
        reason="credential unavailable",
    )

    pending = ResearchQueue(db).pending()

    assert len(pending) == 1
    assert pending[0].status is ResearchStatus.BLOCKED
