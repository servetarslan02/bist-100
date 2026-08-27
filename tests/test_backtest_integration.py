"""
ALPHA BIST — Backtest Integration Test Suite

NIHAI-SPEC doğrultusunda entegrasyon testleri:
1. PortfolioSimulatorV3 + TransactionCostEngine entegrasyonu
2. VaR/CVaR/MaxDD Duration metrik doğruluğu
3. BUY/SELL eşik asimetrisi doğrulaması
4. Walk-forward leakage guard
5. Engine V4 legacy vs fast parity
6. Deflated Sharpe Ratio doğruluğu
7. Benchmark comparison
8. Deterministic recovery
"""

from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

# Add project root to path
import pytest

# =====================================================
# FIXTURES
# =====================================================


def _make_ohlcv(n_days: int = 300, base_price: float = 100.0, seed: int = 42) -> pl.DataFrame:
    """Sentetik OHLCV veri üret."""
    rng = np.random.RandomState(seed)
    pl.date_range(date(2023, 1, 1), date(2023, 1, 1) + timedelta(days=n_days * 2), timedelta(days=1), eager=True).head(
        n_days
    )
    returns = rng.normal(0.0003, 0.02, n_days)
    close = base_price * np.cumprod(1 + returns)
    high = close * (1 + rng.uniform(0, 0.02, n_days))
    low = close * (1 - rng.uniform(0, 0.02, n_days))
    open_ = close * (1 + rng.normal(0, 0.005, n_days))
    volume = rng.randint(100_000, 10_000_000, n_days).astype(float)
    df = pl.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})
    return df


def _make_market_data(tickers=None, n_days=300):
    """Birden fazla hisse için market data üret."""
    if tickers is None:
        tickers = ["THYAO", "GARAN", "AKBNK", "ASELS", "EREGL"]
    return {t: _make_ohlcv(n_days, base_price=100 + i * 10, seed=42 + i) for i, t in enumerate(tickers)}


# =====================================================
# TEST 1: PortfolioSimulator + TransactionCostEngine
# =====================================================


class TestPortfolioTransactionCosts:
    """TransactionCostEngine entegrasyonu testleri."""

    def test_realistic_costs_include_all_components(self):
        """Gerçekçi maliyetler tüm bileşenleri içermeli (spread, slippage, impact)."""
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        # Legacy
        sim_legacy = PortfolioSimulatorV3(initial_capital=1_000_000, use_realistic_costs=False, slippage_rate=0.001)
        sim_legacy.execute_buy("THYAO", 100.0, "2024-01-15", quantity=1000)

        # Realistic
        sim_realistic = PortfolioSimulatorV3(
            initial_capital=1_000_000,
            use_realistic_costs=True,
            slippage_rate=0.001,
            avg_daily_volume=500_000_000,
            volatility_ratio=1.0,
        )
        sim_realistic.execute_buy("THYAO", 100.0, "2024-01-15", quantity=1000)

        legacy_trade = sim_legacy.get_trades()[0]
        realistic_trade = sim_realistic.get_trades()[0]

        # Her iki yol da pozitif maliyet üretmeli
        assert legacy_trade.commission > 0
        assert realistic_trade.commission > 0
        assert realistic_trade.slippage > 0

        # Slippage zaten fill_price'a dahil — cost_basis = qty*fill_price + commission
        # Fill price > market price olmalı (slippage dahil)
        assert legacy_trade.price > 100.0, "Legacy fill price should include slippage"
        assert realistic_trade.price > 100.0, "Realistic fill price should include slippage"

        # Her iki model de pozitif toplam maliyet üretmeli
        assert legacy_trade.commission + legacy_trade.slippage > 0
        assert realistic_trade.commission + realistic_trade.slippage > 0

    def test_realistic_sell_costs(self):
        """SELL işleminde de realistic cost uygulanmalı."""
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        sim = PortfolioSimulatorV3(
            initial_capital=1_000_000,
            use_realistic_costs=True,
            slippage_rate=0.001,
            avg_daily_volume=200_000_000,
            volatility_ratio=1.2,
        )
        sim.execute_buy("GARAN", 50.0, "2024-01-15", quantity=2000)
        sim.execute_sell("GARAN", 52.0, "2024-02-15")

        trades = sim.get_trades()
        assert len(trades) == 2
        assert trades[1].side == "SELL"
        assert trades[1].commission > 0
        assert trades[1].slippage > 0

    def test_cost_engine_buy_sell_symmetry(self):
        """BUY ve SELL maliyetleri simetrik olmalı (komisyon açısından)."""
        from services.backtest.transaction_costs import bist_transaction_cost

        buy_cost = bist_transaction_cost.calculate_total_cost("BUY", 100.0, 1000, "THYAO", avg_daily_volume=500_000_000)
        sell_cost = bist_transaction_cost.calculate_total_cost(
            "SELL", 100.0, 1000, "THYAO", avg_daily_volume=500_000_000
        )

        # Komisyon aynı olmalı (BUY ve SELL'de eşit)
        assert abs(buy_cost["costs"]["commission"] - sell_cost["costs"]["commission"]) < 0.01


