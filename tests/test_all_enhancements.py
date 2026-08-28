"""ALPHA BIST — Tüm Enhancement Testleri

Test edilen modüller:
- FeatureStabilityAnalyzer
- CalibrationEnhanced
- RegimeLimitsManager
- PortfolioEnhancements
- BacktestEnhancements
- EventEnhancements

Kullanım:
    python -m pytest tests/test_all_enhancements.py -v
"""

from __future__ import annotations

import numpy as np
import pytest


# =====================================================
# FEATURE STABILITY TESTS
# =====================================================


class TestFeatureStability:
    """FeatureStabilityAnalyzer testleri."""

    def test_import(self):
        from services.ml.feature_stability import FeatureStabilityAnalyzer, feature_stability
        assert feature_stability is not None

    def test_record_and_check(self):
        from services.ml.feature_stability import FeatureStabilityAnalyzer

        fs = FeatureStabilityAnalyzer()
        np.random.seed(42)

        # İlk dağılım
        fs.record_distribution({"f1": np.random.randn(100), "f2": np.random.randn(100)})

        # Aynı dağılım (stabil)
        fs.record_distribution({"f1": np.random.randn(100), "f2": np.random.randn(100)})

        summary = fs.check_stability()
        assert summary.total_features == 2
        assert summary.overall_stability_score > 0.5

    def test_detect_shift(self):
        from services.ml.feature_stability import FeatureStabilityAnalyzer

        fs = FeatureStabilityAnalyzer()
        np.random.seed(42)

        # Referans dağılım
        fs.record_distribution({"f1": np.random.randn(1000)})

        # Farklı dağılım (shift)
        fs.record_distribution({"f1": np.random.randn(1000) * 5 + 10})

        summary = fs.check_stability()
        # Shift tespit edilmeli
        assert summary.overall_stability_score < 1.0

    def test_get_unstable_features(self):
        from services.ml.feature_stability import FeatureStabilityAnalyzer

        fs = FeatureStabilityAnalyzer()
        fs.record_distribution({"stable": np.random.randn(100), "unstable": np.random.randn(100)})
        fs.record_distribution({"stable": np.random.randn(100), "unstable": np.random.randn(100) * 10 + 50})

        unstable = fs.get_unstable_features(threshold=0.5)
        assert isinstance(unstable, list)


# =====================================================
# CALIBRATION ENHANCED TESTS
# =====================================================


class TestCalibrationEnhanced:
    """CalibrationEnhanced testleri."""

    def test_import(self):
        from services.ml.calibration_enhanced import CalibrationEnhanced, calibration_enhanced
        assert calibration_enhanced is not None

    def test_generate_out_of_fold(self):
        from sklearn.linear_model import Ridge

        from services.ml.calibration_enhanced import CalibrationEnhanced

        np.random.seed(42)
        X = np.random.randn(200, 5)
        y = (X[:, 0] > 0).astype(float)

        ce = CalibrationEnhanced()
        result = ce.generate_out_of_fold(Ridge(), X, y, cv=3)

        assert result.n_folds == 3
        assert len(result.predictions) == 200
        assert result.mean_brier >= 0

    def test_record_and_check_drift(self):
        from services.ml.calibration_enhanced import CalibrationEnhanced

        ce = CalibrationEnhanced()

        # İyi calibration
        ce.record_calibration_metrics(brier_score=0.1, ece=0.05)

        # Kötü calibration (drift)
        ce.record_calibration_metrics(brier_score=0.3, ece=0.2)

        drift = ce.check_calibration_drift()
        assert drift.drift_detected
        assert drift.severity in ("WARNING", "ALERT")

    def test_should_retrain(self):
        from services.ml.calibration_enhanced import CalibrationEnhanced

        ce = CalibrationEnhanced()
        schedule = ce.should_retrain_calibration()
        assert schedule.should_retrain  # İlk retrain

    def test_compare_methods(self):
        from services.ml.calibration_enhanced import CalibrationEnhanced

        ce = CalibrationEnhanced()
        np.random.seed(42)

        predictions = [{"confidence": np.random.random(), "outcome": float(np.random.random() > 0.5)} for _ in range(100)]

        result = ce.compare_calibration_methods(predictions)
        assert "platt_brier" in result or "error" in result


# =====================================================
# REGIME LIMITS TESTS
# =====================================================


