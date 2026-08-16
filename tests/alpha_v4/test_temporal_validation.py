from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.temporal_validation import (
    TemporalSample,
    build_temporal_fold,
    run_temporal_validation,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def sample(name, feature_day, label_known_day, x=None, y=None):
    return TemporalSample(
        sample_id=name,
        feature_time=T0 + feature_day * DAY,
        label_known_at=T0 + label_known_day * DAY,
        X=feature_day if x is None else x,
        y=feature_day * 2 if y is None else y,
    )


def test_old_feature_is_purged_when_label_was_not_known_before_boundary():
    samples = [
        sample("safe", 0, 2),
        sample("leaky", 3, 9),
        sample("test-a", 10, 15),
        sample("test-b", 11, 16),
    ]

    fold = build_temporal_fold(
        samples,
        fold_id="f1",
        test_start=T0 + 10 * DAY,
        test_end=T0 + 12 * DAY,
        purge=2 * DAY,
        embargo=1 * DAY,
    )

    assert fold.train_ids == ("safe",)
    assert fold.purged_ids == ("leaky",)
    assert fold.test_ids == ("test-a", "test-b")


def test_label_exactly_at_purge_cutoff_is_excluded_fail_closed():
    samples = [
        sample("edge", 0, 8),
        sample("test", 10, 12),
    ]

    with pytest.raises(ValueError, match="train and test"):
        build_temporal_fold(
            samples,
            fold_id="f1",
            test_start=T0 + 10 * DAY,
            test_end=T0 + 11 * DAY,
            purge=2 * DAY,
            embargo=DAY,
        )


def test_post_test_samples_inside_embargo_are_explicitly_excluded():
    samples = [
        sample("train", 0, 1),
        sample("test", 10, 12),
        sample("embargo-a", 12, 13),
        sample("embargo-b", 13, 14),
        sample("later", 15, 16),
    ]

    fold = build_temporal_fold(
        samples,
        fold_id="f1",
        test_start=T0 + 10 * DAY,
        test_end=T0 + 12 * DAY,
        purge=DAY,
        embargo=2 * DAY,
    )

    assert fold.embargoed_ids == ("embargo-a", "embargo-b")
    assert "later" not in fold.train_ids
    assert "later" not in fold.test_ids


def test_temporal_validation_retrains_inside_each_fold():
    samples = [sample(f"s{i}", i, i + 1) for i in range(20)]
    fold1 = build_temporal_fold(
        samples,
        fold_id="f1",
        test_start=T0 + 8 * DAY,
        test_end=T0 + 10 * DAY,
        purge=DAY,
        embargo=DAY,
    )
    fold2 = build_temporal_fold(
        samples,
        fold_id="f2",
        test_start=T0 + 12 * DAY,
        test_end=T0 + 14 * DAY,
        purge=DAY,
        embargo=DAY,
    )
    calls = []

    def trainer(X_train, y_train):
        calls.append(tuple(X_train))
        return 2.0

    def predictor(model, X_test):
        return [model * x for x in X_test]

    def mae(y_true, y_pred):
        return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)

    result = run_temporal_validation(
        samples,
        [fold1, fold2],
        trainer=trainer,
        predictor=predictor,
        metric=mae,
    )

    assert result.trainer_calls == 2
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert all(fold.metric_value == 0 for fold in result.folds)


def test_temporal_sample_rejects_impossible_label_availability():
    with pytest.raises(ValueError, match="cannot precede"):
        sample("bad", 5, 4)
