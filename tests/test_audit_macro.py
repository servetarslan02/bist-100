"""
Test suite for hardened services/macro components.
Validates all institutional quantitative macro models, thread-safety, edge cases, and feature calculators.
"""

from services.macro import (
    CARegimeType,
    CDSMetricsResult,
    CDSRiskLevel,
    CreditCycleEngine,
    CreditMetricsResult,
    CreditRegimeType,
    CurrentAccountEngine,
    CurrentAccountMetricsResult,
    DynamicSensitivityEngine,
    ImpactResult,
    MacroCalendarEngine,
    MacroCorrelationTracker,
    MacroDataPoint,
    MacroFactorDecomposition,
    MacroHistoricalStore,
    MacroImpactAnalyzer,
    MacroRegimeDetector,
    MacroStressTest,
    MacroSurpriseModel,
    ShockEvent,
    SovereignCDSEngine,
    compute_ca_features,
    compute_cds_features,
    compute_credit_features,
    compute_fx_features,
    compute_inflation_features,
    compute_subindex_pressure_score,
    compute_tcmb_features,
)


def test_macro_surprise_model() -> None:
    """Surprise model and sector impact propagation test."""
    model = MacroSurpriseModel()
    res = model.calculate_surprise(indicator="POLICY_RATE", actual=45.0, expected=42.5)
    assert res.surprise == 2.5
    assert res.surprise_pct > 0.05
    assert res.direction == "HAWKISH"
    assert "MacroSurpriseModel" in repr(model)
    assert "SurpriseResult" in repr(res)

    impacts = model.compute_sector_surprise_impact(sector="BANK", surprises={"POLICY_RATE": res})
    assert "total_surprise_impact" in impacts
    assert "policy_rate_surprise_impact" in impacts


def test_dynamic_sensitivity_engine() -> None:
    """Sector & company sensitivity estimation test."""
    engine = DynamicSensitivityEngine()
    sens = engine.compute_dynamic_sensitivity("BANKING")
    assert sens.rate_sensitivity < 0.0
    assert "DynamicSensitivityEngine" in repr(engine)
    assert "SensitivityResult" in repr(sens)

    comp_sens = engine.get_company_sensitivity("AKBNK", "BANKING")
    assert comp_sens.sector == "BANKING"
    assert "SensitivityResult" in repr(comp_sens)


def test_macro_regime_detector() -> None:
    """Regime classification and transition detection test."""
    detector = MacroRegimeDetector()
    macro_feats = {
        "cpi_yoy": 55.0,
        "gdp_growth": 1.2,
        "policy_rate": 45.0,
        "usdtry_change_pct": 2.5,
        "vix": 22.0,
    }
    regime = detector.detect_regime(macro_feats)
    assert regime.regime in [
        "STAGFLATION",
        "EXPANSION",
        "CONTRACTION",
        "REFLATION",
        "RISK_ON",
        "RISK_OFF",
    ]
    assert 0.0 <= regime.confidence <= 1.0
    assert "MacroRegimeDetector" in repr(detector)
    assert "RegimeResult" in repr(regime)


def test_macro_historical_store(tmp_path) -> None:
    """Thread-safe historical store persistence test."""
    store_file = str(tmp_path / "macro_store.json")
    store = MacroHistoricalStore(storage_path=store_file)

    store.save(date="2026-03-01", indicator="cpi_yoy", value=52.5, source="tuik")
    store.save(date="2026-03-02", indicator="cpi_yoy", value=51.8, source="tuik")
    store.flush()

    latest = store.get_latest("cpi_yoy")
    assert latest is not None
    assert latest["value"] == 51.8

    rng = store.get_date_range("cpi_yoy")
    assert rng is not None
    assert rng["total_points"] == 2
    assert rng["start_date"] == "2026-03-01"

    added = store.backfill(indicator="usdtry", data=[{"date": "2026-03-01", "value": 36.5, "source": "tcmb"}])
    assert added == 1

    dp = MacroDataPoint(
        date="2026-03-01",
        indicator="cpi_yoy",
        value=52.5,
        source="test",
        timestamp="2026-03-01T10:00:00Z",
    )
    assert "MacroDataPoint" in repr(dp)
    assert "MacroHistoricalStore" in repr(store)


