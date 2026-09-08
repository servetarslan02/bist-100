"""MLflow Model Senkronizasyon Yöneticisi (services/ml/sync_mlflow.py) Kapsamlı Test Paketi.

8 denetim kuralına tam uyum:
- Sahte/mock veri olmadan kanonik deney şablon doğrulaması
- Dataclass serileştirme (to_dict, from_dict, to_orjson_bytes)
- Ağ erişimi yokluğunda fail-closed hata yönetimi
- DuckDB WAL denetim izi ve get_audit_as_polars()
- İş parçacığı güvenliği (threading.RLock)
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import polars as pl

if TYPE_CHECKING:
    from pathlib import Path

from services.ml.sync_mlflow import (
    ALL_EXPERIMENTS,
    MLflowSyncManager,
    SyncResult,
)


def test_sync_result_dataclass_serialization():
    """SyncResult veri modeli serileştirme ve from_dict testi."""
    res = SyncResult(
        success=True,
        synced_experiments=5,
        synced_runs=12,
        registered_models=4,
        errors=[],
        timestamp="2026-09-08T12:00:00Z",
    )
    r_dict = res.to_dict()
    assert r_dict["success"] is True
    assert r_dict["synced_experiments"] == 5
    assert r_dict["registered_models"] == 4
    assert isinstance(res.to_orjson_bytes(), bytes)

    restored = SyncResult.from_dict(r_dict)
    assert restored.success is True
    assert restored.synced_runs == 12
    assert restored.timestamp == "2026-09-08T12:00:00Z"


def test_all_experiments_structure():
    """ALL_EXPERIMENTS şablon listesinin şema ve zorunlu alan kontrolü."""
    assert len(ALL_EXPERIMENTS) >= 3
    for exp in ALL_EXPERIMENTS:
        assert "experiment_name" in exp
        assert "description" in exp
        assert "models" in exp
        for model in exp["models"]:
            assert "run_name" in model
            assert "tags" in model
            assert "params" in model
            assert "metrics" in model
            assert isinstance(model["params"], dict)
            assert isinstance(model["metrics"], dict)


def test_mlflow_sync_offline_fail_closed(tmp_path: Path, monkeypatch: Any):
    """Tracking sunucusu çevrimdışı olduğunda fail-closed hata yönetimi ve DuckDB denetim kaydı testi."""
    db_file = tmp_path / "sync_offline.duckdb"
    manager = MLflowSyncManager(tracking_uri="http://127.0.0.1:59999", duckdb_path=str(db_file))

    # Ağ çağrısının saatlerce soket beklemesini önlemek için bağlantı hatası fırlatan simülasyon
    def raise_conn_err():
        raise ConnectionError("MLflow Tracking sunucusuna erisilemedi (Offline)")

    monkeypatch.setattr(manager, "_get_client", raise_conn_err)

    # sync_all çağrısı patlamamalı, fail-closed SyncResult(success=False) dönmeli
    res = manager.sync_all()
    assert isinstance(res, SyncResult)
    assert res.success is False
    assert len(res.errors) >= 1
    assert "MLflow" in res.errors[0]

    # DuckDB'ye hata denetim kaydı işlenmiş olmalı
    df_audit = manager.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["success"][0] is False


def test_mlflow_sync_with_mocked_client(tmp_path: Path, monkeypatch: Any):
    """MLflow istemcisi mock'landığında deney ve modellerin başarıyla işlenmesi testi."""
    db_file = tmp_path / "sync_mock.duckdb"
    manager = MLflowSyncManager(duckdb_path=str(db_file))

    mock_client = MagicMock()
    mock_exp = MagicMock()
    mock_exp.experiment_id = "exp_101"
    mock_client.get_experiment_by_name.return_value = mock_exp

    manager._client = mock_client
    monkeypatch.setattr("services.ml.sync_mlflow.MLflowSyncManager._get_client", lambda self: mock_client)

    # Basit tek deneylik senaryo
    test_exp = [
        {
            "experiment_name": "test_exp",
            "description": "Test",
            "models": [
                {
                    "run_name": "TestModel_v1",
                    "registered_model": "TestModel",
                    "model_description": "Desc",
                    "tags": {"role": "TEST"},
                    "params": {"lr": 0.01},
                    "metrics": {"ic": 0.05},
                }
            ],
        }
    ]

    import mlflow

    mock_run_ctx = MagicMock()
    mock_run_ctx.__enter__.return_value = MagicMock()
    mock_run_ctx.__exit__.return_value = None

    monkeypatch.setattr(mlflow, "set_experiment", MagicMock())
    monkeypatch.setattr(mlflow, "start_run", MagicMock(return_value=mock_run_ctx))
    monkeypatch.setattr(mlflow, "set_tags", MagicMock())
    monkeypatch.setattr(mlflow, "log_params", MagicMock())
    monkeypatch.setattr(mlflow, "log_metrics", MagicMock())

    res = manager.sync_all(experiments=test_exp)
    assert isinstance(res, SyncResult)
    assert res.success is True
    assert res.synced_experiments == 1
    assert res.synced_runs == 1
    assert res.registered_models == 1

    df_audit = manager.get_audit_as_polars()
    assert df_audit.height >= 1
    assert df_audit["success"][0] is True


def test_duckdb_wal_save_and_polars_read(tmp_path: Path, monkeypatch: Any):
    """DuckDB WAL denetim kaydının yazılması ve Polars ile okunması testi."""
    db_file = tmp_path / "audit_test.duckdb"
    manager = MLflowSyncManager(tracking_uri="http://invalid-host:9999", duckdb_path=str(db_file))

    monkeypatch.setattr(manager, "_get_client", MagicMock(side_effect=ConnectionError("Sunucu yok")))

    manager.sync_all()
    df_audit = manager.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert "timestamp" in df_audit.columns
    assert "errors_json" in df_audit.columns


def test_thread_safety_sync_manager(tmp_path: Path, monkeypatch: Any):
    """Çoklu iş parçacığı altında MLflowSyncManager eşzamanlı erişim güvenliği testi."""
    db_file = tmp_path / "thread_test.duckdb"
    manager = MLflowSyncManager(tracking_uri="http://invalid-host:9999", duckdb_path=str(db_file))

    monkeypatch.setattr(manager, "_get_client", MagicMock(side_effect=ConnectionError("Sunucu yok")))

    def worker(_: int) -> bool:
        res = manager.sync_all()
        return res.success

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(worker, range(8)))

    assert len(results) == 8
    # Hepsi sunucu yokluğunda güvenle False dönmeli
    assert all(r is False for r in results)
