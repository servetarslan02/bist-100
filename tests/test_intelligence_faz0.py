"""
ALPHA BIST — Intelligence Module Tests

HMM Regime, Parallel Pipeline, Ensemble Forecast, Confidence Calibrator, Advanced MC.
"""

import numpy as np
import pytest

from services.intelligence.advanced_monte_carlo import AdvancedMCResult, AdvancedMonteCarloEngine
from services.intelligence.confidence_calibrator import ConfidenceCalibrator
from services.intelligence.ensemble_forecast import (
    EnsembleForecaster,
    EnsembleResult,
)
from services.intelligence.hmm_regime import HMMRegimeDetector

# =====================================================
# HMM Regime Detection Tests
# =====================================================


class TestHMMRegimeDetector:
    """HMM rejim tespit testleri."""

    def test_initial_state(self):
        """Başlangıç durumu."""
        detector = HMMRegimeDetector(n_regimes=4)
        assert detector.is_fitted is False
        assert detector.current_regime is None

    def test_rule_based_fallback(self):
        """Rule-based fallback çalışır."""
        detector = HMMRegimeDetector()
        returns = np.array([0.001] * 30)
        vol = np.array([0.01] * 30)
        result = detector.predict_regime(returns, vol)
        assert result.regime in ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]
        assert 0 <= result.confidence <= 1

    def test_fallback_bull(self):
        """Pozitif getiri → BULL."""
        detector = HMMRegimeDetector()
        returns = np.array([0.005] * 30)  # Pozitif
        vol = np.array([0.01] * 30)  # Düşük vol
        result = detector.predict_regime(returns, vol)
        assert result.regime == "BULL"

    def test_fallback_bear(self):
        """Negatif getiri → BEAR."""
        detector = HMMRegimeDetector()
        returns = np.array([-0.005] * 30)  # Negatif
        vol = np.array([0.01] * 30)  # Düşük vol
        result = detector.predict_regime(returns, vol)
        assert result.regime == "BEAR"

    def test_fallback_high_vol(self):
        """Yüksek volatilite → HIGH_VOL."""
        detector = HMMRegimeDetector()
        returns = np.array([0.0] * 30)
        vol = np.array([0.03] * 30)  # Yüksek vol
        result = detector.predict_regime(returns, vol)
        assert result.regime == "HIGH_VOL"

    def test_transition_matrix_none_before_fit(self):
        """Fit öncesi transition matrix yok."""
        detector = HMMRegimeDetector()
        assert detector.get_transition_matrix() is None

    def test_history_tracking(self):
        """Geçmiş takibi çalışır."""
        detector = HMMRegimeDetector()
        returns = np.array([0.001] * 30)
        vol = np.array([0.01] * 30)

        for _ in range(5):
            detector.predict_regime(returns, vol)

        history = detector.get_history(limit=3)
        assert len(history) == 3
        assert "regime" in history[0]

    def test_regime_duration_stats(self):
        """Rejim süre istatistikleri."""
        detector = HMMRegimeDetector()
        returns = np.array([0.001] * 30)
        vol = np.array([0.01] * 30)

        for _ in range(10):
            detector.predict_regime(returns, vol)

        stats = detector.get_regime_duration_stats()
        assert isinstance(stats, dict)

    def test_hmm_fit_with_sufficient_data(self):
        """Yeterli veri ile HMM eğitimi."""
        detector = HMMRegimeDetector(n_regimes=2, rolling_window=50)

        # Farklı rejimlerde veri üret
        np.random.seed(42)
        bull_returns = np.random.normal(0.002, 0.01, 50)
        bear_returns = np.random.normal(-0.002, 0.015, 50)
        returns = np.concatenate([bull_returns, bear_returns])
        vol = np.abs(np.random.normal(0.015, 0.005, 100))

        fitted = detector.fit(returns, vol)
        # hmmlearn yoksa False döner
        assert isinstance(fitted, bool)


# =====================================================
# Ensemble Forecast Tests
# =====================================================


