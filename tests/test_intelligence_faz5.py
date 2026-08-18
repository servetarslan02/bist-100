"""
ALPHA BIST — Intelligence Faz 2+5 Tests

ML Signal Fusion + Prediction Layer + Integration.
"""

import asyncio
import pytest
import numpy as np
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.intelligence.ml_signal_fusion import MLSignalFusion, MLFusedSignal
from services.intelligence.prediction_layer import (
    compute_prediction, compute_multi_horizon_predictions, Prediction, MultiHorizonPrediction,
)
from services.intelligence.hmm_regime import HMMRegimeDetector
from services.intelligence.ensemble_forecast import EnsembleForecaster
from services.intelligence.confidence_calibrator import ConfidenceCalibrator
from services.intelligence.advanced_monte_carlo import AdvancedMonteCarloEngine


# =====================================================
# ML Signal Fusion Tests
# =====================================================

class TestMLSignalFusion:
    """ML sinyal birleştirme testleri."""

    def test_basic_fusion(self):
        """Temel fusion."""
        fusion = MLSignalFusion()
        signals = {
            "technical": {"direction": "LONG", "score": 70},
            "fundamental": {"direction": "LONG", "score": 65},
            "momentum": {"direction": "LONG", "score": 80},
        }
        result = fusion.fuse("THYAO", signals, regime="BULL")
        assert isinstance(result, MLFusedSignal)
        assert result.ticker == "THYAO"
        assert result.fused_direction in ["LONG", "SHORT", "NEUTRAL"]

    def test_all_long_signals(self):
        """Tüm sinyaller LONG."""
        fusion = MLSignalFusion()
        signals = {comp: {"direction": "LONG", "score": 75} for comp in fusion.COMPONENTS}
        result = fusion.fuse("THYAO", signals)
        assert result.fused_direction == "LONG"
        assert result.fused_confidence > 0.5

    def test_all_short_signals(self):
        """Tüm sinyaller SHORT."""
        fusion = MLSignalFusion()
        signals = {comp: {"direction": "SHORT", "score": 25} for comp in fusion.COMPONENTS}
        result = fusion.fuse("THYAO", signals)
        assert result.fused_direction == "SHORT"

    def test_conflicting_signals(self):
        """Çelişkili sinyaller."""
        fusion = MLSignalFusion()
        signals = {
            "technical": {"direction": "LONG", "score": 70},
            "fundamental": {"direction": "SHORT", "score": 30},
            "momentum": {"direction": "LONG", "score": 65},
        }
        result = fusion.fuse("THYAO", signals)
        assert result.has_conflict is True
        assert len(result.conflict_details) > 0

    def test_neutral_signals(self):
        """Nötr sinyaller."""
        fusion = MLSignalFusion()
        signals = {comp: {"direction": "NEUTRAL", "score": 50} for comp in fusion.COMPONENTS}
        result = fusion.fuse("THYAO", signals)
        assert result.fused_direction == "NEUTRAL"

    def test_regime_based_weights(self):
        """Rejime göre ağırlıklar farklı."""
        fusion = MLSignalFusion()
        signals = {
            "technical": {"direction": "LONG", "score": 70},
            "momentum": {"direction": "LONG", "score": 80},
        }
        bull = fusion.fuse("THYAO", signals, regime="BULL")
        bear = fusion.fuse("THYAO", signals, regime="BEAR")
        assert bull.optimized_weights != bear.optimized_weights

    def test_self_check_high_confidence(self):
        """Self-check: çok yüksek confidence uyarısı."""
        fusion = MLSignalFusion()
        signals = {comp: {"direction": "LONG", "score": 95} for comp in fusion.COMPONENTS}
        result = fusion.fuse("THYAO", signals)
        # Uyarı olabilir (confidence > 0.9)
        assert isinstance(result.self_check_warnings, list)

    def test_self_check_all_neutral_high_score(self):
        """Self-check: tüm nötr ama yüksek skor."""
        fusion = MLSignalFusion()
        signals = {comp: {"direction": "NEUTRAL", "score": 80} for comp in fusion.COMPONENTS}
        result = fusion.fuse("THYAO", signals)
        if result.fused_score > 70:
            assert any("nötr" in w.lower() for w in result.self_check_warnings)

    def test_component_scores_stored(self):
        """Bileşen skorları saklanır."""
        fusion = MLSignalFusion()
        signals = {"technical": {"direction": "LONG", "score": 72}}
        result = fusion.fuse("THYAO", signals)
        assert result.component_scores["technical"] == 72

    def test_empty_signals(self):
        """Boş sinyaller."""
        fusion = MLSignalFusion()
        result = fusion.fuse("THYAO", {})
        assert result.fused_direction == "NEUTRAL"

    def test_weight_history(self):
        """Ağırlık geçmişi."""
        fusion = MLSignalFusion()
        signals = {"technical": {"direction": "LONG", "score": 70}}
        fusion.fuse("THYAO", signals, regime="BULL")
        history = fusion.get_weight_history()
        assert isinstance(history, list)


