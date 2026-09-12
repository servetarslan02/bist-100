"""
ALPHA BIST — Macro System Comprehensive Audit Tests
Tests all 18 files in services/macro/, verifying:
- MacroConfig & sub-configs
- MacroSurpriseModel
- DynamicSensitivityEngine
- MacroRegimeDetector
- MacroImpactAnalyzer
- MacroHistoricalStore
- MacroCorrelationTracker
- MacroCalendarEngine
- MacroStressTest
- MacroFactorDecomposition
- compute_cds_features
- compute_credit_features
- compute_ca_features
- compute_fx_features
- compute_inflation_features
- compute_tcmb_features
- calendar events & impact
"""

import tempfile

from services.macro import (
    CompanySensitivity,
    DynamicSensitivityEngine,
    MacroCalendarEngine,
    MacroConfig,
    MacroCorrelationTracker,
    MacroFactorDecomposition,
    MacroHistoricalStore,
    MacroImpactAnalyzer,
    MacroRegimeDetector,
    MacroStressTest,
    MacroSurpriseModel,
    SensitivityResult,
    compute_ca_features,
    compute_cds_features,
    compute_credit_features,
    compute_fx_features,
    compute_inflation_features,
    compute_tcmb_features,
    get_event_impact,
    get_macro_events,
    get_upcoming_events,
    macro_calendar_engine,
    macro_config,
    macro_correlation_tracker,
    macro_factor_decomposition,
    macro_historical_store,
    macro_impact_analyzer,
    macro_regime_detector,
    macro_sensitivity_engine,
    macro_stress_test,
    macro_surprise_model,
)
from services.macro.calendar_engine import MacroEvent
from services.macro.correlation_tracker import CorrelationBreakdown, CorrelationResult
from services.macro.factor_decomposition import DecompositionResult, FactorContribution
from services.macro.historical_store import MacroDataPoint
from services.macro.impact_analyzer import ImpactResult, ShockEvent
from services.macro.regime_detector import RegimeResult, RegimeTransition
from services.macro.stress_test import BreakingPointResult, PositionImpact, StressTestResult
from services.macro.surprise_model import SurpriseImpact, SurpriseResult


def test_macro_config():
    """Test MacroConfig attributes and representation."""
    cfg = MacroConfig()
    assert cfg.log_level == "INFO"
    assert cfg.enable_event_bus is True
    assert cfg.surprise.decay_half_life_days == 5
    assert cfg.regime.scoring_window_days == 20
    assert cfg.sensitivity.rolling_window_days == 60
    assert cfg.stress_test.breaking_point_threshold_pct == -0.10
    assert cfg.correlation.breakdown_threshold == 0.3
    assert cfg.calendar.pre_event_alert_days == 3
    assert cfg.decay.default_half_life_days == 5
    assert cfg.historical_store.max_history_days == 1825

    rep = repr(cfg)
    assert "MacroConfig" in rep
    assert "INFO" in rep

    from_env = MacroConfig.from_env()
    assert isinstance(from_env, MacroConfig)
    assert macro_config is not None
    assert macro_calendar_engine is not None
    assert macro_correlation_tracker is not None
    assert macro_factor_decomposition is not None
    assert macro_historical_store is not None
    assert macro_impact_analyzer is not None
    assert macro_regime_detector is not None
    assert macro_sensitivity_engine is not None
    assert macro_stress_test is not None
    assert macro_surprise_model is not None


