"""Finite governed worker cycles for ALPHA v4 official-source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .providers import SnapshotProvider, official_snapshot_provider
from .runtime import AlphaRuntime


@dataclass(frozen=True)
class SnapshotCycleResult:
    job_name: str
    cycle_key: str
    status: str
    run_id: str | None
    document_id: str | None
    body_sha256: str | None
    byte_count: int


def run_snapshot_cycle(
    runtime: AlphaRuntime,
    *,
    source_id: str,
    surface: str,
    owner_id: str,
    cycle_key: str,
    started_at: datetime | None = None,
    lease_for: timedelta = timedelta(minutes=5),
    provider: SnapshotProvider | None = None,
) -> SnapshotCycleResult:
    """Run one idempotent acquisition cycle; never loops or creates hidden workers."""
    if (
        not source_id.strip()
        or not surface.strip()
        or not owner_id.strip()
        or not cycle_key.strip()
    ):
        raise ValueError("source_id, surface, owner_id and cycle_key are required")

    observed_at = started_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    job_name = f"official-snapshot:{source_id}:{surface}"

    run = runtime.jobs.try_start(
        job_name=job_name,
        owner_id=owner_id,
        idempotency_key=cycle_key,
        started_at=observed_at,
        lease_for=lease_for,
    )
    if run is None:
        return SnapshotCycleResult(
            job_name=job_name,
            cycle_key=cycle_key,
            status="SKIPPED",
            run_id=None,
            document_id=None,
            body_sha256=None,
            byte_count=0,
        )

    snapshot_provider = provider or official_snapshot_provider(
        source_id,
        raw_store=runtime.raw_documents,
        source_history=runtime.source_registry,
    )
    try:
        document = snapshot_provider.snapshot(surface, fetched_at=observed_at)
        runtime.audit.append(
            "SOURCE_SNAPSHOT_COMPLETED",
            {
                "job_name": job_name,
                "run_id": run.run_id,
                "cycle_key": cycle_key,
                "source_id": source_id,
                "surface": surface,
                "document_id": document.document_id,
                "status_code": document.status_code,
                "body_sha256": document.body_sha256,
                "byte_count": len(document.body),
            },
            created_at=observed_at,
        )
        runtime.jobs.finish(run.run_id, status="SUCCEEDED", finished_at=observed_at)
        return SnapshotCycleResult(
            job_name=job_name,
            cycle_key=cycle_key,
            status="SUCCEEDED",
            run_id=run.run_id,
            document_id=document.document_id,
            body_sha256=document.body_sha256,
            byte_count=len(document.body),
        )
    except Exception as exc:
        runtime.audit.append(
            "SOURCE_SNAPSHOT_FAILED",
            {
                "job_name": job_name,
                "run_id": run.run_id,
                "cycle_key": cycle_key,
                "source_id": source_id,
                "surface": surface,
                "error_type": type(exc).__name__,
            },
            created_at=observed_at,
        )
        runtime.jobs.finish(run.run_id, status="FAILED", finished_at=observed_at)
        raise
