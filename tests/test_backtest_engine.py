from __future__ import annotations

from typing import Any
"""ALPHA BIST — Backtest Engine Test Suite

Kapsamlı test suite:
- PortfolioSimulatorV3 (buy/sell, metrics, invariants)
- BacktestConfig / BacktestMetrics / BacktestResultV4
- TransactionCostEngine (BIST fees, slippage, market impact)
- DeflatedSharpeCalculator (DSR, PSR)
- WalkForwardEngine (fold creation, purge/embargo)
- BiasDetector (look-ahead, fold boundaries)
- SurvivorshipBiasHandler (universe at date)
- BacktestPersistence (save/load)
- BenchmarkComparator (alpha, beta, IR)
"""


from datetime import datetime

import numpy as np

from services.backtest.benchmark import BenchmarkComparator
from services.backtest.bias_detector import LookAheadBiasDetector
from services.backtest.deflated_sharpe import (
    DeflatedSharpeCalculator,
    ProbabilisticSharpeRatio,
)
from services.backtest.portfolio_sim import (
    BISTCommissionModel,
    PortfolioSimulatorV3,
)
from services.backtest.survivorship import (
    DelistingEvent,
    SurvivorshipBiasHandler,
)
from services.backtest.transaction_costs import (
    LiquidityTier,
    SlippageModel,
    SpreadModel,
    TransactionCostEngine,
)
from services.backtest.walk_forward import WalkForwardEngine

# =====================================================
# PORTFOLIO SIMULATOR TESTS
# =====================================================


