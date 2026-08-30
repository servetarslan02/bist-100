from typing import Any

"""Factors Nihai Sistem Testleri — 10 Modül, 60+ Test."""

import numpy as np

# ─── Piotroski F-Score Tests ───


class TestPiotroski:
    """Otomatik eklendi."""
    def test_strong_score(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score

        fin = {
            "net_income": 100,
            "operating_cf": 150,
            "roa": 0.12,
            "leverage": 0.3,
            "current_ratio": 2.0,
            "shares_outstanding": 1000,
            "gross_margin": 0.45,
            "asset_turnover": 1.5,
        }
        prev = {
            "roa": 0.08,
            "leverage": 0.5,
            "current_ratio": 1.5,
            "shares_outstanding": 1000,
            "gross_margin": 0.40,
            "asset_turnover": 1.2,
        }
        r = calculate_f_score(fin, prev)
        assert r["f_score"] >= 7
        assert r["category"] == "STRONG"
        assert r["signal"] == "BUY"

    def test_weak_score(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score

        fin = {
            "net_income": -50,
            "operating_cf": -20,
            "roa": 0.02,
            "leverage": 0.8,
            "current_ratio": 0.8,
            "shares_outstanding": 1200,
            "gross_margin": 0.20,
            "asset_turnover": 0.5,
        }
        prev = {
            "roa": 0.05,
            "leverage": 0.6,
            "current_ratio": 1.2,
            "shares_outstanding": 1000,
            "gross_margin": 0.30,
            "asset_turnover": 0.8,
        }
        r = calculate_f_score(fin, prev)
        assert r["f_score"] <= 3
        assert r["category"] == "WEAK"

    def test_backward_compat(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score_simple

        s = calculate_f_score_simple({"net_income": 100, "operating_cf": 150})
        assert 0 <= s <= 9

    def test_sub_scores(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score

        r = calculate_f_score({"net_income": 100, "operating_cf": 150})
        assert "sub_scores" in r
        assert "profitability" in r["sub_scores"]

    def test_custom_weights(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.piotroski import calculate_f_score

        weights = {
            "net_income_positive": 2.0,
            "operating_cf_positive": 2.0,
            "roa_increasing": 1.0,
            "cf_gt_ni": 1.0,
            "leverage_decreasing": 1.0,
            "current_ratio_increasing": 1.0,
            "no_dilution": 1.0,
            "gross_margin_increasing": 1.0,
            "asset_turnover_increasing": 1.0,
        }
        r = calculate_f_score({"net_income": 100, "operating_cf": 150}, weights=weights)
        assert r["f_score"] >= 0


# ─── Beneish M-Score Tests ───


class TestBeneish:
    """Otomatik eklendi."""
    def test_with_raw_indices(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score

        r = calculate_m_score(
            {"dsri": 1.0, "gmi": 1.0, "aqi": 1.0, "sgi": 1.0, "depi": 1.0, "sgai": 1.0, "lvgi": 1.0, "tata": 0.0}
        )
        assert "m_score" in r
        assert "category" in r
        assert r["manipulation_likely"] is False  # M-Score < -1.78

    def test_manipulation_detected(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score

        r = calculate_m_score(
            {"dsri": 2.0, "gmi": 1.5, "aqi": 1.5, "sgi": 2.0, "depi": 1.2, "sgai": 1.3, "lvgi": 1.5, "tata": 0.1}
        )
        assert r["m_score"] > -1.78
        assert r["manipulation_likely"] is True
        assert r["category"] == "HIGH_RISK"

    def test_with_real_data(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score

        current = {
            "receivables": 500,
            "revenue": 2000,
            "gross_margin": 0.40,
            "current_assets": 1000,
            "ppe": 500,
            "total_assets": 3000,
            "depreciation": 100,
            "sga": 300,
            "total_debt": 1500,
            "net_income": 200,
            "operating_cf": 300,
        }
        previous = {
            "receivables": 400,
            "revenue": 1800,
            "gross_margin": 0.38,
            "current_assets": 900,
            "ppe": 550,
            "total_assets": 2800,
            "depreciation": 90,
            "sga": 280,
            "total_debt": 1400,
            "net_income": 180,
            "operating_cf": 250,
        }
        r = calculate_m_score(current, previous)
        assert "m_score" in r
        assert "components" in r
        assert len(r["components"]) == 8

    def test_backward_compat(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score_simple

        m = calculate_m_score_simple({"dsri": 1.0, "gmi": 1.0})
        assert isinstance(m, float)

    def test_risk_score(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.beneish import calculate_m_score

        r = calculate_m_score(
            {"dsri": 1.0, "gmi": 1.0, "aqi": 1.0, "sgi": 1.0, "depi": 1.0, "sgai": 1.0, "lvgi": 1.0, "tata": 0.0}
        )
        assert "risk_score" in r


# ─── Altman Z-Score Tests ───


class TestAltman:
    """Otomatik eklendi."""
    def test_safe_zone(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score

        fin = {
            "working_capital": 500,
            "total_assets": 2000,
            "retained_earnings": 800,
            "ebit": 400,
            "market_cap": 3000,
            "total_debt": 500,
            "revenue": 1500,
        }
        r = calculate_z_score(fin, turkey_adjusted=False)
        assert r["z_score"] > 2.99
        assert r["zone"] == "SAFE"

    def test_distress_zone(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score

        fin = {
            "working_capital": -500,
            "total_assets": 2000,
            "retained_earnings": -200,
            "ebit": 50,
            "market_cap": 200,
            "total_debt": 2000,
            "revenue": 300,
        }
        r = calculate_z_score(fin, turkey_adjusted=False)
        assert r["zone"] == "DISTRESS"

    def test_turkey_adjustment(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score

        fin = {
            "working_capital": 500,
            "total_assets": 2000,
            "retained_earnings": 800,
            "ebit": 400,
            "market_cap": 3000,
            "total_debt": 500,
            "revenue": 1500,
        }
        r_orig = calculate_z_score(fin, turkey_adjusted=False)
        r_turk = calculate_z_score(fin, sector="BANKA", turkey_adjusted=True)
        assert r_turk["z_score"] != r_orig["z_score"]
        assert r_turk["adjustments"]["sector"] == 1.10

    def test_backward_compat(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score_simple

        z = calculate_z_score_simple(
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
        assert isinstance(z, float)

    def test_signal(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.altman import calculate_z_score

        fin = {
            "working_capital": 500,
            "total_assets": 2000,
            "retained_earnings": 800,
            "ebit": 400,
            "market_cap": 3000,
            "total_debt": 500,
            "revenue": 1500,
        }
        r = calculate_z_score(fin)
        assert "signal" in r


# ─── Fama-French Tests ───


class TestFamaFrench:
    """Otomatik eklendi."""
    def test_factor_scores(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.fama_french import calculate_factor_scores

        stock = {"pb_ratio": 5, "mom_6m": 10, "roe": 15, "market_cap": 1e9, "volatility": 25}
        stats = {
            "pb_ratio_median": 8,
            "pb_ratio_std": 3,
            "mom_6m_median": 5,
            "mom_6m_std": 10,
            "roe_median": 12,
            "roe_std": 5,
            "market_cap_median": 2e9,
            "market_cap_std": 1e9,
            "volatility_median": 20,
            "volatility_std": 10,
        }
        s = calculate_factor_scores(stock, stats)
        assert "value" in s
        assert "momentum" in s
        assert "quality" in s

    def test_batch(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.fama_french import calculate_factor_scores_batch

        universe = [
            {"ticker": "A", "pb_ratio": 5, "roe": 15, "market_cap": 1e9},
            {"ticker": "B", "pb_ratio": 10, "roe": 20, "market_cap": 2e9},
            {"ticker": "C", "pb_ratio": 3, "roe": 10, "market_cap": 5e8},
        ]
        r = calculate_factor_scores_batch(universe)
        assert len(r) == 3
        assert "factor_scores" in r[0]

    def test_factor_weights(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.fama_french import get_factor_weights

        w = get_factor_weights("BULL")
        assert w["momentum"] > w["low_vol"]

    def test_factor_definitions(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.fama_french import FACTOR_DEFINITIONS

        assert len(FACTOR_DEFINITIONS) >= 7


# ─── BIST Anomalies Tests ───


class TestBISTAnomalies:
    """Otomatik eklendi."""
    def test_anomalies(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.bist_anomalies import calculate_bist_anomalies

        stock = {
            "dividend_yield": 5,
            "avg_volume": 5_000_000,
            "usdtry_beta": 0.8,
            "sector_momentum": 3,
            "foreign_ownership": 20,
        }
        r = calculate_bist_anomalies(stock)
        assert "dividend_yield" in r
        assert "liquidity_premium" in r
        assert "fx_sensitivity" in r

    def test_anomaly_score(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.bist_anomalies import calculate_anomaly_score

        anomalies = {"dividend_yield": 0.5, "liquidity_premium": 0.3, "fx_sensitivity": 0.2}
        score = calculate_anomaly_score(anomalies)
        assert 0 <= score <= 100

    def test_batch(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.bist_anomalies import calculate_bist_anomalies_batch

        universe = [{"ticker": "A", "dividend_yield": 5}, {"ticker": "B", "avg_volume": 1_000_000}]
        r = calculate_bist_anomalies_batch(universe)
        assert "bist_anomalies" in r[0]
        assert "anomaly_score" in r[0]


# ─── Ranking Tests ───


class TestRanking:
    """Otomatik eklendi."""
    def test_rank_stocks(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.ranking import rank_stocks

        stocks = [
            {"name": "A", "factors": {"value": 0.8, "momentum": 0.7}, "risk_score": 80},
            {"name": "B", "factors": {"value": 0.3, "momentum": 0.4}, "risk_score": 60},
            {"name": "C", "factors": {"value": 0.6, "momentum": 0.9}, "risk_score": 90},
        ]
        ranked = rank_stocks(stocks)
        assert ranked[0]["rank"] == 1
        assert "factor_score" in ranked[0]
        assert "risk_adjusted_score" in ranked[0]

    def test_regime_weights(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.ranking import rank_stocks

        stocks = [{"name": "A", "factors": {"momentum": 0.9, "quality": 0.5}, "risk_score": 80}]
        r_bull = rank_stocks([dict(stocks[0])], regime="BULL")
        r_bear = rank_stocks([dict(stocks[0])], regime="BEAR")
        assert r_bull[0]["factor_score"] != r_bear[0]["factor_score"]

    def test_sector_neutral(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.ranking import rank_stocks

        stocks = [
            {"name": "A", "sector": "BANKA", "factors": {"value": 0.8}, "risk_score": 80},
            {"name": "B", "sector": "BANKA", "factors": {"value": 0.6}, "risk_score": 70},
            {"name": "C", "sector": "SANAYI", "factors": {"value": 0.7}, "risk_score": 75},
        ]
        ranked = rank_stocks(stocks, sector_neutral=True)
        assert len(ranked) == 3

    def test_top_bottom(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.ranking import get_bottom_n, get_top_n, rank_stocks

        stocks = [{"name": f"S{i}", "factors": {"value": i / 10}, "risk_score": 50} for i in range(10)]
        ranked = rank_stocks(stocks)
        assert len(get_top_n(ranked, 3)) == 3
        assert len(get_bottom_n(ranked, 3)) == 3


# ─── Performance Tests ───


class TestPerformance:
    """Otomatik eklendi."""
    def test_basic_performance(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.performance import track_factor_performance

        r = track_factor_performance([0.01, 0.02, -0.01, 0.015, -0.005])
        assert "total_return" in r
        assert "sharpe_ratio" in r
        assert "max_drawdown" in r
        assert "win_rate" in r

    def test_with_benchmark(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.performance import track_factor_performance

        f = [0.01, 0.02, -0.01, 0.015, -0.005]
        b = [0.005, 0.01, -0.005, 0.008, -0.003]
        r = track_factor_performance(f, b)
        assert "alpha" in r
        assert "beta" in r
        assert "information_ratio" in r

    def test_batch(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.performance import track_factor_performance_batch

        factors = {"value": [0.01, 0.02, -0.01], "momentum": [0.02, 0.03, -0.02]}
        r = track_factor_performance_batch(factors)
        assert len(r) == 2
        assert "value" in r

    def test_edge_cases(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.performance import track_factor_performance

        r = track_factor_performance([])
        assert "error" in r
        r2 = track_factor_performance([0.01])
        assert "error" in r2


# ─── Factor Correlation Tests ───


class TestFactorCorrelation:
    """Otomatik eklendi."""
    def test_correlation(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_correlation import calculate_factor_correlation

        factors = {
            "value": [0.01, -0.02, 0.03, -0.01, 0.02],
            "momentum": [0.02, -0.01, 0.025, -0.015, 0.018],
            "quality": [0.015, -0.015, 0.02, -0.008, 0.012],
        }
        r = calculate_factor_correlation(factors)
        assert "correlation_matrix" in r
        assert "diversification_score" in r
        assert "avg_correlation" in r

    def test_rolling_correlation(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_correlation import calculate_rolling_correlation

        f1 = list(np.random.randn(100) * 0.02)
        f2 = list(np.random.randn(100) * 0.02)
        r = calculate_rolling_correlation(f1, f2, window=20)
        assert len(r) > 0

    def test_insufficient_factors(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_correlation import calculate_factor_correlation

        r = calculate_factor_correlation({"value": [0.01, 0.02]})
        assert "error" in r


# ─── Factor Rotation Tests ───


class TestFactorRotation:
    """Otomatik eklendi."""
    def test_detect_regime(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_rotation import detect_regime

        # Bear market
        returns = [-0.02] * 60 + [-0.01] * 20
        r = detect_regime(returns)
        assert r["regime"] in ["BEAR", "HIGH_VOL", "NORMAL"]

    def test_rotation_weights(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_rotation import get_rotation_weights

        w = get_rotation_weights("BULL")
        assert "momentum" in w
        total = sum(w.values())
        assert abs(total - 1.0) < 0.01

    def test_rotation_signal(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_rotation import calculate_rotation_signal

        perf = {"value": 0.05, "momentum": 0.08, "quality": -0.02, "low_vol": -0.03}
        r = calculate_rotation_signal(perf)
        assert "rotation_signal" in r
        assert "top_factors" in r

    def test_regime_factor_map(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_rotation import REGIME_FACTOR_MAP

        assert "BULL" in REGIME_FACTOR_MAP
        assert "BEAR" in REGIME_FACTOR_MAP


# ─── Time Series Tests ───


class TestTimeSeries:
    """Otomatik eklendi."""
    def test_factor_returns(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_time_series import calculate_factor_returns

        long = [0.05, 0.03, -0.02, 0.04]
        short = [0.02, 0.01, -0.01, 0.01]
        r = calculate_factor_returns(long, short)
        assert len(r) == 4
        assert abs(r[0] - 0.03) < 0.001

    def test_factor_trend(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_time_series import analyze_factor_trend

        returns = [0.01] * 60  # Upward trend
        r = analyze_factor_trend(returns, window=60)
        assert r["trend_direction"] == "UP"

    def test_factor_momentum(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_time_series import calculate_factor_momentum

        returns = [0.01, -0.005, 0.02, -0.01, 0.015] * 30
        r = calculate_factor_momentum(returns, periods=[5, 20, 60])
        assert "mom_5d" in r
        assert "mom_20d" in r

    def test_seasonality(self) -> Any:
        """Otomatik eklendi."""
        from services.factors.factor_time_series import detect_seasonality

        returns = [0.01, -0.005, 0.02] * 100
        r = detect_seasonality(returns)
        assert "monthly_avg_returns" in r or "error" in r


# ─── Integration Tests ───


class TestIntegration:
    """Otomatik eklendi."""
    def test_full_pipeline(self) -> Any:
        """Finansal veri → Piotroski + Beneish + Altman → Ranking."""
        from services.factors.altman import calculate_z_score
        from services.factors.piotroski import calculate_f_score
        from services.factors.ranking import rank_stocks

        # Hisse verileri
        stocks = []
        for i in range(5):
            fin = {
                "net_income": 100 + i * 50,
                "operating_cf": 150 + i * 30,
                "roa": 0.08 + i * 0.02,
                "leverage": 0.5 - i * 0.05,
                "current_ratio": 1.5 + i * 0.2,
                "shares_outstanding": 1000,
                "gross_margin": 0.35 + i * 0.03,
                "asset_turnover": 1.0 + i * 0.2,
                "working_capital": 200 + i * 100,
                "total_assets": 2000,
                "retained_earnings": 300 + i * 100,
                "ebit": 200 + i * 50,
                "market_cap": 1000 + i * 500,
                "total_debt": 500,
                "revenue": 1000 + i * 200,
            }
            f_score = calculate_f_score(fin)["f_score"]
            calculate_z_score(fin)["z_score"]

            stocks.append(
                {
                    "ticker": f"STOCK{i}",
                    "factors": {
                        "value": 0.5 + i * 0.1,
                        "momentum": 0.3 + i * 0.1,
                        "quality": f_score / 9.0,
                    },
                    "risk_score": 50 + i * 10,
                }
            )

        ranked = rank_stocks(stocks)
        assert len(ranked) == 5
        assert ranked[0]["rank"] == 1

    def test_factor_correlation_rotation(self) -> Any:
        """Factor correlation + rotation pipeline."""
        from services.factors.factor_correlation import calculate_factor_correlation
        from services.factors.factor_rotation import detect_regime, get_rotation_weights

        factors = {
            "value": list(np.random.randn(100) * 0.02),
            "momentum": list(np.random.randn(100) * 0.03),
            "quality": list(np.random.randn(100) * 0.015),
        }
        corr = calculate_factor_correlation(factors)
        assert corr["n_factors"] == 3

        regime = detect_regime(factors["momentum"])
        weights = get_rotation_weights(regime["regime"])
        assert abs(sum(weights.values()) - 1.0) < 0.01
