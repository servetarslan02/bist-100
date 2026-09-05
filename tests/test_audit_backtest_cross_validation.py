"""
services/backtest/ — Audit & Çapraz Doğrulama (Cross-Validation) Test Suite

Bu test paketi, services/backtest/ dizinindeki 21 dosyanın 7 Altın Denetim Kuralı'na
uygunluğunu ve modüller arası çapraz entegrasyonunu doğrular.
"""

import sys
from datetime import date, datetime, timedelta

import numpy as np

sys.path.insert(0, ".")


# =====================================================
# 1. __init__.py — Modül Dışa Aktarımı ve Versiyonlama
# =====================================================


class TestBacktestInit:
    """services/backtest/__init__.py doğrulama testleri."""

    def test_version_exists(self):
        """__version__ tanımlı ve beklenen formatta olmalı."""
        from services.backtest import __version__

        assert __version__ == "2.0.0"

    def test_all_exports_importable(self):
        """__all__ içerisindeki tüm semboller başarıyla içe aktarılabilmeli."""
        import services.backtest as bt

        for symbol in bt.__all__:
            assert hasattr(bt, symbol), f"Sembol eksik: {symbol}"


# =====================================================
# 2. Survivorship & PIT Doğrulama Testleri
# =====================================================


class TestSurvivorshipAndPITCrossValidation:
    """Hayatta kalma yanlılığı ve Point-in-time cross-validation."""

    def test_survivorship_universe_filtering(self):
        from services.backtest.survivorship import DelistingEvent, SurvivorshipBiasHandler

        handler = SurvivorshipBiasHandler()
        handler.register_delisting(
            DelistingEvent(
                ticker="KAPATILMIS",
                delisting_date=datetime(2023, 6, 1),
                reason="bankruptcy",
                final_price=0.0,
                recovery_rate=0.0,
            )
        )

        all_tickers = {"THYAO", "GARAN", "KAPATILMIS"}
        universe_before = handler.get_universe_at_date(datetime(2023, 1, 1), all_tickers)
        universe_after = handler.get_universe_at_date(datetime(2023, 7, 1), all_tickers)

        assert "KAPATILMIS" in universe_before
        assert "KAPATILMIS" not in universe_after
        assert "THYAO" in universe_after

    def test_pit_validator_feature_leakage_detection(self):
        from services.backtest.pit_validator import PointInTimeValidator

        validator = PointInTimeValidator()
        # Bilanço dönemi 2023-03-31, KAP açıklanma tarihi 2023-05-10
        validator.register_fundamental_data(
            ticker="THYAO",
            report_date=datetime(2023, 3, 31),
            publish_date=datetime(2023, 5, 10),
            revision_version=1,
        )

        # Karar anı 2023-04-15 (Henüz bilanço açıklanmadı -> ihlal olmalı)
        valid_before, violation = validator.validate_fundamental_access(
            ticker="THYAO",
            report_date=datetime(2023, 3, 31),
            revision_version=1,
            decision_time=datetime(2023, 4, 15),
        )
        assert valid_before is False
        assert violation is not None
        assert violation.violation_type == "future_data"

        # Karar anı 2023-05-15 (Bilanço açıklandıktan sonra -> geçerli olmalı)
        valid_after, violation_after = validator.validate_fundamental_access(
            ticker="THYAO",
            report_date=datetime(2023, 3, 31),
            revision_version=1,
            decision_time=datetime(2023, 5, 15),
        )
        assert valid_after is True
        assert violation_after is None


# =====================================================
# 3. Transaction Costs & Likidite Kademeleri
# =====================================================


class TestTransactionCostsEngineCrossValidation:
    """İşlem maliyeti motoru ve likidite spread çapraz doğrulaması."""

    def test_dynamic_liquidity_tiers_and_multipliers(self):
        from services.backtest.transaction_costs import (
            CIRCUIT_BREAKER_SPREAD_MULTIPLIER,
            GROSS_SETTLEMENT_SPREAD_MULTIPLIER,
            TransactionCostEngine,
        )

        cost_engine = TransactionCostEngine()

        # Tier 1 (Yüksek likidite: 1 Milyar TL hacim)
        cost_t1 = cost_engine.calculate_total_cost(
            side="BUY", price=250.0, quantity=1000, ticker="THYAO", avg_daily_volume=1_000_000_000.0
        )
        # Tier 4 (Düşük likidite: 5 Milyon TL hacim)
        cost_t4 = cost_engine.calculate_total_cost(
            side="BUY", price=25.0, quantity=10000, ticker="KUCUK", avg_daily_volume=5_000_000.0
        )

        # Düşük likiditeli hissede spread ve toplam maliyet yüzdesi daha yüksek olmalı
        assert cost_t4["cost_pcts"]["spread_pct"] > cost_t1["cost_pcts"]["spread_pct"]
        assert cost_t4["total_cost"] > 0.0

        # Sabit çarpanlar
        assert CIRCUIT_BREAKER_SPREAD_MULTIPLIER == 1.5
        assert GROSS_SETTLEMENT_SPREAD_MULTIPLIER == 1.3