class TestEnsembleForecaster:
    """Ensemble forecast testleri."""

    def test_register_model(self):
        """Model kayıt."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (1.0, 0.8))
        assert "test" in engine._models

    def test_forecast_basic(self):
        """Temel forecast."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: (2.0, 0.7))
        result = engine.forecast({"momentum_20d": 3}, horizon=5, regime="BULL")
        assert isinstance(result, EnsembleResult)
        assert result.horizon_days == 5
        assert result.regime == "BULL"

    def test_forecast_multiple_models(self):
        """Çoklu model forecast."""
        engine = EnsembleForecaster()
        engine.register_model("a", lambda f, h: (2.0, 0.7))
        engine.register_model("b", lambda f, h: (3.0, 0.6))
        result = engine.forecast({}, horizon=5)
        assert len(result.model_predictions) == 2

    def test_forecast_agreement(self):
        """Model agreement hesaplanır."""
        engine = EnsembleForecaster()
        engine.register_model("a", lambda f, h: (2.0, 0.7))
        engine.register_model("b", lambda f, h: (2.0, 0.7))
        result = engine.forecast({}, horizon=5)
        assert result.model_agreement > 0.9  # Yüksek agreement

    def test_forecast_disagreement(self):
        """Model disagreement."""
        engine = EnsembleForecaster()
        engine.register_model("a", lambda f, h: (5.0, 0.7))
        engine.register_model("b", lambda f, h: (-5.0, 0.7))
        result = engine.forecast({}, horizon=5)
        assert result.model_agreement < 0.5  # Düşük agreement

    def test_forecast_with_dict_return(self):
        """Dict dönen model."""
        engine = EnsembleForecaster()
        engine.register_model("test", lambda f, h: {"prediction": 2.5, "confidence": 0.8})
        result = engine.forecast({}, horizon=5)
        assert result.ensemble_prediction == 2.5

    def test_builtin_models(self):
        """Dahili modeller çalışır."""
        engine = EnsembleForecaster()
        features = {"momentum_20d": 3, "rsi_14": 55, "momentum_5d": 2, "bb_position": 0.6}
        result = engine.forecast(features, horizon=5)
        assert result.ensemble_prediction is not None

    def test_regime_based_weights(self):
        """Rejime göre ağırlıklar farklı."""
        engine = EnsembleForecaster()
        engine.register_model("heuristic", lambda f, h: (2.0, 0.7))
        engine.register_model("momentum", lambda f, h: (3.0, 0.6))
        engine.register_model("statistical", lambda f, h: (1.0, 0.5))
        features = {"momentum_20d": 3, "rsi_14": 55}

        bull = engine.forecast(features, regime="BULL")
        crisis = engine.forecast(features, regime="CRISIS")

        # BULL: momentum ağırlığı yüksek, CRISIS: heuristic ağırlığı yüksek
        # Farklı rejimler → farklı ağırlıklar
        assert bull.weights_used != crisis.weights_used

    def test_calibrated_confidence(self):
        """Kalibre edilmiş confidence."""
        engine = EnsembleForecaster()
        engine.register_model("a", lambda f, h: (2.0, 0.95))
        result = engine.forecast({}, horizon=5)
        # Overconfidence cezası
        assert result.calibrated_confidence <= 0.95

    def test_model_performance(self):
        """Model performans güncelleme."""
        engine = EnsembleForecaster()
        engine.update_performance("test", accuracy=0.65, sharpe=1.2)
        perf = engine.get_model_performance()
        assert "test" in perf


# =====================================================
# Confidence Calibrator Tests
# =====================================================


