from datetime import datetime, timezone

from alpha_v4.artifacts import EvaluationArtifact, ModelArtifact, ModelLifecycle
from alpha_v4.governance import GovernancePolicy
from alpha_v4.model_registry import ModelRegistry

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def model():
    return ModelArtifact(
        model_id="m1",
        model_type="baseline_ranker",
        horizon="5D",
        dataset_manifest_id="dataset-1",
        code_commit="research-commit",
        hyperparameters={"direction": "higher"},
        random_seed=42,
        calibration_method=None,
        lifecycle=ModelLifecycle.RESEARCH,
        created_at=T0,
    )


def evaluation(*, independent=True):
    return EvaluationArtifact(
        model_id="m1",
        dataset_manifest_id="dataset-1",
        evaluator_code_commit="validator-commit",
        fold_ids=("f1", "f2", "f3"),
        metrics={"rank_ic": 0.05, "precision_at_k": 0.12},
        cost_assumptions={"commission_bps": 10},
        independently_recomputed=independent,
        created_at=T0,
    )


def policy():
    return GovernancePolicy(
        policy_version="1.0",
        required_metric_names=("rank_ic", "precision_at_k"),
        minimum_fold_count=3,
    )


def test_rejected_transition_is_recorded_but_does_not_change_lifecycle(tmp_path):
    db = tmp_path / "models.sqlite3"
    registry = ModelRegistry(db)
    registry.register(model())
    registry.add_evaluation("eval-1", evaluation())

    decision = registry.request_transition(
        "m1",
        ModelLifecycle.CHAMPION,
        requested_at=T0,
        policy=policy(),
        evaluation_id="eval-1",
    )

    assert not decision.approved
    assert ModelRegistry(db).current_lifecycle("m1") is ModelLifecycle.RESEARCH
    history = ModelRegistry(db).transition_history("m1")
    assert len(history) == 1
    assert history[0]["approved"] == 0


def test_valid_research_to_validated_transition_survives_restart(tmp_path):
    db = tmp_path / "models.sqlite3"
    registry = ModelRegistry(db)
    registry.register(model())
    registry.add_evaluation("eval-1", evaluation())

    decision = registry.request_transition(
        "m1",
        ModelLifecycle.VALIDATED,
        requested_at=T0,
        policy=policy(),
        evaluation_id="eval-1",
    )

    assert decision.approved
    assert ModelRegistry(db).current_lifecycle("m1") is ModelLifecycle.VALIDATED
    assert ModelRegistry(db).get("m1").lifecycle is ModelLifecycle.VALIDATED


def test_non_independent_evaluation_cannot_validate_model(tmp_path):
    registry = ModelRegistry(tmp_path / "models.sqlite3")
    registry.register(model())
    registry.add_evaluation("eval-bad", evaluation(independent=False))

    decision = registry.request_transition(
        "m1",
        ModelLifecycle.VALIDATED,
        requested_at=T0,
        policy=policy(),
        evaluation_id="eval-bad",
    )

    assert not decision.approved
    assert "independent_recompute_required" in decision.reasons
    assert registry.current_lifecycle("m1") is ModelLifecycle.RESEARCH


def test_transition_without_required_evaluation_fails_closed(tmp_path):
    registry = ModelRegistry(tmp_path / "models.sqlite3")
    registry.register(model())

    decision = registry.request_transition(
        "m1",
        ModelLifecycle.VALIDATED,
        requested_at=T0,
        policy=policy(),
        evaluation_id=None,
    )

    assert not decision.approved
    assert "evaluation_required" in decision.reasons
