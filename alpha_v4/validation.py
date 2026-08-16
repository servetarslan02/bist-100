"""Leakage-conscious walk-forward validation primitives.

The key invariant is that training happens inside every fold. This module does not
accept a precomputed all-history prediction vector and call slicing 'walk-forward'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    train_indices: Tuple[int, ...]
    purge_indices: Tuple[int, ...]
    test_indices: Tuple[int, ...]

    def __post_init__(self) -> None:
        train = set(self.train_indices)
        purge = set(self.purge_indices)
        test = set(self.test_indices)
        if train & purge or train & test or purge & test:
            raise ValueError("train/purge/test indices must be disjoint")
        if not self.train_indices or not self.test_indices:
            raise ValueError("fold requires non-empty train and test sets")
        if max(self.train_indices) >= min(self.test_indices):
            raise ValueError("training must precede testing")


def expanding_walk_forward_folds(
    n_samples: int,
    *,
    min_train_size: int,
    test_size: int,
    purge_size: int,
    step_size: int | None = None,
) -> Tuple[WalkForwardFold, ...]:
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    if min_train_size <= 0 or test_size <= 0 or purge_size < 0:
        raise ValueError("invalid fold sizes")
    step = step_size or test_size
    if step <= 0:
        raise ValueError("step_size must be positive")

    folds: List[WalkForwardFold] = []
    test_start = min_train_size + purge_size
    fold_number = 1
    while test_start + test_size <= n_samples:
        train_end = test_start - purge_size
        train_indices = tuple(range(0, train_end))
        purge_indices = tuple(range(train_end, test_start))
        test_indices = tuple(range(test_start, test_start + test_size))
        folds.append(
            WalkForwardFold(
                fold_id=f"wf-{fold_number:04d}",
                train_indices=train_indices,
                purge_indices=purge_indices,
                test_indices=test_indices,
            )
        )
        fold_number += 1
        test_start += step
    return tuple(folds)


@dataclass(frozen=True)
class FoldEvaluation:
    fold_id: str
    metric_value: float
    train_size: int
    test_size: int


@dataclass(frozen=True)
class WalkForwardResult:
    folds: Tuple[FoldEvaluation, ...]
    trainer_calls: int


Trainer = Callable[[Sequence[Any], Sequence[Any]], Any]
Predictor = Callable[[Any, Sequence[Any]], Sequence[float]]
Metric = Callable[[Sequence[Any], Sequence[float]], float]


def run_walk_forward(
    X: Sequence[Any],
    y: Sequence[Any],
    folds: Iterable[WalkForwardFold],
    *,
    trainer: Trainer,
    predictor: Predictor,
    metric: Metric,
) -> WalkForwardResult:
    if len(X) != len(y):
        raise ValueError("X and y length mismatch")

    evaluations: List[FoldEvaluation] = []
    trainer_calls = 0

    for fold in folds:
        X_train = [X[i] for i in fold.train_indices]
        y_train = [y[i] for i in fold.train_indices]
        X_test = [X[i] for i in fold.test_indices]
        y_test = [y[i] for i in fold.test_indices]

        # Critical invariant: a fresh train operation occurs inside each fold.
        model = trainer(X_train, y_train)
        trainer_calls += 1
        predictions = list(predictor(model, X_test))
        if len(predictions) != len(y_test):
            raise ValueError("predictor output length mismatch")

        evaluations.append(
            FoldEvaluation(
                fold_id=fold.fold_id,
                metric_value=float(metric(y_test, predictions)),
                train_size=len(X_train),
                test_size=len(X_test),
            )
        )

    return WalkForwardResult(folds=tuple(evaluations), trainer_calls=trainer_calls)