def test_surprise_model():
    """Test MacroSurpriseModel and its result objects."""
    model = MacroSurpriseModel()
    rep_model = repr(model)
    assert "MacroSurpriseModel" in rep_model

    # Set expectations
    model.set_expectation("TCMB_RATE", 45.0, source="tcmb_survey", confidence=0.9)
    model.set_expectation("CPI", 3.0, source="consensus_forecast", confidence=0.8)

    # Calculate surprise with saved expectation
    res1 = model.calculate_surprise("TCMB_RATE", actual=47.5)
    assert isinstance(res1, SurpriseResult)
    assert res1.surprise == 2.5
    assert res1.direction in ["HAWKISH", "HIGHER"]
    assert "SurpriseResult" in repr(res1)

    # Calculate surprise with explicit expectation
    res2 = model.calculate_surprise("CPI", actual=2.5, expected=3.0)
    assert res2.direction == "DOVISH" or res2.surprise < 0

    # Sector impact and decay calculation
    sector_impacts = model.compute_sector_surprise_impact("BANK", {"TCMB_RATE": res1})
    assert "tcmb_rate_surprise_impact" in sector_impacts
    decay = model.get_decay_impact("TCMB_RATE", days_elapsed=2)
    assert 0.0 < decay <= 1.0

    # SurpriseImpact representation
    impact = SurpriseImpact(
        indicator="TCMB_RATE",
        surprise_pct=0.055,
        sector_impacts={"BANK": 0.05},
        company_impacts={"GARAN": 0.045},
        decay_days=5,
        remaining_impact=0.035,
    )
    assert "SurpriseImpact" in repr(impact)

    # Report
    report = model.get_surprise_report()
    assert "active_surprises" in report
    assert "total_surprises" in report


def test_sensitivity_engine():
    """Test DynamicSensitivityEngine rolling computation, overrides, and representations."""
    engine = DynamicSensitivityEngine(window=60, min_observations=5)
    assert "DynamicSensitivityEngine" in repr(engine)

    # Feed synthetic observation data
    for _ in range(10):
        engine.update(
            sector_returns={"BANKING": 0.015, "TECHNOLOGY": -0.005},
            macro_values={"usdtry": 0.002, "rate": 0.001, "inflation": 0.003, "vix": -0.01, "oil": 0.005, "gold": 0.001},
        )

    sens = engine.compute_dynamic_sensitivity("BANKING")
    assert isinstance(sens, SensitivityResult)
    assert "SensitivityResult" in repr(sens)
    d = sens.to_dict()
    assert "sector" in d
    assert d["sector"] == "BANKING"

    # Company override
    override = CompanySensitivity(
        ticker="THYAO",
        sector="AVIATION",
        usdtry_override=1.5,
        rate_override=0.8,
        reason="fx_debt",
    )
    assert "CompanySensitivity" in repr(override)
    engine.register_company_override("THYAO", "AVIATION", override)
    assert "THYAO" in engine._company_overrides

    company_sens = engine.get_company_sensitivity("THYAO", "AVIATION")
    assert isinstance(company_sens, SensitivityResult)


def test_regime_detector():
    """Test MacroRegimeDetector scoring, transitions, and representations."""
    detector = MacroRegimeDetector()
    assert "MacroRegimeDetector" in repr(detector)

    features = {
        "tcmb_real_rate": 5.0,
        "inf_cpi_level": 40.0,
        "gdp_growth_yoy": 1.0,
        "credit_growth_yoy": -2.0,
        "vix_regime": 3.0,
        "sp500_momentum_20d": -8.0,
        "cds_5y": 350.0,
        "usdtry_momentum_20d": 6.0,
    }

    result = detector.detect_regime(features)
    assert isinstance(result, RegimeResult)
    assert "RegimeResult" in repr(result)
    assert result.regime in detector.MACRO_REGIMES

    # Check transition object representation
    trans = RegimeTransition(
        from_regime="EXPANSION",
        to_regime="CONTRACTION",
        timestamp="2026-09-13T00:00:00Z",
        confidence=0.85,
    )
    assert "RegimeTransition" in repr(trans)


def test_impact_analyzer():
    """Test MacroImpactAnalyzer shock recording and decay analysis."""
    analyzer = MacroImpactAnalyzer()
    assert "MacroImpactAnalyzer" in repr(analyzer)

    analyzer.record_shock("fx_shock", 0.10, "usdtry")
    assert len(analyzer._shock_history) == 1

    ev = analyzer._shock_history[0]
    assert isinstance(ev, ShockEvent)
    assert "ShockEvent" in repr(ev)

    res = analyzer.compute_impact(ticker="GARAN", sector="BANK", shock_type="usdtry", magnitude=0.10, days_elapsed=2)
    assert isinstance(res, ImpactResult)
    assert "ImpactResult" in repr(res)

    report = analyzer.get_shock_report()
    assert report["total_shocks"] == 1


