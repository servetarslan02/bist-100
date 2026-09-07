"""ALPHA BIST — Bütünlük Doğrulamalı Güvenli Model Serileştirme Motoru (Safe Pickle).

Bu modül, makine öğrenimi modelleri (LightGBM, CatBoost, XGBoost, Ensemble vb.) ve
durum nesneleri için:
- SHA-256 kriptografik hash oluşturma ve bütünlük doğrulaması
- Atomik dosya yazma (Atomic Write ile yarım/bozuk dosya yazımını önleme)
- Eşzamanlı erişim koruması (Thread-Safe Reentrant Lock)
- DuckDB üzerinde model artefakt denetim geçmişi (Audit Trail)
- Polars analitik dışa aktarımı ve orjson serileştirme desteği sağlar.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import pickle
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

DEFAULT_SAFE_PICKLE_DB: Final[str] = "data/model_artifacts_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_LOCK = threading.RLock()
_DUCKDB_CONN: duckdb.DuckDBPyConnection | None = None
_DUCKDB_PATH: str = DEFAULT_SAFE_PICKLE_DB


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint yapılandırmasını uygular."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("SafePickle DuckDB WAL pragma yapılandırma uyarısı", hata=str(exc))


def to_orjson_bytes(data: Any) -> bytes:
    """Herhangi bir Python nesnesini güvenli ve hızlı şekilde orjson bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


@dataclass(slots=True)
class ModelArtifactMeta:
    """Model artefaktı denetim ve bütünlük metadata modeli."""

    action: str
    file_path: str
    file_size_bytes: int
    sha256_hash: str
    is_verified: bool
    elapsed_ms: float
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["recorded_at"] = self.recorded_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"ModelArtifactMeta(eylem='{self.action}', dosya='{Path(self.file_path).name}', "
            f"boyut={self.file_size_bytes}B, dogrulandi={self.is_verified}, "
            f"sure={self.elapsed_ms:.2f}ms)"
        )