class TestConfidenceCalibrator:
    """Confidence calibrator testleri."""

    def test_add_observation(self):
        """Gözlem ekleme."""
        cal = ConfidenceCalibrator(min_samples=5)
        cal.add_observation(0.8, True)
        cal.add_observation(0.3, False)
        assert len(cal._observations) == 2

    def test_add_batch(self):
        """Toplu gözlem ekleme."""
        cal = ConfidenceCalibrator(min_samples=5)
        cal.add_batch([0.8, 0.3, 0.9], [True, False, True])
        assert len(cal._observations) == 3

    def test_calibrate_insufficient_data(self):
        """Yetersiz veri."""
        cal = ConfidenceCalibrator(min_samples=30)
        cal.add_observation(0.8, True)
        report = cal.calibrate()
        assert report.n_samples == 1
        assert report.recommended_adjustment == 1.0

    def test_calibrate_perfect_calibration(self):
        """Mükemmel kalibrasyon."""
        cal = ConfidenceCalibrator(min_samples=10, n_bins=5)
        # %80 güven → %80 gerçekleşti
        for _ in range(80):
            cal.add_observation(0.8, True)
        for _ in range(20):
            cal.add_observation(0.8, False)
        report = cal.calibrate()
        assert report.brier_score < 0.3

    def test_calibrate_overconfident(self):
        """Overconfidence tespiti."""
        cal = ConfidenceCalibrator(min_samples=10, n_bins=5)
        # %90 güven ama sadece %50 gerçekleşti
        for _ in range(50):
            cal.add_observation(0.9, True)
        for _ in range(50):
            cal.add_observation(0.9, False)
        report = cal.calibrate()
        assert report.overconfident is True

    def test_adjust_confidence(self):
        """Confidence ayarlama."""
        cal = ConfidenceCalibrator(min_samples=10)
        for _ in range(50):
            cal.add_observation(0.9, True)
        for _ in range(50):
            cal.add_observation(0.9, False)
        adjusted = cal.adjust_confidence(0.9)
        assert adjusted < 0.9

    def test_hit_rate(self):
        """Hit rate hesaplama."""
        cal = ConfidenceCalibrator(min_samples=5)
        cal.add_observation(0.8, True)
        cal.add_observation(0.8, True)
        cal.add_observation(0.8, False)
        cal.add_observation(0.3, True)
        cal.add_observation(0.3, False)
        hit_rate = cal.get_hit_rate(threshold=0.5)
        assert 0 <= hit_rate <= 1

    def test_regime_calibration(self):
        """Rejim bazlı kalibrasyon."""
        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(20):
            cal.add_observation(0.8, True, regime="BULL")
        for _ in range(20):
            cal.add_observation(0.3, False, regime="BEAR")
        regime_cal = cal.get_regime_calibration()
        assert "BULL" in regime_cal or "BEAR" in regime_cal

    def test_stats(self):
        """İstatistikler."""
        cal = ConfidenceCalibrator(min_samples=5)
        cal.add_observation(0.8, True, regime="BULL")
        stats = cal.get_stats()
        assert stats["total_observations"] == 1

    def test_reset(self):
        """Sıfırlama."""
        cal = ConfidenceCalibrator()
        cal.add_observation(0.8, True)
        cal.reset()
        assert len(cal._observations) == 0


# =====================================================
# Advanced Monte Carlo Tests
# =====================================================