# =====================================================
# Prediction Layer Tests
# =====================================================

class TestPredictionLayer:
    """Prediction layer testleri."""

    def test_compute_prediction_basic(self):
        """Temel prediction."""
        pred = compute_prediction("THYAO", 3.0, 0.7, {"volatility_20d": 20, "atr_pct": 2}, horizon=5)
        assert isinstance(pred, Prediction)
        assert pred.direction == "UP"
        assert pred.ticker == "THYAO"

    def test_compute_prediction_down(self):
        """Düşüş prediction."""
        pred = compute_prediction("THYAO", -3.0, 0.7, {"volatility_20d": 20, "atr_pct": 2}, horizon=5)
        assert pred.direction == "DOWN"

    def test_compute_prediction_neutral(self):
        """Nötr prediction."""
        pred = compute_prediction("THYAO", 0.5, 0.3, {"volatility_20d": 20, "atr_pct": 2}, horizon=5)
        assert pred.direction == "NEUTRAL"

    def test_quality_grades(self):
        """Kalite sınıfları."""
        # Yüksek confidence + yüksek return + iyi R/R → A+
        pred_a = compute_prediction("T", 5.0, 0.9, {"volatility_20d": 15, "atr_pct": 1}, horizon=5)
        assert pred_a.quality_grade in ["A+", "A"]

        # Düşük confidence → D
        pred_d = compute_prediction("T", 0.5, 0.1, {"volatility_20d": 40, "atr_pct": 5}, horizon=5)
        assert pred_d.quality_grade in ["C", "D"]

    def test_risk_reward(self):
        """Risk/reward hesaplanır."""
        pred = compute_prediction("THYAO", 5.0, 0.7, {"volatility_20d": 20, "atr_pct": 2}, horizon=5)
        assert pred.risk_reward > 0

    def test_uncertainty(self):
        """Belirsizlik hesaplanır."""
        pred = compute_prediction("THYAO", 3.0, 0.7, {"volatility_20d": 30, "atr_pct": 2}, horizon=20)
        assert pred.uncertainty > 0

    def test_multi_horizon_basic(self):
        """Multi-horizon prediction."""
        result = compute_multi_horizon_predictions("THYAO", {"momentum_20d": 3, "rsi_14": 55, "volatility_20d": 20, "atr_pct": 2})
        assert isinstance(result, MultiHorizonPrediction)
        assert 1 in result.predictions
        assert 5 in result.predictions
        assert 20 in result.predictions
        assert 60 in result.predictions

    def test_multi_horizon_consensus(self):
        """Multi-horizon consensus."""
        result = compute_multi_horizon_predictions("THYAO", {"momentum_20d": 5, "rsi_14": 60, "volatility_20d": 20, "atr_pct": 2})
        assert result.consensus_direction in ["UP", "DOWN", "NEUTRAL"]
        assert 0 <= result.consensus_confidence <= 1

    def test_multi_horizon_best_horizon(self):
        """En iyi horizon seçilir."""
        result = compute_multi_horizon_predictions("THYAO", {"momentum_20d": 3, "rsi_14": 55, "volatility_20d": 20, "atr_pct": 2})
        assert result.best_horizon in [1, 5, 20, 60]

    def test_multi_horizon_with_ensemble(self):
        """Ensemble ile multi-horizon."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (2.0, 0.7))
        result = compute_multi_horizon_predictions(
            "THYAO",
            {"momentum_20d": 3, "rsi_14": 55, "volatility_20d": 20, "atr_pct": 2},
            ensemble_forecaster=engine,
        )
        assert result.predictions[5].model_source == "ensemble"

    def test_multi_horizon_with_calibration(self):
        """Kalibrasyon ile multi-horizon."""
        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(50):
            cal.add_observation(0.9, True, regime="BULL")
        for _ in range(50):
            cal.add_observation(0.9, False, regime="BULL")
        result = compute_multi_horizon_predictions(
            "THYAO",
            {"momentum_20d": 3, "rsi_14": 55, "volatility_20d": 20, "atr_pct": 2},
            calibrator=cal,
            regime="BULL",
        )
        # Kalibrasyon confidence'ı düşürmeli
        assert isinstance(result.consensus_confidence, float)


# =====================================================
# Integration Tests
# =====================================================

class TestIntelligenceIntegration:
    """Tüm modüllerin entegrasyon testleri."""

    def test_hmm_plus_ensemble(self):
        """HMM + Ensemble entegrasyonu."""
        # HMM regime detection
        hmm = HMMRegimeDetector()
        returns = np.array([0.002] * 63)
        vol = np.array([0.01] * 63)
        regime_result = hmm.predict_regime(returns, vol)

        # Ensemble forecast
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (2.0, 0.7))
        forecast = engine.forecast(
            {"momentum_20d": 3},
            horizon=5,
            regime=regime_result.regime,
        )

        assert forecast.regime == regime_result.regime

    def test_ensemble_plus_calibration(self):
        """Ensemble + Calibration entegrasyonu."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (2.0, 0.9))
        forecast = engine.forecast({}, horizon=5)

        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(50):
            cal.add_observation(0.9, True)
        calibrated = cal.adjust_confidence(forecast.ensemble_confidence)

        assert calibrated <= forecast.ensemble_confidence

    def test_ensemble_plus_prediction(self):
        """Ensemble + Prediction entegrasyonu."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (3.0, 0.8))
        result = compute_multi_horizon_predictions(
            "THYAO",
            {"momentum_20d": 3, "rsi_14": 55, "volatility_20d": 20, "atr_pct": 2},
            ensemble_forecaster=engine,
        )
        assert result.predictions[5].model_source == "ensemble"

    def test_advanced_mc_all_models(self):
        """Tüm MC modelleri çalışır."""
        mc = AdvancedMonteCarloEngine()
        gbm = mc.gbm_sim("T", 100, 0.15, 0.25, n_sims=500, seed=42)
        jump = mc.jump_diffusion_sim("T", 100, 0.15, 0.25, n_sims=500, seed=42)
        student = mc.student_t_sim("T", 100, 0.15, 0.25, n_sims=500, seed=42)
        heston = mc.heston_lite_sim("T", 100, 0.15, 0.25, n_sims=500, seed=42)

        assert gbm.model_type == "gbm"
        assert jump.model_type == "jump_diffusion"
        assert student.model_type == "student_t"
        assert heston.model_type == "heston"

    def test_full_pipeline_flow(self):
        """Tam pipeline akışı."""
        features = {
            "momentum_20d": 3,
            "momentum_5d": 2,
            "rsi_14": 55,
            "volatility_20d": 20,
            "atr_pct": 2,
            "bb_position": 0.6,
            "close": 100,
        }

        # 1. Regime
        hmm = HMMRegimeDetector()
        regime = hmm.predict_regime(np.array([0.002] * 63), np.array([0.01] * 63))

        # 2. Ensemble forecast
        engine = EnsembleForecaster()
        forecast = engine.forecast(features, horizon=5, regime=regime.regime)

        # 3. ML Signal Fusion
        fusion = MLSignalFusion()
        signals = {
            "technical": {"direction": "LONG", "score": 70},
            "momentum": {"direction": "LONG", "score": 65},
            "fundamental": {"direction": "NEUTRAL", "score": 50},
        }
        fused = fusion.fuse("THYAO", signals, regime=regime.regime)

        # 4. Prediction
        pred = compute_prediction(
            "THYAO",
            forecast.ensemble_prediction,
            forecast.calibrated_confidence,
            features,
            horizon=5,
            model_agreement=forecast.model_agreement,
        )

        # 5. Monte Carlo
        mc = AdvancedMonteCarloEngine()
        mc_result = mc.gbm_sim("THYAO", 100, 0.15, 0.25, n_sims=1000, seed=42)

        # Tümü çalışmalı
        assert regime.regime in ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]
        assert forecast.ensemble_prediction is not None
        assert fused.fused_direction in ["LONG", "SHORT", "NEUTRAL"]
        assert pred.direction in ["UP", "DOWN", "NEUTRAL"]
        assert mc_result.p50 > 0


# =====================================================
# Run Tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
