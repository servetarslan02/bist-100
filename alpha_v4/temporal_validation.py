"""Time-aware purged/embargoed validation for ALPHA v4.

Unlike index-only splitting, eligibility is determined from when each sample's label
actually became knowable. A training sample whose outcome is revealed too close to or
after the OOS boundary is excluded even if its feature timestamp is historically old.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Sequence, Tuple


@dataclass(frozen=True)
class TemporalSample:
    sample_id: str
    feature_time: datetime
    label_known_at: datetime
    X: Any
    y: Any

    def __post_init__(self) -> None:
        if not self.sample_id.strip():
            raise ValueError("sample_id is required")
        if self.label_known_at < self.feature_time:
            raise ValueError("label_known_at cannot precede feature_time")


@dataclass(frozen=True)
class TemporalFold:
    fold_id: str
    train_ids: Tuple[str, ...]
    test_ids: Tuple[str, ...]
    purged_ids: Tuple[str, ...]
    embargoed_ids: Tuple[str, ...]
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        groups = [set(self.train_ids), set(self.test_ids), set(self.purged_ids), set(self.embargoed_ids)]
        for index, left in enumerate(groups):
            for right in groups[index + 1 :]:
                if left & right:
                    raise ValueError("temporal fold groups must be disjoint")
        if not self.train_ids or not self.test_ids:
            raise ValueError("temporal fold requires train and test samples")
        if self.test_end <= self.test_start:
            raise ValueError("test_end must be after test_start")


def build_temporal_fold(
    samples: Iterable[TemporalSample],
    *,
    fold_id: str,
    test_start: datetime,
    test_end: datetime,
    purge: timedelta,
    embargo: timedelta,
) -> TemporalFold:
    if purge < timedelta(0) or embargo < timedelta(0):
        raise ValueError("purge and embargo must be non-negative")
    if test_end <= test_start:
        raise ValueError("test_end must be after test_start")

    train_ids = []
    test_ids = []
    purged_ids = []
    embargoed_ids = []

    train_label_cutoff = test_start - purge
    embargo_end = test_end + embargo

    for sample in sorted(samples, key=lambda item: (item.feature_time, item.sample_id)):
        if test_start <= sample.feature_time < test_end:
            test_ids.append(sample.sample_id)
            continue

        if sample.feature_time < test_start:
            # Even an old feature row leaks if its future outcome was not yet known by
            # the permitted training cutoff.
            if sample.label_known_at >= train_label_cutoff:
                purged_ids.append(sample.sample_id)
            else:
                train_ids.append(sample.sample_id)
            continue

        if test_end <= sample.feature_time < embargo_end:
            embargoed_ids.append(sample.sample_id)
        # Samples after embargo are neither train nor test for this fold.

    return TemporalFold(
        fold_id=fold_id,
        train_ids=tuple(train_ids),
        test_ids=tuple(test_ids),
        purged_ids=tuple(purged_ids),
        embargoed_ids=tuple(embargoed_ids),
        test_start=test_start,
        test_end=test_end,
    )


@dataclass(frozen=True)
class TemporalFoldResult:
    fold_id: str
    metric_value: float
    train_size: int
    test_size: int
    purged_size: int
    embargoed_size: int


@dataclass(frozen=True)
class TemporalValidationResult:
    folds: Tuple[TemporalFoldResult, ...]
    trainer_calls: int


Trainer = Callable[[Sequence[Any], Sequence[Any]], Any]
Predictor = Callable[[Any, Sequence[Any]], Sequence[float]]
Metric = Callable[[Sequence[Any], Sequence[float]], float]


def run_temporal_validation(
    samples: Iterable[TemporalSample],
    folds: Iterable[TemporalFold],
    *,
    trainer: Trainer,
    predictor: Predictor,
    metric: Metric,
) -> TemporalValidationResult:
    sample_map = {sample.sample_id: sample for sample in samples}
    results = []
    trainer_calls = 0

    for fold in folds:
        train_samples = [sample_map[sample_id] for sample_id in fold.train_ids]
        test_samples = [sample_map[sample_id] for sample_id in fold.test_ids]

        model = trainer([sample.X for sample in train_samples], [sample.y for sample in train_samples])
        trainer_calls += 1
        predictions = list(predictor(model, [sample.X for sample in test_samples]))
        if len(predictions) != len(test_samples):
            raise ValueError("predictor output length mismatch")

        value = float(metric([sample.y for sample in test_samples], predictions))
        results.append(
            TemporalFoldResult(
                fold_id=fold.fold_id,
                metric_value=value,
                train_size=len(train_samples),
                test_size=len(test_samples),
                purged_size=len(fold.purged_ids),
                embargoed_size=len(fold.embargoed_ids),
            )
        )

    return TemporalValidationResult(folds=tuple(results), trainer_calls=trainer_calls)
