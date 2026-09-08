"""ALPHA BIST — ModelRegistry Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik modeller ve metadata
- ModelEntry dataclass serileştirme (to_dict, from_dict, orjson)
- register() ile model ekleme ve otomatik versiyonlama (v1 -> v2)
- promote() ile CHAMPION yapma ve önceki şampiyonu RETIRED etme
- reject() ve archive() durum yaşam döngüsü geçişleri
- list_models_polars() ve compare_versions_polars() Polars tabloları
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- Çoklu iş parçacığı (threading) eşzamanlı kayıt kilit testi
"""

import threading
from pathlib import Path
import polars as pl
import pytest

from services.ml.model_registry import (
    ModelEntry,
    ModelRegistry,
    ModelStatus,
)


def test_model_entry_dataclass_serialization():
    """ModelEntry serileştirme ve from_dict testi."""
    entry = ModelEntry(
        model_id="champion_lgb",
        version="v1",
        model_type="LIGHTGBM",
        status=ModelStatus.CANDIDATE.value,
        metrics={"ic": 0.12, "rmse": 0.05},
        hyperparams={"learning_rate": 0.05},
        features=["f1", "f2"],
        description="Ilk test modeli",
        author="quant_team",
    )
    d = entry.to_dict()
    assert d["model_id"] == "champion_lgb"
    assert d["status"] == "CANDIDATE"
    assert isinstance(entry.to_orjson_bytes(), bytes)

    restored = ModelEntry.from_dict(d)
    assert restored.model_id == "champion_lgb"
    assert restored.metrics["ic"] == 0.12
    assert "ModelEntry" in repr(restored)


def test_register_and_auto_versioning(tmp_path: Path):
    """Model kaydı ve otomatik sürüm artırma (v1 -> v2) testi."""
    reg_dir = tmp_path / "registry"
    db_file = tmp_path / "reg.duckdb"
    registry = ModelRegistry(registry_path=str(reg_dir), duckdb_path=str(db_file))

    dummy_model_v1 = {"weights": [1, 2, 3]}
    key1 = registry.register(
        model_id="lgb_model",
        model=dummy_model_v1,
        model_type="LIGHTGBM",
        metrics={"ic": 0.10},
    )
    assert key1 == "lgb_model:v1"

    dummy_model_v2 = {"weights": [4, 5, 6]}
    key2 = registry.register(
        model_id="lgb_model",
        model=dummy_model_v2,
        model_type="LIGHTGBM",
        metrics={"ic": 0.15},
    )
    assert key2 == "lgb_model:v2"


def test_promote_and_lifecycle_transitions(tmp_path: Path):
    """Model terfi etme, şampiyonluk devri ve durum geçişleri testi."""
    reg_dir = tmp_path / "registry"
    db_file = tmp_path / "reg.duckdb"
    registry = ModelRegistry(registry_path=str(reg_dir), duckdb_path=str(db_file))

    key1 = registry.register(model_id="alpha_net", model="m1", model_type="NN", metrics={"sharpe": 1.2})
    key2 = registry.register(model_id="alpha_net", model="m2", model_type="NN", metrics={"sharpe": 1.8})

    # v1'i şampiyon yap
    assert registry.promote(model_id="alpha_net", version="v1", reason="Ilk model") is True
    champ1 = registry.get_champion("alpha_net")
    assert champ1 is not None
    assert champ1["entry"].version == "v1"

    # v2'yi şampiyon yap -> v1 RETIRED olmalı
    assert registry.promote(model_id="alpha_net", version="v2", reason="Daha yuksek Sharpe") is True
    champ2 = registry.get_champion("alpha_net")
    assert champ2["entry"].version == "v2"

    v1_entry = registry.get_entry(key1)
    assert v1_entry is not None
    assert v1_entry.status == ModelStatus.RETIRED.value

    # reject ve archive testleri
    assert registry.reject("alpha_net", "v1", reason="Eski ve basarisiz") is True
    assert registry.get_entry(key1).status == ModelStatus.FAILED.value

    assert registry.archive("alpha_net", "v1") is True
    assert registry.get_entry(key1).status == ModelStatus.ARCHIVED.value


def test_list_and_compare_polars(tmp_path: Path):
    """Polars DataFrame model listeleme ve sürüm karşılaştırma testi."""
    reg_dir = tmp_path / "registry"
    db_file = tmp_path / "reg.duckdb"
    registry = ModelRegistry(registry_path=str(reg_dir), duckdb_path=str(db_file))

    registry.register(
        model_id="comp_model",
        model="m1",
        model_type="LGB",
        metrics={"ic": 0.08, "sharpe": 1.2},
        features=["a", "b"],
    )
    registry.register(
        model_id="comp_model",
        model="m2",
        model_type="LGB",
        metrics={"ic": 0.12, "sharpe": 1.5},
        features=["a", "b", "c"],
    )

    df_list = registry.list_models_polars(model_id="comp_model")
    assert isinstance(df_list, pl.DataFrame)
    assert df_list.height == 2

    df_diff = registry.compare_versions_polars("comp_model", "v1", "v2")
    assert isinstance(df_diff, pl.DataFrame)
    assert df_diff.height >= 2
    assert "metric" in df_diff.columns
    assert "pct_change" in df_diff.columns


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL denetim izi kaydetme ve Polars ile geri okuma testi."""
    reg_dir = tmp_path / "registry"
    db_file = tmp_path / "reg.duckdb"
    registry = ModelRegistry(registry_path=str(reg_dir), duckdb_path=str(db_file))

    registry.register(
        model_id="audit_model",
        model="test",
        model_type="CATBOOST",
        metrics={"ic": 0.11},
    )
    registry.promote(model_id="audit_model", version="v1", reason="Canliya alma")

    df_audit = registry.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 2
    assert "event_type" in df_audit.columns
    assert df_audit["event_type"][0] in ("PROMOTE", "REGISTER")


def test_thread_safety_model_registry(tmp_path: Path):
    """Çoklu iş parçacığı altında eşzamanlı kayıt güvenliği testi."""
    reg_dir = tmp_path / "registry"
    db_file = tmp_path / "reg.duckdb"
    registry = ModelRegistry(registry_path=str(reg_dir), duckdb_path=str(db_file))
    errors = []

    def worker(tid: int):
        try:
            for i in range(5):
                registry.register(
                    model_id=f"thread_model_{tid}",
                    model=f"obj_{i}",
                    model_type="LGB",
                    metrics={"i": i},
                )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(registry.list_models()) == 20
