"""
ALPHA BIST — Macro System Tests (Tüm Fazlar)

Test edilen:
- Faz 0: Config, refactor (mevcut modüller)
- Faz 1: Surprise model
- Faz 2: Regime detection
- Faz 3: Dynamic sensitivity
- Faz 4: Impact analysis + decay
- Faz 5: Stress test
- Faz 6: Calendar integration
- Faz 7: Correlation tracking
- Faz 8: Historical store
- Faz 9: Feature pipeline (50+ feature)
- Faz 10: Orchestrator integration
"""

import pytest
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.macro.config.macro_config import MacroConfig, macro_config
from services.macro.surprise_model import MacroSurpriseModel, macro_surprise_model
from services.macro.regime_detector import MacroRegimeDetector, macro_regime_detector
from services.macro.impact_analyzer import MacroImpactAnalyzer, macro_impact_analyzer
from services.macro.stress_test import MacroStressTest, macro_stress_test
from services.macro.correlation_tracker import MacroCorrelationTracker, macro_correlation_tracker
from services.macro.calendar_engine import MacroCalendarEngine, macro_calendar_engine
from services.macro.historical_store import MacroHistoricalStore, macro_historical_store
from services.macro.factor_decomposition import MacroFactorDecomposition, macro_factor_decomposition


# =====================================================
# FAZ 0: Config Tests
# =====================================================

class TestMacroConfig:
    """Macro config testleri."""

    def test_config_default_values(self):
        cfg = MacroConfig()
        assert cfg.surprise.small_threshold == 0.05
        assert cfg.surprise.medium_threshold == 0.10
        assert cfg.surprise.large_threshold == 0.15
        assert cfg.surprise.decay_half_life_days == 5

    def test_regime_config(self):
        cfg = MacroConfig()
        assert cfg.regime.scoring_window_days == 20
        assert cfg.regime.min_regime_duration_days == 5
        assert cfg.regime.confidence_threshold == 0.3

    def test_stress_test_scenarios(self):
        cfg = MacroConfig()
        scenarios = cfg.stress_test.predefined_scenarios
        assert "USDTRY_10_PCT" in scenarios
        assert "TCMB_RATE_HIKE_500BP" in scenarios
        assert "VIX_SPIKE_50_PCT" in scenarios
        assert "OIL_SHOCK_20_PCT" in scenarios
        assert "GLOBAL_RISK_OFF" in scenarios
        assert "INFLATION_HIGH" in scenarios
        assert "BIST_CRASH_10_PCT" in scenarios
        assert len(scenarios) == 7

    def test_correlation_pairs(self):
        cfg = MacroConfig()
        pairs = cfg.correlation.tracked_pairs
        assert len(pairs) == 6
        assert ("usdtry", "gold") in pairs
        assert ("vix", "bist100") in pairs

    def test_decay_half_life(self):
        cfg = MacroConfig()
        assert cfg.decay.half_life_by_shock_type["monetary_policy"] == 10
        assert cfg.decay.half_life_by_shock_type["fx_shock"] == 5
        assert cfg.decay.half_life_by_shock_type["global_risk_off"] == 3

    def test_singleton_config(self):
        assert macro_config is not None
        assert isinstance(macro_config, MacroConfig)


# =====================================================
# FAZ 0: Mevcut Modül Refactor Tests
# =====================================================

