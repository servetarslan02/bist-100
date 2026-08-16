from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.jobs import JobCoordinator

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def test_two_coordinators_cannot_run_same_job_concurrently(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    first = JobCoordinator(database)
    second = JobCoordinator(database)

    winner = first.try_start(
        job_name="kap-ingestion",
        owner_id="worker-a",
        idempotency_key="2026-08-16T12:00",
        started_at=T0,
        lease_for=timedelta(minutes=5),
    )
    loser = second.try_start(
        job_name="kap-ingestion",
        owner_id="worker-b",
        idempotency_key="2026-08-16T12:01",
        started_at=T0 + timedelta(minutes=1),
        lease_for=timedelta(minutes=5),
    )

    assert winner is not None
    assert loser is None


def test_expired_lease_can_be_recovered_by_another_worker(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    coordinator = JobCoordinator(database)
    first = coordinator.try_start(
        job_name="market-refresh",
        owner_id="worker-a",
        idempotency_key="attempt-1",
        started_at=T0,
        lease_for=timedelta(minutes=1),
    )
    recovered = JobCoordinator(database).try_start(
        job_name="market-refresh",
        owner_id="worker-b",
        idempotency_key="attempt-2",
        started_at=T0 + timedelta(minutes=2),
        lease_for=timedelta(minutes=1),
    )

    assert first is not None
    assert recovered is not None
    assert recovered.owner_id == "worker-b"


def test_idempotency_key_never_executes_twice_even_after_success(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    coordinator = JobCoordinator(database)
    run = coordinator.try_start(
        job_name="daily-state-build",
        owner_id="worker-a",
        idempotency_key="2026-08-16",
        started_at=T0,
        lease_for=timedelta(minutes=10),
    )
    assert run is not None

    finished = coordinator.finish(
        run.run_id,
        status="SUCCEEDED",
        finished_at=T0 + timedelta(minutes=1),
    )
    duplicate = JobCoordinator(database).try_start(
        job_name="daily-state-build",
        owner_id="worker-b",
        idempotency_key="2026-08-16",
        started_at=T0 + timedelta(hours=1),
        lease_for=timedelta(minutes=10),
    )

    assert finished.status == "SUCCEEDED"
    assert duplicate is None
    assert JobCoordinator(database).get(run.run_id).status == "SUCCEEDED"


def test_job_history_survives_restart_and_rejects_double_finish(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    coordinator = JobCoordinator(database)
    run = coordinator.try_start(
        job_name="research-evaluation",
        owner_id="worker-a",
        idempotency_key="model-17",
        started_at=T0,
        lease_for=timedelta(minutes=10),
    )
    assert run is not None
    coordinator.finish(
        run.run_id,
        status="FAILED",
        finished_at=T0 + timedelta(minutes=2),
    )

    restarted = JobCoordinator(database)
    persisted = restarted.get(run.run_id)
    assert persisted.status == "FAILED"
    assert persisted.finished_at == T0 + timedelta(minutes=2)

    with pytest.raises(ValueError, match="already final"):
        restarted.finish(
            run.run_id,
            status="SUCCEEDED",
            finished_at=T0 + timedelta(minutes=3),
        )


def test_naive_timestamps_and_nonpositive_leases_are_rejected(tmp_path):
    coordinator = JobCoordinator(tmp_path / "jobs.sqlite3")
    naive_time = T0.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        coordinator.try_start(
            job_name="x",
            owner_id="worker",
            idempotency_key="key",
            started_at=naive_time,
            lease_for=timedelta(minutes=1),
        )

    with pytest.raises(ValueError, match="positive"):
        coordinator.try_start(
            job_name="x",
            owner_id="worker",
            idempotency_key="key",
            started_at=T0,
            lease_for=timedelta(0),
        )
