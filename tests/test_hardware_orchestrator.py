"""ALPHA BIST — Donanım Orkestratörü (Hardware Orchestrator) Birim Testleri."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import duckdb
import orjson
import polars as pl

from services.core.hardware_orchestrator import (
    HardwareOrchestrator,
    HardwareProfile,
    SSDThrottledWriter,
    hardware_orchestrator,
)


def test_hardware_profile_model() -> None:
    """HardwareProfile veri modeli, serileştirme ve metot testleri."""
    profile = HardwareProfile(
        device_type="cpu",
        gpu_name="N/A",
        gpu_vram_gb=0.0,
        cuda_version=None,
        total_ram_gb=16.0,
        available_ram_gb=8.5,
        cpu_cores=8,
        ssd_free_gb=120.0,
        ssd_write_buffer_enabled=True,
    )

    d = profile.to_dict()
    assert d["device_type"] == "cpu"
    assert d["total_ram_gb"] == 16.0
    assert d["ssd_write_buffer_enabled"] is True

    raw_bytes = profile.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)
    parsed = orjson.loads(raw_bytes)
    assert parsed["cpu_cores"] == 8

    repr_str = repr(profile)
    assert "HardwareProfile" in repr_str
    assert "cpu" in repr_str


def test_hardware_orchestrator_properties() -> None:
    """HardwareOrchestrator temel durum ve donanım profili alma."""
    orchestrator = HardwareOrchestrator(enable_ssd_writer=False)

    assert orchestrator.device in ("cuda", "cpu")
    assert isinstance(orchestrator.is_gpu_available(), bool)

    profile = orchestrator.get_hardware_profile()
    assert isinstance(profile, HardwareProfile)
    assert profile.cpu_cores >= 1
    assert profile.total_ram_gb > 0.0
    assert profile.available_ram_gb >= 0.0
    assert profile.ssd_free_gb >= 0.0

    repr_str = repr(orchestrator)
    assert "HardwareOrchestrator" in repr_str


def test_ml_model_params_generation() -> None:
    """CatBoost, XGBoost ve LightGBM model parametrelerinin üretilmesi."""
    orchestrator = HardwareOrchestrator(enable_ssd_writer=False)

    # CatBoost
    cb_params = orchestrator.get_catboost_params({"iterations": 100})
    assert cb_params["iterations"] == 100
    assert "task_type" in cb_params

    # XGBoost
    xgb_params = orchestrator.get_xgboost_params({"max_depth": 6})
    assert xgb_params["max_depth"] == 6
    assert "tree_method" in xgb_params
    assert "device" in xgb_params

    # LightGBM
    lgb_params = orchestrator.get_lightgbm_params({"learning_rate": 0.05})
    assert lgb_params["learning_rate"] == 0.05
    assert "n_jobs" in lgb_params
    assert lgb_params["n_jobs"] >= 1


def test_ssd_throttled_writer_flow(tmp_path: Path) -> None:
    """SSDThrottledWriter kuyruklama, blok flush ve kapatma."""
    writer = SSDThrottledWriter(flush_interval_sec=10.0, max_buffer_size=100)
    assert writer.is_running is True

    target_txt = tmp_path / "test_buffered.txt"
    target_bin = tmp_path / "test_buffered.bin"

    # Metin kuyruklama
    writer.enqueue_write(target_txt, "TICK_1_GARAN\n", append=True)
    writer.enqueue_write(target_txt, "TICK_2_THYAO\n", append=True)

    # Bayt kuyruklama
    writer.enqueue_write(target_bin, b"BINARY_DATA_BLOCK\n", append=True)

    stats = writer.get_stats()
    assert isinstance(stats["pending_queue_size"], int)

    # Flush işlemi
    writer.flush()
    assert target_txt.exists()
    assert target_bin.exists()

    content = target_txt.read_text(encoding="utf-8")
    assert "TICK_1_GARAN" in content
    assert "TICK_2_THYAO" in content

    bin_content = target_bin.read_bytes()
    assert b"BINARY_DATA_BLOCK" in bin_content

    stats_after = writer.get_stats()
    assert stats_after["total_flushes"] >= 1
    assert stats_after["total_mb_written"] >= 0.0

    writer.shutdown()
    assert writer.is_running is False


def test_polars_and_duckdb_integration(tmp_path: Path) -> None:
    """Polars DataFrame ve DuckDB denetim izi dışa aktarımı."""
    orchestrator = HardwareOrchestrator(enable_ssd_writer=False)

    # Polars
    df = orchestrator.export_profile_to_polars()
    assert isinstance(df, pl.DataFrame)
    assert len(df) == 1
    assert "device_type" in df.columns
    assert "cpu_cores" in df.columns
    assert "total_ram_gb" in df.columns

    # DuckDB
    audit_db = tmp_path / "hardware_audit.duckdb"
    inserted = orchestrator.export_profile_to_duckdb(db_path=str(audit_db))
    assert inserted == 1

    with duckdb.connect(str(audit_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM hardware_profile_audit").fetchone()[0]
        assert count == 1
        row = conn.execute("SELECT device_type, cpu_cores, profile_json FROM hardware_profile_audit").fetchone()
        assert row[0] in ("cuda", "cpu")
        assert row[1] >= 1
        parsed = orjson.loads(row[2])
        assert "available_ram_gb" in parsed


def test_global_singleton() -> None:
    """Global singleton örneğinin erişilebilirliği."""
    assert hardware_orchestrator is not None
    assert hardware_orchestrator.device in ("cuda", "cpu")
    assert hardware_orchestrator.ssd_writer is not None
