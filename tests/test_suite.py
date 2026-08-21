"""
ALPHA BIST — Test Suite v2.0 (pytest entegrasyonu)

Tüm testler pytest fixtures kullanıyor.
Coverage: Feature, Motor, Karar, Risk, Portföy, API

FAZ 12: Testing & Validation
"""

import pytest
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any

# === FIXTURES ===

@pytest.fixture
def sample_price_data():
    """Örnek fiyat verisi."""
    import pandas as pd
    import numpy as np

    dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
    np.random.seed(42)

    close = 100 + np.cumsum(np.random.randn(60) * 2)
    high = close + np.abs(np.random.randn(60)) * 3
    low = close - np.abs(np.random.randn(60)) * 3
    volume = np.random.randint(1000000, 10000000, 60)

    return pd.DataFrame({
        'Open': close - np.abs(np.random.randn(60)),
        'High': high,
        'Low': low,
        'Close': close,
        'Volume': volume,
    }, index=dates)

@pytest.fixture
def sample_features():
    """Örnek feature'lar."""
    return {
        "roc_5d": 3.5,
        "roc_20d": 8.2,
        "momentum_20d": 12.4,
        "rsi_14": 58.0,
        "volume_zscore": 1.8,
        "volume_trend": 15.0,
        "bb_position": 0.65,
        "price_vs_sma20": 4.2,
        "price_vs_sma50": 8.1,
        "adx": 28.0,
        "sentiment_score": 0.45,
        "sentiment_momentum": 0.12,
        "fundamental_score": 65.0,
        "pe_ratio": 12.5,
        "pb_ratio": 1.8,
        "debt_to_equity": 0.45,
        "roe": 18.5,
        "profit_margin": 12.0,
        "atr_14": 2.5,
        "atr_pct": 2.5,
        "price": 100.0,
        # RankingModel rejim ağırlıklarında kullanılan ek feature'lar
        "trend_slope_20d": 1.5,
        "rs_vs_bist_5d": 2.0,
        "breakout_failure": 0.0,
        "drawdown_20d": -3.0,
        "falling_is_temporary": 0.0,
        "balance_sheet_quality": 70.0,
        "sector_norm_pe_ratio": 0.9,
        "fcf_yield_pct": 5.5,
    }

@pytest.fixture
def decision_input(sample_features):
    """Örnek karar girdisi."""
    from services.core.decision_engine import DecisionInput
    return DecisionInput(
        ticker="THYAO",
        price=100.0,
        features=sample_features,
        signals={"momentum": 0.8, "breakout": 0.6},
        regime="BULL",
        ml_score=75.0,
        ml_confidence=0.85,
        news_sentiment=0.3,
        sector="Havacılık",
        market_cap=50000000000,
        atr=2.5,
        atr_pct=2.5,
    )

@pytest.fixture
def portfolio():
    """Boş portföy."""
    from services.portfolio.portfolio_manager import PortfolioManager
    return PortfolioManager(initial_capital=100000)

# === FEATURE TESTS ===

class TestFeatureCalculator:
    """Feature hesaplama testleri."""

    def test_compute_all_features(self, sample_price_data):
        """Tüm feature'ların hesaplandığını doğrula."""
        from services.features.calculator import feature_calculator

        features = feature_calculator.compute_all_features(sample_price_data)

        assert len(features) > 0
        assert "sma_20" in features
        assert "rsi_14" in features
        assert "macd" in features
        assert "atr_14" in features
        assert "stoch_k" in features
        assert "stoch_d" in features

    def test_stochastic_calculation(self, sample_price_data):
        """Stochastic D = SMA(3) of K doğrula."""
        from services.features.calculator import feature_calculator

        features = feature_calculator.compute_all_features(sample_price_data)

        k = features["stoch_k"]
        d = features["stoch_d"]

        # D, K'nın ortalaması olmalı (yaklaşık)
        assert 0 <= k <= 100
        assert 0 <= d <= 100
        assert abs(d - k) < 30  # Yakın olmalı

    def test_atr_calculation(self, sample_price_data):
        """ATR hesaplamasını doğrula."""
        from services.features.calculator import feature_calculator

        features = feature_calculator.compute_all_features(sample_price_data)

        atr = features["atr_14"]
        atr_pct = features["atr_pct"]

        assert atr > 0
        assert atr_pct > 0
        assert atr_pct == pytest.approx((atr / sample_price_data["Close"].iloc[-1]) * 100, rel=0.01)

# === DECISION ENGINE TESTS ===