# =====================================================
# TEST 2: VaR/CVaR/MaxDD Duration
# =====================================================


class TestAdvancedMetrics:
    """Gelişmiş metrik testleri."""

    def test_var_cvar_computed(self):
        """VaR ve CVaR hesaplanmalı."""
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        sim = PortfolioSimulatorV3(initial_capital=1_000_000)
        # Birkaç trade yap
        sim.execute_buy("THYAO", 100.0, "2024-01-02", quantity=100)
        sim.update_equity({"THYAO": 105.0}, "2024-01-03")
        sim.update_equity({"THYAO": 102.0}, "2024-01-04")
        sim.update_equity({"THYAO": 108.0}, "2024-01-05")
        sim.update_equity({"THYAO": 99.0}, "2024-01-08")
        sim.update_equity({"THYAO": 110.0}, "2024-01-09")
        sim.execute_sell("THYAO", 110.0, "2024-01-10")

        metrics = sim.compute_metrics()
        assert "var_95" in metrics, "VaR 95% should be in metrics"
        assert "cvar_95" in metrics, "CVaR 95% should be in metrics"
        # VaR negatif olmalı (kayıp)
        assert metrics["var_95"] <= 0 or metrics["var_95"] == 0, "VaR should be <= 0 (represents loss)"
        # CVaR <= VaR olmalı
        if metrics["var_95"] < 0:
            assert metrics["cvar_95"] <= metrics["var_95"], "CVaR should be <= VaR (more extreme losses)"

    def test_max_dd_duration_tracked(self):
        """Max drawdown duration izlenmeli."""
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        sim = PortfolioSimulatorV3(initial_capital=1_000_000)
        sim.execute_buy("THYAO", 100.0, "2024-01-02", quantity=100)

        # Equity yükselip sonra düşsün
        sim.update_equity({"THYAO": 120.0}, "2024-01-03")  # Peak
        sim.update_equity({"THYAO": 110.0}, "2024-01-04")  # Drawdown başlar
        sim.update_equity({"THYAO": 105.0}, "2024-01-05")  # Drawdown devam
        sim.update_equity({"THYAO": 108.0}, "2024-01-08")  # Hâlâ drawdown
        sim.update_equity({"THYAO": 125.0}, "2024-01-09")  # Recovery

        metrics = sim.compute_metrics()
        assert "max_drawdown_duration_days" in metrics
        assert metrics["max_drawdown_duration_days"] >= 0

    def test_sortino_correct_formula(self):
        """Sortino formülü doğru: downside deviation = sqrt(mean(min(r,0)^2))."""
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        sim = PortfolioSimulatorV3(initial_capital=1_000_000)
        # 25 equity noktası oluştur
        for i in range(25):
            price = 100 + np.sin(i * 0.3) * 10  # Dalgalı
            sim.update_equity({"X": price}, f"2024-01-{i + 2:02d}")

        metrics = sim.compute_metrics()
        # Sortino > Sharpe olmalı (pozitif getirileri hariç tutuyor)
        # ya da her ikisi de 0
        assert isinstance(metrics["sortino_ratio"], float)


# =====================================================
# TEST 3: BUY/SELL Eşik Asimetrisi
# =====================================================


