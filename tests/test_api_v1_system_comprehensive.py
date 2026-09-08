"""
Tests for services/api/v1/system.py
Covers:
- /time
- /status and /health (with PostgreSQL, Redis, ClickHouse mocks & resource collection)
- /databases
- /db-performance
- /alerts
- /optimize_storage
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.system import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/system")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_system_time(client: TestClient) -> None:
    resp = client.get("/api/v1/system/time")
    assert resp.status_code == 200
    data = resp.json()
    assert "utc" in data
    assert "istanbul" in data
    assert "timestamp_ms" in data
    assert "is_market_open" in data
    assert "market_status" in data


def test_system_status_and_health(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchval", new_callable=AsyncMock) as mock_pg,
        patch("services.core.database.get_redis", new_callable=AsyncMock) as mock_redis_getter,
        patch("services.core.database.ch_execute") as mock_ch,
    ):
        mock_pg.return_value = 1

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis_getter.return_value = mock_redis

        ch_res = MagicMock()
        ch_res.result_rows = [(1,)]
        mock_ch.return_value = ch_res

        resp = client.get("/api/v1/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        assert data["services"]["postgresql"] == "healthy"
        assert data["services"]["redis"] == "healthy"
        assert data["services"]["clickhouse"] == "healthy"
        assert "resources" in data
        assert "system_details" in data
        assert "pipeline_stats" in data

        resp_health = client.get("/api/v1/system/health")
        assert resp_health.status_code == 200


def test_system_status_degraded_on_error(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchval", side_effect=Exception("DB Error")),
        patch("services.core.database.get_redis", side_effect=Exception("Redis Error")),
        patch("services.core.database.ch_execute", side_effect=Exception("CH Error")),
    ):
        resp = client.get("/api/v1/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["services"]["postgresql"] == "unhealthy"
        assert data["services"]["redis"] == "unhealthy"
        assert data["services"]["clickhouse"] == "unhealthy"


def test_system_databases(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchval", new_callable=AsyncMock) as mock_pg_val,
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_pg_fetch,
        patch("services.core.database.get_redis", new_callable=AsyncMock) as mock_redis_getter,
        patch("services.core.database.ch_execute") as mock_ch,
    ):
        mock_pg_val.return_value = "150 MB"
        mock_pg_fetch.return_value = [
            {"table_name": "orders", "row_count": 1200, "total_size": "25 MB"}
        ]

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {"used_memory_human": "45M"}
        mock_redis.dbsize.return_value = 350
        mock_redis_getter.return_value = mock_redis

        ch_res1 = MagicMock()
        ch_res1.result_rows = [("12.5 GB", 5000000)]
        ch_res2 = MagicMock()
        ch_res2.result_rows = [("ticks", 5000000, "12.5 GB")]
        mock_ch.side_effect = [ch_res1, ch_res2]

        resp = client.get("/api/v1/system/databases")
        assert resp.status_code == 200
        data = resp.json()
        assert "databases" in data
        assert len(data["databases"]) == 4
        db_names = [d["name"] for d in data["databases"]]
        assert any("ClickHouse" in name for name in db_names)
        assert any("PostgreSQL" in name for name in db_names)
        assert any("Redis" in name for name in db_names)
        assert any("NATS" in name for name in db_names)


def test_system_db_performance(client: TestClient) -> None:
    with (
        patch("services.core.database.pg_fetchrow", new_callable=AsyncMock) as mock_fetchrow,
        patch("services.core.database.pg_fetch", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_fetchrow.side_effect = [
            {"cache_hit_pct": 99.4},
            {"total": 10, "active": 2, "idle": 8, "idle_in_tx": 0, "max_conn": 100},
        ]
        mock_fetch.side_effect = [
            [{"tablename": "ticks", "total_size": "100 MB", "row_count": 1000, "dead_rows": 5}],
            [{"query": "SELECT * FROM ticks", "calls": 5, "mean_ms": 1.2, "total_ms": 6.0, "rows": 50}],
        ]

        resp = client.get("/api/v1/system/db-performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cache_hit_ratio"] == 99.4
        assert data["connections"]["total"] == 10
        assert len(data["table_sizes"]) == 1
        assert len(data["slow_queries"]) == 1


def test_system_alerts(client: TestClient) -> None:
    with (
        patch("services.core.redis_helper.get_cached") as mock_get_cached,
        patch("services.risk.drawdown_response.drawdown_system.get_state") as mock_dd,
    ):
        mock_get_cached.side_effect = lambda key: (
            [{"symbol": "THYAO", "score": 88, "price": 280.0}] if key == "radar:data"
            else {"regime": "BULLISH", "description": "Piyasa yukselis trendinde"} if key == "market:regime"
            else None
        )

        dd_mock = MagicMock()
        dd_mock.current_drawdown_pct = 4.2
        dd_mock.description = "Normal seviye"
        mock_dd.return_value = dd_mock

        from services.api.v1.system import _alerts_cache
        _alerts_cache._cache = None

        resp = client.get("/api/v1/system/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert data["count"] >= 2
        categories = {a["category"] for a in data["alerts"]}
        assert "SIGNAL" in categories
        assert "RISK" in categories


def test_system_optimize_storage(client: TestClient) -> None:
    with patch("services.core.database.ch_execute") as mock_ch:
        parts_mock = MagicMock()
        parts_mock.result_rows = [("bist_ticks",), ("bist_ohlcv",)]
        mock_ch.side_effect = [parts_mock, None, None]

        resp = client.post("/api/v1/system/optimize_storage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "ClickHouse" in data["message"]