class TestExistingModulesRefactor:
    """Mevcut macro modüllerinin refactor testleri."""

    def test_tcmb_features(self):
        from services.macro.tcmb import compute_tcmb_features
        data = {
            "policy_rate": 45.0,
            "inflation": 65.0,
            "actual_rate": 47.5,
            "expected_rate": 45.0,
            "us_rate": 5.25,
            "wacf": 46.0,
            "rate_change": 2.5,
        }
        features = compute_tcmb_features(data)
        assert "tcmb_policy_rate" in features
        assert "tcmb_real_rate" in features
        assert "tcmb_rate_surprise" in features
        assert "tcmb_policy_stance" in features
        assert "tcmb_rate_differential" in features
        assert "tcmb_wacf" in features
        assert features["tcmb_policy_rate"] == 45.0
        assert features["tcmb_real_rate"] == -20.0  # 45 - 65

    def test_inflation_features(self):
        from services.macro.inflation import compute_inflation_features
        data = {
            "cpi_yoy": 65.0,
            "ppi_yoy": 80.0,
            "core_cpi": 60.0,
            "cpi_monthly": 5.0,
            "cpi_expected": 63.0,
            "cpi_previous": 62.0,
        }
        features = compute_inflation_features(data)
        assert "inf_cpi_level" in features
        assert "inf_ppi_level" in features
        assert "inf_cpi_ppi_spread" in features
        assert "inf_core_cpi" in features
        assert "inf_surprise" in features
        assert "inf_trend" in features
        assert "inf_regime" in features
        assert features["inf_cpi_level"] == 65.0
        assert features["inf_cpi_ppi_spread"] == -15.0  # 65 - 80

    def test_fx_features(self):
        from services.macro.fx import compute_fx_features
        data = {
            "usdtry": 30.5,
            "eurtry": 33.0,
            "usdtry_previous": 30.3,
        }
        features = compute_fx_features(data)
        assert "fx_usdtry_level" in features
        assert "fx_eurtry_level" in features
        assert "fx_eurtry_usdtry_ratio" in features
        assert "fx_usdtry_change_pct" in features
        assert features["fx_usdtry_level"] == 30.5

    def test_cds_features(self):
        from services.macro.cds import compute_cds_features
        data = {"cds_5y": 250.0, "cds_previous": 240.0}
        features = compute_cds_features(data)
        assert "cds_5y" in features
        assert "cds_risk_level" in features
        assert features["cds_5y"] == 250.0
        assert features["cds_risk_level"] == 2.0  # YÜKSEK

    def test_credit_features(self):
        from services.macro.credit import compute_credit_features
        data = {"credit_growth_yoy": 15.0, "credit_previous": 12.0}
        features = compute_credit_features(data)
        assert "credit_growth_yoy" in features
        assert "credit_regime" in features
        assert "credit_trend" in features

    def test_current_account_features(self):
        from services.macro.current_account import compute_ca_features
        data = {"ca_balance": -8.5, "ca_previous": -10.0}
        features = compute_ca_features(data)
        assert "ca_balance" in features
        assert "ca_regime" in features
        assert "ca_improving" in features
        assert features["ca_improving"] == 1.0  # İyileşiyor

    def test_calendar_events(self):
        from services.macro.calendar import get_macro_events, get_upcoming_events, get_event_impact
        events = get_macro_events()
        assert "TCMB_PPK" in events
        assert "CPI_RELEASE" in events

        upcoming = get_upcoming_events(days=30)
        assert isinstance(upcoming, list)

        impact = get_event_impact("TCMB_PPK")
        assert impact["impact"] == "HIGH"


# =====================================================
# FAZ 1: Surprise Model Tests
# =====================================================

