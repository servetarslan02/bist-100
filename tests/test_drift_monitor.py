import pytest
import numpy as np
from services.learning.drift_monitor import DataDriftMonitor, DriftResult

class TestDataDriftMonitor:
    def test_continuous_drift_ks_test(self):
        monitor = DataDriftMonitor(ks_threshold=0.05)
        
        # Baseline: Normal distribution (mean=0, std=1)
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        monitor.set_reference("feature_1", baseline)
        
        # Test 1: Similar distribution (No drift)
        current_similar = np.random.normal(0, 1.1, 100)
        result = monitor.check_continuous_drift("feature_1", current_similar)
        assert result is not None
        assert not result.is_drifted
        assert result.drift_score >= 0.05
        
        # Test 2: Drifted distribution (mean=2, std=1)
        current_drifted = np.random.normal(2, 1, 100)
        result_drifted = monitor.check_continuous_drift("feature_1", current_drifted)
        assert result_drifted is not None
        assert result_drifted.is_drifted
        assert result_drifted.drift_score < 0.05

    def test_prediction_drift_psi(self):
        monitor = DataDriftMonitor(psi_threshold=0.2)
        
        # Baseline Predictions: Uniform between 0 and 1
        np.random.seed(42)
        baseline_preds = np.random.uniform(0, 1, 1000)
        monitor.set_reference("pred_model_A", baseline_preds)
        
        # Test 1: Similar predictions
        current_similar = np.random.uniform(0, 1, 100)
        result = monitor.check_prediction_drift("model_A", current_similar)
        assert result is not None
        assert not result.is_drifted
        assert result.drift_score < 0.2
        
        # Test 2: Drifted predictions (skewed towards 1)
        current_drifted = np.random.uniform(0.6, 1, 100)
        result_drifted = monitor.check_prediction_drift("model_A", current_drifted)
        assert result_drifted is not None
        assert result_drifted.is_drifted
        assert result_drifted.drift_score > 0.2