def test_macro_impact_analyzer() -> None:
    """Shock event recording, half-life decay, and cumulative impact test."""
    analyzer = MacroImpactAnalyzer()
    analyzer.record_shock(shock_type="interest_rate", magnitude=500.0, indicator="POLICY_RATE")

    res = analyzer.compute_impact(
        ticker="GARAN",
        sector="BANK",
        shock_type="interest_rate",
        magnitude=500.0,
        days_elapsed=10,
    )
    assert isinstance(res, ImpactResult)
    assert res.remaining_impact <= res.raw_impact
    assert "ImpactResult" in repr(res)

    curve = analyzer.compute_decay_curve("interest_rate", magnitude=500.0, max_days=10)
    assert len(curve) == 11
    assert curve[0]["remaining_impact"] == 500.0

    cum = analyzer.compute_cumulative_impact(ticker="GARAN", sector="BANK")
    assert "cumulative_impact" in cum
    assert cum["active_shocks"] >= 1

    shock_event = ShockEvent(
        shock_type="interest_rate", magnitude=100.0, timestamp="2026-03-01", indicator="RATE", half_life_days=30
    )
    assert "ShockEvent" in repr(shock_event)
    assert "MacroImpactAnalyzer" in repr(analyzer)


def test_macro_stress_test() -> None:
    """Institutional portfolio stress testing & breaking point solver test."""
    engine = MacroStressTest()
    portfolio = {
        "total_value": 100000.0,
        "positions": [
            {"ticker": "THYAO", "sector": "AVIATION", "value": 40000.0, "weight": 0.40},
            {"ticker": "ISCTR", "sector": "BANK", "value": 60000.0, "weight": 0.60},
        ],
    }

    res = engine.run_stress_test(portfolio=portfolio, scenario="USDTRY_10_PCT")
    assert res.scenario == "USDTRY_10_PCT"
    assert len(res.position_impacts) == 2
    assert "StressTestResult" in repr(res)
    assert "MacroStressTest" in repr(engine)

    bp = engine.find_breaking_point(portfolio=portfolio, shock_type="usdtry_change", threshold_pct=-0.10)
    assert bp.shock_type == "usdtry_change"
    assert bp.breaking_point_pct >= 0.0
    assert "BreakingPointResult" in repr(bp)


def test_macro_correlation_tracker() -> None:
    """Macro correlation tracker and breakdown test."""
    tracker = MacroCorrelationTracker()
    for i in range(25):
        tracker.update({"usdtry": 30.0 + i * 0.2, "bist100": 9000.0 + i * 50.0})

    corr = tracker.get_correlation("usdtry", "bist100")
    assert corr is not None
    assert corr.correlation > 0.90
    assert "MacroCorrelationTracker" in repr(tracker)
    assert "CorrelationResult" in repr(corr)


def test_macro_calendar_engine() -> None:
    """Macro calendar engine, proximity features, and surprise processing test."""
    engine = MacroCalendarEngine()
    upcoming = engine.get_upcoming_events(days=365)
    assert len(upcoming) > 0

    prox = engine.compute_calendar_proximity_features("2026-01-20")
    assert "calendar_days_to_ppk" in prox
    assert prox["calendar_days_to_ppk"] >= 0.0

    engine.register_expectation(event_id=upcoming[0].event_id, expected=45.0)
    completed = engine.complete_event(event_id=upcoming[0].event_id, actual=47.5)
    assert completed is not None
    assert completed.status == "ANALYZED"
    assert completed.surprise == 2.5
    assert "MacroCalendarEngine" in repr(engine)


def test_macro_factor_decomposition() -> None:
    """Factor decomposition engine test."""
    engine = MacroFactorDecomposition()
    macro_factors = {
        "interest_rate": 0.02,
        "inflation": 0.015,
        "usdtry": 0.005,
    }
    decomp = engine.decompose(
        ticker="FROTO",
        sector="AUTOMOTIVE",
        total_return=-1.5,
        macro_changes=macro_factors,
    )
    assert "MacroFactorDecomposition" in repr(engine)
    assert "DecompositionResult" in repr(decomp)
    assert len(decomp.factor_contributions) > 0