class TestDecisionEngine:
    """Karar motoru testleri."""

    def test_decision_with_atr(self, decision_input):
        """ATR bazlı stop/target hesaplaması."""
        from services.core.decision_engine import decision_engine

        decision = decision_engine.decide(decision_input)

        assert decision.stop_price > 0
        assert decision.target_price > 0

        # LONG için stop < price < target
        if decision.direction == "LONG":
            assert decision.stop_price < decision_input.price
            assert decision.target_price > decision_input.price

    def test_short_position_check(self, decision_input):
        """SHORT kararı için pozisyon kontrolü."""
        from services.core.decision_engine import decision_engine

        # Bearish features
        decision_input.features["momentum_20d"] = -15
        decision_input.features["roc_5d"] = -8
        decision_input.features["rsi_14"] = 35
        decision_input.ml_score = 30

        decision = decision_engine.decide(decision_input)

        # Portföyde pozisyon yoksa SELL veto edilmeli
        # (Bu run_system'de kontrol ediliyor)
        assert decision.action in ["SELL", "NO_ACTION", "HOLD"]

    def test_composite_score_range(self, decision_input):
        """Composite skor 0-100 aralığında."""
        from services.core.decision_engine import decision_engine

        decision = decision_engine.decide(decision_input)

        assert 0 <= decision.score <= 100
        assert 0 <= decision.confidence <= 1

# === RANKING MODEL TESTS ===

class TestRankingModel:
    """Sıralama modeli testleri."""

    def test_feature_name_sync(self, sample_features):
        """Feature isimlerinin senkronizasyonunu doğrula."""
        from services.ml.ranking_model import ranking_model

        # Tüm rejim-bazlı ağırlık isimleri sample_features'ta olmalı
        for regime_weights in ranking_model._regime_feature_weights.values():
            for name in regime_weights.keys():
                assert name in sample_features, f"Feature '{name}' eksik"

    def test_rank_output(self, sample_features):
        """Sıralama çıktısını doğrula."""
        from services.ml.ranking_model import ranking_model

        features_map = {
            "THYAO": sample_features,
            "GARAN": {**sample_features, "momentum_20d": -5, "roc_5d": -3},
        }

        result = ranking_model.rank(features_map, "BULL")
        scores = result.scores

        assert len(scores) == 2
        # Yüksek skor = üst sıra (rank 1)
        assert scores[0].score >= scores[1].score  # Sıralı (azalan)
        assert all(s.direction in ["LONG", "SHORT"] for s in scores)

# === PORTFOLIO TESTS ===

class TestPortfolioManager:
    """Portföy yöneticisi testleri."""

    def test_open_position(self, portfolio):
        """Pozisyon açma."""
        notional = 100 * 100.0
        expected_commission = portfolio.calculate_commission(notional)
        result = portfolio.open_position(
            ticker="THYAO",
            direction="LONG",
            quantity=100,
            price=100.0,
            stop_price=95.0,
            target_price=110.0,
        )

        assert result["success"] is True
        assert "THYAO" in portfolio._positions
        # Nakit, işlem tutarı + gerçekçi komisyon kadar azalır (bkz.
        # documentation/06 — execution simülasyonu maliyetleri görmezden
        # gelmez).
        assert portfolio._cash == pytest.approx(100000.0 - notional - expected_commission, abs=0.01)

    def test_close_position(self, portfolio):
        """Pozisyon kapatma."""
        portfolio.open_position("THYAO", "LONG", 100, 100.0)

        result = portfolio.close_position("THYAO", 110.0)

        assert result["success"] is True
        assert "THYAO" not in portfolio._positions
        # PnL, brüt kâr eksi giriş+çıkış komisyonları olmalı; sabit
        # (110-100)*100=1000 varsayımı gerçekçi komisyon modelini
        # görmezden geldiği için brüt kârdan az olmalı ama yakın olmalı.
        gross_pnl = (110.0 - 100.0) * 100
        assert result["trade"]["pnl"] < gross_pnl
        assert result["trade"]["pnl"] == pytest.approx(gross_pnl, abs=20.0)

    def test_insufficient_cash(self, portfolio):
        """Yetersiz nakit kontrolü."""
        result = portfolio.open_position(
            ticker="THYAO",
            direction="LONG",
            quantity=2000,  # 200000 TL gerekli
            price=100.0,
        )

        assert result["success"] is False
        assert "Yetersiz nakit" in result["error"]

    def test_risk_metrics(self, portfolio):
        """Risk metrikleri."""
        portfolio.open_position("THYAO", "LONG", 100, 100.0, sector="Havacılık")
        portfolio.open_position("GARAN", "LONG", 200, 50.0, sector="Bankacılık")

        risk = portfolio.get_risk_metrics()

        assert "risk_level" in risk
        assert "max_position_pct" in risk
        assert "sector_concentration" in risk

    def test_stop_loss_check(self, portfolio):
        """Stop-loss kontrolü."""
        portfolio.open_position("THYAO", "LONG", 100, 100.0, stop_price=95.0)

        assert portfolio.check_stop_loss("THYAO", 94.0) is True
        assert portfolio.check_stop_loss("THYAO", 96.0) is False
        assert portfolio.check_stop_loss("THYAO", 100.0) is False

# === LEARNING SYSTEM TESTS ===

