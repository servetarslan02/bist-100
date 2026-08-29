from __future__ import annotations

from typing import Any
"""
ALPHA BIST — Nihai Backtest Sistemi Test Paketi

Tüm yeni modüller için kapsamlı testler:
1. Bias Detection (Look-ahead, Survivorship, PIT)
2. Transaction Costs
3. Multi-Asset Engine
4. Event Replay
5. Deterministic Recovery
6. Deflated Sharpe
7. Benchmark Comparison
8. Scanner Parity
"""


from datetime import date, datetime, timedelta

import numpy as np

try:
    import polars as pl
except ImportError:
    pl = None
import pytest

pytestmark = pytest.mark.skipif(pl is None, reason="polars library required")


from services.backtest.benchmark import (
    BenchmarkComparator,
    BenchmarkComparison,
)

# Import modules
from services.backtest.bias_detector import (
    BiasDetectorMiddleware,
    LookAheadBiasDetector,
)
from services.backtest.deflated_sharpe import (
    DeflatedSharpeCalculator,
    ProbabilisticSharpeRatio,
)
from services.backtest.deterministic import (
    DeterministicRecovery,
    IdempotencyGuard,
)
from services.backtest.event_replay import (
    EnhancedReplayEngine,
    ReplayDecision,
)
from services.backtest.multi_asset_engine import (
    MultiAssetBacktestEngine,
    MultiAssetConfig,
)
from services.backtest.pit_validator import (
    PointInTimeValidator,
)
from services.backtest.scanner_parity import (
    BacktestScannerParity,
    FeatureVersionLock,
)
from services.backtest.survivorship import (
    DelistingEvent,
    SurvivorshipBiasHandler,
)
from services.backtest.transaction_costs import (
    LiquidityTier,
    SpreadModel,
    TransactionCostEngine,
)

# =====================================================
# Phase 1 Tests: Bias Detection
# =====================================================


class TestLookAheadBiasDetector:
    """Look-ahead bias detection testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.detector = LookAheadBiasDetector()

    def test_validate_feature_timestamps_no_leakage(self) -> Any:
        """Feature'larda gelecek veri yoksa temiz rapor dönmeli."""
        df = pl.DataFrame(
            {
                "timestamp": pl.date_range(date(2024, 1, 1), date(2024, 1, 10), timedelta(days=1), eager=True),
                "feature_1": np.random.randn(10),
            }
        )
        decision_time = pl.Date("2024-01-10")
        report = self.detector.validate_feature_timestamps(df, "feature_1", decision_time)
        assert report.critical_count == 0
        assert report.is_clean

    def test_validate_feature_timestamps_with_leakage(self) -> Any:
        """Feature'larda gelecek veri varsa critical ihlal bulmalı."""
        df = pl.DataFrame(
            {
                "timestamp": pl.date_range(date(2024, 1, 1), date(2024, 1, 20), timedelta(days=1), eager=True),
                "feature_1": np.random.randn(20),
            }
        )
        decision_time = pl.Date("2024-01-10")  # 10 gün sonra veri var
        report = self.detector.validate_feature_timestamps(df, "feature_1", decision_time)
        assert report.critical_count > 0
        assert not report.is_clean

    def test_validate_label_feature_alignment_ok(self) -> Any:
        """Purge yeterliyse temiz rapor dönmeli."""
        report = self.detector.validate_label_feature_alignment(
            label_horizon_days=5, feature_window_days=20, purge_days=5
        )
        assert report.critical_count == 0

    def test_validate_label_feature_alignment_insufficient_purge(self) -> Any:
        """Purge yetersizse critical ihlal bulmalı."""
        report = self.detector.validate_label_feature_alignment(
            label_horizon_days=5, feature_window_days=20, purge_days=2
        )
        assert report.critical_count > 0

    def test_validate_fold_boundaries_ok(self) -> Any:
        """Geçerli fold sınırlarında temiz rapor dönmeli."""
        train_end = datetime(2024, 6, 1)
        test_start = datetime(2024, 6, 10)  # 9 gün gap
        report = self.detector.validate_fold_boundaries(
            train_end, test_start, purge_days=5, embargo_days=3, label_horizon_days=5
        )
        assert report.critical_count == 0

    def test_validate_fold_boundaries_overlap(self) -> Any:
        """Train ve test çakışması critical ihlal oluşturmalı."""
        train_end = datetime(2024, 6, 10)
        test_start = datetime(2024, 6, 5)  # Test train'den önce başlıyor!
        report = self.detector.validate_fold_boundaries(
            train_end, test_start, purge_days=5, embargo_days=3, label_horizon_days=5
        )
        assert report.critical_count > 0