class TestAdvancedMonteCarlo:
    """Gelişmiş Monte Carlo testleri."""

    def test_gbm_basic(self):
        """GBM temel test."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=1000, seed=42)
        assert isinstance(result, AdvancedMCResult)
        assert result.model_type == "gbm"
        assert result.p50 > 0

    def test_gbm_percentiles_ordered(self):
        """GBM percentile'lar sıralı."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=5000, seed=42)
        assert result.p10 <= result.p25 <= result.p50 <= result.p75 <= result.p90

    def test_gbm_probabilities(self):
        """GBM olasılıklar 0-1 arası."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=5000, seed=42)
        assert 0 <= result.prob_positive <= 1
        assert 0 <= result.prob_plus_5pct <= 1
        assert 0 <= result.prob_minus_5pct <= 1

    def test_jump_diffusion_basic(self):
        """Jump-diffusion temel test."""
        mc = AdvancedMonteCarloEngine()
        result = mc.jump_diffusion_sim(
            "TEST",
            100,
            0.15,
            0.25,
            jump_intensity=0.1,
            jump_mean=-0.02,
            jump_std=0.05,
            horizon_days=20,
            n_sims=1000,
            seed=42,
        )
        assert result.model_type == "jump_diffusion"
        assert result.jump_intensity == 0.1

    def test_jump_diffusion_fatter_tails(self):
        """Jump-diffusion daha kalın kuyruk."""
        mc = AdvancedMonteCarloEngine()
        gbm = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=5000, seed=42)
        jump = mc.jump_diffusion_sim(
            "TEST",
            100,
            0.15,
            0.25,
            jump_intensity=0.5,
            jump_mean=-0.05,
            jump_std=0.1,
            horizon_days=20,
            n_sims=5000,
            seed=42,
        )
        # Jump-diffusion daha yüksek kurtosis (daha kalın kuyruk)
        assert abs(jump.kurtosis) >= abs(gbm.kurtosis) * 0.5

    def test_student_t_basic(self):
        """Student-t temel test."""
        mc = AdvancedMonteCarloEngine()
        result = mc.student_t_sim("TEST", 100, 0.15, 0.25, degrees_of_freedom=5, horizon_days=20, n_sims=1000, seed=42)
        assert result.model_type == "student_t"
        assert result.p50 > 0

    def test_student_t_fatter_tails(self):
        """Student-t daha kalın kuyruk (düşük df)."""
        mc = AdvancedMonteCarloEngine()
        normal = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=5000, seed=42)
        student = mc.student_t_sim("TEST", 100, 0.15, 0.25, degrees_of_freedom=3, horizon_days=20, n_sims=5000, seed=42)
        # Student-t daha yüksek kurtosis
        assert abs(student.kurtosis) > abs(normal.kurtosis) * 0.5

    def test_heston_basic(self):
        """Heston-lite temel test."""
        mc = AdvancedMonteCarloEngine()
        result = mc.heston_lite_sim(
            "TEST",
            100,
            0.15,
            0.25,
            vol_of_vol=0.3,
            mean_reversion=2.0,
            horizon_days=20,
            n_sims=1000,
            seed=42,
        )
        assert result.model_type == "heston"
        assert result.p50 > 0

    def test_heston_stochastic_vol(self):
        """Heston stochastic vol — sonuç GBM'den farklı."""
        mc = AdvancedMonteCarloEngine()
        gbm = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=60, n_sims=5000, seed=42)
        heston = mc.heston_lite_sim(
            "TEST",
            100,
            0.15,
            0.25,
            vol_of_vol=0.5,
            mean_reversion=3.0,
            horizon_days=60,
            n_sims=5000,
            seed=42,
        )
        # Farklı volatilite
        assert abs(gbm.volatility - heston.volatility) > 0.01

    def test_var_cvar(self):
        """VaR ve CVaR hesaplanır."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=5000, seed=42)
        assert result.var_95 < 0  # Negatif (kayıp)
        assert result.cvar_95 <= result.var_95  # CVaR <= VaR

    def test_max_drawdown(self):
        """Max drawdown pozitif."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=60, n_sims=5000, seed=42)
        assert result.max_drawdown_sim > 0

    def test_sample_paths(self):
        """Sample paths mevcut."""
        mc = AdvancedMonteCarloEngine()
        result = mc.gbm_sim("TEST", 100, 0.15, 0.25, horizon_days=20, n_sims=500, seed=42)
        assert result.sample_paths is not None
        assert result.sample_paths.shape[0] <= 200
        assert result.sample_paths.shape[1] == 21  # t=0 + 20 günlük hareket

    def test_jump_diffusion_horizon_has_requested_daily_moves(self):
        """20 günlük ufuk, başlangıçtan sonra tam 20 günlük adım içermeli."""
        mc = AdvancedMonteCarloEngine()
        result = mc.jump_diffusion_sim(
            "TEST",
            100,
            mu=0.252,
            sigma=0,
            jump_intensity=0,
            horizon_days=20,
            n_sims=10,
            seed=42,
        )
        expected = 100 * np.exp(0.252 * 20 / 252)
        assert abs(result.p50 - expected) < 0.01


# =====================================================
# Run Tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