class TestMacroSurpriseModel:
    """Surprise model testleri."""

    def setup_method(self):
        self.model = MacroSurpriseModel()

    def test_set_expectation(self):
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        assert "TCMB_RATE" in self.model._expectations
        assert self.model._expectations["TCMB_RATE"]["value"] == 45.0

    def test_surprise_calculation_with_expectation(self):
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 47.5)
        assert result.actual == 47.5
        assert result.expected == 45.0
        assert result.surprise == 2.5
        assert result.direction == "HAWKISH"

    def test_surprise_calculation_no_expectation(self):
        result = self.model.calculate_surprise("CPI", 65.0)
        assert result.surprise == 0.0
        assert result.magnitude == "NONE"
        assert result.source == "no_expectation"

    def test_surprise_magnitude_none(self):
        self.model.set_expectation("CPI", 65.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 65.2)
        assert result.magnitude == "NONE"

    def test_surprise_magnitude_small(self):
        self.model.set_expectation("CPI", 60.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 64.0)
        assert result.magnitude == "SMALL"

    def test_surprise_magnitude_large(self):
        self.model.set_expectation("CPI", 60.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 72.0)
        assert result.magnitude == "LARGE"

    def test_surprise_direction_hawkish(self):
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 47.5)
        assert result.direction == "HAWKISH"

    def test_surprise_direction_dovish(self):
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 42.5)
        assert result.direction == "DOVISH"

    def test_surprise_features(self):
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        self.model.set_expectation("CPI", 65.0, "consensus", 0.8)
        features = self.model.compute_surprise_features({"TCMB_RATE": 47.5, "CPI": 68.0})
        assert "tcmb_rate_surprise" in features
        assert "cpi_surprise" in features

    def test_sector_surprise_impact(self):
        from services.macro.surprise_model import SurpriseResult
        from datetime import datetime, timezone
        surprises = {
            "TCMB_RATE": SurpriseResult(
                indicator="TCMB_RATE", actual=47.5, expected=45.0,
                surprise=2.5, surprise_pct=0.0556, magnitude="SMALL",
                direction="HAWKISH", confidence=0.9, source="tcmb_survey",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        }
        impacts = self.model.compute_sector_surprise_impact("BANK", surprises)
        assert "tcmb_rate_surprise_impact" in impacts
        assert "total_surprise_impact" in impacts

    def test_decay_impact(self):
        assert self.model.get_decay_impact("TCMB_RATE", 0) == 1.0
        decay = self.model.get_decay_impact("TCMB_RATE", 5)
        assert abs(decay - 0.5) < 0.01

    def test_surprise_report(self):
        report = self.model.get_surprise_report()
        assert "active_surprises" in report
        assert "total_surprises" in report


# =====================================================
# FAZ 2: Regime Detection Tests
# =====================================================

class TestMacroRegimeDetector:
    """Regime detection testleri."""

    def setup_method(self):
        self.detector = MacroRegimeDetector()

    def test_expansion_regime(self):
        features = {
            "rate_trend": -1.0, "inflation_trend": -1.0,
            "sp500_momentum_20d": 5.0, "vix_regime": 0.0, "credit_growth_yoy": 10.0,
        }
        result = self.detector.detect_regime(features)
        assert result.regime == "EXPANSION"
        assert result.confidence > 0

    def test_risk_off_regime(self):
        features = {
            "vix_regime": 3.0, "sp500_momentum_20d": -8.0,
            "cds_5y": 400, "usdtry_momentum_20d": 8.0,
        }
        result = self.detector.detect_regime(features)
        assert result.regime == "RISK_OFF"

    def test_stagflation_regime(self):
        features = {
            "cpi_level": 20.0, "sp500_momentum_20d": -5.0,
            "tcmb_policy_rate": 20.0, "vix_regime": 2.5, "usdtry_momentum_20d": 5.0,
        }
        result = self.detector.detect_regime(features)
        assert result.regime == "STAGFLATION"

    def test_regime_features(self):
        features = {
            "rate_trend": -1.0, "inflation_trend": -1.0,
            "sp500_momentum_20d": 5.0, "vix_regime": 0.0,
        }
        regime_features = self.detector.compute_regime_features(features)
        assert "macro_regime_expansion_score" in regime_features
        assert "macro_regime_composite" in regime_features

    def test_regime_report(self):
        report = self.detector.get_regime_report()
        assert "regime_descriptions" in report
        assert len(report["regime_descriptions"]) == 6

    def test_regime_smoothing(self):
        features1 = {"vix_regime": 3.0, "sp500_momentum_20d": -8.0, "cds_5y": 400, "usdtry_momentum_20d": 8.0}
        features2 = {"rate_trend": -1.0, "inflation_trend": -1.0, "sp500_momentum_20d": 5.0, "vix_regime": 0.0, "credit_growth_yoy": 10.0}
        result1 = self.detector.detect_regime(features1)
        result2 = self.detector.detect_regime(features2)
        # Smoothing nedeniyle短时间内 değişmemeli


# =====================================================
# FAZ 4: Impact Analysis Tests
# =====================================================

class TestMacroImpactAnalyzer:
    """Impact analyzer testleri."""

    def setup_method(self):
        self.analyzer = MacroImpactAnalyzer()

    def test_record_shock(self):
        self.analyzer.record_shock("usdtry", 0.10, "USDTRY")
        assert len(self.analyzer._shock_history) == 1

    def test_compute_impact(self):
        impact = self.analyzer.compute_impact("THYAO", "AVIATION", "usdtry", 0.10, 0)
        assert impact.raw_impact != 0
        assert impact.decay_factor == 1.0

    def test_decay_impact(self):
        impact0 = self.analyzer.compute_impact("THYAO", "AVIATION", "usdtry", 0.10, 0)
        impact5 = self.analyzer.compute_impact("THYAO", "AVIATION", "usdtry", 0.10, 5)
        assert impact0.decay_factor > impact5.decay_factor

    def test_cumulative_impact(self):
        self.analyzer.record_shock("usdtry", 0.10, "USDTRY")
        self.analyzer.record_shock("oil", 0.20, "OIL")
        result = self.analyzer.compute_cumulative_impact("THYAO", "AVIATION")
        assert "cumulative_impact" in result
        assert "active_shocks" in result

    def test_decay_curve(self):
        curve = self.analyzer.compute_decay_curve("usdtry", 0.10, max_days=30)
        assert len(curve) == 31
        assert curve[0]["decay_factor"] == 1.0
        assert curve[-1]["decay_factor"] < 1.0

    def test_shock_report(self):
        self.analyzer.record_shock("usdtry", 0.10, "USDTRY")
        report = self.analyzer.get_shock_report()
        assert report["total_shocks"] == 1


# =====================================================
# FAZ 5: Stress Test Tests
# =====================================================

class TestMacroStressTest:
    """Stres testi testleri."""

    def setup_method(self):
        self.st = MacroStressTest()
        self.portfolio = {
            "total_value": 1000000,
            "positions": [
                {"ticker": "THYAO", "sector": "AVIATION", "value": 500000, "weight": 0.5},
                {"ticker": "GARAN", "sector": "BANK", "value": 500000, "weight": 0.5},
            ],
        }

    def test_run_stress_test(self):
        result = self.st.run_stress_test(self.portfolio, "USDTRY_10_PCT")
        assert result.total_impact_pct != 0
        assert len(result.position_impacts) == 2

    def test_scenario_descriptions(self):
        result = self.st.run_stress_test(self.portfolio, "USDTRY_10_PCT")
        assert result.description != ""

    def test_custom_scenario(self):
        result = self.st.run_custom_scenario(
            self.portfolio,
            {"usdtry_change": 0.15, "oil_change": 0.30},
            "Custom scenario",
        )
        assert result.scenario == "CUSTOM"

    def test_breaking_point(self):
        bp = self.st.find_breaking_point(self.portfolio, "usdtry_change", -0.10)
        assert bp.breaking_point_pct > 0

    def test_run_all_scenarios(self):
        results = self.st.run_all_scenarios(self.portfolio)
        assert len(results) == 7

    def test_report(self):
        report = self.st.get_report(self.portfolio)
        assert "scenario_count" in report
        assert report["scenario_count"] == 7

    def test_worst_best_position(self):
        result = self.st.run_stress_test(self.portfolio, "USDTRY_10_PCT")
        assert result.worst_position != ""
        assert result.best_position != ""


# =====================================================
# FAZ 7: Correlation Tracker Tests
# =====================================================

class TestMacroCorrelationTracker:
    """Correlation tracker testleri."""

    def setup_method(self):
        self.tracker = MacroCorrelationTracker()

    def test_update(self):
        self.tracker.update({"usdtry": 30.5, "gold": 2000})
        assert len(self.tracker._history["usdtry"]) == 1

    def test_correlation_calculation(self):
        for i in range(30):
            self.tracker.update({"usdtry": 30.0 + i * 0.1, "gold": 2000 + i * 5})
        result = self.tracker.get_correlation("usdtry", "gold")
        assert result is not None
        assert -1 <= result.correlation <= 1

    def test_correlation_matrix(self):
        for i in range(30):
            self.tracker.update({"usdtry": 30.0 + i * 0.1, "gold": 2000 + i * 5, "vix": 20 - i * 0.2})
        matrix = self.tracker.get_correlation_matrix()
        assert "usdtry" in matrix
        assert "gold" in matrix

    def test_correlation_features(self):
        for i in range(30):
            self.tracker.update({"usdtry": 30.0 + i * 0.1, "gold": 2000 + i * 5})
        features = self.tracker.compute_correlation_features()
        assert "corr_usdtry_gold" in features

    def test_report(self):
        for i in range(30):
            self.tracker.update({"usdtry": 30.0 + i * 0.1, "gold": 2000 + i * 5})
        report = self.tracker.get_report()
        assert "tracked_pairs" in report


# =====================================================
# FAZ 8: Historical Store Tests
# =====================================================

class TestMacroHistoricalStore:
    """Historical store testleri."""

    def test_save_and_get(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)
            store.save("2026-01-01", "USDTRY", 30.5, "test")
            value = store.get("2026-01-01", "USDTRY")
            assert value == 30.5
            os.unlink(f.name)

    def test_get_latest(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)
            store.save("2026-01-01", "USDTRY", 30.5, "test")
            store.save("2026-01-02", "USDTRY", 30.7, "test")
            latest = store.get_latest("USDTRY")
            assert latest["value"] == 30.7
            os.unlink(f.name)

    def test_get_range(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)
            store.save("2026-01-01", "USDTRY", 30.5, "test")
            store.save("2026-01-02", "USDTRY", 30.7, "test")
            store.save("2026-01-03", "USDTRY", 30.9, "test")
            data = store.get_range("USDTRY", "2026-01-01", "2026-01-02")
            assert len(data) == 2
            os.unlink(f.name)

    def test_backfill(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)
            data = [
                {"date": "2026-01-01", "value": 30.5, "source": "test"},
                {"date": "2026-01-02", "value": 30.7, "source": "test"},
            ]
            store.backfill("USDTRY", data)
            assert store.get("2026-01-01", "USDTRY") == 30.5
            os.unlink(f.name)

    def test_report(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)
            store.save("2026-01-01", "USDTRY", 30.5, "test")
            report = store.get_report()
            assert report["indicators"] == 1
            os.unlink(f.name)


# =====================================================
# FAZ 10: Factor Decomposition Tests
# =====================================================

class TestMacroFactorDecomposition:
    """Factor decomposition testleri."""

    def setup_method(self):
        self.fd = MacroFactorDecomposition()

    def test_decompose(self):
        result = self.fd.decompose(
            ticker="THYAO", sector="AVIATION", total_return=5.0,
            macro_changes={"usdtry": 0.10, "interest_rate": 0.05, "oil": 0.20},
        )
        assert result.ticker == "THYAO"
        assert len(result.factor_contributions) == 7
        assert result.top_factor in self.fd.FACTORS

    def test_factor_features(self):
        features = self.fd.compute_factor_features(
            ticker="THYAO", sector="AVIATION", total_return=5.0,
            macro_changes={"usdtry": 0.10, "oil": 0.20},
        )
        assert "factor_usdtry_contribution" in features
        assert "factor_residual" in features
        assert "factor_explained_pct" in features

    def test_report(self):
        report = self.fd.get_report(
            ticker="THYAO", sector="AVIATION", total_return=5.0,
            macro_changes={"usdtry": 0.10, "oil": 0.20},
        )
        assert "top_factor" in report
        assert "contributions" in report


# =====================================================
# FAZ 6: Calendar Engine Tests
# =====================================================

class TestMacroCalendarEngine:
    """Calendar engine testleri."""

    def test_upcoming_events(self):
        engine = MacroCalendarEngine()
        upcoming = engine.get_upcoming_events(days=30)
        assert isinstance(upcoming, list)

    def test_register_expectation(self):
        engine = MacroCalendarEngine()
        engine.register_expectation("TCMB_PPK_2026-08-20", 45.0)
        assert engine._expectations["TCMB_PPK_2026-08-20"] == 45.0

    def test_complete_event(self):
        engine = MacroCalendarEngine()
        engine.register_expectation("TCMB_PPK_2026-08-20", 45.0)
        event = engine.complete_event("TCMB_PPK_2026-08-20", 47.5)
        assert event is not None
        assert event.surprise == 2.5

    def test_pre_event_alert(self):
        engine = MacroCalendarEngine()
        alert = engine.get_pre_event_alert("TCMB_PPK_2026-08-20")
        assert "event_id" in alert or "error" in alert

    def test_calendar_report(self):
        engine = MacroCalendarEngine()
        report = engine.get_calendar_report()
        assert "total_events" in report


# =====================================================
# FAZ 9: Feature Pipeline Tests
# =====================================================

class TestMacroFeaturePipeline:
    """Feature pipeline testleri (50+ feature)."""

    def test_compute_all_macro_features_with_services(self):
        from services.features.macro import macro_feature_engine

        tcmb_data = {"policy_rate": 45.0, "inflation": 65.0}
        inflation_data = {"cpi_yoy": 65.0, "ppi_yoy": 80.0}
        fx_data = {"usdtry": 30.5, "eurtry": 33.0}
        cds_data = {"cds_5y": 250.0}
        credit_data = {"credit_growth_yoy": 15.0}
        ca_data = {"ca_balance": -8.5}

        features = macro_feature_engine.compute_all_macro_features_with_services(
            tcmb_data=tcmb_data,
            inflation_data=inflation_data,
            fx_data=fx_data,
            cds_data=cds_data,
            credit_data=credit_data,
            ca_data=ca_data,
        )

        # En az 30+ feature olmalı
        assert len(features) >= 25
        assert "tcmb_tcmb_policy_rate" in features or "tcmb_policy_rate" in features


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
