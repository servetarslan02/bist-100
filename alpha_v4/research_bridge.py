"""Bridge diagnostic evidence into the governed Research Brain backlog."""

from __future__ import annotations

from datetime import datetime

from .drift import DriftAssessment
from .research_queue import ResearchQueue, ResearchTask


def enqueue_drift_research(
    queue: ResearchQueue,
    assessment: DriftAssessment,
    *,
    evidence_id: str,
    subject: str,
    created_at: datetime,
    priority: int,
) -> ResearchTask | None:
    if not evidence_id.strip() or not subject.strip():
        raise ValueError("evidence_id and subject are required")
    if not assessment.detected:
        return None

    return queue.create(
        created_at=created_at,
        trigger_type="NUMERIC_DRIFT",
        hypothesis=(
            f"Diagnose why {subject} changed: " + ", ".join(assessment.reasons)
        ),
        experiment_type="drift_diagnosis",
        trigger_evidence_ids=(evidence_id,),
        priority=priority,
        metadata={
            "subject": subject,
            "drift_policy_version": assessment.policy_version,
            "reference_count": assessment.reference_count,
            "recent_count": assessment.recent_count,
            "standardized_mean_shift": assessment.standardized_mean_shift,
            "std_ratio": assessment.std_ratio,
            "reasons": list(assessment.reasons),
        },
    )
