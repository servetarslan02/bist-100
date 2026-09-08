"""Comprehensive unit tests for services.backtest.walk_forward_engine."""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pytest

from services.backtest.walk_forward_engine import (
    IC_SIGNIFICANCE_THRESHOLD,
    MAX_PURGE_RATIO,
    MIN_FOLDS_FOR_VALIDATION,
    MIN_TEST_SAMPLES,
    MIN_TRAINING_SAMPLES,
    STABILITY_THRESHOLD,
    FoldConfig,
    FoldMetrics,
    FoldSnapshot,
    FoldStatus,
    RegimeType,
    WalkForwardEngineV5,
    WalkForwardResultV5,
    walk_forward_engine_v5,
)


class DummyModel:
    """Mock model implementing ModelProtocol for unit test validation."""

    def __init__(self, **kwargs):
        self.params = kwargs

    def fit(self, X: np.ndarray, y: np.ndarray, **kwargs: Any) -> None:
        pass

    def predict(self, X: np.ndarray) -> np.ndarray:
        # Predict positive slope based on first feature or zeros
        if len(X) == 0:
            return np.array([])
        return np.asarray(X[:, 0], dtype=float)

    def get_feature_importance(self) -> dict[str, float]:
        return {"feat_1": 0.8, "feat_2": 0.2}

    def get_params(self) -> dict[str, Any]:
        return self.params


class DummyFeatureCalculator:
    """Mock feature calculator implementing FeatureCalculatorProtocol."""

    def compute_features(self, data: dict[str, Any], ticker: str, as_of_date: str) -> dict[str, float]:
        return {"feat_1": 0.5, "feat_2": 1.2}


def test_enums_and_constants():
    """Verify enums representation and constants."""
    assert FoldStatus.COMPLETED == "completed"
    assert "FoldStatus.COMPLETED" in repr(FoldStatus.COMPLETED)
    assert RegimeType.BULL == "BULL"
    assert "RegimeType.BULL" in repr(RegimeType.BULL)

    assert MIN_TRAINING_SAMPLES == 5
    assert MIN_TEST_SAMPLES == 1
    assert MIN_FOLDS_FOR_VALIDATION == 3
    assert STABILITY_THRESHOLD == 0.6
    assert IC_SIGNIFICANCE_THRESHOLD == 0.03
    assert MAX_PURGE_RATIO == 0.3


def test_dataclasses_repr_and_helpers():
    """Verify dataclasses representation and helper methods."""
    fc = FoldConfig(
        fold_id=1,
        train_start="2024-01-01",
        train_end="2024-09-30",
        purge_start="2024-10-01",
        purge_end="2024-10-07",
        test_start="2024-10-08",
        test_end="2024-12-31",
        embargo_start="2025-01-01",
        embargo_end="2025-01-07",
    )
    fc_repr = repr(fc)
    assert "FoldConfig" in fc_repr
    assert "id=1" in fc_repr

    fm = FoldMetrics(
        total_return=0.15,
        annualized_return=0.20,
        sharpe_ratio=1.5,
        max_drawdown=5.0,
        precision_at_5=0.7,
        ic=0.05,
    )

    fs = FoldSnapshot(
        fold_config=fc,
        status=FoldStatus.COMPLETED,
        metrics=fm,
        train_samples=200,
        test_samples=60,
    )
    fs_repr = repr(fs)
    assert "FoldSnapshot" in fs_repr
    assert "sharpe=1.50" in fs_repr
    fs_dict = fs.to_dict()
    assert fs_dict["fold_id"] == 1
    assert fs_dict["status"] == "completed"
    assert fs_dict["purge_days"] == 6

    res = WalkForwardResultV5(
        run_id="test_run_123",
        total_folds=2,
        completed_folds=2,
        failed_folds=0,
        skipped_folds=0,
        avg_test_sharpe=1.4,
        stability_score=0.85,
        deflated_sharpe=1.1,
    )
    d = res.to_dict()
    assert d["run_id"] == "test_run_123"
    assert d["completed_folds"] == 2
    assert "WalkForwardResultV5" in repr(res)


def test_engine_v5_init_validation():
    """Test boundary validation in WalkForwardEngineV5 constructor."""
    with pytest.raises(ValueError, match="purge_days >= 0"):
        WalkForwardEngineV5(purge_days=-1)

    with pytest.raises(ValueError, match="embargo_days >= 0"):
        WalkForwardEngineV5(embargo_days=-1)

    with pytest.raises(ValueError, match="train_days >= 60"):
        WalkForwardEngineV5(train_days=30)

    with pytest.raises(ValueError, match="test_days >= 5"):
        WalkForwardEngineV5(test_days=2)

    with pytest.raises(ValueError, match="step_days >= 1"):
        WalkForwardEngineV5(step_days=0)

    with pytest.raises(ValueError, match="transaction_cost_pct"):
        WalkForwardEngineV5(transaction_cost_pct=-0.01)

    engine = WalkForwardEngineV5(train_days=60, test_days=10, step_days=5, purge_days=2, embargo_days=2)
    assert "WalkForwardEngineV5" in repr(engine)


def test_engine_v5_create_folds():
    """Test creation of purge-embargo folds."""
    engine = WalkForwardEngineV5(train_days=60, test_days=15, step_days=10, purge_days=3, embargo_days=3)

    # Missing or unsorted dates
    with pytest.raises(ValueError, match="dates boş olamaz"):
        engine.create_folds([])

    with pytest.raises(ValueError, match="Tarihler sıralı olmalı"):
        engine.create_folds(["2024-02-01", "2024-01-01"])

    start_d = datetime.date(2024, 1, 1)
    dates = [(start_d + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(150)]

    folds = engine.create_folds(dates)
    assert len(folds) >= 2

    for f in folds:
        assert isinstance(f, FoldConfig)
        assert f.train_start <= f.train_end < f.test_start <= f.test_end


def test_engine_v5_empty_result():
    """Test empty result fallback."""
    engine = WalkForwardEngineV5()
    res = engine._empty_result("empty_run")
    assert res.run_id == "empty_run"
    assert res.total_folds == 0
    assert not res.is_valid()


def test_singleton_v5_instance():
    """Verify singleton instance."""
    assert walk_forward_engine_v5 is not None
    assert isinstance(walk_forward_engine_v5, WalkForwardEngineV5)