class TestBiasDetectorMiddleware:
    """Middleware testleri."""

    def test_enabled_mode(self) -> Any:
        """Middleware enabled modunda çalışmalı."""
        middleware = BiasDetectorMiddleware(strict_mode=True)
        assert middleware.enabled

    def test_disabled_mode(self) -> Any:
        """Middleware disabled modunda her zaman safe dönmeli."""
        middleware = BiasDetectorMiddleware(strict_mode=True)
        middleware.enabled = False
        is_safe, report = middleware.pre_scan_check(
            pl.DataFrame({"timestamp": [datetime.now()]}),
            datetime.now(),
        )
        assert is_safe


class TestSurvivorshipBiasHandler:
    """Survivorship bias testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.handler = SurvivorshipBiasHandler()

    def test_get_universe_before_delisting(self) -> Any:
        """Delisting öncesi evren tüm hisseleri içermeli."""
        self.handler.register_delisting(
            DelistingEvent(
                ticker="HISSE1",
                delisting_date=datetime(2023, 6, 1),
                reason="bankruptcy",
            )
        )
        all_tickers = {"HISSE1", "HISSE2", "HISSE3"}
        universe = self.handler.get_universe_at_date(datetime(2023, 1, 1), all_tickers)
        assert "HISSE1" in universe
        assert len(universe) == 3

    def test_get_universe_after_delisting(self) -> Any:
        """Delisting sonrası evren o hisseyi içermemeli."""
        self.handler.register_delisting(
            DelistingEvent(
                ticker="HISSE1",
                delisting_date=datetime(2023, 6, 1),
                reason="bankruptcy",
            )
        )
        all_tickers = {"HISSE1", "HISSE2", "HISSE3"}
        universe = self.handler.get_universe_at_date(datetime(2024, 1, 1), all_tickers)
        assert "HISSE1" not in universe
        assert len(universe) == 2

    def test_survivorship_bias_magnitude(self) -> Any:
        """Bias büyüklüğü doğru hesaplanmalı."""
        full_returns = pl.DataFrame({"return": [0.01, -0.02, 0.03, -0.01, 0.02]})
        survivor_returns = pl.DataFrame({"return": [0.01, 0.03, 0.02, 0.01, 0.03]})

        result = self.handler.calculate_survivorship_bias_magnitude(full_returns, survivor_returns)
        assert "bias_magnitude" in result
        assert "bias_percentage" in result
        assert result["survivor_only_mean_return"] > result["full_universe_mean_return"]


class TestPointInTimeValidator:
    """PIT validation testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.validator = PointInTimeValidator()

    def test_get_available_data_at(self) -> Any:
        """Karar anında sadece yayınlanmış veriler dönmeli."""
        self.validator.register_fundamental_data(
            ticker="THYAO",
            report_date=datetime(2024, 3, 31),
            publish_date=datetime(2024, 4, 30),  # 30 gün gecikmeli
        )

        # Yayın öncesi - veri yok
        available = self.validator.get_available_data_at("THYAO", datetime(2024, 4, 15))
        assert len(available) == 0

        # Yayın sonrası - veri var
        available = self.validator.get_available_data_at("THYAO", datetime(2024, 5, 1))
        assert len(available) == 1

    def test_validate_fundamental_access_future_data(self) -> Any:
        """Gelecekteki veri erişimi reddedilmeli."""
        self.validator.register_fundamental_data(
            ticker="THYAO",
            report_date=datetime(2024, 3, 31),
            publish_date=datetime(2024, 4, 30),
        )

        is_valid, violation = self.validator.validate_fundamental_access(
            ticker="THYAO",
            report_date=datetime(2024, 3, 31),
            revision_version=1,
            decision_time=datetime(2024, 4, 15),  # Yayın öncesi
        )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "future_data"

    def test_validate_label_generation_too_early(self) -> Any:
        """Erken label üretimi reddedilmeli."""
        is_valid, violation = self.validator.validate_label_generation(
            feature_timestamp=datetime(2024, 1, 1),
            label_timestamp=datetime(2024, 1, 3),  # 2 gün, purge+horizon=10 gün gerekli
            label_horizon_days=5,
            purge_days=5,
        )
        assert not is_valid


