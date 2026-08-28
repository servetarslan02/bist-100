"""
ALPHA BIST — Portfolio Optimizer Test Suite
Doğrulanan Özellikler:
1. Risk Parity (Equal Risk Contribution)
2. Hierarchical Risk Parity (HRP)
3. Max Sharpe / Mean-Variance (Markowitz + L2 Regularizer)
4. Black-Litterman (Model Ranking Skor Görüşleri)
5. Min Variance
6. BIST Kısıtları: Max %10 pozisyon, Max %30 sektör, Min %1.5 tozluluk filtresi
7. Likidite haircut, Hysteresis, Turnover cezası, Rejim maruziyet sınırları
8. Uç durumlar: Tek hisse, boş hisse, singular kovaryans matrisi
"""

import numpy as np
import pytest

from services.portfolio.portfolio_enhancements import (
    PortfolioConstraints,
    PortfolioEnhancements,
    portfolio_enhancements,
)
from services.portfolio.portfolio_optimizer import (
    OptimizationMethod,
    OptimizationResult,
    PortfolioOptimizer,
    PortfolioOptimizerConstraints,
    portfolio_optimizer,
)


class TestPortfolioOptimizer:
    """Portföy Optimizasyon Motoru Testleri."""

    @pytest.fixture(autouse=True)
    def setup(self):
        np.random.seed(42)
        self.optimizer = PortfolioOptimizer()
        self.tickers = ["THYAO", "ASELS", "TUPRS", "GARAN", "BIMAS", "KCHOL", "SAHOL", "SISE", "EREGL", "AKBNK"]
        n_assets = len(self.tickers)
        # 100 günlük sentetik getiri serisi
        self.returns = np.random.normal(0.001, 0.02, size=(100, n_assets))
        self.sector_map = {
            "THYAO": "HAVACILIK",
            "ASELS": "SAVUNMA",
            "TUPRS": "ENERJI",
            "GARAN": "FINANS",
            "AKBNK": "FINANS",
            "BIMAS": "PERAKENDE",
            "KCHOL": "HOLDING",
            "SAHOL": "HOLDING",
            "SISE": "CAM",
            "EREGL": "METAL",
        }
        self.liquidity_scores = {
            "THYAO": 95.0,
            "ASELS": 90.0,
            "TUPRS": 88.0,
            "GARAN": 92.0,
            "AKBNK": 85.0,
            "BIMAS": 80.0,
            "KCHOL": 82.0,
            "SAHOL": 78.0,
            "SISE": 75.0,
            "EREGL": 30.0,  # Düşük likidite
        }
        self.model_scores = {
            "THYAO": 92.0,
            "ASELS": 88.0,
            "TUPRS": 84.0,
            "GARAN": 80.0,
            "AKBNK": 76.0,
            "BIMAS": 74.0,
            "KCHOL": 70.0,
            "SAHOL": 68.0,
            "SISE": 65.0,
            "EREGL": 55.0,
        }

    def test_risk_parity_optimization(self):
        """Risk parity optimizasyonu ağırlık ve metrik doğrulaması."""
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.RISK_PARITY,
            regime="BULL",
            sector_map=self.sector_map,
        )
        assert isinstance(res, OptimizationResult)
        assert res.is_optimal is True
        assert res.portfolio_volatility > 0
        assert res.diversification_ratio >= 1.0

        # Long only ve pozisyon limiti
        for t, w in res.weights.items():
            assert w >= 0.0
            assert w <= 0.10 + 1e-4

        # Toplam maruziyet + nakit = 1.0
        total_inv = sum(res.weights.values())
        assert pytest.approx(total_inv + res.cash_weight, abs=1e-3) == 1.0

    def test_hrp_optimization(self):
        """Hierarchical Risk Parity (HRP) optimizasyon testi."""
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.HIERARCHICAL_RISK_PARITY,
            regime="BULL",
            sector_map=self.sector_map,
        )
        assert res.is_optimal is True
        assert len(res.weights) > 0
        for w in res.weights.values():
            assert 0.0 <= w <= 0.10 + 1e-4

    def test_max_sharpe_with_model_scores(self):
        """Model skorları ve L2 regularization ile Max Sharpe testi."""
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.MAX_SHARPE,
            model_scores=self.model_scores,
            regime="SIDEWAYS",
            sector_map=self.sector_map,
        )
        assert res.is_optimal is True
        assert res.effective_positions_count > 0
        # En yüksek skorlu THYAO pozisyon almalı
        assert "THYAO" in res.weights

    def test_black_litterman_optimization(self):
        """Black-Litterman model sinyali optimizasyon testi."""
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.BLACK_LITTERMAN,
            model_scores=self.model_scores,
            regime="SIDEWAYS",
            sector_map=self.sector_map,
        )
        assert res.is_optimal is True
        assert sum(res.weights.values()) <= 0.80 + 1e-3  # SIDEWAYS rejim tavanı

    def test_sector_concentration_cap(self):
        """Sektör konsantrasyon tavanı (%30) kuralının uygulanması."""
        c = PortfolioOptimizerConstraints(max_sector_pct=0.25)
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.EQUAL_WEIGHT,
            sector_map=self.sector_map,
            constraints=c,
            regime="BULL",
        )
        # FINANS sektörü (GARAN + AKBNK) veya HOLDING (KCHOL + SAHOL) %25'i geçemez
        for sec, sec_w in res.sector_exposures.items():
            assert sec_w <= 0.25 + 1e-3

    def test_liquidity_haircut(self):
        """Düşük likiditeli hissede haircut (küçültme) kuralı."""
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.RISK_PARITY,
            liquidity_scores=self.liquidity_scores,
            sector_map=self.sector_map,
            regime="BULL",
        )
        # EREGL likidite skoru 30 (düşük) -> ağırlığı normalden düşük olmalı veya kırpılmalı
        if "EREGL" in res.weights:
            assert res.weights["EREGL"] < 0.08

    def test_regime_adaptive_exposure(self):
        """Rejim bazlı nakit kalkanı ve maruziyet tavanları."""
        # CRISIS rejimi: Maks %15 hisse maruziyeti, %85 nakit
        res_crisis = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.RISK_PARITY,
            regime="CRISIS",
        )
        invested_crisis = sum(res_crisis.weights.values())
        assert invested_crisis <= 0.15 + 1e-3
        assert res_crisis.cash_weight >= 0.85 - 1e-3

        # BEAR rejimi: Maks %45 hisse
        res_bear = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.RISK_PARITY,
            regime="BEAR",
        )
        invested_bear = sum(res_bear.weights.values())
        assert invested_bear <= 0.45 + 1e-3
        assert res_bear.cash_weight >= 0.55 - 1e-3

    def test_dust_position_filter(self):
        """Toz pozisyonların (%1.5 altı) temizlenmesi."""
        c = PortfolioOptimizerConstraints(min_position_pct=0.02)
        res = self.optimizer.optimize(
            tickers=self.tickers,
            returns_matrix=self.returns,
            method=OptimizationMethod.MIN_VARIANCE,
            constraints=c,
            regime="BULL",
        )
        for w in res.weights.values():
            assert w >= 0.02

    def test_edge_cases(self):
        """Uç durum testleri: Tek hisse, boş hisse, tekil matris."""
        # Boş hisse
        res_empty = self.optimizer.optimize(tickers=[], returns_matrix=np.empty((10, 0)))
        assert res_empty.is_optimal is False
        assert len(res_empty.weights) == 0

        # Tek hisse
        res_single = self.optimizer.optimize(
            tickers=["THYAO"],
            returns_matrix=np.random.normal(0, 1, size=(50, 1)),
        )
        assert res_single.is_optimal is True
        assert res_single.weights["THYAO"] == 0.95
        assert res_single.cash_weight == 0.05

        # Tekil / Sıfır Varyanslı Matris (Collinear)
        collinear_returns = np.ones((50, 4)) * 0.01
        res_collinear = self.optimizer.optimize(
            tickers=["A", "B", "C", "D"],
            returns_matrix=collinear_returns,
            method=OptimizationMethod.RISK_PARITY,
        )
        assert isinstance(res_collinear, OptimizationResult)
        assert sum(res_collinear.weights.values()) > 0