class TestRegimeLimits:
    """RegimeLimitsManager testleri."""

    def test_import(self):
        from services.risk.regime_limits import RegimeLimitsManager, regime_limits
        assert regime_limits is not None

    def test_get_limits(self):
        from services.risk.regime_limits import RegimeLimitsManager

        rm = RegimeLimitsManager()

        bull = rm.get_limits("BULL")
        bear = rm.get_limits("BEAR")

        assert bull.max_position_pct > bear.max_position_pct
        assert bull.max_total_exposure > bear.max_total_exposure

    def test_adjust_for_confidence(self):
        from services.risk.regime_limits import RegimeLimitsManager

        rm = RegimeLimitsManager()

        # Yüksek confidence
        high = rm.adjust_for_confidence(0.05, confidence=0.9, regime="BULL")

        # Düşük confidence
        low = rm.adjust_for_confidence(0.05, confidence=0.1, regime="BULL")

        assert high > low

    def test_check_sector_concentration(self):
        from services.risk.regime_limits import RegimeLimitsManager

        rm = RegimeLimitsManager()

        positions = {"GARAN": 0.15, "AKBNK": 0.15, "THYAO": 0.10}
        sector_map = {"GARAN": "BANK", "AKBNK": "BANK", "THYAO": "TRANSPORT"}

        is_within, sectors = rm.check_sector_concentration(positions, sector_map, "BEAR")
        # BANK = 0.30, BEAR limit = 0.20 → aşırı
        assert not is_within

    def test_check_liquidity(self):
        from services.risk.regime_limits import RegimeLimitsManager

        rm = RegimeLimitsManager()

        assert rm.check_liquidity("THYAO", liquidity_score=0.8, regime="BULL")
        assert not rm.check_liquidity("THYAO", liquidity_score=0.1, regime="CRISIS")

    def test_get_all_regimes(self):
        from services.risk.regime_limits import RegimeLimitsManager

        rm = RegimeLimitsManager()
        regimes = rm.get_all_regimes()
        assert "BULL" in regimes
        assert "BEAR" in regimes
        assert "CRISIS" in regimes


# =====================================================
# PORTFOLIO ENHANCEMENTS TESTS
# =====================================================


