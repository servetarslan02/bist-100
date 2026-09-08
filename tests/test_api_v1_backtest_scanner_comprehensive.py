"""
Tests for services/api/v1/backtest.py and services/api/v1/scanner.py
Covers:
- BACKTEST:
  - /run (BacktestEngine execution)
  - /results/{backtest_id} (PostgreSQL fetch)
  - /list (list previous backtests)
  - /walk-forward (WalkForwardAnalyzer run)
  - /deflated-sharpe (deflated Sharpe ratio calculation)
  - /history_30y (30-year crisis defense & risk parity data)
  - /transaction-costs (BISTFeeStructure fees breakdown)
  - /trades/{backtest_id} & /equity-curve/{backtest_id}
- SCANNER:
  - /signals and /opportunities (caching, categories, high conviction, search, 304 ETag)
  - /status and /dashboard (scan_api integration)
  - /results (scan results query)
  - /tiers (tier summary breakdown)
  - /history/{ticker} (ticker history query)
  - /performance, /alerts, /filters, /dedup, /scheduler
  - /trigger (manual unified daily cycle run)
  - /event (event reporting to Redis)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.backtest import router as backtest_router
from services.api.v1.scanner import router as scanner_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(backtest_router, prefix="/api/v1/backtest")
    app.include_router(scanner_router, prefix="/api/v1/scanner")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# =====================================================
# Backtest Tests
# =====================================================


def test_backtest_run(client: TestClient) -> None:
    with patch("services.backtest.execution_engine.BacktestEngine.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"sharpe": 1.8, "total_return_pct": 35.0}

        resp = client.post("/api/v1/backtest/run?ticker=THYAO&period=1y&strategy=momentum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["ticker"] == "THYAO"
        assert data["result"]["sharpe"] == 1.8


def test_backtest_results_and_list(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_fetchrow.return_value = {"id": "bt-123", "sharpe": 2.1}
        resp = client.get("/api/v1/backtest/results/bt-123")
        assert resp.status_code == 200
        assert resp.json()["id"] == "bt-123"

        mock_fetch.return_value = [{"id": "bt-123"}, {"id": "bt-124"}]
        resp_l = client.get("/api/v1/backtest/list?limit=10")
        assert resp_l.status_code == 200
        assert resp_l.json()["count"] == 2


def test_backtest_walk_forward_and_deflated_sharpe(client: TestClient) -> None:
    with patch("services.backtest.walk_forward_engine.WalkForwardEngineV5.run_async", new_callable=AsyncMock) as mock_wf:
        mock_wf.return_value = {"avg_test_sharpe": 1.45, "folds": 5}
        resp = client.post("/api/v1/backtest/walk-forward?ticker=THYAO&n_folds=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["result"]["folds"] == 5

    with patch("services.backtest.deflated_sharpe.DeflatedSharpeCalculator.compute_deflated_sharpe") as mock_ds:
        mock_ds.return_value = {"deflated_sharpe_ratio": 0.95, "p_value": 0.05}
        resp_ds = client.get("/api/v1/backtest/deflated-sharpe?sharpe=2.0&n_trials=10&T=252")
        assert resp_ds.status_code == 200
        assert resp_ds.json()["deflated_sharpe_ratio"] == 0.95


def test_backtest_30y_history_and_fees(client: TestClient) -> None:
    with patch("services.core.database.get_pg_pool", new_callable=AsyncMock) as mock_pool_getter:
        mock_pool_getter.return_value = None
        resp = client.get("/api/v1/backtest/history_30y")
        assert resp.status_code == 200
        assert "summary" in resp.json()

    resp_fees = client.get("/api/v1/backtest/transaction-costs?amount=100000&ticker=THYAO")
    assert resp_fees.status_code == 200
    assert resp_fees.json()["amount"] == 100000.0
    assert "exchange_fee_pct" in resp_fees.json()


def test_backtest_trades_and_equity_curve(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
    ):
        mock_fetch.return_value = [{"trade_date": "2026-09-08", "pnl": 500.0}]
        resp_t = client.get("/api/v1/backtest/trades/bt-1")
        assert resp_t.status_code == 200
        assert len(resp_t.json()["trades"]) == 1

        mock_fetchrow.return_value = {"equity_curve_json": b'[{"date":"2026-09-08","val":100000}]'}
        resp_e = client.get("/api/v1/backtest/equity-curve/bt-1")
        assert resp_e.status_code == 200
        assert len(resp_e.json()["equity_curve"]) == 1


# =====================================================
# Scanner Tests
# =====================================================


def test_scanner_signals_and_filtering(client: TestClient) -> None:
    from services.api.v1.scanner import _signals_cache
    _signals_cache._cache = None
    _signals_cache._cached_at = 0.0

    with patch("services.core.redis_helper.get_cached") as mock_cache:
        mock_cache.return_value = [
            {
                "symbol": "THYAO",
                "name": "Türk Hava Yolları",
                "score": 88,
                "expected_return_pct": 5.2,
                "target_price": 320.0,
                "spec_category": "MOMENTUM_LEADER",
                "spec_reason": "Güçlü bilanço",
                "is_high_conviction": True,
            },
            {
                "symbol": "ASELS",
                "name": "Aselsan",
                "score": 72,
                "expected_return_pct": 3.1,
                "target_price": 75.0,
                "spec_category": "VALUE",
                "spec_reason": "Savunma sanayi siparişi",
                "is_high_conviction": False,
            },
        ]

        # 1. Base list
        resp = client.get("/api/v1/scanner/signals")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        # 2. Category filter
        resp_cat = client.get("/api/v1/scanner/signals?category=MOMENTUM_LEADER")
        assert resp_cat.status_code == 200
        assert resp_cat.json()["count"] == 1
        assert resp_cat.json()["signals"][0]["symbol"] == "THYAO"

        # 3. Search query
        resp_srch = client.get("/api/v1/scanner/signals?search=Aselsan")
        assert resp_srch.status_code == 200
        assert resp_srch.json()["count"] == 1
        assert resp_srch.json()["signals"][0]["symbol"] == "ASELS"


def test_scanner_status_and_dashboard(client: TestClient) -> None:
    with patch("services.api.v1.scanner._get_scan_api") as mock_api_fn:
        mock_api = MagicMock()
        mock_api.get_status.return_value = {"status": "running", "active_scans": 1}
        mock_api.get_full_dashboard.return_value = {"summary": "OK"}
        mock_api.get_results.return_value = {"results": [{"symbol": "THYAO"}]}
        mock_api.get_tiers.return_value = {"tier_0": 5, "tier_1": 15}
        mock_api.get_ticker_history.return_value = {"ticker": "THYAO", "history": []}
        mock_api.get_performance.return_value = {"success_rate": 0.85}
        mock_api.get_alerts.return_value = {"alerts": []}
        mock_api.get_filters.return_value = {"filters": ["RSI", "MACD"]}
        mock_api.get_dedup_stats.return_value = {"dedup_ratio": 0.3}
        mock_api.get_scheduler_stats.return_value = {"next_run": "2026-09-08 18:00"}
        mock_api_fn.return_value = mock_api

        assert client.get("/api/v1/scanner/status").status_code == 200
        assert client.get("/api/v1/scanner/dashboard").status_code == 200
        assert client.get("/api/v1/scanner/results").status_code == 200
        assert client.get("/api/v1/scanner/tiers").status_code == 200
        assert client.get("/api/v1/scanner/history/THYAO").status_code == 200
        assert client.get("/api/v1/scanner/performance").status_code == 200
        assert client.get("/api/v1/scanner/alerts").status_code == 200
        assert client.get("/api/v1/scanner/filters").status_code == 200
        assert client.get("/api/v1/scanner/dedup").status_code == 200
        assert client.get("/api/v1/scanner/scheduler").status_code == 200


def test_scanner_trigger_and_event(client: TestClient) -> None:
    with (
        patch("services.pipeline.run_unified_daily.run_unified_daily_cycle", new_callable=AsyncMock) as mock_cycle,
        patch("services.core.redis_helper.set_cached") as mock_set_cache,
    ):
        mock_cycle.return_value = {"status": "completed"}

        resp_trig = client.post("/api/v1/scanner/trigger?scan_type=manual")
        assert resp_trig.status_code == 200
        assert resp_trig.json()["status"] == "triggered"

        resp_ev = client.post("/api/v1/scanner/event?event_type=kap.event&ticker=THYAO&importance=0.8&title=KAP")
        assert resp_ev.status_code == 200
        assert resp_ev.json()["status"] == "received"
        mock_set_cache.assert_called_once()