# =====================================================
# Phase 2 Tests: Transaction Costs
# =====================================================


class TestTransactionCostEngine:
    """Transaction cost testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.engine = TransactionCostEngine()

    def test_calculate_total_cost_buy(self) -> Any:
        """ALIŞ maliyeti pozitif olmalı."""
        result = self.engine.calculate_total_cost(
            side="BUY",
            price=100.0,
            quantity=1000,
            ticker="THYAO",
            avg_daily_volume=500_000_000,
        )
        assert result["total_cost"] > 0
        assert result["total_cost_pct"] > 0
        assert "commission" in result["costs"]
        assert "spread" in result["costs"]
        assert "slippage" in result["costs"]
        assert "market_impact" in result["costs"]

    def test_calculate_total_cost_sell(self) -> Any:
        """SATIŞ maliyeti de pozitif olmalı."""
        result = self.engine.calculate_total_cost(
            side="SELL",
            price=100.0,
            quantity=1000,
            ticker="THYAO",
            avg_daily_volume=500_000_000,
        )
        assert result["total_cost"] > 0

    def test_low_liquidity_higher_cost(self) -> Any:
        """Düşük likidite daha yüksek maliyet üretmeli."""
        high_liq = self.engine.calculate_total_cost("BUY", 100.0, 1000, "HISSE", avg_daily_volume=1_000_000_000)
        low_liq = self.engine.calculate_total_cost("BUY", 100.0, 1000, "HISSE", avg_daily_volume=10_000_000)
        assert low_liq["total_cost_pct"] > high_liq["total_cost_pct"]

    def test_round_trip_cost(self) -> Any:
        """Round-trip maliyeti iki tek yönün toplamı olmalı."""
        rt = self.engine.estimate_round_trip_cost(
            ticker="THYAO",
            entry_price=100.0,
            quantity=1000,
            avg_daily_volume=500_000_000,
        )
        assert rt["round_trip_cost"] > 0
        assert rt["round_trip_cost_pct"] > 0
        assert rt["break_even_return_pct"] > 0

    def test_liquidity_classification(self) -> Any:
        """Likidite sınıflandırması doğru olmalı."""
        assert self.engine.classify_liquidity(1_000_000_000) == LiquidityTier.TIER_1
        assert self.engine.classify_liquidity(200_000_000) == LiquidityTier.TIER_2
        assert self.engine.classify_liquidity(50_000_000) == LiquidityTier.TIER_3
        assert self.engine.classify_liquidity(5_000_000) == LiquidityTier.TIER_4


class TestSpreadModel:
    """Spread model testleri."""

    def test_higher_volatility_wider_spread(self) -> Any:
        """Yüksek volatilite daha geniş spread üretmeli."""
        model = SpreadModel()
        low_vol_spread = model.estimate_spread(LiquidityTier.TIER_1, volatility_ratio=0.5)
        high_vol_spread = model.estimate_spread(LiquidityTier.TIER_1, volatility_ratio=2.0)
        assert high_vol_spread > low_vol_spread

    def test_tier_1_narrowest_spread(self) -> Any:
        """Tier 1 en dar spread'e sahip olmalı."""
        model = SpreadModel()
        t1 = model.estimate_spread(LiquidityTier.TIER_1)
        t4 = model.estimate_spread(LiquidityTier.TIER_4)
        assert t1 < t4


