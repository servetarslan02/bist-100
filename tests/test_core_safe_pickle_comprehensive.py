"""ALPHA BIST — services/core/safe_pickle kapsamlı test suite.

Test edilen bileşenler:
- ModelArtifactMeta: Denetim metadata veri modeli
- safe_pickle_dump(): Atomik pickle kaydetme + SHA-256
- safe_pickle_load(): SHA-256 doğrulamalı güvenli yükleme
- set_safe_pickle_duckdb_connection(): DuckDB bağlantı enjeksiyonu
- export_artifact_audit_to_polars(): Denetim geçmişi dışa aktarım
- clear_artifact_audit_duckdb(): Denetim tablosu temizleme
- to_orjson_bytes(): Hızlı JSON serileştirme
- Fail-Closed davranışları: Bozuk hash, eksik dosya, boş dosya
"""

from __future__ import annotations

import pickle
import threading
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import orjson
import polars as pl
import pytest

from services.core.safe_pickle import (
    ModelArtifactMeta,
    clear_artifact_audit_duckdb,
    export_artifact_audit_to_polars,
    read_artifact_audit_from_duckdb,
    safe_pickle_dump,
    safe_pickle_load,
    set_safe_pickle_duckdb_connection,
    set_safe_pickle_duckdb_path,
    to_orjson_bytes,
)


# ==============================================================================
# Test yardımcıları
# ==============================================================================


@pytest.fixture
def pkl_path(tmp_path: Path) -> Path:
    """Geçici pickle dosyası yolu."""
    return tmp_path / "test_model.pkl"