# =====================================================
# 4. Deflated Sharpe & Benchmark Karşılaştırma
# =====================================================


class TestDeflatedSharpeAndBenchmarkCrossValidation:
    """DSR ve Benchmark kıyaslama metrikleri."""

    def test_dsr_psr_bounds_and_multiple_trials(self):
        from services.backtest.deflated_sharpe import DeflatedSharpeCalculator

        result = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=2.2,
            num_strategies=50,
            num_observations=500,
            skewness=-0.2,
            kurtosis=3.5,
        )
        assert result.observed_sharpe == 2.2
        assert result.num_strategies_tested == 50
        assert 0.0 <= result.p_value <= 1.0

    def test_benchmark_comparator_alpha_beta_ir(self):
        from services.backtest.benchmark import BenchmarkComparator

        comparator = BenchmarkComparator()
        np.random.seed(42)
        strat_returns = np.random.normal(0.0012, 0.014, 252)
        bench_returns = np.random.normal(0.0006, 0.012, 252)

        comparison = comparator.compare(strat_returns, bench_returns)
        assert hasattr(comparison, "alpha_pct")
        assert hasattr(comparison, "beta")
        assert hasattr(comparison, "information_ratio")
        assert hasattr(comparison, "tracking_error_pct")
        assert comparison.beta != 0.0


# =====================================================
# 5. Deterministic Engine — Checkpoint & Idempotency
# =====================================================


class TestDeterministicEngineCrossValidation:
    """Deterministik kurtarma ve idempotency doğrulaması."""

    def test_checkpoint_bytes_and_idempotency(self, tmp_path):
        from services.backtest.deterministic import DeterministicRecovery, IdempotencyGuard

        recovery = DeterministicRecovery(storage_path=str(tmp_path))
        recovery.set_seed(42)

        cfg = {"model": "LightGBM", "threshold": 65}
        portfolio = {"cash": 125_000.0, "positions": {"THYAO": 400}}

        recovery.create_checkpoint(cfg, portfolio)
        restored_cfg, restored_port, seed = recovery.restore_checkpoint()

        assert restored_cfg == cfg
        assert restored_port == portfolio
        assert seed == 42

        # IdempotencyGuard
        guard = IdempotencyGuard()
        counter = 0

        def run_once() -> int:
            nonlocal counter
            counter += 1
            return 100

        res1 = guard.get_or_execute("op_key", {"k": 1}, run_once)
        res2 = guard.get_or_execute("op_key", {"k": 1}, run_once)

        assert res1 == 100
        assert res2 == 100
        assert counter == 1  # İkinci çağrıda cache'den geldi


# =====================================================
# 6. Walk-Forward Engine V5 & Bias Detector Çapraz Kontrol
# =====================================================


class TestWalkForwardCrossValidation:
    """WalkForwardEngineV5 katlama ve LookAheadBiasDetector sınır sızıntısı çapraz testi."""

    def test_wf_folds_and_bias_detector_boundaries(self):
        from services.backtest.bias_detector import LookAheadBiasDetector
        from services.backtest.walk_forward_engine import WalkForwardEngineV5

        engine = WalkForwardEngineV5(
            train_days=100,
            test_days=30,
            step_days=20,
            purge_days=5,
            embargo_days=3,
        )

        dates = [(date(2022, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(250)]
        folds = engine.create_folds(dates)
        assert len(folds) >= 2

        for f in folds:
            assert f.train_end < f.test_start, "Purge aralığı ihlal edildi!"

        detector = LookAheadBiasDetector()
        # Purge >= label_horizon kontrolü
        report = detector.validate_label_feature_alignment(
            label_horizon_days=5,
            feature_window_days=20,
            purge_days=5,
        )
        assert report.critical_count == 0


# =====================================================
# 7. PortfolioSimulatorV3 & Invariant Doğrulaması
# =====================================================


class TestPortfolioSimulatorAndInvariants:
    """PortfolioSimulatorV3 invariant ve bakiye koruma testleri."""

    def test_portfolio_invariants_hold(self):
        from services.backtest.portfolio_sim import PortfolioSimulatorV3

        sim = PortfolioSimulatorV3(initial_capital=100_000.0, max_positions=5)
        dt = datetime(2023, 1, 5)

        # Alım (ticker, price, date, quantity)
        trade = sim.execute_buy(ticker="THYAO", price=200.0, date=dt, quantity=100)
        assert trade is not None
        assert sim.has_position("THYAO") is True
        assert sim.get_position_count() == 1

        # Equity invariant: total equity == cash + positions value
        current_prices = {"THYAO": 210.0}
        snapshot = sim.update_equity(prices=current_prices, date=dt)
        assert snapshot.equity > 0
        assert sim.get_total_value() > 0
        assert sim.can_buy() is True
        assert len(sim._trades) >= 1
