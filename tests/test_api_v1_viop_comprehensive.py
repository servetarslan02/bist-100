"""
Tests for services/api/v1/viop.py
Covers:
- /options & /options/price
- /options/implied-vol
- /greeks (portfolio greeks aggregation)
- /strategies & /strategies/analyze
- /hedge & /hedge/gamma-scalp
- /margin (SPAN margin calculation)
- /arbitrage & /parity
- /risk (portfolio VIOP risk)
- /contracts & /contracts/{symbol}
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.viop import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/viop")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_viop_options_and_pricing(client: TestClient) -> None:
    # 1. Catalog contract info
    resp = client.get("/api/v1/viop/options?symbol=XU030")
    assert resp.status_code == 200
    data = resp.json()
    assert "contract" in data

    # 404 for unknown contract
    resp_nf = client.get("/api/v1/viop/options?symbol=UNKNOWN")
    assert resp_nf.status_code == 404

    # 2. Black-Scholes pricing
    resp_p = client.post("/api/v1/viop/options/price?S=100&K=100&T=0.25&r=0.15&sigma=0.25&option_type=call")
    assert resp_p.status_code == 200
    p_data = resp_p.json()
    assert p_data["price"] > 0
    assert "greeks" in p_data
    assert "delta" in p_data["greeks"]


def test_viop_implied_vol(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/viop/options/implied-vol?market_price=5.0&S=100&K=100&T=0.25&r=0.15&option_type=call"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "implied_vol" in data
    assert data["implied_vol"] > 0


def test_viop_portfolio_greeks(client: TestClient) -> None:
    positions = [
        {
            "option_type": "call",
            "S": 100.0,
            "K": 100.0,
            "T": 0.25,
            "r": 0.15,
            "sigma": 0.25,
            "quantity": 10,
            "side": "long",
        }
    ]
    resp = client.post("/api/v1/viop/greeks", json=positions)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_delta" in data
    assert "total_gamma" in data

    # Empty positions 400
    resp_empty = client.post("/api/v1/viop/greeks", json=[])
    assert resp_empty.status_code == 400


def test_viop_strategies(client: TestClient) -> None:
    # 1. List strategies
    resp = client.get("/api/v1/viop/strategies")
    assert resp.status_code == 200
    assert len(resp.json()["strategies"]) > 0

    # 2. Analyze strategy
    resp_an = client.post("/api/v1/viop/strategies/analyze?strategy=COVERED_CALL&spot=100")
    assert resp_an.status_code == 200
    data = resp_an.json()
    assert "max_profit" in data or "strategy" in data or "legs" in data

    # Unknown strategy 400
    resp_bad = client.post("/api/v1/viop/strategies/analyze?strategy=INVALID&spot=100")
    assert resp_bad.status_code == 400


def test_viop_hedging(client: TestClient) -> None:
    # 1. Delta hedge
    resp_h = client.post("/api/v1/viop/hedge?portfolio_delta=150&spot_price=100&futures_price=105")
    assert resp_h.status_code == 200
    assert "contracts_needed" in resp_h.json() or "hedge_contracts" in resp_h.json() or "target_delta" in resp_h.json() or "action" in resp_h.json()

    # 2. Gamma scalp
    resp_gs = client.post("/api/v1/viop/hedge/gamma-scalp?portfolio_gamma=0.05&spot_price=100&price_move_pct=2.0")
    assert resp_gs.status_code == 200


def test_viop_margin_and_arbitrage_and_parity(client: TestClient) -> None:
    # 1. SPAN margin
    positions = [
        {"ticker": "XU030", "value": 50000.0, "delta": 0.5, "gamma": 0.01, "vega": 15.0, "spot_price": 100.0}
    ]
    resp_m = client.post("/api/v1/viop/margin", json=positions)
    assert resp_m.status_code == 200

    # 2. Arbitrage
    resp_arb = client.post(
        "/api/v1/viop/arbitrage?spot_price=100&futures_price=106&risk_free_rate=0.15&dividend_yield=0.02&time_to_expiry=0.25"
    )
    assert resp_arb.status_code == 200

    # 3. Put-call parity
    resp_par = client.post(
        "/api/v1/viop/parity?call_price=5.5&put_price=3.2&spot_price=100&strike=100&r=0.15&T=0.25"
    )
    assert resp_par.status_code == 200


def test_viop_risk_and_contracts(client: TestClient) -> None:
    # 1. VIOP risk
    viop_positions = [{"symbol": "F_XU030", "position": 5, "price": 105.0, "multiplier": 100}]
    resp_r = client.post("/api/v1/viop/risk?portfolio_value=100000", json=viop_positions)
    assert resp_r.status_code == 200

    # 2. Contract list & detail
    resp_c = client.get("/api/v1/viop/contracts")
    assert resp_c.status_code == 200
    assert len(resp_c.json()["contracts"]) > 0

    resp_cd = client.get("/api/v1/viop/contracts/XU030")
    assert resp_cd.status_code == 200
    assert resp_cd.json()["symbol"] == "XU030"
