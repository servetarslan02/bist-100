"""ALPHA BIST — Sağlık Raporlayıcı (Health Reporter) Birim Testleri."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

import duckdb
import orjson
import polars as pl

from services.core.health_reporter import (
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    HealthReporter,
    SystemHealthReport,
    health_reporter,
)


def test_system_health_report_model() -> None:
    """SystemHealthReport veri modeli, serileştirme ve metot testleri."""
    report = SystemHealthReport(
        timestamp="2026-09-05T20:00:00+00:00",
        overall_health=STATUS_HEALTHY,
        uptime={"seconds": 3600.0, "hours": 1.0, "days": 0.04},
        components={"connectivity": {"status": "online"}},
        issues=[],
        generation_duration_seconds=0.012,
    )

    d = report.to_dict()
    assert d["overall_health"] == STATUS_HEALTHY
    assert d["generation_duration_seconds"] == 0.012
    assert d["uptime"]["hours"] == 1.0

    raw_bytes = report.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)
    parsed = orjson.loads(raw_bytes)
    assert parsed["overall_health"] == STATUS_HEALTHY

    repr_str = repr(report)
    assert "SystemHealthReport" in repr_str
    assert STATUS_HEALTHY in repr_str


@pytest.mark.anyio
async def test_generate_report_mock() -> None:
    """Mock veritabanı ve istemcilerle tam sağlık raporu üretimi."""
    reporter = HealthReporter(max_history=10)

    # Mock ClickHouse
    mock_ch = MagicMock()
    mock_ch.query.return_value.result_rows = [["ClickHouse 26.3.1"]]

    # Mock PostgreSQL
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = "PostgreSQL 17.0 on x86_64"
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Mock Redis
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {"used_memory_human": "24.5M"}
    mock_redis.dbsize.return_value = 150

    result = await reporter.generate_report(
        clickhouse_client=mock_ch,
        pg_pool=mock_pool,
        redis_client=mock_redis,
    )

    assert isinstance(result, dict)
    assert result["overall_health"] in (STATUS_HEALTHY, STATUS_DEGRADED)
    assert "components" in result
    assert result["components"]["postgresql"]["connected"] is True
    assert result["components"]["clickhouse"]["connected"] is True
    assert result["components"]["redis"]["connected"] is True

    # Son rapor ve özet kontrolü
    last_dict = reporter.get_last_report()
    assert last_dict is not None
    assert last_dict["timestamp"] == result["timestamp"]

    last_model = reporter.get_last_report_model()
    assert last_model is not None
    assert isinstance(last_model, SystemHealthReport)

    summary = reporter.get_summary()
    assert summary["overall_health"] == result["overall_health"]
    assert "timestamp" in summary

    history = reporter.get_history(limit=5)
    assert len(history) == 1


@pytest.mark.anyio
async def test_polars_and_duckdb_export(tmp_path: Path) -> None:
    """Polars DataFrame ve DuckDB denetim izi dışa aktarımı."""
    reporter = HealthReporter(max_history=10)

    # Henüz rapor üretilmemişken boş Polars kontrolü
    empty_df = reporter.export_history_to_polars()
    assert isinstance(empty_df, pl.DataFrame)
    assert len(empty_df) == 0

    # Rapor üret
    await reporter.generate_report()

    # Polars aktarımı
    df = reporter.export_history_to_polars()
    assert isinstance(df, pl.DataFrame)
    assert len(df) == 1
    assert "overall_health" in df.columns
    assert "uptime_seconds" in df.columns

    # DuckDB aktarımı
    audit_db = tmp_path / "health_audit.duckdb"
    inserted = reporter.export_to_duckdb(db_path=str(audit_db))
    assert inserted == 1

    with duckdb.connect(str(audit_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM system_health_audit").fetchone()[0]
        assert count == 1
        row = conn.execute("SELECT overall_health, report_json FROM system_health_audit").fetchone()
        assert row[0] in (STATUS_HEALTHY, STATUS_DEGRADED)
        parsed = orjson.loads(row[1])
        assert "components" in parsed


def test_global_singleton() -> None:
    """Global singleton örneğinin erişilebilirliği."""
    assert health_reporter is not None
    assert isinstance(health_reporter, HealthReporter)
