from datetime import datetime, timezone

from alpha_v4.artifacts import EvaluationArtifact, ModelArtifact, ModelLifecycle
from alpha_v4.baseline import rank_single_feature
from alpha_v4.features import FeatureRecord
from alpha_v4.governance import GovernancePolicy, evaluate_transition

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _feature(instrument_id, value):
    return FeatureRecord(
        instrument_id=instrument_id,
        feature_id="momentum@1",
        value=value,
        effective_at=T0,
        known_at=T0,
        source_ids=("market",),
        input_timestamps=(T0,),
        status="VALID",
    )


def _model(lifecycle=ModelLifecycle.RESEARCH):
    return ModelArtifact(
        model_id="model-1",
        model_type="baseline",
        horizon="5D",
        dataset_manifest_id="dataset-1",
        code_commit="abc",
        hyperparameters={},
        random_seed=42,
        calibration_method=None,
        lifecycle=lifecycle,
        created_at=T0,
    )


def _evaluation(*, independent=True, folds=3):
    return EvaluationArtifact(
        model_id="model-1",
        dataset_manifest_id="dataset-1",
        evaluator_code_commit="validator-abc",
        fold_ids=tuple(f"f{i}" for i in range(folds)),
        metrics={"rank_ic": 0.1, "precision_at_k": 0.2},
        cost_assumptions={"commission_bps": 10.0},
        independently_recomputed=independent,
        created_at=T0,
    )


def _policy():
    return GovernancePolicy(
        policy_version="1.0",
        required_metric_names=("rank_ic", "precision_at_k"),
        minimum_fold_count=3,
    )


def test_baseline_rank_is_explicitly_non_probabilistic():
    ranking = rank_single_feature(
        [_feature("a", 1.0), _feature("b", 3.0), _feature("c", 2.0)],
        higher_is_better=True,
    )

    assert [row.instrument_id for row in ranking.ranks] == ["b", "c", "a"]
    assert all(row.score_kind == "NON_PROBABILISTIC_RANK" for row in ranking.ranks)
    assert ranking.ranks[0].percentile == 1.0
    assert ranking.ranks[-1].percentile == 0.0


def test_research_model_cannot_jump_directly_to_champion():
    decision = evaluate_transition(
        _model(ModelLifecycle.RESEARCH),
        ModelLifecycle.CHAMPION,
        policy=_policy(),
        evaluation=_evaluation(),
    )

    assert not decision.approved
    assert any("transition_not_allowed" in reason for reason in decision.reasons)


def test_validation_requires_independent_recompute():
    decision = evaluate_transition(
        _model(ModelLifecycle.RESEARCH),
        ModelLifecycle.VALIDATED,
        policy=_policy(),
        evaluation=_evaluation(independent=False),
    )

    assert not decision.approved
    assert "independent_recompute_required" in decision.reasons


def test_validation_requires_sufficient_fold_evidence():
    decision = evaluate_transition(
        _model(ModelLifecycle.RESEARCH),
        ModelLifecycle.VALIDATED,
        policy=_policy(),
        evaluation=_evaluation(folds=2),
    )

    assert not decision.approved
    assert "insufficient_fold_evidence" in decision.reasons


def test_validated_transition_is_allowed_with_matching_evidence():
    decision = evaluate_transition(
        _model(ModelLifecycle.RESEARCH),
        ModelLifecycle.VALIDATED,
        policy=_policy(),
        evaluation=_evaluation(),
    )

    assert decision.approved
    assert decision.reasons == ()
