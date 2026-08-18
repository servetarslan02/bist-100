"""
ALPHA BIST — Macro System Tests (Faz 0-2)

Test edilen:
- Faz 0: Config, refactor
- Faz 1: Surprise model
- Faz 2: Regime detection
"""

import pytest
import sys
import os
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
        """Varsayılan değerler doğru mu?"""
        cfg = MacroConfig()
        assert cfg.surprise.small_threshold == 0.05
        assert cfg.surprise.medium_threshold == 0.10
        assert cfg.surprise.large_threshold == 0.15
        assert cfg.surprise.decay_half_life_days == 5

    def test_regime_config(self):
        """Regime config doğru mu?"""
        cfg = MacroConfig()
        assert cfg.regime.scoring_window_days == 20
        assert cfg.regime.min_regime_duration_days == 5
        assert cfg.regime.confidence_threshold == 0.3

    def test_stress_test_scenarios(self):
        """Stres test senaryoları tanımlı mı?"""
        cfg = MacroConfig()
        scenarios = cfg.stress_test.predefined_scenarios
        assert "USDTRY_10_PCT" in scenarios
        assert "TCMB_RATE_HIKE_500BP" in scenarios
        assert "VIX_SPIKE_50_PCT" in scenarios
        assert len(scenarios) == 7

    def test_correlation_pairs(self):
        """Korelasyon çiftleri tanımlı mı?"""
        cfg = MacroConfig()
        pairs = cfg.correlation.tracked_pairs
        assert len(pairs) == 6
        assert ("usdtry", "gold") in pairs
        assert ("vix", "bist100") in pairs

    def test_decay_half_life(self):
        """Half-life değerleri doğru mu?"""
        cfg = MacroConfig()
        assert cfg.decay.half_life_by_shock_type["monetary_policy"] == 10
        assert cfg.decay.half_life_by_shock_type["fx_shock"] == 5
        assert cfg.decay.half_life_by_shock_type["global_risk_off"] == 3

    def test_singleton_config(self):
        """Singleton config çalışıyor mu?"""
        assert macro_config is not None
        assert isinstance(macro_config, MacroConfig)


# =====================================================
# FAZ 1: Surprise Model Tests
# =====================================================

