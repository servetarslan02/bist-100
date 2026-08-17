"""Bölüm 24 — Feature Engineering Testleri."""
import pytest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.features.technical_features import TechnicalFeatureEngine
from services.features.feature_selector import FeatureSelector


class TestTechnicalFeatures:
    def test_trend_features(self):
        e = TechnicalFeatureEngine()
        prices = np.random.uniform(90, 110, 100)
        f = e.compute_trend_features(prices)
        assert "sma_20" in f
        assert "sma_50" in f
        assert "ema_20" in f
        assert "macd" in f
        assert "sma_20_50_cross" in f

    def test_momentum_features(self):
        e = TechnicalFeatureEngine()
        prices = np.random.uniform(90, 110, 50)
        highs = prices * 1.02
        lows = prices * 0.98
        f = e.compute_momentum_features(prices, highs, lows)
        assert "rsi_14" in f
        assert 0 <= f["rsi_14"] <= 100
        assert "roc_5d" in f
        assert "stochastic_k" in f

    def test_volatility_features(self):
        e = TechnicalFeatureEngine()
        prices = np.random.uniform(90, 110, 100)
        highs = prices * 1.02
        lows = prices * 0.98
        f = e.compute_volatility_features(prices, highs, lows, prices)
        assert "realized_vol_20d" in f
        assert "atr_14" in f
        assert "bb_upper" in f
        assert "bb_lower" in f
        assert f["bb_upper"] > f["bb_lower"]

    def test_volume_features(self):
        e = TechnicalFeatureEngine()
        prices = np.random.uniform(90, 110, 50)
        volumes = np.random.uniform(100000, 1000000, 50)
        f = e.compute_volume_features(prices, volumes)
        assert "volume_sma_20" in f
        assert "volume_ratio" in f
        assert "obv" in f

    def test_rsi_boundaries(self):
        e = TechnicalFeatureEngine()
        # Tüm yukarı
        prices = np.arange(100, 120, dtype=float)
        rsi = e._rsi(prices)
        assert rsi == 100.0

        # Tüm aşağı
        prices = np.arange(120, 100, -1, dtype=float)
        rsi = e._rsi(prices)
        assert rsi == 0.0

    def test_empty_data(self):
        e = TechnicalFeatureEngine()
        assert e.compute_trend_features(np.array([])) == {}
        assert e.compute_momentum_features(np.array([])) == {}


class TestFeatureSelector:
    def test_correlation_filter(self):
        s = FeatureSelector()
        X = np.random.rand(100, 5)
        X[:, 1] = X[:, 0] * 1.001  # Yüksek korelasyon
        names = ["a", "b", "c", "d", "e"]
        X_sel, names_sel = s.select_by_correlation(X, names, threshold=0.95)
        assert len(names_sel) < 5
        assert "a" in names_sel

    def test_variance_filter(self):
        s = FeatureSelector()
        X = np.random.rand(100, 4)
        X[:, 2] = 0.0001  # Düşük varyans
        names = ["a", "b", "c", "d"]
        X_sel, names_sel = s.select_by_variance(X, names, threshold=0.01)
        assert "c" not in names_sel

    def test_importance_ranking(self):
        s = FeatureSelector()
        imp = np.array([0.1, 0.5, 0.3, 0.05, 0.4])
        names = ["a", "b", "c", "d", "e"]
        ranked = s.rank_by_importance(imp, names, top_n=3)
        assert ranked[0][0] == "b"
        assert len(ranked) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