class TestLearningSystem:
    """Öğrenme sistemi testleri."""

    def test_record_prediction(self):
        """Tahmin kaydetme."""
        from services.learning.integrated_learning import learning_system

        pred_id = learning_system.record_prediction(
            ticker="THYAO",
            regime="BULL",
            predicted_direction="UP",
            confidence=0.85,
        )

        assert pred_id.startswith("PRED_")
        assert len(learning_system._predictions) > 0

    def test_record_outcome(self):
        """Outcome kaydetme."""
        from services.learning.integrated_learning import learning_system

        # Önce tahmin kaydet
        learning_system.record_prediction(
            ticker="THYAO",
            regime="BULL",
            predicted_direction="UP",
            confidence=0.85,
        )

        # Sonra outcome
        result = learning_system.record_outcome(
            ticker="THYAO",
            actual_price=110.0,
            entry_price=100.0,
        )

        assert result["success"] is True
        assert result["outcome"]["actual_return"] == 10.0

    def test_get_pending_outcomes(self):
        """Bekleyen tahminleri getir."""
        from services.learning.integrated_learning import learning_system

        learning_system.record_prediction(
            ticker="THYAO",
            regime="BULL",
            predicted_direction="UP",
            confidence=0.85,
        )

        pending = learning_system.get_pending_outcomes()

        assert len(pending) > 0
        assert pending[0]["ticker"] == "THYAO"

    def test_regime_accuracy(self):
        """Regime bazlı doğruluk."""
        from services.learning.integrated_learning import learning_system

        # Doğru tahmin
        learning_system.record_prediction("THYAO", "BULL", "UP", 0.8)
        learning_system.record_outcome("THYAO", 110.0, 100.0)

        # Yanlış tahmin
        learning_system.record_prediction("GARAN", "BEAR", "UP", 0.7)
        learning_system.record_outcome("GARAN", 90.0, 100.0)

        stats = learning_system.get_stats()

        assert stats["total_predictions"] >= 2
        assert "regime_accuracy" in stats

# === API TESTS ===

class TestAPI:
    """API endpoint testleri."""

    @pytest.fixture
    def client(self):
        """Test client."""
        from fastapi.testclient import TestClient
        from services.api.app import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded", "HEALTHY"]

    def test_market_endpoint(self, client):
        """Piyasa verisi."""
        response = client.get("/api/v1/market/state")
        assert response.status_code == 200
        data = response.json()
        assert "regime" in data

    def test_opportunities_endpoint(self, client):
        """Fırsatlar."""
        response = client.get("/api/v1/scanner/results?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data or isinstance(data, list)

    def test_portfolio_endpoint(self, client):
        """Portföy."""
        response = client.get("/api/v1/portfolio/state")
        assert response.status_code == 200
        data = response.json()
        assert "cash" in data or "portfolio" in data

    def test_learning_endpoint(self, client):
        """Öğrenme."""
        response = client.get("/api/v1/learning/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

# === INTEGRATION TESTS ===

class TestIntegration:
    """Entegrasyon testleri."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, sample_price_data, sample_features):
        """Tam pipeline testi."""
        from services.features.calculator import feature_calculator
        from services.intelligence.regime import regime_engine
        from services.ml.ranking_model import ranking_model
        from services.core.decision_engine import decision_engine, DecisionInput
        from services.portfolio.portfolio_manager import portfolio_manager

        # 1. Feature hesapla
        features = feature_calculator.compute_all_features(sample_price_data)
        assert len(features) > 0

        # 2. Rejim tespit (regime-level feature'lar ile, per-ticker fiyat verisiyle değil)
        regime_features = {
            "breadth_pct": 56.0,
            "momentum_avg": 1.5,
            "volatility_avg": 20.0,
            "rsi_avg": 55.0,
            "risk_appetite": 0.5,
            "usdtry_momentum": 0.0,
            "vix_level": 18.0,
            "global_momentum": 0.5,
        }
        regime = regime_engine.detect_regime(regime_features)
        assert regime.regime is not None

        # 3. Sıralama
        features_map = {"THYAO": {**sample_features, **features}}
        result = ranking_model.rank(features_map, regime.regime.value)
        scores = result.scores
        assert len(scores) > 0

        # 4. Karar
        decision_input = DecisionInput(
            ticker="THYAO",
            price=sample_price_data["Close"].iloc[-1],
            features=features_map["THYAO"],
            signals={},
            regime=regime.regime.value,
            ml_score=scores[0].score,
            ml_confidence=scores[0].confidence,
            news_sentiment=0.3,
            sector="Havacılık",
            market_cap=50000000000,
            atr=features.get("atr_14", 0),
            atr_pct=features.get("atr_pct", 0),
        )

        decision = decision_engine.decide(decision_input)
        assert decision.action in ["BUY", "SELL", "HOLD", "NO_ACTION"]
        if decision.action in ["BUY", "SELL"]:
            assert decision.stop_price > 0
            assert decision.target_price > 0

        # 5. Portföy
        if decision.action == "BUY":
            result = portfolio_manager.open_position(
                ticker="THYAO",
                direction="LONG",
                quantity=100,
                price=decision_input.price,
                stop_price=decision.stop_price,
                target_price=decision.target_price,
            )
            assert result["success"] is True

# === RUN ===
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
