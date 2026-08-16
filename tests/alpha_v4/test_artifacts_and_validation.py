from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.artifacts import (
    DatasetManifest,
    FeatureDefinition,
    MissingPolicy,
    ModelArtifact,
    ModelLifecycle,
)
from alpha_v4.validation import expanding_walk_forward_folds, run_walk_forward

UTC = timezone.utc
T0 = datetime(2020, 1, 1, tzinfo=UTC)


def test_dataset_manifest_id_is_reproducible_and_order_stable():
    kwargs = dict(
        universe_snapshot_id="universe-1",
        feature_ids=("b@1", "a@1"),
        label_ids=("y@1",),
        start_time=T0,
        end_time=T0 + timedelta(days=365),
        code_commit="abc123",
        source_manifest_hash="sourcehash",
        mask_policy_version="1.0",
        created_at=T0 + timedelta(days=400),
    )
    first = DatasetManifest(**kwargs)
    second = DatasetManifest(**{**kwargs, "feature_ids": ("a@1", "b@1")})

    assert first.manifest_id == second.manifest_id


def test_feature_definition_requires_explicit_availability_and_missing_policy():
    feature = FeatureDefinition(
        name="return_5d",
        version="1.0",
        inputs=("close",),
        lookback="5 trading days",
        availability_rule="only bars observed by decision timestamp",
        missing_policy=MissingPolicy.MASK,
        horizon="5D",
    )

    assert feature.feature_id == "return_5d@1.0"


def test_champion_artifact_requires_recorded_seed():
    with pytest.raises(ValueError):
        ModelArtifact(
            model_id="m1",
            model_type="lightgbm_ranker",
            horizon="5D",
            dataset_manifest_id="d1",
            code_commit="abc123",
            hyperparameters={"num_leaves": 31},
            random_seed=None,
            calibration_method=None,
            lifecycle=ModelLifecycle.CHAMPION,
            created_at=T0,
        )


def test_walk_forward_has_disjoint_purge_and_test_windows():
    folds = expanding_walk_forward_folds(
        40,
        min_train_size=15,
        test_size=5,
        purge_size=3,
    )

    assert len(folds) > 1
    for fold in folds:
        assert set(fold.train_indices).isdisjoint(fold.purge_indices)
        assert set(fold.train_indices).isdisjoint(fold.test_indices)
        assert set(fold.purge_indices).isdisjoint(fold.test_indices)
        assert max(fold.train_indices) < min(fold.test_indices)


def test_walk_forward_retrains_inside_every_fold():
    X = list(range(30))
    y = [value * 2 for value in X]
    folds = expanding_walk_forward_folds(
        len(X),
        min_train_size=10,
        test_size=5,
        purge_size=2,
    )
    trained_on = []

    def trainer(X_train, y_train):
        trained_on.append((tuple(X_train), tuple(y_train)))
        return {"scale": 2.0}

    def predictor(model, X_test):
        return [model["scale"] * value for value in X_test]

    def mae(y_true, y_pred):
        return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)

    result = run_walk_forward(
        X,
        y,
        folds,
        trainer=trainer,
        predictor=predictor,
        metric=mae,
    )

    assert result.trainer_calls == len(folds)
    assert len(trained_on) == len(folds)
    assert all(item.metric_value == 0 for item in result.folds)
    assert len({len(train_x) for train_x, _ in trained_on}) > 1


def test_walk_forward_rejects_preposterous_fold_overlap():
    from alpha_v4.validation import WalkForwardFold

    with pytest.raises(ValueError):
        WalkForwardFold(
            fold_id="bad",
            train_indices=(0, 1, 2),
            purge_indices=(2, 3),
            test_indices=(4, 5),
        )