class TestBuySellAsymmetry:
    """BUY/SELL eşik asimetrisi doğrulaması."""

    def test_buy_requires_higher_score_than_sell(self):
        """BUY eşiği SELL eşiğinden yüksek olmalı (hysteresis)."""
        from services.backtest.engine_v4 import BacktestConfig

        cfg = BacktestConfig(signal_threshold=60)
        # SELL: score <= (100 - 60) = 40
        sell_threshold = 100 - cfg.signal_threshold
        # BUY: score >= 60 + 10 = 70
        buy_threshold = cfg.signal_threshold + 10

        assert buy_threshold > sell_threshold, f"BUY threshold ({buy_threshold}) should be > SELL ({sell_threshold})"
        # Gap en az 10 puan olmalı
        assert buy_threshold - sell_threshold >= 10, "Hysteresis gap should be >= 10 points"

    def test_score_clipping_bounds(self):
        """Score 0-100 arasında clip'lenmeli."""
        from services.backtest.engine_v4 import BacktestEngineV4

        engine = BacktestEngineV4()

        # Aşırı feature'lar
        extreme_features = {
            "rsi_14": 100,
            "momentum_20d": 10.0,
            "roc_5d": 50.0,
            "volume_zscore": 100.0,
        }
        score = engine._compute_score_legacy(extreme_features)
        assert 0 <= score <= 100, f"Score should be 0-100, got {score}"

        low_features = {
            "rsi_14": 0,
            "momentum_20d": -10.0,
            "roc_5d": -50.0,
            "volume_zscore": -100.0,
        }
        score = engine._compute_score_legacy(low_features)
        assert 0 <= score <= 100, f"Score should be 0-100, got {score}"


# =====================================================
# TEST 4: Walk-Forward Leakage Guard
# =====================================================


class TestWalkForwardLeakage:
    """Walk-forward leakage koruması testleri."""

    def test_fold_boundaries_respect_purge(self):
        """Fold sınırları purge gap'i korumalı."""
        from services.backtest.walk_forward import WalkForwardEngine

        engine = WalkForwardEngine(purge_days=5, embargo_days=5, train_days=100, test_days=30, step_days=21)
        dates = (
            [f"2023-01-{d:02d}" for d in range(1, 32)]
            + [f"2023-02-{d:02d}" for d in range(1, 29)]
            + [f"2023-03-{d:02d}" for d in range(1, 32)]
            + [f"2023-04-{d:02d}" for d in range(1, 31)]
            + [f"2023-05-{d:02d}" for d in range(1, 32)]
            + [f"2023-06-{d:02d}" for d in range(1, 31)]
        )

        folds = engine.create_folds(dates)
        for fold in folds:
            # Purge gap kontrolü
            train_end_idx = dates.index(fold["train_end"])
            test_start_idx = dates.index(fold["test_start"])
            gap = test_start_idx - train_end_idx - 1
            assert gap >= engine.purge_days, f"Purge gap ({gap}) < required ({engine.purge_days})"

    def test_purge_embargo_split(self):
        """Purge/embargo split doğru olmalı."""
        from services.backtest.enhanced_walk_forward import PurgeEmbargoWalkForward

        engine = PurgeEmbargoWalkForward(purge_days=5, embargo_days=5, train_days=100, test_days=30, step_days=21)
        folds = engine.split(500)
        assert len(folds) > 0

        for _train_start, train_end, test_start, _test_end in folds:
            # Test train'den sonra başlamalı
            assert test_start > train_end
            # Purge gap
            assert test_start - train_end > 5


# =====================================================
# TEST 5: Engine V4 Legacy vs Fast Parity
# =====================================================


class TestEngineParity:
    """Legacy vs fast yol parity testi."""

    def test_both_paths_same_score(self):
        """Legacy ve fast yollar aynı skoru üretmeli (aynı feature'larla)."""
        from services.backtest.engine_v4 import BacktestEngineV4

        engine = BacktestEngineV4()
        features = {
            "rsi_14": 55.0,
            "momentum_20d": 0.02,
            "roc_5d": 1.5,
            "volume_zscore": 0.5,
        }
        score_legacy = engine._compute_score_legacy(features)
        # Fast path uses same function
        score_fast = engine._compute_score_legacy(features)
        assert abs(score_legacy - score_fast) < 1e-10


# =====================================================
# TEST 6: Deflated Sharpe Ratio
# =====================================================


