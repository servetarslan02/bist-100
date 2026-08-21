"""Event Study Nihai Sistem Testleri — 14 Modül, 50+ Test."""
import pytest
import numpy as np
from datetime import datetime, timedelta


# ─── Estimation Window Tests ───

class TestEstimationWindow:
    def test_default_window(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager()
        event_date = datetime(2025, 6, 15)
        start, end = mgr.get_window(event_date, "DEFAULT")
        assert (end - start).days >= 50
        assert end < event_date  # Look-ahead bias kontrolü

    def test_financial_results_window(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager()
        start, end = mgr.get_window(datetime(2025, 6, 15), "FINANCIAL_RESULTS")
        assert (end - start).days >= 100

    def test_gap_days(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager(gap_days=6)
        event_date = datetime(2025, 6, 15)
        _, end = mgr.get_window(event_date)
        assert (event_date - end).days >= 6

    def test_validate_data_sufficient(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager()
        returns = np.random.randn(100) * 0.02
        assert mgr.validate_data(returns, "DEFAULT") is True

    def test_validate_data_insufficient(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager()
        returns = np.random.randn(5) * 0.02
        assert mgr.validate_data(returns, "DEFAULT") is False

    def test_extract_window_data(self):
        from services.event_study.estimation_window import EstimationWindowManager
        mgr = EstimationWindowManager()
        returns = np.random.randn(200) * 0.02
        dates = np.array([datetime(2025, 1, 1) + timedelta(days=i) for i in range(200)])
        event_date = datetime(2025, 7, 1)
        wr, wd = mgr.extract_window_data(returns, dates, event_date, "DEFAULT")
        assert len(wr) > 0
        assert len(wd) == len(wr)


# ─── Event Window Tests ───

class TestEventWindow:
    def test_default_window(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        start, end = mgr.get_window("DEFAULT")
        assert start == -5
        assert end == 5

    def test_financial_results_window(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        start, end = mgr.get_window("FINANCIAL_RESULTS")
        assert start == -5
        assert end == 5

    def test_tcmb_window(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        start, end = mgr.get_window("TCMB_RATE")
        assert start == -1
        assert end == 3

    def test_window_size(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        assert mgr.get_window_size("FINANCIAL_RESULTS") == 11
        assert mgr.get_window_size("DIVIDEND") == 7

    def test_get_window_dates(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        event_date = datetime(2025, 6, 15)
        start, end = mgr.get_window_dates(event_date, "DIVIDEND")
        assert start < event_date
        assert end > event_date

    def test_align_to_event_day(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        returns = np.random.randn(20) * 0.02
        dates = np.array([datetime(2025, 6, 10) + timedelta(days=i) for i in range(20)])
        aligned = mgr.align_to_event_day(returns, dates, datetime(2025, 6, 15), "DIVIDEND")
        assert isinstance(aligned, dict)
        assert 0 in aligned  # Event günü

    def test_sub_windows(self):
        from services.event_study.event_window import EventWindowManager
        mgr = EventWindowManager()
        subs = mgr.get_sub_windows("DEFAULT")
        assert "pre" in subs
        assert "event" in subs
        assert "post" in subs
        assert "full" in subs


# ─── Expected Return Tests ───

class TestExpectedReturn:
    def test_market_model(self):
        from services.event_study.expected_return import calculate_expected_return
        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        result = calculate_expected_return(sr, mr, model="market")
        assert "alpha" in result
        assert "beta_market" in result
        assert "r_squared" in result
        assert result["model"] == "market"

    def test_fama_french_3(self):
        from services.event_study.expected_return import calculate_expected_return
        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        smb = np.random.randn(100) * 0.01
        hml = np.random.randn(100) * 0.01
        result = calculate_expected_return(sr, mr, model="fama_french_3", smb_returns=smb, hml_returns=hml)
        assert result["model"] == "fama_french_3"
        assert "beta_smb" in result
        assert "beta_hml" in result

    def test_insufficient_data(self):
        from services.event_study.expected_return import calculate_expected_return
        sr = np.random.randn(3) * 0.02
        mr = np.random.randn(3) * 0.015
        result = calculate_expected_return(sr, mr)
        assert result["alpha"] == 0.0
        assert result["beta_market"] == 1.0

    def test_predict_value(self):
        from services.event_study.expected_return import calculate_expected_return_value
        params = {"alpha": 0.001, "beta_market": 1.2, "beta_smb": 0.0, "beta_hml": 0.0, "beta_rmw": 0.0, "beta_cma": 0.0}
        er = calculate_expected_return_value(params, 0.02)
        assert abs(er - (0.001 + 1.2 * 0.02)) < 0.0001

    def test_backward_compat(self):
        from services.event_study.expected_return import calculate_expected_return_simple
        sr = np.random.randn(50) * 0.02
        mr = np.random.randn(50) * 0.015
        alpha, beta = calculate_expected_return_simple(sr, mr)
        assert isinstance(alpha, float)
        assert isinstance(beta, float)


# ─── Abnormal Return Tests ───

class TestAbnormalReturn:
    def test_basic_ar(self):
        from services.event_study.abnormal_return import calculate_abnormal_return
        sr = np.array([0.05, -0.03, 0.02])
        mr = np.array([0.03, -0.02, 0.01])
        ar = calculate_abnormal_return(sr, mr, 0.0, 1.0)
        assert len(ar) == 3
        assert abs(ar[0] - 0.02) < 0.001  # 0.05 - 0.03

    def test_with_alpha_beta(self):
        from services.event_study.abnormal_return import calculate_abnormal_return
        sr = np.array([0.05, -0.03, 0.02])
        mr = np.array([0.03, -0.02, 0.01])
        ar = calculate_abnormal_return(sr, mr, 0.01, 0.8)
        assert len(ar) == 3

    def test_batch(self):
        from services.event_study.abnormal_return import calculate_abnormal_return_batch
        stocks = {"A": np.random.randn(50) * 0.02, "B": np.random.randn(50) * 0.02}
        mr = np.random.randn(50) * 0.015
        params = {"A": {"alpha": 0.0, "beta_market": 1.0}, "B": {"alpha": 0.01, "beta_market": 0.9}}
        results = calculate_abnormal_return_batch(stocks, mr, params)
        assert len(results) == 2
        assert "A" in results


# ─── CAR Tests ───

class TestCAR:
    def test_basic_car(self):
        from services.event_study.car import calculate_car
        ar = np.array([0.01, 0.02, -0.005])
        car = calculate_car(ar)
        assert abs(car - 0.025) < 0.001

    def test_car_window(self):
        from services.event_study.car import calculate_car_window
        ar = np.array([0.01, 0.02, -0.005, 0.03, -0.01])
        offsets = np.array([-2, -1, 0, 1, 2])
        car = calculate_car_window(ar, offsets, -1, 1)
        assert abs(car - (0.02 + -0.005 + 0.03)) < 0.001

    def test_car_sub_windows(self):
        from services.event_study.car import calculate_car_sub_windows
        ar = np.array([0.01, 0.02, -0.005, 0.03, -0.01])
        offsets = np.array([-2, -1, 0, 1, 2])
        subs = calculate_car_sub_windows(ar, offsets)
        assert "pre_event" in subs
        assert "event_day" in subs
        assert "post_event" in subs
        assert "full" in subs

    def test_car_series(self):
        from services.event_study.car import calculate_car_series
        ar = np.array([0.01, 0.02, -0.005])
        series = calculate_car_series(ar)
        assert len(series) == 3
        assert abs(series[0] - 0.01) < 0.001
        assert abs(series[2] - 0.025) < 0.001

    def test_aar(self):
        from services.event_study.car import calculate_aar
        cars = {"A": 0.05, "B": -0.02, "C": 0.03}
        aar = calculate_aar(cars)
        assert abs(aar - 0.02) < 0.001


# ─── Statistical Test Tests ───

class TestStatisticalTest:
    def test_significance_basic(self):
        from services.event_study.statistical_test import test_significance
        ar = np.random.randn(100) * 0.02
        r = test_significance(0.05, ar)
        assert "t_statistic" in r
        assert "p_value" in r
        assert "significant" in r
        assert "confidence_lower" in r
        assert "confidence_upper" in r
        assert "df" in r

    def test_t_distribution(self):
        from services.event_study.statistical_test import test_significance
        # Büyük CAR, düşük volatilite → significant olmalı
        ar = np.random.randn(100) * 0.001
        r = test_significance(0.05, ar)
        assert r["significant"] is True

    def test_not_significant(self):
        from services.event_study.statistical_test import test_significance
        # Küçük CAR, yüksek volatilite → significant olmamalı
        ar = np.random.randn(100) * 0.10
        r = test_significance(0.001, ar)
        assert r["significant"] is False

    def test_cross_sectional(self):
        from services.event_study.statistical_test import test_significance_cross_sectional
        cars = [0.05, -0.02, 0.03, 0.01, -0.01, 0.04, 0.02, -0.03, 0.06, 0.01]
        r = test_significance_cross_sectional(cars)
        assert "t_statistic" in r
        assert "mean_car" in r
        assert r["n_events"] == 10

    def test_bonferroni(self):
        from services.event_study.statistical_test import bonferroni_correction
        p_values = [0.01, 0.03, 0.04, 0.06, 0.08]
        r = bonferroni_correction(p_values, alpha=0.05)
        assert r["n_tests"] == 5
        assert r["adjusted_alpha"] == 0.01
        # 0.01 == 0.01 → not strictly less → False
        assert r["significant_flags"][0] is False  # 0.01 == 0.01 (not <)
        assert r["significant_flags"][1] is False  # 0.03 > 0.01

    def test_benjamini_hochberg(self):
        from services.event_study.statistical_test import benjamini_hochberg_correction
        p_values = [0.001, 0.008, 0.039, 0.041, 0.060]
        r = benjamini_hochberg_correction(p_values, alpha=0.05)
        assert r["n_tests"] == 5
        assert len(r["significant_flags"]) == 5

    def test_wilcoxon(self):
        from services.event_study.statistical_test import wilcoxon_test
        cars = [0.05, -0.02, 0.03, 0.01, -0.01, 0.04, 0.02, -0.03, 0.06, 0.01]
        r = wilcoxon_test(cars)
        assert "statistic" in r
        assert "p_value" in r


# ─── Impact Tests ───

class TestImpact:
    def test_basic_impact(self):
        from services.event_study.impact import calculate_event_impact
        r = calculate_event_impact(0.05, 0.01, 0.3)
        assert r["impact_score"] > 0
        assert r["direction"] == "POSITIVE"
        assert r["significant"] is True

    def test_event_type_weights(self):
        from services.event_study.impact import calculate_event_impact
        r1 = calculate_event_impact(0.05, 0.01, 0.3, "FINANCIAL_RESULTS")
        r2 = calculate_event_impact(0.05, 0.01, 0.3, "MANAGEMENT_CHANGE")
        # FINANCIAL_RESULTS daha yüksek ağırlığa sahip
        assert r1["impact_score"] >= r2["impact_score"]

    def test_impact_levels(self):
        from services.event_study.impact import calculate_event_impact
        r_high = calculate_event_impact(0.15, 0.001, 0.8, "MERGER")
        r_low = calculate_event_impact(0.003, 0.50, 0.0, "DEFAULT")
        assert r_high["impact_level"] in ["HIGH", "VERY_HIGH"]
        assert r_low["impact_level"] in ["LOW", "MEDIUM"]

    def test_batch(self):
        from services.event_study.impact import calculate_impact_batch
        events = [
            {"car": 0.05, "p_value": 0.01, "volume_change": 0.3, "event_type": "FINANCIAL_RESULTS"},
            {"car": -0.02, "p_value": 0.15, "volume_change": 0.1, "event_type": "DIVIDEND"},
        ]
        r = calculate_impact_batch(events)
        assert r["summary"]["n_events"] == 2
        assert "mean_score" in r["summary"]


# ─── KAP Event Tests ───

class TestKAPEvent:
    def test_classify_financial(self):
        from services.event_study.kap_event import classify_kap_event
        r = classify_kap_event("2025 yılı 3. dönem konsolide finansal sonuçları")
        assert r["event_type"] == "FINANCIAL_RESULTS"
        assert r["confidence"] > 0

    def test_classify_dividend(self):
        from services.event_study.kap_event import classify_kap_event
        r = classify_kap_event("Nakit temettü dağıtımı kararı")
        assert r["event_type"] == "DIVIDEND"

    def test_classify_buyback(self):
        from services.event_study.kap_event import classify_kap_event
        r = classify_kap_event("Pay geri alım programı")
        assert r["event_type"] == "BUYBACK"

    def test_classify_unknown(self):
        from services.event_study.kap_event import classify_kap_event
        r = classify_kap_event("Genel bilgilendirme")
        assert r["event_type"] == "UNKNOWN"

    def test_analyze_kap_event(self):
        from services.event_study.kap_event import analyze_kap_event
        est_sr = np.random.randn(100) * 0.02
        est_mr = np.random.randn(100) * 0.015
        evt_sr = np.random.randn(11) * 0.02
        evt_mr = np.random.randn(11) * 0.015
        r = analyze_kap_event(
            ticker="THYAO",
            event_description="Finansal sonuçlar açıklandı",
            event_date=datetime(2025, 6, 15),
            estimation_stock_returns=est_sr,
            estimation_market_returns=est_mr,
            event_stock_returns=evt_sr,
            event_market_returns=evt_mr,
        )
        assert r["ticker"] == "THYAO"
        assert "car" in r
        assert "significance" in r
        assert "impact" in r

    def test_analyze_kap_event_simple(self):
        from services.event_study.kap_event import analyze_kap_event_simple
        sr = np.random.randn(50) * 0.02
        mr = np.random.randn(50) * 0.015
        r = analyze_kap_event_simple(
            ticker="THYAO",
            event_description="Finansal sonuçlar",
            event_date=datetime(2025, 6, 15),
            stock_returns=sr,
            market_returns=mr,
        )
        assert r["ticker"] == "THYAO"
        assert "car" in r


# ─── Macro Event Tests ───

class TestMacroEvent:
    def test_tcmb_hawkish(self):
        from services.event_study.macro_event import analyze_tcmb_event
        mr = np.array([0.01, -0.02, -0.015, 0.005])
        r = analyze_tcmb_event(45.0, 42.5, 42.5, mr)
        assert r["surprise"] == 2.5
        assert r["direction"] == "HAWKISH"

    def test_tcmb_dovish(self):
        from services.event_study.macro_event import analyze_tcmb_event
        mr = np.array([-0.01, 0.02, 0.015, -0.005])
        r = analyze_tcmb_event(40.0, 42.5, 42.5, mr)
        assert r["surprise"] == -2.5
        assert r["direction"] == "DOVISH"

    def test_tcmb_neutral(self):
        from services.event_study.macro_event import analyze_tcmb_event
        mr = np.array([0.001, -0.002, 0.001, 0.0])
        r = analyze_tcmb_event(42.5, 42.5, 42.5, mr)
        assert r["surprise"] == 0.0
        assert r["direction"] == "NEUTRAL"

    def test_macro_event_inflation(self):
        from services.event_study.macro_event import analyze_macro_event
        mr = np.array([0.01, -0.02, -0.015, 0.005])
        r = analyze_macro_event("INFLATION", 65.0, 60.0, 62.0, mr)
        assert r["event_type"] == "INFLATION"
        assert r["direction"] == "NEGATIVE_SURPRISE"  # Beklentiden yüksek kötü

    def test_macro_event_gdp(self):
        from services.event_study.macro_event import analyze_macro_event
        mr = np.array([0.01, 0.02, 0.015, 0.005])
        r = analyze_macro_event("GDP", 5.5, 4.5, 4.0, mr)
        assert r["direction"] == "POSITIVE_SURPRISE"

    def test_batch(self):
        from services.event_study.macro_event import analyze_macro_events_batch
        mr = np.random.randn(20) * 0.015
        events = [
            {"event_type": "INFLATION", "actual": 65.0, "expected": 60.0, "previous": 62.0},
            {"event_type": "GDP", "actual": 5.5, "expected": 4.5, "previous": 4.0},
        ]
        r = analyze_macro_events_batch(events, mr)
        assert r["summary"]["n_events"] == 2


# ─── Multi-Factor Tests ───

class TestMultiFactor:
    def test_fit_market(self):
        from services.event_study.multi_factor import MultiFactorModel
        model = MultiFactorModel("market")
        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        params = model.fit(sr, mr)
        assert params["model"] == "market"
        assert params["r_squared"] >= 0

    def test_fit_ff3(self):
        from services.event_study.multi_factor import MultiFactorModel
        model = MultiFactorModel("fama_french_3")
        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        smb = np.random.randn(100) * 0.01
        hml = np.random.randn(100) * 0.01
        params = model.fit(sr, mr, smb_returns=smb, hml_returns=hml)
        assert params["model"] == "fama_french_3"

    def test_predict(self):
        from services.event_study.multi_factor import MultiFactorModel
        model = MultiFactorModel("market")
        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        model.fit(sr, mr)
        er = model.predict(0.02)
        assert isinstance(er, float)

    def test_predict_without_fit(self):
        from services.event_study.multi_factor import MultiFactorModel
        model = MultiFactorModel("market")
        with pytest.raises(ValueError):
            model.predict(0.02)

    def test_factors(self):
        from services.event_study.multi_factor import FamaFrenchFactors
        smb = FamaFrenchFactors.calculate_smb(
            np.array([0.03, 0.02]),
            np.array([0.01, 0.01]),
        )
        assert abs(smb[0] - 0.02) < 0.001


# ─── Cross-Sectional Tests ───

class TestCrossSectional:
    def test_analyze(self):
        from services.event_study.cross_sectional import CrossSectionalEventStudy
        cs = CrossSectionalEventStudy()
        events = [
            {"ticker": "A", "event_type": "FIN", "sector": "BANKA", "car": 0.05, "p_value": 0.01},
            {"ticker": "B", "event_type": "FIN", "sector": "SANAYI", "car": -0.02, "p_value": 0.20},
            {"ticker": "C", "event_type": "DIV", "sector": "BANKA", "car": 0.03, "p_value": 0.04},
        ]
        r = cs.analyze(events)
        assert r["n_events"] == 3
        assert "average_car" in r
        assert "t_statistic" in r

    def test_analyze_by_type(self):
        from services.event_study.cross_sectional import CrossSectionalEventStudy
        cs = CrossSectionalEventStudy()
        events = [
            {"ticker": "A", "event_type": "FIN", "car": 0.05},
            {"ticker": "B", "event_type": "FIN", "car": -0.02},
            {"ticker": "C", "event_type": "DIV", "car": 0.03},
        ]
        r = cs.analyze_by_type(events)
        assert "FIN" in r
        assert "DIV" in r

    def test_regression(self):
        from services.event_study.cross_sectional import CrossSectionalEventStudy
        cs = CrossSectionalEventStudy()
        events = [
            {"car": 0.05, "volume": 1.5, "size": 100},
            {"car": -0.02, "volume": 0.8, "size": 50},
            {"car": 0.03, "volume": 1.2, "size": 80},
            {"car": 0.01, "volume": 0.5, "size": 30},
            {"car": -0.01, "volume": 0.9, "size": 60},
        ]
        r = cs.regression_analysis(events, ["volume", "size"])
        assert "coefficients" in r or "error" in r

    def test_empty(self):
        from services.event_study.cross_sectional import CrossSectionalEventStudy
        cs = CrossSectionalEventStudy()
        r = cs.analyze([])
        assert r["n_events"] == 0


# ─── Event Clustering Tests ───

class TestEventClustering:
    def test_detect_clusters(self):
        from services.event_study.event_clustering import EventClusteringDetector
        detector = EventClusteringDetector(window_days=3)
        events = [
            {"date": "2025-06-10", "ticker": "A", "event_type": "FIN", "car": 0.05},
            {"date": "2025-06-11", "ticker": "B", "event_type": "DIV", "car": 0.03},
            {"date": "2025-06-20", "ticker": "C", "event_type": "FIN", "car": -0.02},
        ]
        clusters = detector.detect_clusters(events)
        assert len(clusters) >= 1  # A ve B aynı cluster'da

    def test_no_clusters(self):
        from services.event_study.event_clustering import EventClusteringDetector
        detector = EventClusteringDetector(window_days=2)
        events = [
            {"date": "2025-06-10", "ticker": "A", "event_type": "FIN", "car": 0.05},
            {"date": "2025-06-20", "ticker": "B", "event_type": "DIV", "car": 0.03},
        ]
        clusters = detector.detect_clusters(events)
        assert len(clusters) == 0

    def test_cluster_statistics(self):
        from services.event_study.event_clustering import EventClusteringDetector
        detector = EventClusteringDetector()
        clusters = [
            {"events": [1, 2], "size": 2},
            {"events": [3, 4, 5], "size": 3},
        ]
        stats = detector.get_cluster_statistics(clusters)
        assert stats["n_clusters"] == 2
        assert stats["avg_size"] == 2.5

    def test_adjust_car(self):
        from services.event_study.event_clustering import EventClusteringDetector
        detector = EventClusteringDetector(window_days=3)
        events = [
            {"date": "2025-06-10", "ticker": "A", "event_type": "FIN", "car": 0.05},
            {"date": "2025-06-11", "ticker": "B", "event_type": "DIV", "car": 0.03},
        ]
        mr = np.random.randn(20) * 0.015
        dates = np.array([datetime(2025, 6, 1) + timedelta(days=i) for i in range(20)])
        adjusted = detector.adjust_car_for_clustering(events, mr, dates)
        assert len(adjusted) == 2


# ─── Event Decay Tests ───

class TestEventDecay:
    def test_decay_basic(self):
        from services.event_study.event_decay import EventImpactDecay
        decay = EventImpactDecay()
        ar = np.array([0.05, 0.035, 0.025, 0.018, 0.013, 0.01])
        r = decay.calculate_decay(ar)
        assert "decay_rate" in r
        assert "half_life_days" in r
        assert "pattern" in r
        assert r["decay_rate"] > 0

    def test_no_decay(self):
        from services.event_study.event_decay import EventImpactDecay
        decay = EventImpactDecay()
        ar = np.array([0.05, 0.05, 0.05, 0.05])
        r = decay.calculate_decay(ar)
        assert r["pattern"] == "PERSISTENT"

    def test_batch(self):
        from services.event_study.event_decay import EventImpactDecay
        decay = EventImpactDecay()
        ar_list = [
            np.array([0.05, 0.03, 0.02, 0.01]),
            np.array([0.04, 0.025, 0.015, 0.008]),
        ]
        r = decay.calculate_decay_batch(ar_list)
        assert r["n_events"] == 2
        assert "average_decay_rate" in r


# ─── Sector Event Tests ───

class TestSectorEvent:
    def test_sector_event(self):
        from services.event_study.sector_event import SectorEventAnalyzer
        analyzer = SectorEventAnalyzer()
        sr = np.random.randn(20) * 0.02
        mr = np.random.randn(20) * 0.015
        r = analyzer.analyze_sector_event("BANKA", "FINANCIAL_RESULTS", sr, mr)
        assert "sector" in r
        assert "stock_car" in r
        assert "outperformed_bist" in r

    def test_peer_comparison(self):
        from services.event_study.sector_event import SectorEventAnalyzer
        analyzer = SectorEventAnalyzer()
        peers = {
            "AKBNK": np.random.randn(20) * 0.02,
            "GARAN": np.random.randn(20) * 0.02,
            "ISCTR": np.random.randn(20) * 0.02,
        }
        mr = np.random.randn(20) * 0.015
        r = analyzer.analyze_peer_comparison("BANKA", "FINANCIAL_RESULTS", peers, mr, "GARAN")
        assert "peer_cars" in r
        assert "rankings" in r
        assert "target_analysis" in r

    def test_sector_rotation(self):
        from services.event_study.sector_event import SectorEventAnalyzer
        analyzer = SectorEventAnalyzer()
        sector_cars = {"BANKA": 0.05, "SANAYI": -0.03, "TEKNOLOJI": 0.02, "ENERJI": -0.05}
        r = analyzer.detect_sector_rotation(sector_cars)
        assert "inflow_sectors" in r
        assert "outflow_sectors" in r
        assert "rotation_signal" in r

    def test_get_sector_stocks(self):
        from services.event_study.sector_event import SectorEventAnalyzer
        analyzer = SectorEventAnalyzer()
        stocks = analyzer.get_sector_stocks("BANKA")
        assert "AKBNK" in stocks
        assert "GARAN" in stocks

    def test_get_stock_sector(self):
        from services.event_study.sector_event import SectorEventAnalyzer
        analyzer = SectorEventAnalyzer()
        sector = analyzer.get_stock_sector("THYAO")
        assert sector is not None


# ─── Integration Tests ───

class TestIntegration:
    def test_full_pipeline(self):
        """Tam pipeline: estimation → expected return → AR → CAR → test → impact."""
        from services.event_study.estimation_window import EstimationWindowManager
        from services.event_study.event_window import EventWindowManager
        from services.event_study.expected_return import calculate_expected_return
        from services.event_study.abnormal_return import calculate_abnormal_return
        from services.event_study.car import calculate_car, calculate_car_sub_windows
        from services.event_study.statistical_test import test_significance
        from services.event_study.impact import calculate_event_impact

        # Simüle veri
        est_returns = np.random.randn(100) * 0.02
        est_market = np.random.randn(100) * 0.015
        event_returns = np.random.randn(11) * 0.02
        event_market = np.random.randn(11) * 0.015

        # 1. Estimation window → params
        params = calculate_expected_return(est_returns, est_market, model="market")

        # 2. Event window → AR
        ar = calculate_abnormal_return(event_returns, event_market, params["alpha"], params["beta_market"])

        # 3. CAR
        car = calculate_car(ar)

        # 4. Statistical test
        significance = test_significance(car, ar)

        # 5. Impact
        impact = calculate_event_impact(car, significance["p_value"])

        assert isinstance(car, float)
        assert "t_statistic" in significance
        assert "impact_score" in impact

    def test_kap_to_cross_sectional(self):
        """KAP event → cross-sectional pipeline."""
        from services.event_study.kap_event import analyze_kap_event
        from services.event_study.cross_sectional import CrossSectionalEventStudy

        events = []
        for i in range(5):
            est_sr = np.random.randn(100) * 0.02
            est_mr = np.random.randn(100) * 0.015
            evt_sr = np.random.randn(11) * 0.02
            evt_mr = np.random.randn(11) * 0.015
            r = analyze_kap_event(
                ticker=f"STOCK{i}",
                event_description="Finansal sonuçlar",
                event_date=datetime(2025, 6, 15),
                estimation_stock_returns=est_sr,
                estimation_market_returns=est_mr,
                event_stock_returns=evt_sr,
                event_market_returns=evt_mr,
            )
            events.append(r)

        cs = CrossSectionalEventStudy()
        result = cs.analyze(events, group_by="event_type")
        assert result["n_events"] == 5
