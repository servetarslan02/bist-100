"""Model lifecycle governance for ALPHA v4.

Research components can request transitions; this gate decides whether the transition
is structurally admissible. Metric thresholds remain versioned policy, not hidden
magic constants inside a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .artifacts import EvaluationArtifact, ModelArtifact, ModelLifecycle

_ALLOWED_TRANSITIONS = {
    ModelLifecycle.RESEARCH: {
        ModelLifecycle.VALIDATED,
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.RETIRED,
    },
    ModelLifecycle.VALIDATED: {
        ModelLifecycle.SHADOW,
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.RETIRED,
    },
    ModelLifecycle.SHADOW: {
        ModelLifecycle.CHALLENGER,
        ModelLifecycle.DEGRADED,
        ModelLifecycle.QUARANTINED,
    },
    ModelLifecycle.CHALLENGER: {
        ModelLifecycle.PAPER_ELIGIBLE,
        ModelLifecycle.DEGRADED,
        ModelLifecycle.QUARANTINED,
    },
    ModelLifecycle.PAPER_ELIGIBLE: {
        ModelLifecycle.CHAMPION,
        ModelLifecycle.DEGRADED,
        ModelLifecycle.QUARANTINED,
    },
    ModelLifecycle.CHAMPION: {
        ModelLifecycle.DEGRADED,
        ModelLifecycle.RETIRED,
        ModelLifecycle.QUARANTINED,
    },
    ModelLifecycle.DEGRADED: {
        ModelLifecycle.SHADOW,
        ModelLifecycle.RETIRED,
        ModelLifecycle.QUARANTINED,
    },
    ModelLifecycle.RETIRED: set(),
    ModelLifecycle.QUARANTINED: {ModelLifecycle.RESEARCH, ModelLifecycle.RETIRED},
}


@dataclass(frozen=True)
class GovernancePolicy:
    policy_version: str
    required_metric_names: tuple[str, ...]
    minimum_fold_count: int
    require_independent_recompute: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.minimum_fold_count <= 0:
            raise ValueError("minimum_fold_count must be positive")


@dataclass(frozen=True)
class GovernanceDecision:
    approved: bool
    requested_state: ModelLifecycle
    reasons: tuple[str, ...]
    policy_version: str


def evaluate_transition(
    model: ModelArtifact,
    requested_state: ModelLifecycle,
    *,
    policy: GovernancePolicy,
    evaluation: EvaluationArtifact | None = None,
) -> GovernanceDecision:
    reasons = []

    if requested_state not in _ALLOWED_TRANSITIONS[model.lifecycle]:
        reasons.append(
            f"transition_not_allowed:{model.lifecycle.value}->{requested_state.value}"
        )

    evidence_required = requested_state in {
        ModelLifecycle.VALIDATED,
        ModelLifecycle.SHADOW,
        ModelLifecycle.CHALLENGER,
        ModelLifecycle.PAPER_ELIGIBLE,
        ModelLifecycle.CHAMPION,
    }
    if evidence_required:
        if evaluation is None:
            reasons.append("evaluation_required")
        else:
            if evaluation.model_id != model.model_id:
                reasons.append("evaluation_model_mismatch")
            if evaluation.dataset_manifest_id != model.dataset_manifest_id:
                reasons.append("evaluation_dataset_mismatch")
            if (
                policy.require_independent_recompute
                and not evaluation.independently_recomputed
            ):
                reasons.append("independent_recompute_required")
            if len(evaluation.fold_ids) < policy.minimum_fold_count:
                reasons.append("insufficient_fold_evidence")
            missing_metrics = [
                name
                for name in policy.required_metric_names
                if name not in evaluation.metrics
            ]
            if missing_metrics:
                reasons.append("missing_metrics:" + ",".join(sorted(missing_metrics)))

    return GovernanceDecision(
        approved=not reasons,
        requested_state=requested_state,
        reasons=tuple(reasons),
        policy_version=policy.policy_version,
    )