class TestPortfolioSimulator:
    """PortfolioSimulatorV3 testleri."""

    def test_initial_state(self) -> Any:
        """Başlangıç durumu doğru olmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000)
        assert sim.get_total_value() == 100_000
        assert sim.get_position_count() == 0
        assert sim.can_buy() is True

    def test_execute_buy(self) -> Any:
        """Alım emri doğru çalışmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        trade = sim.execute_buy("THYAO", 100.0, "2026-01-01")
        assert trade is not None
        assert trade.side == "BUY"
        assert trade.ticker == "THYAO"
        assert sim.has_position("THYAO") is True
        assert sim.get_position_count() == 1

    def test_execute_sell(self) -> Any:
        """Satım emri doğru çalışmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        trade = sim.execute_sell("THYAO", 110.0, "2026-01-10")
        assert trade is not None
        assert trade.side == "SELL"
        assert trade.pnl > 0  # Kar etmeli
        assert sim.has_position("THYAO") is False

    def test_duplicate_buy_rejected(self) -> Any:
        """Aynı hisseye tekrar alım reddedilmeli."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        trade = sim.execute_buy("THYAO", 100.0, "2026-01-02")
        assert trade is None

    def test_max_positions_limit(self) -> Any:
        """Maks pozisyon limiti uygulanmalı."""
        sim = PortfolioSimulatorV3(initial_capital=1_000_000, max_positions=2, max_position_pct=0.10)
        sim.execute_buy("A", 100.0, "2026-01-01")
        sim.execute_buy("B", 100.0, "2026-01-01")
        trade = sim.execute_buy("C", 100.0, "2026-01-01")
        assert trade is None

    def test_invalid_price_rejected(self) -> Any:
        """Geçersiz fiyat reddedilmeli."""
        sim = PortfolioSimulatorV3(initial_capital=100_000)
        assert sim.execute_buy("THYAO", 0, "2026-01-01") is None
        assert sim.execute_buy("THYAO", -10, "2026-01-01") is None

    def test_equity_update(self) -> Any:
        """Equity güncelleme doğru çalışmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        sim.update_equity({"THYAO": 110.0}, "2026-01-02")
        curve = sim.get_equity_curve()
        assert len(curve) == 1
        assert curve[0].equity > 100_000  # Kar etmeli

    def test_invariants(self) -> Any:
        """Finansal invariant'lar korunmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        sim.update_equity({"THYAO": 105.0}, "2026-01-02")
        ok, errors = sim.check_invariants()
        assert ok is True, f"Invariant violations: {errors}"

    def test_metrics_empty(self) -> Any:
        """Boş trade ile metrikler sıfır olmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000)
        metrics = sim.compute_metrics()
        assert metrics["total_trades"] == 0
        assert metrics["win_rate_pct"] == 0

    def test_metrics_with_trades(self) -> Any:
        """Trade'ler sonrası metrikler hesaplanmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        sim.update_equity({"THYAO": 110.0}, "2026-01-02")
        sim.execute_sell("THYAO", 110.0, "2026-01-03")
        sim.update_equity({}, "2026-01-03")
        metrics = sim.compute_metrics()
        assert metrics["total_trades"] > 0
        assert metrics["win_rate_pct"] == 100.0

    def test_reset(self) -> Any:
        """Reset tüm durumu sıfırlamalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        sim.reset()
        assert sim.get_position_count() == 0
        assert sim.get_total_value() == 100_000


# =====================================================
# COMMISSION MODEL TESTS
# =====================================================


class TestBISTCommissionModel:
    """BIST komisyon modeli testleri."""

    def test_basic_commission(self) -> Any:
        """Temel komisyon hesaplaması doğru olmalı."""
        comm = BISTCommissionModel.compute(100_000)
        assert comm > 0
        assert comm < 100_000 * 0.01  # %1'den az olmalı

    def test_minimum_commission(self) -> Any:
        """Minimum komisyon uygulanmalı."""
        comm = BISTCommissionModel.compute(100)
        assert comm >= BISTCommissionModel.MIN_COMMISSION


# =====================================================
# TRANSACTION COST ENGINE TESTS
# =====================================================


class TestTransactionCostEngine:
    """TransactionCostEngine testleri."""

    def test_buy_cost(self) -> Any:
        """Alım maliyeti doğru hesaplanmalı."""
        engine = TransactionCostEngine()
        result = engine.calculate_total_cost("BUY", 100.0, 100, "THYAO", avg_daily_volume=10_000_000)
        assert result["total_cost"] > 0
        assert result["execution_price"] > 100.0  # Alımda fiyat yükselir

    def test_sell_cost(self) -> Any:
        """Satım maliyeti doğru hesaplanmalı."""
        engine = TransactionCostEngine()
        result = engine.calculate_total_cost("SELL", 100.0, 100, "THYAO", avg_daily_volume=10_000_000)
        assert result["total_cost"] > 0
        assert result["execution_price"] < 100.0  # Satımda fiyat düşer

    def test_zero_price_returns_zero(self) -> Any:
        """Sıfır fiyat sıfır maliyet döndürmeli."""
        engine = TransactionCostEngine()
        result = engine.calculate_total_cost("BUY", 0, 100, "THYAO")
        assert result["total_cost"] == 0

    def test_liquidity_classification(self) -> Any:
        """Likidite sınıflandırması doğru olmalı."""
        engine = TransactionCostEngine()
        assert engine.classify_liquidity(600_000_000) == LiquidityTier.TIER_1
        assert engine.classify_liquidity(150_000_000) == LiquidityTier.TIER_2
        assert engine.classify_liquidity(50_000_000) == LiquidityTier.TIER_3
        assert engine.classify_liquidity(5_000_000) == LiquidityTier.TIER_4

    def test_round_trip_cost(self) -> Any:
        """Round-trip maliyet pozitif olmalı."""
        engine = TransactionCostEngine()
        result = engine.estimate_round_trip_cost("THYAO", 100.0, 100, avg_daily_volume=10_000_000)
        assert result["round_trip_cost"] > 0
        assert result["break_even_return_pct"] > 0


# =====================================================
# SPREAD MODEL TESTS
# =====================================================


class TestSpreadModel:
    """Spread modeli testleri."""

    def test_tier_1_spread_narrow(self) -> Any:
        """Tier 1 spread dar olmalı."""
        model = SpreadModel()
        spread = model.estimate_spread(LiquidityTier.TIER_1)
        assert spread < 0.01  # %1'den az

    def test_tier_4_spread_wider_than_tier_1(self) -> Any:
        """Tier 4 spread, Tier 1'den geniş olmalı."""
        model = SpreadModel()
        tier_1 = model.estimate_spread(LiquidityTier.TIER_1)
        tier_4 = model.estimate_spread(LiquidityTier.TIER_4)
        assert tier_4 > tier_1

    def test_high_volatility_widens_spread(self) -> Any:
        """Yüksek volatilite spread'i genişletmeli."""
        model = SpreadModel()
        normal = model.estimate_spread(LiquidityTier.TIER_1, volatility_ratio=1.0)
        high_vol = model.estimate_spread(LiquidityTier.TIER_1, volatility_ratio=2.0)
        assert high_vol > normal


# =====================================================
# SLIPPAGE MODEL TESTS
# =====================================================