class TestPortfolioEnhancements:
    """PortfolioEnhancements testleri."""

    def test_import(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements, portfolio_enhancements
        assert portfolio_enhancements is not None

    def test_turnover_penalty(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        target = {"A": 0.5, "B": 0.3, "C": 0.2}
        current = {"A": 0.3, "B": 0.4, "C": 0.3}

        adjusted = pe.apply_turnover_penalty(target, current, penalty=0.01)

        # Penalty uygulandığı için target'a daha yakın ama tamamen eşit değil
        assert abs(adjusted["A"] - 0.5) < abs(current["A"] - 0.5)

    def test_should_rebalance(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements, PortfolioConstraints

        pe = PortfolioEnhancements(PortfolioConstraints(hysteresis_threshold=0.02))

        # Büyük değişim
        decision = pe.should_rebalance(
            {"A": 0.5, "B": 0.5},
            {"A": 0.1, "B": 0.9},
        )
        assert decision.should_rebalance

        # Küçük değişim
        decision = pe.should_rebalance(
            {"A": 0.5, "B": 0.5},
            {"A": 0.49, "B": 0.51},
        )
        assert not decision.should_rebalance

    def test_hysteresis(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        target = {"A": 0.52, "B": 0.28, "C": 0.20}
        current = {"A": 0.50, "B": 0.30, "C": 0.20}

        filtered = pe.apply_hysteresis(target, current, threshold=0.03)

        # A: diff=0.02 < 0.03 → current korunmalı
        assert filtered["A"] == 0.50
        # B: diff=0.02 < 0.03 → current korunmalı
        assert filtered["B"] == 0.30

    def test_sector_constraints(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        weights = {"GARAN": 0.20, "AKBNK": 0.20, "THYAO": 0.10}
        sector_map = {"GARAN": "BANK", "AKBNK": "BANK", "THYAO": "TRANSPORT"}

        adjusted = pe.apply_sector_constraints(weights, sector_map, max_sector_pct=0.30)

        # BANK toplamı 0.30'u aşmamalı
        bank_total = adjusted["GARAN"] + adjusted["AKBNK"]
        assert bank_total <= 0.301  # Floating point toleransı

    def test_liquidity_constraints(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        weights = {"A": 0.5, "B": 0.3, "C": 0.2}
        liquidity = {"A": 0.8, "B": 0.1, "C": 0.6}

        adjusted = pe.apply_liquidity_constraints(weights, liquidity, min_score=0.3)

        # B likidite yetersiz → çıkarılmalı
        assert adjusted["B"] == 0.0

    def test_min_position(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        weights = {"A": 0.50, "B": 0.30, "C": 0.005, "D": 0.195}
        filtered = pe.apply_min_position(weights, min_pct=0.01)

        # C çok küçük → çıkarılmalı
        assert "C" not in filtered

    def test_position_limits(self):
        from services.portfolio.portfolio_enhancements import PortfolioEnhancements

        pe = PortfolioEnhancements()

        weights = {"A": 0.30, "B": 0.40, "C": 0.30}
        adjusted = pe.apply_position_limits(weights, max_pct=0.10)

        # Hiçbiri %10'u aşmamalı
        assert all(w <= 0.101 for w in adjusted.values())


# =====================================================
# BACKTEST ENHANCEMENTS TESTS
# =====================================================


class TestBacktestEnhancements:
    """BacktestEnhancements testleri."""

    def test_import(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements, backtest_enhancements
        assert backtest_enhancements is not None

    def test_t_plus_1(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()

        # Normal gün
        result = be.check_t_plus_1("THYAO", "2026-01-05")
        assert result.can_execute
        assert result.delay_days >= 1

        # Cuma → Pazartesi
        result = be.check_t_plus_1("THYAO", "2026-01-02")  # Cuma
        assert result.can_execute
        assert result.delay_days >= 2  # Hafta sonu

    def test_market_impact(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()

        # Küçük işlem
        impact = be.estimate_market_impact("THYAO", trade_size=100_000, adv=100_000_000)
        assert impact.is_feasible
        assert impact.total_impact_pct < 1.0

        # Büyük işlem
        impact = be.estimate_market_impact("THYAO", trade_size=50_000_000, adv=100_000_000)
        assert not impact.is_feasible  # %50 participation

    def test_delisted(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()
        be.register_delisted("XYZ", "2026-06-01")

        assert not be.is_delisted("XYZ", "2026-05-01")
        assert be.is_delisted("XYZ", "2026-06-01")
        assert be.is_delisted("XYZ", "2026-07-01")
        assert not be.is_delisted("ABC", "2026-07-01")

    def test_ipo_handling(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()
        be.register_ipo("NEW", "2026-06-01")

        assert not be.is_post_ipo("NEW", "2026-06-15", min_days=30)
        assert be.is_post_ipo("NEW", "2026-07-15", min_days=30)

    def test_corporate_actions(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements, CorporateAction

        be = BacktestEnhancements()
        be.register_corporate_action(CorporateAction(
            ticker="THYAO",
            action_type="dividend",
            ex_date="2026-06-15",
            value=5.0,
            description="Temettü",
        ))

        actions = be.get_corporate_actions("THYAO", "2026-01-01", "2026-12-31")
        assert len(actions) == 1

    def test_dividend_adjustment(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()
        adjusted = be.adjust_for_dividend(100.0, 5.0)
        assert adjusted == 95.0

    def test_split_adjustment(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()
        adjusted = be.adjust_for_split(200.0, 2.0)
        assert adjusted == 100.0

    def test_liquidity_check(self):
        from services.backtest.backtest_enhancements import BacktestEnhancements

        be = BacktestEnhancements()

        is_liquid, reason = be.check_liquidity("THYAO", adv=100_000_000, trade_size=1_000_000)
        assert is_liquid

        is_liquid, reason = be.check_liquidity("THYAO", adv=100_000, trade_size=1_000_000)
        assert not is_liquid


# =====================================================
# EVENT ENHANCEMENTS TESTS
# =====================================================


class TestEventEnhancements:
    """EventEnhancements testleri."""

    def test_import(self):
        from services.core.event_enhancements import EventEnhancements, event_enhancements
        assert event_enhancements is not None

    def test_idempotency(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()

        assert not ee.is_duplicate("event_1")
        ee.mark_processed("event_1")
        assert ee.is_duplicate("event_1")
        assert not ee.is_duplicate("event_2")

    def test_process_with_idempotency(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()

        results = []
        result = ee.process_with_idempotency("event_1", lambda: results.append(1) or "ok")
        assert result == "ok"

        # Duplicate
        result = ee.process_with_idempotency("event_1", lambda: results.append(2) or "ok")
        assert result is None
        assert len(results) == 1

    def test_retry_policy(self):
        from services.core.event_enhancements import EventEnhancements, RetryPolicy

        ee = EventEnhancements(retry_policy=RetryPolicy(max_retries=3))

        assert ee.should_retry("event_1", attempt=0)
        assert ee.should_retry("event_1", attempt=2)
        assert not ee.should_retry("event_1", attempt=3)

    def test_retry_delay(self):
        from services.core.event_enhancements import EventEnhancements, RetryPolicy

        ee = EventEnhancements(retry_policy=RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=False))

        d0 = ee.get_retry_delay(0)
        d1 = ee.get_retry_delay(1)
        d2 = ee.get_retry_delay(2)

        assert d0 < d1 < d2

    def test_correlation_id(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()

        corr_id = ee.generate_correlation_id()
        assert len(corr_id) > 0

        ee.link_event(corr_id, "event_1")
        ee.link_event(corr_id, "event_2")

        linked = ee.get_linked_events(corr_id)
        assert "event_1" in linked
        assert "event_2" in linked

    def test_sequence_number(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()

        assert ee.get_next_sequence("topic_a") == 1
        assert ee.get_next_sequence("topic_a") == 2
        assert ee.get_next_sequence("topic_b") == 1

    def test_create_metadata(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()

        meta = ee.create_metadata("event_1", "corr_1")
        assert meta.event_id == "event_1"
        assert meta.correlation_id == "corr_1"
        assert meta.timestamp is not None

    def test_stats(self):
        from services.core.event_enhancements import EventEnhancements

        ee = EventEnhancements()
        ee.mark_processed("event_1")

        stats = ee.get_stats()
        assert stats["processed_events"] == 1