@pytest.fixture
def in_memory_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB bağlantısı."""
    conn = duckdb.connect(":memory:")
    set_safe_pickle_duckdb_connection(conn)
    yield conn
    try:
        clear_artifact_audit_duckdb()
    except Exception:
        pass
    conn.close()


# ==============================================================================
# to_orjson_bytes testleri
# ==============================================================================


class TestToOrjsonBytes:
    """to_orjson_bytes() yardımcı fonksiyon testleri."""

    def test_dict_serialization(self) -> None:
        data = {"key": "value", "count": 42}
        raw = to_orjson_bytes(data)
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["key"] == "value"

    def test_datetime_serialized_as_string(self) -> None:
        data = {"ts": datetime.now(UTC)}
        raw = to_orjson_bytes(data)
        parsed = orjson.loads(raw)
        assert isinstance(parsed["ts"], str)

    def test_nested_structure(self) -> None:
        data = {"list": [1, 2, 3], "nested": {"a": "b"}}
        raw = to_orjson_bytes(data)
        parsed = orjson.loads(raw)
        assert parsed["list"] == [1, 2, 3]

    def test_empty_dict(self) -> None:
        raw = to_orjson_bytes({})
        parsed = orjson.loads(raw)
        assert parsed == {}


# ==============================================================================
# ModelArtifactMeta veri modeli testleri
# ==============================================================================


class TestModelArtifactMeta:
    """ModelArtifactMeta dataclass testleri."""

    def _make_meta(
        self,
        action: str = "DUMP",
        file_path: str = "/tmp/model.pkl",
        file_size_bytes: int = 1024,
        sha256_hash: str = "abc123",
        is_verified: bool = True,
        elapsed_ms: float = 5.5,
    ) -> ModelArtifactMeta:
        return ModelArtifactMeta(
            action=action,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            sha256_hash=sha256_hash,
            is_verified=is_verified,
            elapsed_ms=elapsed_ms,
        )

    def test_creation_and_fields(self) -> None:
        meta = self._make_meta()
        assert meta.action == "DUMP"
        assert meta.is_verified is True
        assert meta.elapsed_ms == pytest.approx(5.5)

    def test_recorded_at_auto_set(self) -> None:
        meta = self._make_meta()
        assert meta.recorded_at is not None
        assert isinstance(meta.recorded_at, datetime)

    def test_to_dict(self) -> None:
        meta = self._make_meta()
        d = meta.to_dict()
        assert "action" in d
        assert "file_path" in d
        assert "sha256_hash" in d
        assert "recorded_at" in d
        assert isinstance(d["recorded_at"], str)  # ISO format

    def test_to_orjson_bytes(self) -> None:
        meta = self._make_meta()
        raw = meta.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["action"] == "DUMP"
        assert parsed["is_verified"] is True

    def test_repr(self) -> None:
        meta = self._make_meta(action="LOAD", file_path="/models/lgbm.pkl")
        r = repr(meta)
        assert "ModelArtifactMeta" in r
        assert "LOAD" in r

    def test_unverified_meta(self) -> None:
        meta = self._make_meta(is_verified=False)
        d = meta.to_dict()
        assert d["is_verified"] is False


# ==============================================================================
# safe_pickle_dump testleri
# ==============================================================================


class TestSafePickleDump:
    """safe_pickle_dump() atomik yazma testleri."""

    def test_basic_dump_creates_file(self, pkl_path: Path) -> None:
        """Temel nesne dump'ı dosyayı oluşturur."""
        obj = {"model": "lgbm", "accuracy": 0.95}
        safe_pickle_dump(obj, pkl_path)
        assert pkl_path.exists()

    def test_dump_creates_sha256_file(self, pkl_path: Path) -> None:
        """Dump işlemi SHA-256 hash dosyası oluşturur."""
        safe_pickle_dump({"test": True}, pkl_path)
        hash_path = pkl_path.with_suffix(".pkl.sha256")
        assert hash_path.exists()

    def test_dump_returns_hash_string(self, pkl_path: Path) -> None:
        """Dump işlemi SHA-256 hash döner."""
        file_hash = safe_pickle_dump({"data": 42}, pkl_path)
        assert isinstance(file_hash, str)
        assert len(file_hash) == 64  # SHA-256 hex 64 karakter

    def test_dump_various_objects(self, tmp_path: Path) -> None:
        """Farklı Python nesneleri dump edilebilir."""
        objects = [
            {"dict": "value"},
            [1, 2, 3, 4, 5],
            (1, "tuple", 3.14),
            {"nested": {"deep": [1, 2]}},
            42,
            "a string",
        ]
        for i, obj in enumerate(objects):
            path = tmp_path / f"obj_{i}.pkl"
            h = safe_pickle_dump(obj, path)
            assert len(h) == 64

    def test_dump_overwrites_existing(self, pkl_path: Path) -> None:
        """Mevcut dosyanın üzerine yazılabilir."""
        safe_pickle_dump({"v": 1}, pkl_path)
        h1 = safe_pickle_dump({"v": 2}, pkl_path)
        loaded = safe_pickle_load(pkl_path, verify_hash=True)
        assert loaded["v"] == 2

    def test_dump_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Ebeveyn dizinler yoksa oluşturulur."""
        nested_path = tmp_path / "a" / "b" / "c" / "model.pkl"
        safe_pickle_dump({"test": True}, nested_path)
        assert nested_path.exists()

    def test_dump_with_custom_protocol(self, pkl_path: Path) -> None:
        """Belirtilen pickle protokolüyle dump çalışır."""
        safe_pickle_dump({"data": [1, 2, 3]}, pkl_path, protocol=2)
        assert pkl_path.exists()


# ==============================================================================
# safe_pickle_load testleri
# ==============================================================================


class TestSafePickleLoad:
    """safe_pickle_load() hash doğrulamalı yükleme testleri."""

    def test_basic_load_round_trip(self, pkl_path: Path) -> None:
        """Dump → Load döngüsü veriyi doğru şekilde korur."""
        original = {"model": "catboost", "score": 0.88, "features": [1, 2, 3]}
        safe_pickle_dump(original, pkl_path)
        loaded = safe_pickle_load(pkl_path)
        assert loaded == original

    def test_load_verifies_hash(self, pkl_path: Path) -> None:
        """Geçerli hash ile yükleme başarılı."""
        safe_pickle_dump({"ok": True}, pkl_path)
        loaded = safe_pickle_load(pkl_path, verify_hash=True)
        assert loaded["ok"] is True

    def test_load_without_verification(self, pkl_path: Path) -> None:
        """Hash doğrulaması devre dışı bırakılarak yükleme."""
        safe_pickle_dump({"ok": True}, pkl_path)
        loaded = safe_pickle_load(pkl_path, verify_hash=False)
        assert loaded["ok"] is True

    def test_load_missing_file_raises_fnf(self, tmp_path: Path) -> None:
        """Eksik dosya FileNotFoundError fırlatır."""
        missing = tmp_path / "nonexistent.pkl"
        with pytest.raises(FileNotFoundError):
            safe_pickle_load(missing)

    def test_load_empty_file_raises_value_error(self, pkl_path: Path) -> None:
        """Boş dosya ValueError fırlatır."""
        pkl_path.write_bytes(b"")
        with pytest.raises(ValueError, match="boş"):
            safe_pickle_load(pkl_path)

    def test_load_tampered_file_raises_value_error(self, pkl_path: Path) -> None:
        """Bütünlüğü bozulmuş dosya ValueError fırlatır (Fail-Closed)."""
        safe_pickle_dump({"original": True}, pkl_path)
        # Dosyayı değiştir (tamper)
        original_data = pkl_path.read_bytes()
        pkl_path.write_bytes(original_data[:-10] + b"\x00" * 10)
        with pytest.raises((ValueError, pickle.UnpicklingError)):
            safe_pickle_load(pkl_path, verify_hash=True)

    def test_load_complex_objects(self, pkl_path: Path) -> None:
        """Karmaşık nesneler round-trip korumasıyla yüklenir."""
        import numpy as np
        original = {
            "matrix": [[1.0, 2.0], [3.0, 4.0]],
            "labels": ["A", "B", "C"],
            "params": {"n_estimators": 100, "learning_rate": 0.1},
        }
        safe_pickle_dump(original, pkl_path)
        loaded = safe_pickle_load(pkl_path)
        assert loaded["params"]["n_estimators"] == 100
        assert loaded["labels"] == ["A", "B", "C"]


# ==============================================================================
# DuckDB denetim testleri
# ==============================================================================


class TestDuckDBAudit:
    """DuckDB model artefakt denetim tablosu testleri."""

    def test_dump_creates_audit_record(self, pkl_path: Path, in_memory_conn: duckdb.DuckDBPyConnection) -> None:
        """Dump işlemi denetim kaydı oluşturur."""
        safe_pickle_dump({"model": True}, pkl_path)
        df = export_artifact_audit_to_polars()
        assert isinstance(df, pl.DataFrame)
        assert len(df) >= 1

    def test_audit_record_has_correct_action(self, pkl_path: Path, in_memory_conn: duckdb.DuckDBPyConnection) -> None:
        """DUMP eylemi denetim kaydında doğru görünür."""
        safe_pickle_dump({"v": 1}, pkl_path)
        df = export_artifact_audit_to_polars()
        assert "DUMP" in df["action"].to_list()

    def test_load_creates_audit_record(self, pkl_path: Path, in_memory_conn: duckdb.DuckDBPyConnection) -> None:
        """Load işlemi LOAD denetim kaydı oluşturur."""
        safe_pickle_dump({"v": 1}, pkl_path)
        safe_pickle_load(pkl_path)
        df = export_artifact_audit_to_polars()
        assert "LOAD" in df["action"].to_list()

    def test_audit_has_correct_columns(self, pkl_path: Path, in_memory_conn: duckdb.DuckDBPyConnection) -> None:
        """Denetim tablosu beklenen sütunları içerir."""
        safe_pickle_dump({"v": 1}, pkl_path)
        df = export_artifact_audit_to_polars()
        required = {"action", "file_path", "sha256_hash", "is_verified", "elapsed_ms"}
        assert required.issubset(set(df.columns))

    def test_audit_is_verified_flag(self, pkl_path: Path, in_memory_conn: duckdb.DuckDBPyConnection) -> None:
        """Başarılı dump/load işlemlerinde is_verified True."""
        safe_pickle_dump({"v": 1}, pkl_path)
        df = export_artifact_audit_to_polars()
        assert all(df["is_verified"].to_list())


# ==============================================================================
# Thread-safety testleri
# ==============================================================================


class TestThreadSafety:
    """safe_pickle eş zamanlı erişim güvenliği testleri."""

    def test_concurrent_dump_different_files(self, tmp_path: Path) -> None:
        """Farklı dosyalara eş zamanlı dump race condition vermez."""
        errors = []

        def worker(i: int) -> None:
            try:
                path = tmp_path / f"model_{i}.pkl"
                safe_pickle_dump({"worker": i, "data": list(range(100))}, path)
                loaded = safe_pickle_load(path)
                assert loaded["worker"] == i
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_read_after_write(self, pkl_path: Path) -> None:
        """Eş zamanlı okuma + yazma sonrası veri tutarlılığı."""
        safe_pickle_dump({"version": 1}, pkl_path)
        errors = []

        def reader() -> None:
            try:
                obj = safe_pickle_load(pkl_path)
                assert "version" in obj
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