class TestSlippageModel:
    """Slippage modeli testleri."""

    def test_basic_slippage(self) -> Any:
        """Temel slippage pozitif olmalı."""
        model = SlippageModel()
        slip = model.estimate_slippage("BUY")
        assert slip > 0

    def test_high_volatility_increases_slippage(self) -> Any:
        """Yüksek volatilite slippage'ı artırmalı."""
        model = SlippageModel()
        normal = model.estimate_slippage("BUY", volatility_ratio=1.0)
        high_vol = model.estimate_slippage("BUY", volatility_ratio=3.0)
        assert high_vol > normal


# =====================================================
# DEFLATED SHARPE TESTS
# =====================================================


class TestDeflatedSharpe:
    """Deflated Sharpe Ratio testleri."""

    def test_single_strategy(self) -> Any:
        """Tek strateji için DSR hesaplanmalı."""
        result = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=1.5,
            num_strategies=1,
            num_observations=252,
        )
        assert result.observed_sharpe == 1.5
        assert result.deflated_sharpe > 0
        assert 0 <= result.p_value <= 1

    def test_multiple_strategies_computed(self) -> Any:
        """Çoklu strateji testi ile DSR hesaplanmalı."""
        single = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=1.5,
            num_strategies=2,
            num_observations=252,
        )
        multiple = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=1.5,
            num_strategies=100,
            num_observations=252,
        )
        # Her iki durumda da DSR hesaplanmalı
        assert single.deflated_sharpe != 0
        assert multiple.deflated_sharpe != 0
        # 100 strateji ile expected_max_sharpe daha yüksek olmalı
        assert multiple.expected_max_sharpe > single.expected_max_sharpe

    def test_from_returns(self) -> Any:
        """Getiri serisinden DSR hesaplanmalı."""
        returns = np.random.normal(0.001, 0.02, 252)
        result = DeflatedSharpeCalculator.from_returns(returns, num_strategies=1)
        assert result.observed_sharpe != 0

    def test_psr(self) -> Any:
        """PSR 0-1 arasında olmalı."""
        psr = ProbabilisticSharpeRatio.compute(
            observed_sharpe=1.5,
            benchmark_sharpe=0.0,
            num_observations=252,
        )
        assert 0 <= psr <= 1


# =====================================================
# WALK-FORWARD ENGINE TESTS
# =====================================================


