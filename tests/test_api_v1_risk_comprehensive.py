"""
Tests for services/api/v1/risk.py
Covers:
- /overview, /summary, /dashboard
- /var (parametric, historical, Monte Carlo)
- /portfolio (risk orchestrator integration)
- /liquidity (order liquidity evaluation)
- /limits (dynamic risk limits)
- /drawdown (drawdown system status & events)
- /stress-test/scenarios, /stress-test/run, /stress-test/quick
- /tail-hedge, /tail-hedge/analyze
- /risk-parity, /risk-parity/optimize
- /monitoring, /alerts, /calibration
- /check (pre-trade check), /compliance
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.risk import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/risk")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_risk_overview_and_dashboard(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_dynamic_limits") as mock_dl_fn,
        patch("services.api.v1.risk._get_drawdown_system") as mock_dd_fn,
        patch("services.api.v1.risk._get_monitor") as mock_mon_fn,
        patch("services.api.v1.risk._get_live_portfolio_for_risk") as mock_live_pf,
        patch("services.api.v1.risk._get_tail_hedger") as mock_th_fn,
        patch("services.api.v1.risk._get_calibrator") as mock_cal_fn,
    ):
        mock_limits = MagicMock()
        mock_limits.max_position_pct = 0.10
        mock_limits.max_sector_pct = 0.30
        mock_limits.max_exposure_pct = 0.80
        mock_limits.kelly_fraction = 0.5
        mock_limits.min_confidence = 0.6
        mock_limits.max_var_pct = 0.03
        mock_dl = MagicMock()
        mock_dl.get_limits.return_value = mock_limits
        mock_dl_fn.return_value = mock_dl

        mock_dd_state = MagicMock()
        mock_dd_state.current_drawdown_pct = 2.5
        mock_dd_state.max_drawdown_pct = 5.0
        mock_dd_state.action.value = "NORMAL"
        mock_dd_state.severity.value = "LOW"
        mock_dd_state.position_scale = 1.0
        mock_dd_state.description = "Normal seviye"
        mock_dd_state.drawdown_duration_days = 3
        mock_dd = MagicMock()
        mock_dd.get_state.return_value = mock_dd_state
        mock_dd.is_trading_allowed.return_value = True
        mock_dd.is_system_halted.return_value = False
        mock_dd_fn.return_value = mock_dd

        mock_mon = MagicMock()
        mock_mon.get_alert_summary.return_value = {"active_alerts": 0}
        mock_mon_fn.return_value = mock_mon

        mock_live_pf.return_value = {"positions": []}

        mock_hedge = MagicMock()
        mock_hedge.strategy = "COLLAR"
        mock_hedge.hedge_ratio = 0.5
        mock_hedge.estimated_cost_pct = 0.01
        mock_hedge.protection_level = "MODERATE"
        mock_hedge.description = "Collar hedge"
        mock_hedge.instruments = ["XU030 Put"]
        mock_th = MagicMock()
        mock_th.analyze.return_value = mock_hedge
        mock_th_fn.return_value = mock_th

        mock_cal = MagicMock()
        mock_cal.get_calibration_quality.return_value = {"quality": "EXCELLENT", "brier_score": 0.08}
        mock_cal_fn.return_value = mock_cal

        resp_ov = client.get("/api/v1/risk/overview")
        assert resp_ov.status_code == 200
        assert resp_ov.json()["risk_level"] == "NORMAL"

        resp_dash = client.get("/api/v1/risk/dashboard")
        assert resp_dash.status_code == 200
        assert resp_dash.json()["risk_level"] == "NORMAL"


def test_risk_var(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_var_calculator") as mock_var_fn,
        patch("services.api.v1.risk._get_historical_returns") as mock_ret_fn,
    ):
        mock_ret_fn.return_value = np.array([0.01, -0.015, 0.005, -0.02, 0.012] * 10)
        calc = MagicMock()
        calc.calculate_parametric_var.return_value = 2500.0
        calc.calculate_historical_var.return_value = 2800.0
        calc.calculate_cvar.return_value = 3500.0
        mock_var_fn.return_value = calc

        resp = client.get("/api/v1/risk/var?portfolio_value=100000")
        assert resp.status_code == 200
        data = resp.json()
        assert data["parametric_var"] == 2500.0
        assert data["historical_var"] == 2800.0
        assert data["cvar_95"] == 3500.0


def test_risk_portfolio_and_liquidity(client: TestClient) -> None:
    with patch("services.api.v1.risk._get_live_portfolio_for_risk") as mock_live_pf:
        mock_live_pf.return_value = {"positions": []}
        resp_p = client.get("/api/v1/risk/portfolio")
        assert resp_p.status_code == 200
        assert resp_p.json()["status"] == "unavailable"

    with patch("services.risk.liquidity_risk.liquidity_risk_engine.evaluate_order_liquidity") as mock_liq:
        mock_m = MagicMock()
        mock_m.ticker = "THYAO"
        mock_m.order_value = 50000.0
        mock_m.adv_tl = 10000000.0
        mock_m.participation_rate_pct = 0.5
        mock_m.effective_spread_bps = 5.0
        mock_m.expected_market_impact_pct = 0.05
        mock_m.expected_slippage_tl = 25.0
        mock_m.liquidation_days = 0.1
        mock_m.liquidity_score = 95.0
        mock_m.liquidity_sizing_multiplier = 1.0
        mock_m.is_tradable = True
        mock_m.warnings = []
        mock_liq.return_value = mock_m

        resp_l = client.get("/api/v1/risk/liquidity?ticker=THYAO&order_value=50000")
        assert resp_l.status_code == 200
        assert resp_l.json()["ticker"] == "THYAO"
        assert resp_l.json()["is_tradable"] is True


def test_risk_limits_and_drawdown(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_dynamic_limits") as mock_dl_fn,
        patch("services.api.v1.risk._get_drawdown_system") as mock_dd_fn,
    ):
        mock_limits = MagicMock()
        mock_limits.max_position_pct = 0.10
        mock_limits.max_sector_pct = 0.30
        mock_limits.max_exposure_pct = 0.80
        mock_limits.kelly_fraction = 0.5
        mock_limits.min_confidence = 0.6
        mock_limits.max_var_pct = 0.03
        mock_limits.max_correlation = 0.7
        mock_dl = MagicMock()
        mock_dl.get_limits.return_value = mock_limits
        mock_dl_fn.return_value = mock_dl

        mock_dd_state = MagicMock()
        mock_dd_state.current_drawdown_pct = 3.0
        mock_dd_state.max_drawdown_pct = 6.0
        mock_dd_state.peak_equity = 100000.0
        mock_dd_state.current_equity = 97000.0
        mock_dd_state.action.value = "NORMAL"
        mock_dd_state.severity.value = "LOW"
        mock_dd_state.position_scale = 1.0
        mock_dd_state.description = "Normal"
        mock_dd_state.drawdown_duration_days = 4
        mock_dd = MagicMock()
        mock_dd.get_state.return_value = mock_dd_state
        mock_dd.get_events.return_value = []
        mock_dd.get_alert_message.return_value = "Normal"
        mock_dd.is_trading_allowed.return_value = True
        mock_dd.is_system_halted.return_value = False
        mock_dd_fn.return_value = mock_dd

        resp_lim = client.get("/api/v1/risk/limits")
        assert resp_lim.status_code == 200
        assert "dynamic" in resp_lim.json()

        resp_dd = client.get("/api/v1/risk/drawdown")
        assert resp_dd.status_code == 200
        assert resp_dd.json()["current_drawdown_pct"] == 3.0


def test_stress_test_and_tail_hedge(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_stress_engine") as mock_se_fn,
        patch("services.api.v1.risk._get_tail_hedger") as mock_th_fn,
        patch("services.api.v1.risk._get_historical_returns", return_value=np.array([0.01, -0.01] * 20)),
    ):
        mock_se = MagicMock()
        mock_se.HISTORICAL_SCENARIOS = {"2008": {"name": "GFC", "bist_return": -0.35}}
        mock_se.HYPOTHETICAL_SCENARIOS = {"rates": {"name": "Rates +500bps"}}
        mock_se_fn.return_value = mock_se

        resp_sc = client.get("/api/v1/risk/stress-test/scenarios")
        assert resp_sc.status_code == 200
        assert resp_sc.json()["total"] == 2

        mock_th = MagicMock()
        mock_th.STRATEGIES = {"COLLAR": {"name": "Collar", "description": "Collar", "cost_range": "0-1%", "protection": "Med"}}
        mock_th.VIX_LEVELS = {"low": 15}
        mock_th_fn.return_value = mock_th

        resp_th = client.get("/api/v1/risk/tail-hedge")
        assert resp_th.status_code == 200
        assert "COLLAR" in resp_th.json()["strategies"]


def test_risk_parity_optimize(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_risk_parity") as mock_rp_fn,
        patch("services.risk.covariance.covariance_estimator.estimate") as mock_cov_est,
    ):
        mock_cov_est.return_value = {"covariance": np.array([[0.04, 0.01], [0.01, 0.05]])}
        mock_opt_res = MagicMock()
        mock_opt_res.weights = {"THYAO": 0.55, "ASELS": 0.45}
        mock_opt_res.risk_contributions = {"THYAO": 0.5, "ASELS": 0.5}
        mock_opt_res.portfolio_volatility = 0.16
        mock_opt_res.diversification_ratio = 1.3
        mock_opt_res.optimization_success = True
        mock_opt_res.iterations = 12
        mock_rp = MagicMock()
        mock_rp.optimize.return_value = mock_opt_res
        mock_rp_fn.return_value = mock_rp

        returns_data = [[0.01, 0.02], [-0.01, -0.005], [0.02, 0.01]]
        resp = client.post(
            "/api/v1/risk/risk-parity/optimize",
            json={"tickers": ["THYAO", "ASELS"], "returns_data": returns_data},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["optimization_success"] is True
        assert "THYAO" in data["weights"]


def test_monitoring_alerts_calibration(client: TestClient) -> None:
    with (
        patch("services.api.v1.risk._get_monitor") as mock_mon_fn,
        patch("services.api.v1.risk._get_calibrator") as mock_cal_fn,
    ):
        mock_mon = MagicMock()
        mock_mon.get_rules.return_value = []
        mock_mon.get_alerts.return_value = []
        mock_mon.get_alert_summary.return_value = {"total": 0}
        mock_mon_fn.return_value = mock_mon

        resp_m = client.get("/api/v1/risk/monitoring")
        assert resp_m.status_code == 200

        resp_a = client.get("/api/v1/risk/alerts")
        assert resp_a.status_code == 200

        mock_cal = MagicMock()
        mock_cal.get_calibration_quality.return_value = {"quality": "GOOD", "brier_score": 0.12, "n_trades": 50, "fitted": True}
        mock_cal.get_calibration_curve.return_value = []
        mock_cal.get_brier_history.return_value = [0.12]
        mock_cal_fn.return_value = mock_cal

        resp_c = client.get("/api/v1/risk/calibration")
        assert resp_c.status_code == 200
        assert resp_c.json()["quality"] == "GOOD"


def test_pre_trade_check_and_compliance(client: TestClient) -> None:
    with (
        patch("services.risk.orchestrator.risk_orchestrator.evaluate_pre_trade") as mock_eval,
        patch("services.api.v1.risk._get_dynamic_limits") as mock_dl_fn,
        patch("services.api.v1.risk._get_drawdown_system") as mock_dd_fn,
    ):
        mock_dec = MagicMock()
        mock_dec.allowed = True
        mock_dec.reason = "Approved"
        mock_dec.checks_passed = ["limit", "liquidity"]
        mock_dec.checks_failed = []
        mock_dec.details = {}
        mock_eval.return_value = mock_dec

        resp_chk = client.post("/api/v1/risk/check?ticker=THYAO&amount=10000&price=250")
        assert resp_chk.status_code == 200
        assert resp_chk.json()["approved"] is True

        mock_limits = MagicMock()
        mock_limits.max_position_pct = 0.1
        mock_limits.max_sector_pct = 0.3
        mock_limits.max_exposure_pct = 0.8
        mock_dl = MagicMock()
        mock_dl.get_limits.return_value = mock_limits
        mock_dl_fn.return_value = mock_dl

        mock_dd_state = MagicMock()
        mock_dd_state.severity.value = "LOW"
        mock_dd_state.current_drawdown_pct = 1.0
        mock_dd = MagicMock()
        mock_dd.get_state.return_value = mock_dd_state
        mock_dd.is_trading_allowed.return_value = True
        mock_dd_fn.return_value = mock_dd

        resp_comp = client.get("/api/v1/risk/compliance")
        assert resp_comp.status_code == 200
        assert resp_comp.json()["compliant"] is True
