"""ALPHA BIST — Donanım Kaynak Yöneticisi (Hardware Profile) Birim Testleri."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import duckdb
import orjson
import polars as pl

from services.core.hardware_profile import (
    HardwareResourceManager,
    HardwareSpecs,
    ResourceLimits,
    hardware_manager,
)


def test_hardware_specs_model() -> None:
    """HardwareSpecs veri modeli, serileştirme ve metot testleri."""
    specs = HardwareSpecs(
        cpu_cores_logical=16,
        cpu_cores_physical=8,
        ram_total_gb=32.0,
        ram_available_gb=18.5,
        gpu_name="NVIDIA RTX 4080",
        gpu_total_vram_mb=12288.0,
        gpu_available=True,
        cuda_driver_version="550.54",
        ssd_mount="C:",
    )

    d = specs.to_dict()
    assert d["cpu_cores_logical"] == 16
    assert d["ram_total_gb"] == 32.0
    assert d["gpu_available"] is True

    raw_bytes = specs.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)
    parsed = orjson.loads(raw_bytes)
    assert parsed["gpu_name"] == "NVIDIA RTX 4080"

    repr_str = repr(specs)
    assert "HardwareSpecs" in repr_str
    assert "RTX 4080" in repr_str


def test_resource_limits_model() -> None:
    """ResourceLimits veri modeli, serileştirme ve metot testleri."""
    limits = ResourceLimits(
        max_cpu_threads=4,
        max_gpu_vram_mb=3072.0,
        gpu_vram_fraction=0.25,
        max_duckdb_memory_mb=1024,
        max_cache_items=5000,
        process_priority="BELOW_NORMAL",
        ssd_write_limit_mbps=128,
    )

    d = limits.to_dict()
    assert d["max_cpu_threads"] == 4
    assert d["max_duckdb_memory_mb"] == 1024

    raw_bytes = limits.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)
    parsed = orjson.loads(raw_bytes)
    assert parsed["process_priority"] == "BELOW_NORMAL"

    repr_str = repr(limits)
    assert "ResourceLimits" in repr_str
    assert "1024MB" in repr_str


def test_hardware_resource_manager_detection_and_limits() -> None:
    """HardwareResourceManager başlatma, otomatik tarama ve limit üretimi."""
    manager = HardwareResourceManager()

    assert manager.specs.cpu_cores_logical >= 1
    assert manager.specs.cpu_cores_physical >= 1
    assert manager.specs.ram_total_gb > 0.0
    assert manager.specs.ram_available_gb >= 0.0

    assert 2 <= manager.limits.max_cpu_threads <= 4
    assert manager.limits.max_duckdb_memory_mb in (512, 1024)
    assert manager.limits.ssd_write_limit_mbps == 128


def test_apply_profile() -> None:
    """apply_profile ile ortam değişkenlerinin ve sınırların uygulanması."""
    manager = HardwareResourceManager()
    actions = manager.apply_profile()

    assert "cpu_threads_set" in actions
    assert "duckdb_max_memory" in actions
    assert "ssd_limit" in actions
    assert manager._is_applied is True

    # Ortam değişkenleri kontrolü
    assert os.environ["POLARS_MAX_THREADS"] == str(manager.limits.max_cpu_threads)
    assert os.environ["OMP_NUM_THREADS"] == str(manager.limits.max_cpu_threads)


def test_optimal_device_selection() -> None:
    """Görev türü ve batch büyüklüğüne göre cihaz seçimi."""
    manager = HardwareResourceManager()

    # Küçük batch çıkarımlarda PCIe gecikmesi olmaması için daima CPU
    dev_small = manager.get_optimal_device_for_task(batch_size=500, task_type="inference")
    assert dev_small == "cpu"

    # Büyük batch veya eğitimde GPU varsa CUDA, yoksa CPU
    dev_large = manager.get_optimal_device_for_task(batch_size=20_000, task_type="inference")
    expected_large = "cuda" if manager.specs.gpu_available else "cpu"
    assert dev_large == expected_large

    dev_training = manager.get_optimal_device_for_task(batch_size=100, task_type="training")
    expected_training = "cuda" if manager.specs.gpu_available else "cpu"
    assert dev_training == expected_training


def test_status_report() -> None:
    """get_status_report ile kapsamlı durum çıktısının üretilmesi."""
    manager = HardwareResourceManager()
    report = manager.get_status_report()

    assert "specs" in report
    assert "limits" in report
    assert "runtime_state" in report
    assert "cpu_logical_cores" in report["specs"]
    assert "duckdb_memory_cap" in report["limits"]
    assert "current_process_ram_mb" in report["runtime_state"]


def test_polars_and_duckdb_export(tmp_path: Path) -> None:
    """Polars DataFrame ve DuckDB denetim izi dışa aktarımı."""
    manager = HardwareResourceManager()

    # Polars
    df_specs = manager.export_specs_to_polars()
    assert isinstance(df_specs, pl.DataFrame)
    assert len(df_specs) == 1
    assert "cpu_cores_logical" in df_specs.columns

    df_limits = manager.export_limits_to_polars()
    assert isinstance(df_limits, pl.DataFrame)
    assert len(df_limits) == 1
    assert "max_cpu_threads" in df_limits.columns

    # DuckDB
    audit_db = tmp_path / "hardware_profile_audit.duckdb"
    inserted = manager.export_to_duckdb(db_path=str(audit_db))
    assert inserted == 1

    with duckdb.connect(str(audit_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM hardware_resource_audit").fetchone()[0]
        assert count == 1
        row = conn.execute("SELECT cpu_logical, max_cpu_threads, specs_json FROM hardware_resource_audit").fetchone()
        assert row[0] >= 1
        assert row[1] >= 2
        specs_data = orjson.loads(row[2])
        assert "ram_total_gb" in specs_data


def test_global_singleton() -> None:
    """Global singleton örneğinin geçerliliği."""
    assert hardware_manager is not None
    assert isinstance(hardware_manager.specs, HardwareSpecs)
    assert isinstance(hardware_manager.limits, ResourceLimits)