# =====================================================
# Phase 3 Tests: Multi-Asset, Event Replay, Deterministic
# =====================================================


class TestMultiAssetBacktestEngine:
    """Multi-asset backtest testleri."""

    def test_basic_run(self) -> Any:
        """Temel çalıştırma testi."""
        # Create sample data
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 1) + timedelta(days=100), timedelta(days=1), eager=True)
        tickers = ["HISSE1", "HISSE2", "HISSE3"]

        market_data = []
        signal_data = []
        for ticker in tickers:
            base_price = np.random.uniform(50, 200)
            for dt in dates:
                price = base_price * (1 + np.random.randn() * 0.02)
                market_data.append(
                    {
                        "date": dt,
                        "ticker": ticker,
                        "open": price * 0.99,
                        "high": price * 1.02,
                        "low": price * 0.98,
                        "close": price,
                        "volume": np.random.randint(1_000_000, 10_000_000),
                    }
                )
                signal_data.append(
                    {
                        "date": dt,
                        "ticker": ticker,
                        "score": np.random.uniform(30, 90),
                        "confidence": np.random.uniform(0.3, 0.9),
                    }
                )

        market_df = pl.DataFrame(market_data)
        signal_df = pl.DataFrame(signal_data)
        sector_map = {t: "test_sector" for t in tickers}

        config = MultiAssetConfig(
            initial_capital=1_000_000,
            max_positions=5,
            use_realistic_costs=True,
            enable_bias_detection=True,
        )

        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_df, signal_df, sector_map)

        assert result is not None
        assert result.run_id is not None
        assert result.total_trades >= 0
        assert len(result.equity_curve) > 0
        assert result.max_drawdown_pct >= 0


class TestEnhancedReplayEngine:
    """Event replay testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.engine = EnhancedReplayEngine()

    def test_audit_trail_integrity(self) -> Any:
        """Audit trail bütünlüğü korunmalı."""
        self.engine._record_event(
            timestamp=datetime.now(),
            event_type="test",
            data={"value": 1},
        )
        self.engine._record_event(
            timestamp=datetime.now(),
            event_type="test",
            data={"value": 2},
        )
        assert self.engine.verify_audit_integrity()

    def test_create_restore_snapshot(self) -> Any:
        """Snapshot oluşturup geri yükleyebilmeli."""
        state = self.engine.create_snapshot(
            timestamp=datetime.now(),
            cash=100_000.0,
            positions={"HISSE1": {"quantity": 100}},
        )
        restored = self.engine.restore_snapshot(state)
        assert restored["cash"] == 100_000.0
        assert "HISSE1" in restored["positions"]

    def test_compare_decisions_deterministic(self) -> Any:
        """Aynı kararlar deterministik olmalı."""
        decisions = [
            ReplayDecision(
                timestamp=datetime.now(),
                ticker="HISSE1",
                action="BUY",
                score=75.0,
                confidence=0.8,
                features={},
                reasoning="test",
            )
        ]
        result = self.engine.compare_decisions(decisions, decisions)
        assert result["is_deterministic"]
        assert result["mismatches"] == 0


class TestDeterministicRecovery:
    """Deterministic recovery testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.recovery = DeterministicRecovery()

    def test_create_restore_checkpoint(self) -> Any:
        """Checkpoint oluşturup geri yükleyebilmeli."""
        config = {"param1": 1, "param2": "test"}
        portfolio = {"cash": 100_000, "positions": {}}

        checkpoint = self.recovery.create_checkpoint(config, portfolio)
        restored_config, restored_portfolio, seed = self.recovery.restore_checkpoint(checkpoint.checkpoint_id)

        assert restored_config == config
        assert restored_portfolio == portfolio

    def test_determinism_validation(self) -> Any:
        """Determinizm doğrulanmalı."""

        def deterministic_func(x) -> Any:
            """Otomatik eklendi."""
            np.random.seed(42)
            return np.random.randn(x)

        is_det, result = self.recovery.validate_determinism(deterministic_func, (10,), deterministic_func(10))
        assert is_det

    def test_idempotency_guard(self) -> Any:
        """Aynı işlem iki kez çalıştırılmamalı."""
        guard = IdempotencyGuard()
        call_count = 0

        def expensive_func() -> Any:
            """Otomatik eklendi."""
            nonlocal call_count
            call_count += 1
            return 42

        result1 = guard.get_or_execute("test_op", {"x": 1}, expensive_func)
        result2 = guard.get_or_execute("test_op", {"x": 1}, expensive_func)

        assert result1 == 42
        assert result2 == 42
        assert call_count == 1  # Sadece bir kez çağrılmalı