class TestMacroSurpriseModel:
    """Surprise model testleri."""

    def setup_method(self):
        self.model = MacroSurpriseModel()

    def test_set_expectation(self):
        """Beklenti kaydetme çalışıyor mu?"""
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        assert "TCMB_RATE" in self.model._expectations
        assert self.model._expectations["TCMB_RATE"]["value"] == 45.0

    def test_surprise_calculation_with_expectation(self):
        """Beklenti ile surprise hesaplama doğru mu?"""
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 47.5)

        assert result.actual == 47.5
        assert result.expected == 45.0
        assert result.surprise == 2.5
        assert result.direction == "HAWKISH"
        assert result.magnitude in ("SMALL", "MEDIUM", "LARGE")

    def test_surprise_calculation_no_expectation(self):
        """Beklenti yoksa surprise = 0 mı?"""
        result = self.model.calculate_surprise("CPI", 65.0)

        assert result.surprise == 0.0
        assert result.surprise_pct == 0.0
        assert result.magnitude == "NONE"
        assert result.source == "no_expectation"

    def test_surprise_magnitude_none(self):
        """Küçük sürpriz NONE mu?"""
        self.model.set_expectation("CPI", 65.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 65.2)  # %0.3 sürpriz

        assert result.magnitude == "NONE"

    def test_surprise_magnitude_small(self):
        """Orta sürpriz SMALL mu?"""
        self.model.set_expectation("CPI", 60.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 64.0)  # %6.7 sürpriz

        assert result.magnitude == "SMALL"

    def test_surprise_magnitude_large(self):
        """Büyük sürpriz LARGE mu?"""
        self.model.set_expectation("CPI", 60.0, "consensus", 0.8)
        result = self.model.calculate_surprise("CPI", 72.0)  # %20 sürpriz

        assert result.magnitude == "LARGE"

    def test_surprise_direction_hawkish(self):
        """TCMB faiz artışı HAWKISH mi?"""
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 47.5)

        assert result.direction == "HAWKISH"

    def test_surprise_direction_dovish(self):
        """TCMB faiz düşüşü DOVISH mi?"""
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        result = self.model.calculate_surprise("TCMB_RATE", 42.5)

        assert result.direction == "DOVISH"

    def test_surprise_features(self):
        """Surprise feature'ları doğru mu?"""
        self.model.set_expectation("TCMB_RATE", 45.0, "tcmb_survey", 0.9)
        self.model.set_expectation("CPI", 65.0, "consensus", 0.8)

        features = self.model.compute_surprise_features({
            "TCMB_RATE": 47.5,
            "CPI": 68.0,
        })

        assert "tcmb_rate_surprise" in features
        assert "cpi_surprise" in features
        assert "tcmb_rate_surprise_pct" in features

    def test_sector_surprise_impact(self):
        """Sektör surprise etkisi doğru mu?"""
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
        """Decay etkisi doğru mu?"""
        # Gün 0 → %100
        assert self.model.get_decay_impact("TCMB_RATE", 0) == 1.0

        # Half-life gününde → %50
        decay = self.model.get_decay_impact("TCMB_RATE", 5)
        assert abs(decay - 0.5) < 0.01

    def test_surprise_report(self):
        """Surprise raporu çalışıyor mu?"""
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
        """EXPANSION rejim tespiti doğru mu?"""
        features = {
            "rate_trend": -1.0,       # Faiz düşüyor
            "inflation_trend": -1.0,  # Enflasyon düşüyor
            "sp500_momentum_20d": 5.0, # S&P500 yükseliyor
            "vix_regime": 0.0,         # VIX düşük
            "credit_growth_yoy": 10.0, # Kredi büyüyor
        }

        result = self.detector.detect_regime(features)
        assert result.regime == "EXPANSION"
        assert result.confidence > 0

    def test_risk_off_regime(self):
        """RISK_OFF rejim tespiti doğru mu?"""
        features = {
            "vix_regime": 3.0,          # VIX yüksek
            "sp500_momentum_20d": -8.0,  # S&P500 düşüyor
            "cds_5y": 400,               # CDS yüksek
            "usdtry_momentum_20d": 8.0,  # USDTRY yükseliyor
        }

        result = self.detector.detect_regime(features)
        assert result.regime == "RISK_OFF"

    def test_stagflation_regime(self):
        """STAGFLATION rejim tespiti doğru mu?"""
        features = {
            "cpi_level": 20.0,           # Yüksek enflasyon
            "sp500_momentum_20d": -5.0,   # Zayıf büyüme
            "tcmb_policy_rate": 20.0,     # Yüksek faiz
            "vix_regime": 2.5,            # VIX yüksek
            "usdtry_momentum_20d": 5.0,   # Kur baskısı
        }

        result = self.detector.detect_regime(features)
        assert result.regime == "STAGFLATION"

    def test_regime_features(self):
        """Regime feature'ları doğru mu?"""
        features = {
            "rate_trend": -1.0,
            "inflation_trend": -1.0,
            "sp500_momentum_20d": 5.0,
            "vix_regime": 0.0,
        }

        regime_features = self.detector.compute_regime_features(features)

        assert "macro_regime_expansion_score" in regime_features
        assert "macro_regime_composite" in regime_features
        assert "macro_regime_duration_days" in regime_features

    def test_regime_report(self):
        """Regime raporu çalışıyor mu?"""
        report = self.detector.get_regime_report()
        assert "regime_descriptions" in report
        assert len(report["regime_descriptions"]) == 6

    def test_regime_smoothing(self):
        """Rejim smoothing çalışıyor mu? —短时间内 değişmemeli."""
        features1 = {"vix_regime": 3.0, "sp500_momentum_20d": -8.0, "cds_5y": 400, "usdtry_momentum_20d": 8.0}
        features2 = {"rate_trend": -1.0, "inflation_trend": -1.0, "sp500_momentum_20d": 5.0, "vix_regime": 0.0, "credit_growth_yoy": 10.0}

        # İlk tespit
        result1 = self.detector.detect_regime(features1)
        first_regime = result1.regime

        # Hemen ardından farklı rejim
        result2 = self.detector.detect_regime(features2)

        # Smoothing nedeniyle短时间内 değişmemeli
        # (min_regime_duration_days = 5)


