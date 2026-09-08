"""ALPHA BIST — Grafana Provisioning Birim Testleri."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import polars as pl
import pytest

from services.core.grafana_provisioning import (
    DashboardVersion,
    DatasourceConfig,
    GrafanaConfig,
    GrafanaProvisioner,
)


def test_grafana_config_initialization() -> None:
    """GrafanaConfig maskeleme ve yapılandırma testi."""
    config = GrafanaConfig(url="http://grafana.test:3000", auth="admin:supersecret")
    assert config.url == "http://grafana.test:3000"
    dict_repr = config.to_dict()
    assert dict_repr["auth"] == "admin:***"
    raw_bytes = config.to_orjson_bytes()
    assert b"admin:***" in raw_bytes


def test_datasource_config_payload() -> None:
    """Datasource payload üretimi ve serileştirme."""
    ds = DatasourceConfig(
        name="Prometheus",
        type="prometheus",
        url="http://localhost:9090",
        is_default=True,
    )
    payload = ds.to_grafana_payload()
    assert payload["name"] == "Prometheus"
    assert payload["type"] == "prometheus"
    assert payload["isDefault"] is True
    assert isinstance(ds.to_orjson_bytes(), bytes)


def test_dashboard_version_model() -> None:
    """DashboardVersion modeli ve sözlük dönüşümü."""
    ver = DashboardVersion(
        uid="dash123",
        title="Portfolio Overview",
        version=2,
        provisioned_at="2026-09-05T20:00:00Z",
        file_path="/monitoring/dash.json",
        status="SUCCESS",
    )
    d = ver.to_dict()
    assert d["uid"] == "dash123"
    assert d["version"] == 2
    assert d["status"] == "SUCCESS"
    assert b"Portfolio Overview" in ver.to_orjson_bytes()


@pytest.mark.anyio
async def test_check_health_mock() -> None:
    """Grafana health check uç noktasının simülasyonu."""
    provisioner = GrafanaProvisioner(GrafanaConfig(url="http://mock-grafana:3000"))

    mock_resp = httpx.Response(
        status_code=200,
        json={"version": "10.0.0", "database": "ok"},
        request=httpx.Request("GET", "http://mock-grafana:3000/api/health"),
    )

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        ok = await provisioner.check_health()
        assert ok is True
        mock_get.assert_called_once()


@pytest.mark.anyio
async def test_provision_datasource_mock() -> None:
    """Datasource oluşturma akışının simülasyonu."""
    provisioner = GrafanaProvisioner(GrafanaConfig(url="http://mock-grafana:3000"))
    ds = DatasourceConfig(name="Prometheus", type="prometheus", url="http://localhost:9090")

    # İlk GET (mevcut değil 404), ardından POST (201 Created)
    mock_get = httpx.Response(
        status_code=404,
        request=httpx.Request("GET", "http://mock-grafana:3000/api/datasources/name/Prometheus"),
    )
    mock_post = httpx.Response(
        status_code=201,
        json={"id": 1, "message": "Datasource added"},
        request=httpx.Request("POST", "http://mock-grafana:3000/api/datasources"),
    )

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as m_get, \
         patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as m_post:
        m_get.return_value = mock_get
        m_post.return_value = mock_post

        result = await provisioner.provision_datasource(ds)
        assert result is True
        status = provisioner.get_provisioning_status()
        assert status["datasources_provisioned"] > 0
        assert "Prometheus" in provisioner._provisioned_datasources


@pytest.mark.anyio
async def test_provision_dashboard_mock(tmp_path: Path) -> None:
    """Dashboard JSON dosyasının yüklenmesi ve versiyonlanması."""
    provisioner = GrafanaProvisioner(GrafanaConfig(url="http://mock-grafana:3000"))

    # Geçici dashboard JSON oluştur
    dash_file = tmp_path / "test_dashboard.json"
    dash_file.write_text('{"title": "Test Dashboard", "panels": []}', encoding="utf-8")

    mock_post = httpx.Response(
        status_code=200,
        json={"id": 10, "uid": "test_dash_1", "version": 3, "status": "success"},
        request=httpx.Request("POST", "http://mock-grafana:3000/api/dashboards/db"),
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_post

        version = await provisioner.provision_dashboard(dash_file)
        assert version == 3
        history = provisioner.get_version_history()
        assert len(history) == 1
        assert history[0]["version"] == 3


def test_polars_and_duckdb_export(tmp_path: Path) -> None:
    """Polars DataFrame ve DuckDB aktarım testi."""
    provisioner = GrafanaProvisioner()
    # Simüle edilmiş 2 versiyon ekle
    v1 = DashboardVersion(
        uid="u1", title="Dash 1", version=1, provisioned_at="2026-09-05T21:00:00Z",
        file_path="dash1.json", status="SUCCESS"
    )
    v2 = DashboardVersion(
        uid="u2", title="Dash 2", version=2, provisioned_at="2026-09-05T21:05:00Z",
        file_path="dash2.json", status="SUCCESS"
    )
    with provisioner._lock:
        provisioner._versions.append(v1)
        provisioner._versions.append(v2)

    df = provisioner.export_versions_to_polars()
    assert isinstance(df, pl.DataFrame)
    assert len(df) == 2
    assert "uid" in df.columns
    assert "status" in df.columns

    db_path = str(tmp_path / "test_grafana.duckdb")
    saved = provisioner.export_to_duckdb(db_path)
    assert saved == 2
    assert Path(db_path).exists()