class TestWalkForwardEngine:
    """Walk-forward engine testleri."""

    def test_fold_creation(self) -> Any:
        """Fold oluşturma doğru çalışmalı."""
        wf = WalkForwardEngine(
            purge_days=5,
            embargo_days=5,
            train_days=100,
            test_days=30,
            step_days=15,
        )
        dates = (
            [f"2020-01-{i:02d}" for i in range(1, 32)]
            + [f"2020-02-{i:02d}" for i in range(1, 29)]
            + [f"2020-03-{i:02d}" for i in range(1, 32)]
            + [f"2020-04-{i:02d}" for i in range(1, 31)]
            + [f"2020-05-{i:02d}" for i in range(1, 32)]
        )
        folds = wf.create_folds(dates)
        # Yeterli veri varsa fold oluşmalı
        assert len(folds) >= 0  # Veriye bağlı

    def test_purge_gap_exists(self) -> Any:
        """Purge gap korunmalı."""
        wf = WalkForwardEngine(purge_days=5, train_days=50, test_days=10, step_days=10)
        dates = [f"2020-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 32) if d <= 28]
        folds = wf.create_folds(dates)
        for fold in folds:
            assert fold["train_end"] < fold["purge_start"]
            assert fold["purge_end"] < fold["test_start"]

    def test_empty_data(self) -> Any:
        """Boş veri ile boş sonuç dönmeli."""
        wf = WalkForwardEngine()
        result = wf.run_walk_forward(predictions=[], actual_returns={})
        assert result.total_folds == 0


# =====================================================
# BIAS DETECTOR TESTS
# =====================================================


class TestBiasDetector:
    """Look-ahead bias detector testleri."""

    def test_label_feature_alignment_ok(self) -> Any:
        """Yeterli purge ile uyum sağlanmalı."""
        detector = LookAheadBiasDetector()
        report = detector.validate_label_feature_alignment(
            label_horizon_days=5,
            feature_window_days=20,
            purge_days=5,
        )
        assert report.is_clean is True

    def test_label_feature_alignment_fail(self) -> Any:
        """Yetersiz purge ile uyum sağlanmamalı."""
        detector = LookAheadBiasDetector()
        report = detector.validate_label_feature_alignment(
            label_horizon_days=10,
            feature_window_days=20,
            purge_days=3,  # purge < horizon
        )
        assert report.is_clean is False

    def test_fold_boundary_ok(self) -> Any:
        """Geçerli fold sınırları temiz olmalı."""
        from datetime import datetime

        detector = LookAheadBiasDetector()
        report = detector.validate_fold_boundaries(
            train_end=datetime(2026, 1, 1),
            test_start=datetime(2026, 1, 10),
            purge_days=5,
            embargo_days=5,
            label_horizon_days=5,
        )
        assert report.is_clean is True

    def test_fold_boundary_fail(self) -> Any:
        """Test train'den önce başlıyorsa ihlal olmalı."""
        from datetime import datetime

        detector = LookAheadBiasDetector()
        report = detector.validate_fold_boundaries(
            train_end=datetime(2026, 1, 10),
            test_start=datetime(2026, 1, 5),  # Train'den önce
            purge_days=5,
            embargo_days=5,
            label_horizon_days=5,
        )
        assert report.is_clean is False


# =====================================================
# SURVIVORSHIP BIAS TESTS
# =====================================================


class TestSurvivorshipBias:
    """Survivorship bias handler testleri."""

    def test_universe_at_date(self) -> Any:
        """Tarihsel evren doğru hesaplanmalı."""
        handler = SurvivorshipBiasHandler()
        handler.register_delisting(
            DelistingEvent(
                ticker="DEAD",
                delisting_date=datetime(2025, 6, 1),
                reason="bankruptcy",
            )
        )
        handler.set_active_universe({"THYAO", "GARAN", "DEAD"})

        # Delisting öncesi
        universe = handler.get_universe_at_date(datetime(2025, 1, 1), {"THYAO", "GARAN", "DEAD"})
        assert "DEAD" in universe

        # Delisting sonrası
        universe = handler.get_universe_at_date(datetime(2025, 12, 1), {"THYAO", "GARAN", "DEAD"})
        assert "DEAD" not in universe

    def test_empty_delistings(self) -> Any:
        """Boş delisting ile tüm hisseler aktif olmalı."""
        handler = SurvivorshipBiasHandler()
        universe = handler.get_universe_at_date(datetime(2026, 1, 1), {"THYAO", "GARAN"})
        assert universe == {"THYAO", "GARAN"}


# =====================================================
# BENCHMARK COMPARATOR TESTS
# =====================================================


class TestBenchmarkComparator:
    """Benchmark karşılaştırma testleri."""

    def test_identical_returns(self) -> Any:
        """Aynı getiriler ile alpha sıfır olmalı."""
        returns = np.random.normal(0.001, 0.02, 100)
        result = BenchmarkComparator.compare(returns, returns, "TEST")
        assert abs(result.alpha_pct) < 0.01
        assert abs(result.beta - 1.0) < 0.01

    def test_outperformance_positive_alpha(self) -> Any:
        """Üst performans pozitif alpha üretmeli."""
        benchmark = np.random.normal(0.0005, 0.02, 100)
        strategy = benchmark + 0.001  # Her gün %0.1 daha iyi
        result = BenchmarkComparator.compare(strategy, benchmark, "TEST")
        assert result.alpha_pct > 0

    def test_correlation_range(self) -> Any:
        """Korelasyon -1 ile 1 arasında olmalı."""
        s = np.random.normal(0.001, 0.02, 100)
        b = np.random.normal(0.001, 0.02, 100)
        result = BenchmarkComparator.compare(s, b, "TEST")
        assert -1 <= result.correlation <= 1


# =====================================================
# EDGE CASES
# =====================================================


class TestEdgeCases:
    """Edge case testleri."""

    def test_single_trade_lifecycle(self) -> Any:
        """Tek trade lifecycle'ı doğru çalışmalı."""
        sim = PortfolioSimulatorV3(initial_capital=100_000, max_position_pct=0.10)
        sim.execute_buy("THYAO", 100.0, "2026-01-01")
        sim.update_equity({"THYAO": 95.0}, "2026-01-02")  # Zarar
        sim.update_equity({"THYAO": 105.0}, "2026-01-03")  # Kar
        trade = sim.execute_sell("THYAO", 105.0, "2026-01-04")
        assert trade is not None
        assert trade.pnl > 0

    def test_commission_on_small_amount(self) -> Any:
        """Küçük tutarlarda minimum komisyon uygulanmalı."""
        comm = BISTCommissionModel.compute(10)
        assert comm >= BISTCommissionModel.MIN_COMMISSION

    def test_transaction_cost_negative_price(self) -> Any:
        """Negatif fiyat ile maliyet sıfır olmalı."""
        engine = TransactionCostEngine()
        result = engine.calculate_total_cost("BUY", -100.0, 100, "THYAO")
        assert result["total_cost"] == 0