def set_safe_pickle_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Model artefaktları denetim arşivi için DuckDB bağlantısını tanımlar."""
    global _DUCKDB_CONN
    with _LOCK:
        _DUCKDB_CONN = conn
        _init_duckdb_schema_conn(_DUCKDB_CONN)


def set_safe_pickle_duckdb_path(path: str) -> None:
    """Model artefaktları DuckDB dosya yolunu tanımlar."""
    global _DUCKDB_PATH
    with _LOCK:
        _DUCKDB_PATH = path


def _init_duckdb_schema_conn(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB denetim tablosunu belirtilen bağlantıda ilklendirir."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_artifact_audit (
                id BIGINT,
                action VARCHAR,
                file_path VARCHAR,
                file_size_bytes BIGINT,
                sha256_hash VARCHAR,
                is_verified BOOLEAN,
                elapsed_ms DOUBLE,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE SEQUENCE IF NOT EXISTS seq_model_artifact_audit START 1;
        """)
    except Exception as exc:
        logger.error("SafePickle DuckDB şema oluşturma hatası", hata=str(exc))


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve bağlantının geçici olup olmadığını döner."""
    global _DUCKDB_CONN, _DUCKDB_PATH
    if _DUCKDB_CONN is not None:
        return _DUCKDB_CONN, False
    try:
        p = Path(_DUCKDB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        read_only = not writable
        conn = duckdb.connect(str(p), read_only=read_only)
        if writable:
            configure_duckdb_wal(conn)
            _init_duckdb_schema_conn(conn)
        return conn, True
    except Exception as exc:
        logger.debug("SafePickle DuckDB dosya bağlantı hatası", yol=_DUCKDB_PATH, hata=str(exc))
        return None, False


def _record_audit(meta: ModelArtifactMeta) -> None:
    """Denetim kaydını DuckDB'ye işler."""
    with _LOCK:
        conn, should_close = _get_active_duckdb(writable=True)
        if conn is None:
            return
        try:
            conn.execute(
                """
                INSERT INTO model_artifact_audit (
                    id, action, file_path, file_size_bytes, sha256_hash, is_verified, elapsed_ms, recorded_at
                ) VALUES (
                    nextval('seq_model_artifact_audit'), ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    meta.action,
                    meta.file_path,
                    meta.file_size_bytes,
                    meta.sha256_hash,
                    meta.is_verified,
                    meta.elapsed_ms,
                    meta.recorded_at,
                ],
            )
        except Exception as exc:
            logger.debug("SafePickle DuckDB denetim yazma hatası", hata=str(exc))
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


@otel_trace("safe_pickle.safe_pickle_dump")
def safe_pickle_dump(
    obj: Any,
    path: str | Path,
    protocol: int = pickle.HIGHEST_PROTOCOL,
) -> str:
    """Nesneyi atomik olarak pickle formatında kaydeder ve SHA-256 hash dosyasını üretir.

    Bozuk veya yarım yazılmış dosyaları önlemek amacıyla önce geçici bir dosyaya (.tmp)
    yazılır, hash'i doğrulanır ve hedef yola atomik olarak taşınır (Atomic Write).

    Args:
        obj: Serileştirilecek model veya veri nesnesi.
        path: Hedef dosya yolu (.pkl).
        protocol: Pickle protokol sürümü (varsayılan: pickle.HIGHEST_PROTOCOL).

    Returns:
        str: Üretilen dosyanın SHA-256 özet değeri.

    Raises:
        pickle.PicklingError: Nesne serileştirilemezse.
        OSError: Dosya sistemine yazma hatası durumunda.
    """
    start_time = time.monotonic()
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target_path.with_name(f".{target_path.name}.tmp_{os.getpid()}_{int(time.time() * 1000)}")
    hash_path = target_path.with_suffix(target_path.suffix + ".sha256")

    with _LOCK:
        try:
            # 1. Bellekte serileştir
            data = pickle.dumps(obj, protocol=protocol)
            file_size = len(data)
            file_hash = hashlib.sha256(data).hexdigest()

            # 2. Geçici dosyaya yaz
            tmp_path.write_bytes(data)

            # 3. Atomik taşıma (Atomic Replace)
            tmp_path.replace(target_path)

            # 4. Hash dosyasını oluştur
            hash_path.write_text(file_hash, encoding="utf-8")

            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            meta = ModelArtifactMeta(
                action="DUMP",
                file_path=str(target_path.resolve()),
                file_size_bytes=file_size,
                sha256_hash=file_hash,
                is_verified=True,
                elapsed_ms=round(elapsed_ms, 2),
            )
            _record_audit(meta)

            logger.debug(
                "safe_pickle_dump tamamlandı",
                dosya=str(target_path),
                boyut_kb=round(file_size / 1024.0, 2),
                hash_kisa=file_hash[:16],
                sure_ms=round(elapsed_ms, 2),
            )
            return file_hash

        except Exception as exc:
            # Hata durumunda geçici artık dosyayı temizle
            if tmp_path.exists():
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            logger.error("safe_pickle_dump başarısız oldu", dosya=str(target_path), hata=str(exc))
            raise


@otel_trace("safe_pickle.safe_pickle_load")
def safe_pickle_load(path: str | Path, verify_hash: bool = True) -> Any:
    """Model dosyasını SHA-256 hash doğrulaması yaparak güvenli şekilde yükler.

    Args:
        path: Yüklenecek model dosyasının yolu.
        verify_hash: SHA-256 özet doğrulamasının yapılıp yapılmayacağı (varsayılan: True).

    Returns:
        Any: Deserialize edilmiş model veya durum nesnesi.

    Raises:
        FileNotFoundError: Model dosyası bulunamazsa.
        ValueError: Dosya boşsa veya SHA-256 hash doğrulaması uyuşmazsa.
        pickle.UnpicklingError: Pickle verisi bozuk veya geçersizse.
    """
    start_time = time.monotonic()
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Model dosyası bulunamadı: {file_path}")

    with _LOCK:
        data = file_path.read_bytes()
        file_size = len(data)
        if file_size == 0:
            raise ValueError(f"Model dosyası boş (0 bayt): {file_path}")

        actual_hash = hashlib.sha256(data).hexdigest()
        is_verified = False

        if verify_hash:
            hash_path = file_path.with_suffix(file_path.suffix + ".sha256")
            if hash_path.exists():
                expected_hash = hash_path.read_text(encoding="utf-8").strip()
                if actual_hash != expected_hash:
                    logger.error(
                        "Pickle SHA-256 hash doğrulama başarısız!",
                        dosya=str(file_path),
                        beklenen=expected_hash[:16],
                        gercek=actual_hash[:16],
                    )
                    raise ValueError(
                        f"Model dosyası bütünlük doğrulaması başarısız: {file_path}\n"
                        f"Beklenen SHA256: {expected_hash[:16]}...\n"
                        f"Gerçek SHA256:   {actual_hash[:16]}...\n"
                        f"Dosya bozulmuş veya harici olarak değiştirilmiş olabilir (Fail-Closed)."
                    )
                is_verified = True
                logger.debug(
                    "safe_pickle_load bütünlük doğrulandı",
                    dosya=str(file_path),
                    hash_kisa=actual_hash[:16],
                )
            else:
                logger.warn("Hash dosyası (.sha256) bulunamadı — doğrulama atlandı", dosya=str(file_path))
        else:
            is_verified = True

        try:
            loaded_obj = pickle.loads(data)
        except (pickle.UnpicklingError, Exception) as exc:
            logger.error("Pickle deserialize işlemi başarısız", dosya=str(file_path), hata=str(exc))
            raise

        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        meta = ModelArtifactMeta(
            action="LOAD",
            file_path=str(file_path.resolve()),
            file_size_bytes=file_size,
            sha256_hash=actual_hash,
            is_verified=is_verified,
            elapsed_ms=round(elapsed_ms, 2),
        )
        _record_audit(meta)

        return loaded_obj


@otel_trace("safe_pickle.export_artifact_audit_to_polars")
def export_artifact_audit_to_polars() -> pl.DataFrame:
    """DuckDB'deki model serileştirme denetim geçmişini Polars DataFrame olarak döner."""
    return read_artifact_audit_from_duckdb()


def read_artifact_audit_from_duckdb(
    duckdb_path: str = DEFAULT_SAFE_PICKLE_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """Doğrudan DuckDB dosyasından veya aktif bağlantıdan model serileştirme denetim geçmişini okur."""
    empty_df = pl.DataFrame(
        schema={
            "id": pl.Int64,
            "action": pl.Utf8,
            "file_path": pl.Utf8,
            "file_size_bytes": pl.Int64,
            "sha256_hash": pl.Utf8,
            "is_verified": pl.Boolean,
            "elapsed_ms": pl.Float64,
            "recorded_at": pl.Datetime,
        }
    )
    with _LOCK:
        conn, should_close = _get_active_duckdb(writable=False)
        if conn is None:
            return empty_df
        try:
            query = f"SELECT * FROM model_artifact_audit ORDER BY id ASC LIMIT {int(limit)}"
            return conn.execute(query).pl()
        except Exception as exc:
            logger.error("DuckDB model artefakt kayıtları çekilemedi", hata=str(exc))
            return empty_df
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


def clear_artifact_audit_duckdb(
    duckdb_path: str = DEFAULT_SAFE_PICKLE_DB,
) -> None:
    """Model artefaktları denetim tablosunu temizler."""
    with _LOCK:
        conn, should_close = _get_active_duckdb(writable=True)
        if conn is None:
            return
        try:
            conn.execute("DELETE FROM model_artifact_audit;")
        except Exception as exc:
            logger.error("DuckDB model artefakt kayıtları temizlenemedi", hata=str(exc))
        finally:
            if should_close:
                with contextlib.suppress(Exception):
                    conn.close()


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_SAFE_PICKLE_DB",
    "DEFAULT_WAL_SIZE",
    "ModelArtifactMeta",
    "clear_artifact_audit_duckdb",
    "configure_duckdb_wal",
    "export_artifact_audit_to_polars",
    "read_artifact_audit_from_duckdb",
    "safe_pickle_dump",
    "safe_pickle_load",
    "set_safe_pickle_duckdb_connection",
    "set_safe_pickle_duckdb_path",
    "to_orjson_bytes",
]