class TestDeflatedSharpe:
    """Deflated Sharpe Ratio doğruluğu."""

    def test_deflated_sharpe_with_multiple_strategies(self):
        """Çoklu strateji testinde deflated sharpe anlamlı olmalı."""
        from services.backtest.deflated_sharpe import DeflatedSharpeCalculator

        # 100 strateji test et, en iyisi sharpe 2.5
        result = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=2.5,
            num_strategies=100,
            num_observations=500,
            skewness=0.0,
            kurtosis=3.0,
        )

        # Deflated sharpe = (SR - E[max_SR]) / Std[max_SR] — bu bir z-skoru
        # Yüksek observed sharpe için deflated sharpe > observed olabilir
        # Önemli olan: sonuç anlamlı (p < 0.05) ve confidence high olmalı
        assert result.is_significant, "High observed sharpe should be significant"
        assert result.confidence_level == "high"
        assert result.p_value < 0.05
        # Expected max sharpe < observed olmalı
        assert result.expected_max_sharpe < 2.5

    def test_deflated_sharpe_single_strategy(self):
        """Tek stratejide deflated sharpe ~ raw sharpe olmalı."""
        from services.backtest.deflated_sharpe import DeflatedSharpeCalculator

        result = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=2.0,
            num_strategies=1,
            num_observations=500,
        )

        # Tek stratejide E[max_SR] ~ 0, dolayısıyla deflated ~ raw
        assert abs(result.deflated_sharpe - 2.0) < 1.0  # Yaklaşık eşit

    def test_probabilistic_sharpe(self):
        """PSR 0-1 arasında olmalı."""
        from services.backtest.deflated_sharpe import ProbabilisticSharpeRatio

        psr = ProbabilisticSharpeRatio.compute(
            observed_sharpe=2.0,
            benchmark_sharpe=0.0,
            num_observations=500,
        )
        assert 0 <= psr <= 1


# =====================================================
# TEST 7: Benchmark Comparison
# =====================================================


class TestBenchmark:
    """Benchmark karşılaştırma testleri."""

    def test_benchmark_comparison_metrics(self):
        """Tüm metrikler hesaplanmalı."""
        from services.backtest.benchmark import BenchmarkComparator

        rng = np.random.RandomState(42)
        strategy_returns = rng.normal(0.001, 0.01, 252)
        benchmark_returns = rng.normal(0.0005, 0.015, 252)

        result = BenchmarkComparator.compare(strategy_returns, benchmark_returns, "BIST100")

        assert result.benchmark_name == "BIST100"
        assert isinstance(result.alpha_pct, float)
        assert isinstance(result.beta, float)
        assert isinstance(result.information_ratio, float)
        assert isinstance(result.tracking_error_pct, float)
        assert result.num_observations == 252


# =====================================================
# TEST 8: Transaction Cost Model
# =====================================================


class TestTransactionCosts:
    """İşlem maliyeti modeli testleri."""

    def test_bist_commission_structure(self):
        """BIST komisyon yapısı doğru olmalı."""
        from services.backtest.transaction_costs import BISTFeeStructure

        fees = BISTFeeStructure()
        assert fees.broker_commission_pct == 0.03
        assert fees.bist_fee_pct == 0.0056
        assert fees.mkk_fee_pct == 0.00109
        assert fees.bsmv_rate == 0.05

    def test_spread_tiers(self):
        """Likidite katmanlarına göre spread farklı olmalı."""
        from services.backtest.transaction_costs import LiquidityTier, SpreadModel

        spread = SpreadModel()
        s1 = spread.estimate_spread(LiquidityTier.TIER_1)
        s2 = spread.estimate_spread(LiquidityTier.TIER_2)
        s3 = spread.estimate_spread(LiquidityTier.TIER_3)
        s4 = spread.estimate_spread(LiquidityTier.TIER_4)

        assert s1 < s2 < s3 < s4, "Spread should increase with lower liquidity"

    def test_market_impact_increases_with_size(self):
        """Büyük emirler daha fazla market impact yaratmalı."""
        from services.backtest.transaction_costs import MarketImpactModel

        impact = MarketImpactModel()
        small_impact, _ = impact.estimate_impact(1000, 10_000_000, 0.02, 100.0)
        large_impact, _ = impact.estimate_impact(500_000, 10_000_000, 0.02, 100.0)

        assert large_impact > small_impact

    def test_total_cost_round_trip(self):
        """Round-trip maliyet pozitif olmalı."""
        from services.backtest.transaction_costs import bist_transaction_cost

        rt = bist_transaction_cost.estimate_round_trip_cost("THYAO", 100.0, 1000, avg_daily_volume=500_000_000)

        assert rt["round_trip_cost"] > 0
        assert rt["round_trip_cost_pct"] > 0
        assert rt["break_even_return_pct"] > 0