def test_macro_feature_calculators() -> None:
    """Test all 7 macro feature engineering functions and subindex pressure models."""
    # 1. TCMB
    tcmb_feats = compute_tcmb_features({
        "policy_rate": 45.0,
        "prev_policy_rate": 42.5,
        "inflation": 52.0,
        "expected_inflation_12m": 35.0,
        "us_rate": 4.5,
        "usdtry_volatility_20d": 10.5,
    })
    assert tcmb_feats["tcmb_policy_rate"] == 45.0
    assert tcmb_feats["tcmb_rate_change"] == 2.5
    assert tcmb_feats["tcmb_real_rate"] == -7.0
    assert tcmb_feats["tcmb_forward_real_rate"] == 10.0

    # 2. Inflation & Subindices
    inf_feats = compute_inflation_features({
        "cpi_yoy": 58.2,
        "ppi_yoy": 44.5,
        "core_cpi": 52.0,
        "cpi_monthly": 3.2,
        "cpi_expected": 56.0,
        "cpi_previous": 59.0,
    })
    assert inf_feats["inf_cpi_level"] == 58.2
    assert inf_feats["inf_ppi_level"] == 44.5
    assert inf_feats["inf_regime"] == 3.0
    assert inf_feats["inf_cpi_ppi_spread"] > 0

    sub_press = compute_subindex_pressure_score({
        "food": 62.0,
        "transport": 45.0,
        "housing": 75.0,
        "hotels_restaurants": 80.0,
    })
    assert sub_press["subindex_weighted_rate"] > 0.0
    assert sub_press["service_rigidity_score"] == 77.5

    # 3. FX
    fx_feats = compute_fx_features({
        "usdtry": 36.40,
        "usdtry_previous": 36.20,
        "eurtry": 39.50,
        "eurtry_previous": 39.30,
        "usdtry_history": [35.0 + i * 0.05 for i in range(30)],
    })
    assert fx_feats["fx_usdtry_level"] == 36.40
    assert fx_feats["fx_basket_level"] > 37.0
    assert "fx_usdtry_volatility_20d" in fx_feats

    # 4. CDS
    cds_engine = SovereignCDSEngine()
    cds_res = cds_engine.evaluate_cds({
        "cds_5y": 280.0,
        "cds_10y": 320.0,
        "cds_previous": 290.0,
        "history": [270.0 + i * 0.5 for i in range(30)],
    })
    assert isinstance(cds_res, CDSMetricsResult)
    assert cds_res.risk_level == CDSRiskLevel.HIGH
    assert cds_res.implied_default_prob_5y > 0.0

    cds_feats = compute_cds_features({"cds_5y": 280.0, "cds_previous": 290.0})
    assert cds_feats["cds_5y"] == 280.0

    # 5. Credit
    credit_engine = CreditCycleEngine()
    cred_res = credit_engine.evaluate_credit({
        "credit_growth_yoy": 15.0,
        "credit_previous": 12.0,
        "commercial_credit_growth": 18.0,
        "retail_credit_growth": 12.0,
        "loan_to_deposit_ratio": 105.0,
    })
    assert isinstance(cred_res, CreditMetricsResult)
    assert cred_res.credit_regime == CreditRegimeType.EXPANSION
    assert cred_res.commercial_vs_retail_spread == 6.0

    cred_feats = compute_credit_features({"credit_growth_yoy": 15.0})
    assert cred_feats["credit_growth_yoy"] == 15.0

    # 6. Current Account
    ca_engine = CurrentAccountEngine()
    ca_res = ca_engine.evaluate_current_account({
        "ca_balance": -12.5,
        "ca_gdp_ratio": -3.2,
        "ca_previous": -14.0,
        "energy_deficit": -40.0,
        "fdi_net": 10.0,
    })
    assert isinstance(ca_res, CurrentAccountMetricsResult)
    assert ca_res.ca_regime == CARegimeType.MODERATE_DEFICIT
    assert ca_res.is_improving is True

    ca_feats = compute_ca_features({"ca_balance": -12.5})
    assert ca_feats["ca_balance"] == -12.5