# =====================================================
# FAZ 3-8: Integration Tests
# =====================================================

class TestMacroIntegration:
    """Entegrasyon testleri."""

    def test_impact_analyzer(self):
        """Impact analyzer çalışıyor mu?"""
        analyzer = MacroImpactAnalyzer()
        analyzer.record_shock("usdtry", 0.10, "USDTRY")

        impact = analyzer.compute_impact("THYAO", "AVIATION", "usdtry", 0.10, 0)
        assert impact.raw_impact != 0
        assert impact.decay_factor == 1.0  # Gün 0

    def test_stress_test(self):
        """Stres testi çalışıyor mu?"""
        st = MacroStressTest()
        portfolio = {
            "total_value": 1000000,
            "positions": [
                {"ticker": "THYAO", "sector": "AVIATION", "value": 500000, "weight": 0.5},
                {"ticker": "GARAN", "sector": "BANK", "value": 500000, "weight": 0.5},
            ],
        }

        result = st.run_stress_test(portfolio, "USDTRY_10_PCT")
        assert result.total_impact_pct != 0
        assert len(result.position_impacts) == 2

    def test_correlation_tracker(self):
        """Correlation tracker çalışıyor mu?"""
        tracker = MacroCorrelationTracker()

        # Veri ekle
        for i in range(30):
            tracker.update({
                "usdtry": 30.0 + i * 0.1,
                "gold": 2000 + i * 5,
            })

        # Korelasyon hesapla
        result = tracker.get_correlation("usdtry", "gold")
        assert result is not None
        assert -1 <= result.correlation <= 1

    def test_calendar_engine(self):
        """Calendar engine çalışıyor mu?"""
        engine = MacroCalendarEngine()
        upcoming = engine.get_upcoming_events(days=30)

        assert isinstance(upcoming, list)
        report = engine.get_calendar_report()
        assert "total_events" in report

    def test_historical_store(self):
        """Historical store çalışıyor mu?"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            store = MacroHistoricalStore(f.name)

            store.save("2026-01-01", "USDTRY", 30.5, "test")
            store.save("2026-01-02", "USDTRY", 30.7, "test")

            value = store.get("2026-01-01", "USDTRY")
            assert value == 30.5

            latest = store.get_latest("USDTRY")
            assert latest["value"] == 30.7

            os.unlink(f.name)

    def test_factor_decomposition(self):
        """Factor decomposition çalışıyor mu?"""
        fd = MacroFactorDecomposition()

        result = fd.decompose(
            ticker="THYAO",
            sector="AVIATION",
            total_return=5.0,
            macro_changes={
                "usdtry": 0.10,
                "interest_rate": 0.05,
                "oil": 0.20,
            },
        )

        assert result.ticker == "THYAO"
        assert len(result.factor_contributions) == 7
        assert result.top_factor in fd.FACTORS

    def test_factor_features(self):
        """Factor feature'ları doğru mu?"""
        fd = MacroFactorDecomposition()

        features = fd.compute_factor_features(
            ticker="THYAO",
            sector="AVIATION",
            total_return=5.0,
            macro_changes={"usdtry": 0.10, "oil": 0.20},
        )

        assert "factor_usdtry_contribution" in features
        assert "factor_residual" in features
        assert "factor_explained_pct" in features


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