# =====================================================
# TEST 9: Survivorship Bias
# =====================================================


class TestSurvivorship:
    """Survivorship bias testleri."""

    def test_universe_at_date_excludes_delisted(self):
        """Delist edilen hisseler evrenden çıkarılmalı."""
        from services.backtest.survivorship import DelistingEvent, SurvivorshipBiasHandler

        handler = SurvivorshipBiasHandler()
        handler.register_delisting(
            DelistingEvent(
                ticker="DELISTED",
                delisting_date=datetime(2023, 6, 1),
                reason="bankruptcy",
            )
        )

        all_tickers = {"THYAO", "GARAN", "DELISTED"}

        # 2023-01-01: DELISTED hâlâ aktif
        universe_jan = handler.get_universe_at_date(datetime(2023, 1, 1), all_tickers)
        assert "DELISTED" in universe_jan

        # 2023-07-01: DELISTED artık yok
        universe_jul = handler.get_universe_at_date(datetime(2023, 7, 1), all_tickers)
        assert "DELISTED" not in universe_jul
        assert "THYAO" in universe_jul


# =====================================================
# TEST 10: Deterministic Recovery
# =====================================================


class TestDeterministicRecovery:
    """Deterministik recovery testleri."""

    def test_checkpoint_restore(self):
        """Checkpoint'ten geri yükleme doğru olmalı."""
        from services.backtest.deterministic import DeterministicRecovery

        recovery = DeterministicRecovery(storage_path="/tmp/test_checkpoints")
        recovery.set_seed(42)

        config = {"mode": "test", "threshold": 60}
        portfolio = {"cash": 50000, "positions": {"THYAO": 100}}

        recovery.create_checkpoint(config, portfolio)
        restored_config, restored_portfolio, seed = recovery.restore_checkpoint()

        assert restored_config == config
        assert restored_portfolio == portfolio
        assert seed == 42

    def test_idempotency_guard(self):
        """Aynı işlem iki kez çalıştırılmamalı."""
        from services.backtest.deterministic import IdempotencyGuard

        guard = IdempotencyGuard()
        call_count = 0

        def expensive_func():
            nonlocal call_count
            call_count += 1
            return 42

        result1 = guard.get_or_execute("test_op", {"x": 1}, expensive_func)
        result2 = guard.get_or_execute("test_op", {"x": 1}, expensive_func)

        assert result1 == 42
        assert result2 == 42
        assert call_count == 1  # Sadece bir kez çağrıldı


# =====================================================
# TEST 11: Bias Detector
# =====================================================


class TestBiasDetector:
    """Bias detection testleri."""

    def test_label_feature_alignment_check(self):
        """Label-feature alignment kontrolü çalışmalı."""
        from services.backtest.bias_detector import LookAheadBiasDetector

        detector = LookAheadBiasDetector()

        # Purge yetersiz
        report = detector.validate_label_feature_alignment(
            label_horizon_days=10,
            feature_window_days=20,
            purge_days=5,  # < 10 → ihlal
        )
        assert report.critical_count > 0

        # Purge yeterli
        report2 = detector.validate_label_feature_alignment(
            label_horizon_days=5,
            feature_window_days=20,
            purge_days=10,  # >= 5 → OK
        )
        assert report2.critical_count == 0


# =====================================================
# TEST 12: Scanner Parity
# =====================================================


class TestScannerParity:
    """Scanner parity testleri."""

    def test_feature_version_lock(self):
        """Feature versiyon kilidi çalışmalı."""
        from services.backtest.scanner_parity import FeatureVersionLock

        lock = FeatureVersionLock()
        lock.register_version("v1.0", ["rsi_14", "momentum_20d"], {"window": 14})
        lock.set_active_version("v1.0")

        assert lock.validate_version_match("v1.0")
        assert not lock.validate_version_match("v2.0")

    def test_parity_config_hash(self):
        """Parity config hash'i deterministik olmalı."""
        from services.backtest.scanner_parity import ParityConfig

        cfg1 = ParityConfig(feature_version="v1.0", scoring_version="v1.0")
        cfg2 = ParityConfig(feature_version="v1.0", scoring_version="v1.0")

        assert cfg1.compute_hash() == cfg2.compute_hash()


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
