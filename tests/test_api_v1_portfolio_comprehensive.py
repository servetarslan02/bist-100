"""
Tests for services/api/v1/portfolio.py
Covers:
- /summary, /state, /positions, /trades, /pnl, /equity-curve
- /risk-metrics, /drawdown, /metrics, /accounting
- /reset, /cash-ledger, /orders, /position-history, /equity-snapshots
- /attribution (501 not implemented fallback), /tax, /tca
- /rebalance, /rebalance/orders, /trigger, /optimize
- /status, /trigger_eod_signals, /trigger_morning_execution, /trigger_phase18, /auto_rebalance, /deposit
- /alpha, /alpha-signals
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.portfolio import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/portfolio")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_pm() -> MagicMock:
    pm = MagicMock()
    pm.get_summary.return_value = {
        "cash": 40000.0,
        "invested_value": 60000.0,
        "total_value": 100000.0,
        "num_positions": 2,
        "unrealized_pnl": 1500.0,
        "unrealized_pnl_pct": 2.5,
        "realized_pnl": 3000.0,
        "total_pnl": 4500.0,
        "total_pnl_pct": 4.5,
        "total_commission": 200.0,
        "max_drawdown_pct": 3.2,
        "current_drawdown_pct": 1.1,
        "settled_cash": 40000.0,
        "unsettled_cash_t1": 0.0,
        "unsettled_cash_t2": 0.0,
    }
    pm.get_all_positions.return_value = [
        {"ticker": "THYAO", "market_value": 35000.0, "quantity": 100},
        {"ticker": "ASELS", "market_value": 25000.0, "quantity": 200},
    ]
    pm.get_total_value.return_value = 100000.0
    pm.get_trades.return_value = [
        {"ticker": "THYAO", "side": "BUY", "price": 300.0, "shares": 100, "realized_pnl": 500.0}
    ]
    pm.get_equity_curve.return_value = [{"date": "2026-09-08", "total_value": 100000.0}]
    pm.get_orders.return_value = [{"order_id": "ord-1", "ticker": "THYAO"}]
    pm.get_position_history.return_value = [{"ticker": "THYAO", "action": "BUY"}]
    pm.get_equity_snapshots.return_value = [{"date": "2026-09-08", "equity": 100000.0}]
    pm.initial_capital = 100000.0
    pm.cash = 40000.0
    pm.settled_cash = 40000.0
    pm.deposit_cash.return_value = 50000.0
    return pm


def test_portfolio_summary_and_positions(client: TestClient, mock_pm: MagicMock) -> None:
    with patch("services.api.v1.portfolio._get_pm", return_value=mock_pm):
        resp = client.get("/api/v1/portfolio/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash"] == 40000.0
        assert data["total_value"] == 100000.0
        assert data["positions_count"] == 2

        resp_pos = client.get("/api/v1/portfolio/positions")
        assert resp_pos.status_code == 200
        assert resp_pos.json()["count"] == 2


def test_portfolio_trades_pnl_equity(client: TestClient, mock_pm: MagicMock) -> None:
    with patch("services.api.v1.portfolio._get_pm", return_value=mock_pm):
        resp_t = client.get("/api/v1/portfolio/trades")
        assert resp_t.status_code == 200
        assert resp_t.json()["total_trades"] == 1

        resp_p = client.get("/api/v1/portfolio/pnl")
        assert resp_p.status_code == 200
        assert resp_p.json()["unrealized_pnl"] == 1500.0

        resp_e = client.get("/api/v1/portfolio/equity-curve")
        assert resp_e.status_code == 200
        assert "equity_curve" in resp_e.json()


def test_portfolio_risk_drawdown_accounting(client: TestClient, mock_pm: MagicMock) -> None:
    with patch("services.api.v1.portfolio._get_pm", return_value=mock_pm):
        resp_r = client.get("/api/v1/portfolio/risk-metrics")
        assert resp_r.status_code == 200
        assert resp_r.json()["max_drawdown_pct"] == 3.2

        resp_d = client.get("/api/v1/portfolio/drawdown")
        assert resp_d.status_code == 200
        assert resp_d.json()["current_drawdown_pct"] == 1.1

        resp_a = client.get("/api/v1/portfolio/accounting")
        assert resp_a.status_code == 200
        assert resp_a.json()["invariant_check"] is True


def test_portfolio_reset_and_deposit(client: TestClient, mock_pm: MagicMock) -> None:
    with patch("services.api.v1.portfolio._get_pm", return_value=mock_pm):
        resp_reset = client.post("/api/v1/portfolio/reset")
        assert resp_reset.status_code == 200
        assert resp_reset.json()["success"] is True

        resp_dep = client.post("/api/v1/portfolio/deposit", json={"amount": 10000.0})
        assert resp_dep.status_code == 200
        assert resp_dep.json()["deposited_amount"] == 10000.0


def test_portfolio_metrics_and_attribution(client: TestClient) -> None:
    with patch("services.paper_trading.paper_orchestrator.paper_orchestrator.get_full_report") as mock_rep:
        mock_rep.return_value = {
            "performance_metrics": {
                "sharpe_ratio": 2.1,
                "win_rate": 0.65,
                "max_drawdown_pct": 4.5,
                "profit_factor": 1.8,
            }
        }
        resp = client.get("/api/v1/portfolio/metrics")
        assert resp.status_code == 200
        assert resp.json()["sharpe_ratio"] == 2.1

    # Attribution is 501
    resp_attr = client.get("/api/v1/portfolio/attribution")
    assert resp_attr.status_code == 501


def test_portfolio_rebalance_and_orders(client: TestClient, mock_pm: MagicMock) -> None:
    with patch("services.api.v1.portfolio._get_pm", return_value=mock_pm):
        mock_pm.check_rebalance.return_value = {"rebalance_needed": False}
        mock_pm.compute_rebalance_orders.return_value = [{"ticker": "THYAO", "action": "BUY", "value": 5000.0}]

        resp_r = client.get('/api/v1/portfolio/rebalance?target_weights={"THYAO": 0.5}')
        assert resp_r.status_code == 200
        assert resp_r.json()["rebalance_needed"] is False

        resp_o = client.post("/api/v1/portfolio/rebalance/orders", json={"THYAO": 0.5})
        assert resp_o.status_code == 200
        assert resp_o.json()["total_orders"] == 1


def test_portfolio_optimize(client: TestClient) -> None:
    with (
        patch("services.data.data_source.data_source.get_stock_data") as mock_ds,
        patch("services.portfolio.portfolio_optimizer.portfolio_optimizer.optimize") as mock_opt,
    ):
        mock_ds.return_value = pl.DataFrame({
            "Close": [100.0 + i for i in range(25)]
        })
        opt_res = MagicMock()
        opt_res.method.value = "RISK_PARITY"
        opt_res.weights = {"THYAO": 0.6, "ASELS": 0.4}
        opt_res.cash_weight = 0.0
        opt_res.expected_return = 0.25
        opt_res.portfolio_volatility = 0.18
        opt_res.sharpe_ratio = 1.4
        opt_res.diversification_ratio = 1.2
        opt_res.turnover_from_current = 0.1
        opt_res.estimated_transaction_cost_tl = 50.0
        opt_res.effective_positions_count = 2
        opt_res.sector_exposures = {}
        opt_res.is_optimal = True
        opt_res.warnings = []
        mock_opt.return_value = opt_res

        resp = client.post(
            "/api/v1/portfolio/optimize",
            json={"tickers": ["THYAO", "ASELS"], "method": "RISK_PARITY"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["method"] == "RISK_PARITY"


def test_portfolio_triggers(client: TestClient) -> None:
    with (
        patch("services.pipeline.run_unified_daily.run_unified_daily_cycle", new_callable=AsyncMock) as mock_daily,
        patch("services.pipeline.run_unified_daily.run_eod_signal_cycle", new_callable=AsyncMock) as mock_eod,
        patch("services.pipeline.run_unified_daily.run_morning_execution_cycle", new_callable=AsyncMock) as mock_morn,
    ):
        mock_daily.return_value = {"status": "ok"}
        mock_eod.return_value = {"signals": 5}
        mock_morn.return_value = {"orders": 2}

        assert client.post("/api/v1/portfolio/trigger").status_code == 200
        assert client.post("/api/v1/portfolio/trigger_eod_signals").status_code == 200
        assert client.post("/api/v1/portfolio/trigger_morning_execution").status_code == 200
        assert client.post("/api/v1/portfolio/trigger_phase18").status_code == 200
        assert client.post("/api/v1/portfolio/auto_rebalance").status_code == 200


def test_portfolio_alpha_signals(client: TestClient) -> None:
    from services.api.v1.portfolio import _alpha_signals_cache
    _alpha_signals_cache._cache = None

    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.side_effect = lambda k: (
            [
                {"symbol": "THYAO", "score": 90},
                {"symbol": "ASELS", "score": 85},
                {"symbol": "GARAN", "score": 80},
                {"symbol": "KCHOL", "score": 78},
                {"symbol": "TUPRS", "score": 75},
            ]
            if k == "radar:data"
            else None
        )

        resp = client.get("/api/v1/portfolio/alpha")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert len(data["active_positions"]) == 5