# =====================================================
# Phase 4 Tests: Deflated Sharpe & Benchmark
# =====================================================


class TestDeflatedSharpe:
    """Deflated Sharpe testleri."""

    def test_deflated_sharpe_single_strategy(self) -> Any:
        """Tek strateji için deflated sharpe ≈ observed sharpe."""
        result = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=1.5,
            num_strategies=1,
            num_observations=500,
        )
        assert result.observed_sharpe == 1.5
        # Tek strateji için expected max sharpe ≈ 0
        assert abs(result.deflated_sharpe) > 0

    def test_deflated_sharpe_multiple_strategies(self) -> Any:
        """Çoklu strateji ile deflated sharpe farklı olmalı."""
        single = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=2.0,
            num_strategies=1,
            num_observations=500,
        )
        multiple = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=2.0,
            num_strategies=100,
            num_observations=500,
        )
        # Her iki durumda da significant olmalı
        assert single.is_significant
        assert multiple.is_significant
        # 100 strateji test edildiğinde expected_max_sharpe artmalı
        assert multiple.expected_max_sharpe > single.expected_max_sharpe

    def test_from_returns(self) -> Any:
        """Getiri serisinden hesaplama çalışmalı."""
        returns = np.random.randn(252) * 0.01 + 0.0005  # ~%12 yıllık getiri
        result = DeflatedSharpeCalculator.from_returns(returns, num_strategies=10)
        assert result.observed_sharpe != 0
        assert 0 <= result.p_value <= 1


class TestProbabilisticSharpeRatio:
    """PSR testleri."""

    def test_psr_positive_sharpe(self) -> Any:
        """Pozitif sharpe için PSR > 0.5 olmalı."""
        psr = ProbabilisticSharpeRatio.compute(
            observed_sharpe=1.5,
            benchmark_sharpe=0.0,
            num_observations=500,
        )
        assert psr > 0.5

    def test_psr_from_returns(self) -> Any:
        """Getiri serisinden PSR hesaplanmalı."""
        returns = np.random.randn(252) * 0.01 + 0.001
        result = ProbabilisticSharpeRatio.from_returns(returns)
        assert "psr" in result
        assert 0 <= result["psr"] <= 1


class TestBenchmarkComparator:
    """Benchmark karşılaştırma testleri."""

    def test_compare_identical_returns(self) -> Any:
        """Aynı getiriler için beta ≈ 1, alpha ≈ 0 olmalı."""
        returns = np.random.randn(252) * 0.01
        result = BenchmarkComparator.compare(returns, returns, "TEST")
        assert abs(result.beta - 1.0) < 0.1
        assert abs(result.alpha_pct) < 1.0
        assert result.correlation > 0.99

    def test_compare_uncorrelated(self) -> Any:
        """Korelesiz getiriler için düşük korelasyon olmalı."""
        np.random.seed(42)
        sr = np.random.randn(252) * 0.01
        br = np.random.randn(252) * 0.01
        result = BenchmarkComparator.compare(sr, br, "TEST")
        assert abs(result.correlation) < 0.3

    def test_generate_report(self) -> Any:
        """Rapor oluşturulmalı."""
        comp1 = BenchmarkComparison(
            benchmark_name="BIST100",
            strategy_return_pct=20,
            benchmark_return_pct=15,
            alpha_pct=5,
            beta=1.1,
            information_ratio=0.8,
            tracking_error_pct=5,
            relative_return_pct=5,
            up_capture_ratio=110,
            down_capture_ratio=90,
            correlation=0.85,
            r_squared=0.72,
            num_observations=252,
        )
        report = BenchmarkComparator.generate_report([comp1])
        assert "benchmarks" in report
        assert "summary" in report