class TestPortfolioEnhancements:
    """Portfolio Enhancements & Rebalance Karar Motoru Testleri."""

    def test_turnover_penalty_stability(self):
        """Turnover penalty shrinkage stabilitesi ve sınır kontrolü."""
        pe = PortfolioEnhancements()
        target = {"THYAO": 0.30, "ASELS": 0.20, "GARAN": 0.50}
        current = {"THYAO": 0.10, "ASELS": 0.10, "GARAN": 0.80}

        adjusted = pe.apply_turnover_penalty(target, current, penalty=0.05)
        # Hedef ağırlık mevcut ağırlığa doğru yaklaşmalı, ters yöne savrulmamalı
        assert adjusted["THYAO"] >= 0.10
        assert adjusted["THYAO"] <= 0.30
        assert pytest.approx(sum(adjusted.values()), abs=1e-4) == 1.0

    def test_should_rebalance_decision(self):
        """Rebalance maliyet-fayda analizi."""
        pe = PortfolioEnhancements()
        # Küçük sapma -> rebalance yapılmamalı (hysteresis)
        target_small = {"A": 0.51, "B": 0.49}
        current_small = {"A": 0.50, "B": 0.50}
        dec_small = pe.should_rebalance(current_small, target_small)
        assert dec_small.should_rebalance is False

        # Büyük faydalı sapma -> rebalance yapılmalı
        target_large = {"A": 0.80, "B": 0.20}
        current_large = {"A": 0.20, "B": 0.80}
        dec_large = pe.should_rebalance(current_large, target_large)
        assert dec_large.should_rebalance is True
        assert dec_large.turnover > 0.30
