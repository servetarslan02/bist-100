from typing import Any
"""Bölüm 25-32 — ML, Alternative, Macro, Factors, Event Study, VIOP Testleri."""

import numpy as np
import pytest


class TestMLModels:
    """Otomatik eklendi."""
    def test_xgboost_predict(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.xgboost_model import XGBoostModel

        m = XGBoostModel()
        X = np.random.rand(50, 5)
        preds = m.predict(X)  # Model yok → zeros
        assert len(preds) == 50

    def test_lstm_predict(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.lstm_model import StockLSTM

        m = StockLSTM(input_size=5)
        X = np.random.rand(10, 20, 5)
        preds = m.predict(X)
        assert len(preds) == 10

    def test_transformer_predict(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.transformer_model import StockTransformer

        m = StockTransformer(input_size=5)
        X = np.random.rand(10, 20, 5)
        preds = m.predict(X)
        assert len(preds) == 10

    def test_model_comparator(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.model_comparator import ModelComparator

        mc = ModelComparator()
        models = {"a": lambda X: np.random.rand(len(X)), "b": lambda X: np.full(len(X), 0.5)}
        X = np.random.rand(100, 5)
        y = np.random.randint(0, 2, 100)
        results = mc.compare(models, X, y)
        assert len(results) == 2
        assert results[0].name in ["a", "b"]

    def test_ensemble(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.ensemble import EnsembleModel

        em = EnsembleModel()
        models = {"a": lambda X: np.full(len(X), 0.6), "b": lambda X: np.full(len(X), 0.4)}
        weights = {"a": 0.7, "b": 0.3}
        X = np.random.rand(10, 5)
        preds = em.predict(models, weights, X)
        assert abs(preds[0] - 0.54) < 0.01  # 0.6*0.7 + 0.4*0.3

    def test_finrl_env(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.finrl_bist import BISTTradingEnv

        data = np.random.rand(100, 5) * 100
        env = BISTTradingEnv(data)
        state = env.reset()
        assert len(state) == 10
        state, reward, done, _ = env.step(0)
        assert isinstance(reward, (int, float))

    def test_fingpt_sentiment(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.fingpt import FinGPTSentiment

        fg = FinGPTSentiment()
        r = fg.analyze("Hisse yükseliş trendinde, güçlü büyüme")
        assert r["sentiment"] == "POSITIVE"
        r2 = fg.analyze("Düşüş devam ediyor, kriz büyüyor")
        assert r2["sentiment"] == "NEGATIVE"

    def test_hybrid_model(self) -> Any:
        """Otomatik eklendi."""
        from services.ml.hybrid_model import hybrid_predict

        r = hybrid_predict(1, 0.8)
        assert r["action"] == "BUY"


class TestAlternativeData:
    """Otomatik eklendi."""
    def test_web_features(self) -> Any:
        """Otomatik eklendi."""
        from services.alternative.web_scraping import compute_web_features

        f = compute_web_features({"job_posting_growth": 0.2}, "THYAO")
        assert "job_posting_growth" in f

    def test_social_features(self) -> Any:
        """Otomatik eklendi."""
        from services.alternative.social import compute_social_features

        f = compute_social_features({"sentiment": 0.7}, "THYAO")
        assert f["social_sentiment"] == 0.7

    def test_job_features(self) -> Any:
        """Otomatik eklendi."""
        from services.alternative.jobs import compute_job_features

        f = compute_job_features({"posting_growth": 0.15}, "THYAO")
        assert f["job_posting_growth"] == 0.15

    def test_cc_features(self) -> Any:
        """Otomatik eklendi."""
        from services.alternative.credit_card import compute_cc_features

        f = compute_cc_features({"spend_growth": 0.1}, "THYAO")
        assert f["cc_spend_growth"] == 0.1

    def test_satellite_features(self) -> Any:
        """Otomatik eklendi."""
        from services.alternative.satellite import compute_satellite_features

        f = compute_satellite_features({"factory_traffic": 0.05}, "THYAO")
        assert "factory_traffic_change" in f


class TestMacro:
    """Otomatik eklendi."""
    def test_tcmb(self) -> Any:
        """Otomatik eklendi."""
        from services.macro.tcmb import compute_tcmb_features

        f = compute_tcmb_features({"policy_rate": 45, "inflation": 60})
        assert f["real_rate"] == -15

    def test_inflation(self) -> Any:
        """Otomatik eklendi."""
        from services.macro.inflation import compute_inflation_features

        f = compute_inflation_features({"cpi_yoy": 60, "ppi_yoy": 40})
        assert f["ppi_cpi_spread"] == -20

    def test_fx(self) -> Any:
        """Otomatik eklendi."""
        from services.macro.fx import compute_fx_features

        f = compute_fx_features({"usdtry": 34, "usdtry_change": 0.02})
        assert f["usdtry"] == 34

    def test_cds(self) -> Any:
        """Otomatik eklendi."""
        from services.macro.cds import compute_cds_features

        f = compute_cds_features({"cds_5y": 300})
        assert f["risk_level"] == 0.5  # 200 < 300 < 400

    def test_calendar(self) -> Any:
        """Otomatik eklendi."""
        from services.macro.calendar import get_macro_events

        events = get_macro_events()
        assert len(events) > 0


class TestFactors:
    """Otomatik eklendi."""
    def test_piotroski(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score

        r = calculate_f_score({"net_income": 100, "operating_cf": 150, "roa": 0.1})
        assert "f_score" in r
        assert 0 <= r["f_score"] <= 9

    def test_beneish(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score

        r = calculate_m_score({"dsri": 1.0, "gmi": 1.0, "aqi": 1.0, "sgi": 1.0})
        assert "m_score" in r
        assert isinstance(r["m_score"], float)

    def test_altman(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score

        r = calculate_z_score(
            {
                "working_capital": 100,
                "total_assets": 1000,
                "retained_earnings": 200,
                "ebit": 150,
                "market_cap": 500,
                "total_debt": 300,
                "revenue": 800,
            }
        )
        assert "z_score" in r
        assert r["z_score"] > 0

    def test_fama_french(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.fama_french import calculate_factor_scores

        s = calculate_factor_scores(
            {"pb_ratio": 5, "mom_6m": 10, "roe": 15, "market_cap": 1e9, "volatility": 25},
            {"pb_median": 8, "mcap_median": 2e9, "vol_median": 20},
        )
        assert "value" in s
        assert "momentum" in s

    def test_ranking(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.ranking import rank_stocks

        stocks = [{"name": "A", "factors": {"value": 0.8}}, {"name": "B", "factors": {"value": 0.3}}]
        ranked = rank_stocks(stocks, {"value": 1.0})
        assert ranked[0]["name"] == "A"

    def test_performance(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.performance import track_factor_performance

        r = track_factor_performance([0.01, 0.02, -0.01], [0.005, 0.01, -0.005])
        assert "annual_return" in r
        assert "sharpe_ratio" in r


class TestEventStudy:
    """Otomatik eklendi."""
    def test_expected_return(self) -> Any:
        """Otomatik eklendi."""
        from services.event_study.expected_return import calculate_expected_return

        sr = np.random.randn(100) * 0.02
        mr = np.random.randn(100) * 0.015
        result = calculate_expected_return(sr, mr, model="market")
        assert "alpha" in result
        assert "beta_market" in result
        assert isinstance(result["alpha"], float)
        assert isinstance(result["beta_market"], float)

    def test_abnormal_return(self) -> Any:
        """Otomatik eklendi."""
        from services.event_study.abnormal_return import calculate_abnormal_return

        sr = np.array([0.05, -0.03, 0.02])
        mr = np.array([0.03, -0.02, 0.01])
        ar = calculate_abnormal_return(sr, mr, 0.0, 1.0)
        assert len(ar) == 3

    def test_car(self) -> Any:
        """Otomatik eklendi."""
        from services.event_study.car import calculate_car

        ar = np.array([0.01, 0.02, -0.005])
        car = calculate_car(ar)
        assert abs(car - 0.025) < 0.001

    def test_significance(self) -> Any:
        """Otomatik eklendi."""
        from services.event_study.statistical_test import test_significance

        ar = np.random.randn(100) * 0.02
        r = test_significance(0.05, ar)
        assert "t_statistic" in r
        assert "significant" in r

    def test_impact(self) -> Any:
        """Otomatik eklendi."""
        from services.event_study.impact import calculate_event_impact

        r = calculate_event_impact(0.05, 0.01, 0.3)
        assert r["impact_score"] > 0
        assert r["direction"] == "POSITIVE"


class TestVIOP:
    """Otomatik eklendi."""
    def test_black_scholes(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.options_pricing import black_scholes

        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.3)
        assert price > 0

    def test_greeks(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.greeks import calculate_greeks

        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.3)
        assert 0 <= g["delta"] <= 1
        assert g["gamma"] >= 0

    def test_covered_call(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.strategies import create_covered_call

        r = create_covered_call(100, 110, 3, 100)
        assert r["strategy"] == "COVERED_CALL"
        assert r["max_profit"] > 0

    def test_protective_put(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.strategies import create_protective_put

        r = create_protective_put(100, 90, 2, 100)
        assert r["strategy"] == "PROTECTIVE_PUT"

    def test_parity(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.parity import check_put_call_parity

        r = check_put_call_parity(5, 3, 100, 100, 0.15, 0.25)
        assert "parity_holds" in r

    def test_margin(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.margin import calculate_span_margin

        r = calculate_span_margin([{"value": 100000, "margin_rate": 0.15}])
        assert r["total_margin"] == 15000

    def test_hedging(self) -> Any:
        """Otomatik eklendi."""
        from services.viop.hedging import hedge_portfolio

        r = hedge_portfolio(1000000, 1.2, 1500)
        assert r["contracts_needed"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