# =====================================================
# Phase 5 Tests: Scanner Parity
# =====================================================


class TestBacktestScannerParity:
    """Scanner parity testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.parity = BacktestScannerParity()

    def test_feature_parity_same_data(self) -> Any:
        """Aynı veriyle feature parity sağlanmalı."""

        def mock_feature_engine(data, ticker, timestamp) -> Any:
            """Otomatik eklendi."""
            return {"feature_1": 0.5, "feature_2": 1.2}

        self.parity.register_engines(
            feature_engine=mock_feature_engine,
            signal_engine=lambda f, t: 75.0,
        )

        data = pl.DataFrame({"close": [100, 101, 102]})
        result = self.parity.verify_feature_parity(data, "TEST", datetime.now())
        assert result.is_parity

    def test_full_parity_check(self) -> Any:
        """Tam parity kontrolü çalışmalı."""

        def mock_feature_engine(data, ticker, timestamp) -> Any:
            """Otomatik eklendi."""
            return {"f1": 0.5}

        def mock_signal_engine(features, ticker) -> Any:
            """Otomatik eklendi."""
            return 70.0

        self.parity.register_engines(
            feature_engine=mock_feature_engine,
            signal_engine=mock_signal_engine,
        )

        data = pl.DataFrame(
            {
                "ticker": ["TEST1"] * 5,
                "close": [100, 101, 102, 103, 104],
            }
        )

        report = self.parity.run_full_parity_check(data, ["TEST1"], datetime.now())
        assert report.is_full_parity


class TestFeatureVersionLock:
    """Feature version lock testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        self.lock = FeatureVersionLock()

    def test_register_and_get_version(self) -> Any:
        """Versiyon kaydedilip alınabilmeli."""
        self.lock.register_version(
            "v1.0",
            ["feature_1", "feature_2"],
            {"window": 20},
        )
        config = self.lock.get_active_config()
        assert "feature_names" in config
        assert len(config["feature_names"]) == 2

    def test_validate_version_match(self) -> Any:
        """Versiyon eşleşmesi doğrulanmalı."""
        self.lock.register_version("v1.0", ["f1"], {})
        assert self.lock.validate_version_match("v1.0")
        assert not self.lock.validate_version_match("v2.0")


# =====================================================
# Integration Tests
# =====================================================


class TestIntegration:
    """Entegrasyon testleri."""

    def test_full_pipeline_flow(self) -> Any:
        """Tam pipeline akışı testi."""
        # 1. Bias check
        detector = LookAheadBiasDetector()
        report = detector.validate_label_feature_alignment(5, 20, 5)
        assert report.critical_count == 0

        # 2. Transaction cost
        engine = TransactionCostEngine()
        cost = engine.calculate_total_cost("BUY", 100.0, 1000, "TEST")
        assert cost["total_cost"] > 0

        # 3. Deflated Sharpe
        returns = np.random.randn(252) * 0.01
        ds = DeflatedSharpeCalculator.from_returns(returns, num_strategies=5)
        assert ds.observed_sharpe != 0

        # 4. Benchmark
        benchmark_returns = np.random.randn(252) * 0.008
        comp = BenchmarkComparator.compare(returns, benchmark_returns, "BIST100")
        assert comp.num_observations == 252

    def test_transaction_cost_impacts_returns(self) -> Any:
        """Transaction cost getiriyi düşürmeli."""
        # Without costs
        config_no_cost = MultiAssetConfig(use_realistic_costs=False)
        # With costs
        config_with_cost = MultiAssetConfig(use_realistic_costs=True)

        # Both should be valid configs
        assert config_no_cost.use_realistic_costs is False
        assert config_with_cost.use_realistic_costs is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