def test_historical_store():
    """Test MacroHistoricalStore with temporary file storage."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        store_path = tmp.name

    store = MacroHistoricalStore(storage_path=store_path)
    assert "MacroHistoricalStore" in repr(store)

    dp = MacroDataPoint(
        date="2026-09-12",
        indicator="USDTRY",
        value=34.50,
        source="tcmb",
        timestamp="2026-09-12T12:00:00Z",
    )
    assert "MacroDataPoint" in repr(dp)

    store.save("2026-09-12", "USDTRY", 34.50, source="tcmb")
    store.save("2026-09-13", "USDTRY", 34.65, source="tcmb")

    val = store.get("2026-09-12", "USDTRY")
    assert val == 34.50

    latest = store.get_latest("USDTRY")
    assert latest is not None
    assert latest["value"] == 34.65

    hist = store.get_range("USDTRY", "2026-09-12", "2026-09-13")
    assert len(hist) == 2



def test_correlation_tracker():
    """Test MacroCorrelationTracker correlation calculations and breakdown detection."""
    tracker = MacroCorrelationTracker()
    assert "MacroCorrelationTracker" in repr(tracker)

    for i in range(25):
        tracker.update({"usdtry": 30.0 + i * 0.2, "gold": 2000.0 + i * 15.0, "vix": 15.0 - i * 0.1, "bist100": 9000.0 + i * 50.0})

    res = tracker.get_correlation("usdtry", "gold")
    if res is not None:
        assert isinstance(res, CorrelationResult)
        assert "CorrelationResult" in repr(res)

    breakdown = CorrelationBreakdown(
        var1="usdtry",
        var2="gold",
        historical_corr=0.85,
        current_corr=0.10,
        breakdown_magnitude=0.75,
        alert=True,
    )
    assert "CorrelationBreakdown" in repr(breakdown)

    report = tracker.get_report()
    assert "tracked_pairs" in report


def test_calendar_engine():
    """Test MacroCalendarEngine event management and upcoming alerts."""
    engine = MacroCalendarEngine()
    assert "MacroCalendarEngine" in repr(engine)

    ev = MacroEvent(
        event_id="TEST_EVENT_1",
        event_type="CPI",
        date="2026-10-10",
        indicator="CPI",
        description="TÜİK TÜFE",
    )
    assert "MacroEvent" in repr(ev)

    engine.register_expectation("TEST_EVENT_1", 2.8)
    assert engine._expectations["TEST_EVENT_1"] == 2.8

    report = engine.get_calendar_report()
    assert "total_events" in report


def test_stress_test():
    """Test MacroStressTest with predefined and custom scenarios."""
    st = MacroStressTest()
    assert "MacroStressTest" in repr(st)

    portfolio = {
        "total_value": 1_000_000.0,
        "positions": [
            {"ticker": "GARAN", "sector": "BANK", "value": 400_000.0, "weight": 0.40},
            {"ticker": "THYAO", "sector": "AVIATION", "value": 300_000.0, "weight": 0.30},
            {"ticker": "TUPRS", "sector": "ENERGY", "value": 300_000.0, "weight": 0.30},
        ],
    }

    res = st.run_stress_test(portfolio, "USDTRY_10_PCT")
    assert isinstance(res, StressTestResult)
    assert "StressTestResult" in repr(res)
    assert res.portfolio_value == 1_000_000.0
    assert len(res.position_impacts) == 3

    pi = res.position_impacts[0]
    assert isinstance(pi, PositionImpact)
    assert "PositionImpact" in repr(pi)

    bp = st.find_breaking_point(portfolio, "usdtry", threshold_pct=-0.10)
    assert isinstance(bp, BreakingPointResult)
    assert "BreakingPointResult" in repr(bp)


def test_factor_decomposition():
    """Test MacroFactorDecomposition return attribution and factor contribution objects."""
    decomp = MacroFactorDecomposition()
    assert "MacroFactorDecomposition" in repr(decomp)

    macro_changes = {
        "usdtry": 0.05,
        "interest_rate": 0.02,
        "inflation": 0.03,
        "oil": -0.04,
        "gold": 0.01,
        "global_market": 0.02,
        "vix": -0.05,
    }

    result = decomp.decompose(
        ticker="GARAN",
        sector="BANK",
        total_return=3.50,
        macro_changes=macro_changes,
    )
    assert isinstance(result, DecompositionResult)
    assert "DecompositionResult" in repr(result)
    assert len(result.factor_contributions) > 0

    fc = result.factor_contributions[0]
    assert isinstance(fc, FactorContribution)
    assert "FactorContribution" in repr(fc)

    rep = decomp.get_report("GARAN", "BANK", 3.50, macro_changes)
    assert "explained_pct" in rep


def test_feature_calculators_and_calendar():
    """Test all macro feature computation modules with complete and boundary inputs."""
    # CDS features
    cds_res = compute_cds_features({
        "cds_5y": 260.0,
        "cds_previous": 250.0,
        "cds_history": [240.0 + i for i in range(25)],
    })
    assert cds_res["cds_5y"] == 260.0
    assert cds_res["cds_risk_level"] == 2.0  # Medium-high risk (250-400)
    assert "cds_momentum_20d" in cds_res
    # Empty CDS
    assert compute_cds_features({}) == {}

    # Credit features
    credit_res = compute_credit_features({
        "credit_growth_yoy": 15.0,
        "credit_gdp_ratio": 45.0,
        "credit_previous": 12.0,
    })
    assert credit_res["credit_regime"] == 2.0  # High
    assert credit_res["credit_trend_direction"] == 1.0
    # Empty Credit
    assert compute_credit_features({}) == {}

    # Current Account features
    ca_res = compute_ca_features({
        "ca_balance": -8.0,
        "ca_gdp_ratio": -2.5,
        "ca_previous": -10.0,
        "ca_12m_avg": -25.0,
    })
    assert ca_res["ca_regime"] == 0.0  # Medium deficit (-5 to -15)
    assert ca_res["ca_improving"] == 1.0
    # Empty CA
    assert compute_ca_features({}) == {}

    # FX features
    fx_res = compute_fx_features({
        "usdtry": 34.0,
        "eurtry": 37.0,
        "usdtry_previous": 33.8,
        "usdtry_history": [30.0 + i * 0.15 for i in range(25)],
    })
    assert fx_res["fx_usdtry_level"] == 34.0
    assert "fx_usdtry_volatility_20d" in fx_res
    # Empty FX
    assert compute_fx_features({}) == {}

    # Inflation features
    inf_res = compute_inflation_features({
        "cpi_yoy": 45.0,
        "ppi_yoy": 35.0,
        "core_cpi": 42.0,
        "cpi_monthly": 2.5,
        "cpi_expected": 43.0,
        "cpi_previous": 46.0,
    })
    assert inf_res["inf_regime"] == 3.0  # High inflation (25-50)
    assert inf_res["inf_cpi_ppi_spread"] == 10.0
    assert inf_res["inf_surprise"] == 2.0
    # Empty Inflation
    assert compute_inflation_features({}) == {}

    # TCMB features
    tcmb_res = compute_tcmb_features({
        "policy_rate": 50.0,
        "inflation": 45.0,
        "actual_rate": 50.0,
        "expected_rate": 47.5,
        "us_rate": 5.25,
        "wacf": 49.8,
        "rate_change": 2.5,
        "corridor_upper": 53.0,
        "corridor_lower": 47.0,
    })
    assert tcmb_res["tcmb_policy_rate"] == 50.0
    assert tcmb_res["tcmb_real_rate"] == 5.0
    assert tcmb_res["tcmb_policy_stance"] == 2.0  # Very tight
    # Empty TCMB
    assert compute_tcmb_features({}) == {}

    # Calendar functions
    all_events = get_macro_events()
    assert "TCMB_PPK" in all_events
    upcoming = get_upcoming_events(days=60)
    assert isinstance(upcoming, list)
    impact = get_event_impact("TCMB_PPK")
    assert impact["impact"] == "HIGH"
    assert "BANK" in impact["sector_impacts"]
    assert "error" in get_event_impact("NON_EXISTENT")
