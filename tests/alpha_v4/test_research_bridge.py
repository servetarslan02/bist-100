from datetime import datetime, timezone

from alpha_v4.drift import DriftAssessment
from alpha_v4.research_bridge import enqueue_drift_research
from alpha_v4.research_queue import ResearchQueue, ResearchStatus


UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def assessment(detected):
    return DriftAssessment(
        status="DRIFT" if detected else "STABLE",
        detected=detected,
        reference_count=100,
        recent_count=20,
        reference_mean=0.0,
        recent_mean=1.0 if detected else 0.0,
        standardized_mean_shift=3.0 if detected else 0.0,
        std_ratio=1.2,
        reasons=("standardized_mean_shift_exceeded",) if detected else (),
        policy_version="1.0",
    )


def test_detected_drift_creates_evidence_backed_research_task(tmp_path):
    queue = ResearchQueue(tmp_path / "research.sqlite3")

    task = enqueue_drift_research(
        queue,
        assessment(True),
        evidence_id="drift-artifact-1",
        subject="feature:momentum_20d",
        created_at=T0,
        priority=85,
    )

    assert task is not None
    assert task.status is ResearchStatus.NEW
    assert task.trigger_evidence_ids == ("drift-artifact-1",)
    assert task.experiment_type == "drift_diagnosis"
    assert queue.pending()[0].task_id == task.task_id


def test_stable_distribution_does_not_create_busywork_task(tmp_path):
    queue = ResearchQueue(tmp_path / "research.sqlite3")

    task = enqueue_drift_research(
        queue,
        assessment(False),
        evidence_id="stable-artifact",
        subject="feature:momentum_20d",
        created_at=T0,
        priority=85,
    )

    assert task is None
    assert queue.pending() == ()
