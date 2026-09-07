"""ALPHA BIST — Model Kalıcılık ve Üstveri Yönetimi (Model Persistence).

FAZ 5.1: Model üstverilerinin (metadata, metrikler, özellik sözleşmeleri, şampiyon durumu)
PostgreSQL ve çevrimdışı yerel DuckDB üzerinde kalıcı olarak saklanması ve yönetimi.
- Model sürümleme ve aday (candidate) / şampiyon (champion) durum geçişleri
- Özellik sözleşmesi (feature contract) hash doğrulaması
- PostgreSQL bağlantısı kesildiğinde yerel DuckDB otomatik yedeği ve tam çevrimdışı şampiyon sorgulama
- Polars entegrasyonu ile model sürüm ve metrik analitiği
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import orjson
import polars as pl
import structlog

try:
    from services.core.otel import otel_trace
except ImportError:
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("alpha-bist.model_persistence")

        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                if asyncio.iscoroutinefunction(func):
                    @functools.wraps(func)
                    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                        with tracer.start_as_current_span(span_name):
                            return await func(*args, **kwargs)
                    return async_wrapper

                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    with tracer.start_as_current_span(span_name):
                        return func(*args, **kwargs)
                return sync_wrapper
            return decorator
    except ImportError:
        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func
            return decorator

logger = structlog.get_logger(__name__)

DEFAULT_MODEL_METADATA_DB_PATH: Final[str] = "data/model_metadata.duckdb"

_duckdb_lock: Final[threading.RLock] = threading.RLock()


def _has_pg_env() -> bool:
    """PostgreSQL bağlantısının yapılandırılıp yapılandırılmadığını doğrular."""
    return bool(
        "services.core.database" in sys.modules
        or os.getenv("PG_HOST")
        or os.getenv("POSTGRES_HOST")
    )


def configure_duckdb_wal(conn: Any) -> None:
    """DuckDB WAL boyut ve checkpoint ayarlarını SSD koruması için yapılandırır."""
    with contextlib.suppress(Exception):
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")


class ModelPersistence:
    """Model üstveri kalıcılık ve sürüm yönetim motoru."""

    def __repr__(self) -> str:
        return "ModelPersistence(pg_ve_duckdb_hibrit=True, failover=DuckDB)"

    @staticmethod
    def _save_to_local_duckdb(
        model_name: str,
        version: str,
        target_horizon: int,
        feature_names: list[str],
        cs_features: list[str],
        confidence_score: float,
        validation_metrics: dict[str, Any],
        artifact_path: str,
        status: str = "CANDIDATE",
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> None:
        """PostgreSQL erişilemediğinde veya çevrimdışı çalışırken üstveriyi yerel DuckDB defterine yazar."""
        target = Path(db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size == 0:
            with contextlib.suppress(OSError):
                target.unlink()

        try:
            with _duckdb_lock, duckdb.connect(db_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS model_versions_offline (
                        model_name VARCHAR NOT NULL,
                        version VARCHAR NOT NULL,
                        target_horizon INT,
                        feature_names_json VARCHAR,
                        cs_features_json VARCHAR,
                        confidence_score DOUBLE,
                        metrics_json VARCHAR,
                        artifact_path VARCHAR,
                        status VARCHAR DEFAULT 'CANDIDATE',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (model_name, version)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions_offline (status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_model_versions_created ON model_versions_offline (created_at DESC);")
                conn.execute(
                    """
                    INSERT INTO model_versions_offline
                    (model_name, version, target_horizon, feature_names_json, cs_features_json,
                     confidence_score, metrics_json, artifact_path, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (model_name, version) DO UPDATE SET
                        target_horizon = EXCLUDED.target_horizon,
                        feature_names_json = EXCLUDED.feature_names_json,
                        cs_features_json = EXCLUDED.cs_features_json,
                        confidence_score = EXCLUDED.confidence_score,
                        metrics_json = EXCLUDED.metrics_json,
                        artifact_path = EXCLUDED.artifact_path,
                        status = EXCLUDED.status,
                        created_at = now()
                    """,
                    [
                        model_name,
                        version,
                        target_horizon,
                        orjson.dumps(feature_names).decode("utf-8"),
                        orjson.dumps(cs_features).decode("utf-8"),
                        float(confidence_score),
                        orjson.dumps(validation_metrics, default=str).decode("utf-8"),
                        artifact_path,
                        status,
                    ],
                )
        except Exception as exc:
            logger.debug("duckdb_model_metadata_kayit_hatasi", hata=str(exc))

    @classmethod
    @otel_trace("model_persistence.save_model_metadata")
    async def save_model_metadata(
        cls,
        model_name: str,
        version: str,
        model_obj: Any,
        artifact_path: str,
        training_data_start: str | None = None,
        training_data_end: str | None = None,
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> int | None:
        """Model üstverisini PostgreSQL ve yerel DuckDB üzerine kaydeder.

        Args:
            model_name: Model adı (örn: "alpha_bist_lgbm").
            version: Model sürüm etiketi (örn: "v4.5_fold3").
            model_obj: Eğitilmiş model nesnesi (TrainedModel, MultiHorizonModel vb.).
            artifact_path: Diskteki model serileştirme dosya yolu.
            training_data_start: Eğitim veri seti başlangıç tarihi.
            training_data_end: Eğitim veri seti bitiş tarihi.
            db_path: Çevrimdışı yerel DuckDB dosya yolu.

        Returns:
            Veritabanı kayıt kimliği veya bağlantı yoksa None.
        """
        feature_names: list[str] = list(getattr(model_obj, "feature_names", []))
        cs_features: list[str] = list(getattr(model_obj, "cs_features", []))
        validation_metrics: dict[str, Any] = dict(getattr(model_obj, "validation_metrics", {}))
        confidence_score: float = float(getattr(model_obj, "confidence_score", 0.0))
        confidence_details: dict[str, Any] = dict(getattr(model_obj, "confidence_details", {}))
        target_horizon: int = int(getattr(model_obj, "target_horizon", 5))
        train_samples: int = int(getattr(model_obj, "train_samples", 0))

        # Özellik sözleşmesi özeti (contract hash)
        contract_hash = hashlib.sha256(
            orjson.dumps(sorted(feature_names), option=orjson.OPT_SORT_KEYS)
        ).hexdigest()[:16]

        # 1. Aşama: Çevrimdışı dayanıklılık için DuckDB'ye her koşulda yaz
        cls._save_to_local_duckdb(
            model_name=model_name,
            version=version,
            target_horizon=target_horizon,
            feature_names=feature_names,
            cs_features=cs_features,
            confidence_score=confidence_score,
            validation_metrics=validation_metrics,
            artifact_path=artifact_path,
            status="CANDIDATE",
            db_path=db_path,
        )

        # 2. Aşama: PostgreSQL Merkezi Veritabanı
        if not _has_pg_env():
            return None

        try:
            from services.core.database import pg_fetchval

            model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", model_name)
            if model_id is None:
                model_id = await pg_fetchval(
                    """INSERT INTO models (name, model_type, framework, features, status)
                       VALUES ($1, 'lightgbm_ranking', 'lightgbm', $2, 'ACTIVE')
                       RETURNING id""",
                    model_name,
                    orjson.dumps(feature_names).decode("utf-8"),
                )

            version_id = await pg_fetchval(
                """INSERT INTO model_versions
                   (model_id, version, training_data_start, training_data_end,
                    target_horizon, feature_names, cs_features,
                    confidence_score, confidence_details,
                    metrics, artifact_path, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'CANDIDATE')
                   ON CONFLICT (model_id, version) DO UPDATE SET
                    metrics = EXCLUDED.metrics,
                    confidence_score = EXCLUDED.confidence_score,
                    confidence_details = EXCLUDED.confidence_details,
                    artifact_path = EXCLUDED.artifact_path
                   RETURNING id""",
                model_id,
                version,
                training_data_start,
                training_data_end,
                target_horizon,
                orjson.dumps(feature_names).decode("utf-8"),
                orjson.dumps(cs_features).decode("utf-8"),
                confidence_score,
                orjson.dumps(confidence_details).decode("utf-8"),
                orjson.dumps(validation_metrics, default=str).decode("utf-8"),
                artifact_path,
            )

            logger.info(
                "model_ustverisi_kaydedildi",
                model=model_name,
                version=version,
                horizon=target_horizon,
                samples=train_samples,
                confidence=confidence_score,
                contract=contract_hash,
            )

            return int(version_id) if version_id is not None else None

        except Exception as e:
            logger.debug("pg_model_metadata_kayit_atlandi", model=model_name, hata=str(e))
            return None

    @staticmethod
    @otel_trace("model_persistence.get_champion_model")
    async def get_champion_model(
        model_name: str,
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> dict[str, Any] | None:
        """Aktif şampiyon modelin üstverilerini sorgular (önce PG, kesintide DuckDB fallback).

        Args:
            model_name: Sorgulanacak model adı.
            db_path: Çevrimdışı DuckDB dosya yolu.

        Returns:
            Model sürüm bilgilerini içeren sözlük veya bulunamazsa None.
        """
        # 1. Aşama: PostgreSQL
        if _has_pg_env():
            try:
                from services.core.database import pg_fetchrow

                row = await pg_fetchrow(
                    """SELECT mv.*, m.name as model_name
                       FROM model_versions mv
                       JOIN models m ON m.id = mv.model_id
                       WHERE m.name = $1 AND mv.status = 'CHAMPION'
                       ORDER BY mv.created_at DESC LIMIT 1""",
                    model_name,
                )
                if row:
                    return dict(row)
            except Exception as e:
                logger.debug("sampiyon_model_pg_sorgu_hatasi", model=model_name, hata=str(e))

        # 2. Aşama: DuckDB Çevrimdışı Fallback
        target = Path(db_path)
        if target.exists() and target.stat().st_size > 0:
            try:
                with _duckdb_lock, duckdb.connect(db_path, read_only=True) as conn:
                    result = conn.execute(
                        """
                        SELECT model_name, version, target_horizon, feature_names_json,
                               cs_features_json, confidence_score, metrics_json, artifact_path, status, created_at
                        FROM model_versions_offline
                        WHERE model_name = ? AND status = 'CHAMPION'
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        [model_name],
                    ).fetchone()
                    if result:
                        return {
                            "model_name": result[0],
                            "version": result[1],
                            "target_horizon": result[2],
                            "feature_names": orjson.loads(result[3]) if result[3] else [],
                            "cs_features": orjson.loads(result[4]) if result[4] else [],
                            "confidence_score": result[5],
                            "metrics": orjson.loads(result[6]) if result[6] else {},
                            "artifact_path": result[7],
                            "status": result[8],
                            "created_at": result[9],
                        }
            except Exception as exc:
                logger.debug("sampiyon_model_duckdb_sorgu_hatasi", model=model_name, hata=str(exc))

        return None

    @staticmethod
    @otel_trace("model_persistence.promote_to_champion")
    async def promote_to_champion(
        model_name: str,
        version: str,
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> bool:
        """Belirtilen model sürümünü şampiyon (CHAMPION) statüsüne terfi ettirir (PG + DuckDB).

        Args:
            model_name: Model adı.
            version: Şampiyon yapılacak sürüm etiketi.
            db_path: Çevrimdışı DuckDB dosya yolu.

        Returns:
            İşlem başarılı ise True, aksi halde False.
        """
        success = False

        # 1. Aşama: PostgreSQL Terfisi
        if _has_pg_env():
            try:
                from services.core.database import pg_execute, pg_fetchval

                model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", model_name)
                if model_id is not None:
                    await pg_execute(
                        """UPDATE model_versions SET status = 'CANDIDATE'
                           WHERE model_id = $1 AND status = 'CHAMPION'""",
                        model_id,
                    )
                    await pg_execute(
                        """UPDATE model_versions SET status = 'CHAMPION', champion_since = NOW()
                           WHERE model_id = $1 AND version = $2""",
                        model_id,
                        version,
                    )
                    success = True
            except Exception as e:
                logger.debug("model_sampiyon_pg_terfi_atlandi", model=model_name, version=version, hata=str(e))

        # 2. Aşama: DuckDB Yerel Terfisi
        target = Path(db_path)
        if target.exists() and target.stat().st_size > 0:
            try:
                with _duckdb_lock, duckdb.connect(db_path) as conn:
                    configure_duckdb_wal(conn)
                    conn.execute(
                        "UPDATE model_versions_offline SET status = 'CANDIDATE' WHERE model_name = ? AND status = 'CHAMPION'",
                        [model_name],
                    )
                    conn.execute(
                        "UPDATE model_versions_offline SET status = 'CHAMPION' WHERE model_name = ? AND version = ?",
                        [model_name, version],
                    )
                    success = True
            except Exception as exc:
                logger.debug("model_sampiyon_duckdb_terfi_hatasi", model=model_name, version=version, hata=str(exc))

        if success:
            logger.info("model_sampiyon_yapildi", model=model_name, version=version)
        return success

    @staticmethod
    @otel_trace("model_persistence.verify_feature_contract")
    def verify_feature_contract(expected_features: list[str], candidate_features: list[str]) -> bool:
        """Girdi özellik kümesinin modelin eğitim sözleşmesine uygunluğunu doğrular.

        Args:
            expected_features: Modelin eğitime dahil ettiği zorunlu özellikler listesi.
            candidate_features: Canlı tahmine sunulan özellikler listesi.

        Returns:
            Tüm zorunlu özellikler aday kümede mevcutsa True, aksi halde False.
        """
        expected_set = set(expected_features)
        candidate_set = set(candidate_features)
        missing = expected_set - candidate_set
        if missing:
            logger.warning("ozellik_sozlesmesi_eksik_ozellikler", eksik=sorted(missing))
            return False
        return True

    @staticmethod
    @otel_trace("model_persistence.list_model_versions")
    async def list_model_versions(model_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Modelin tüm sürümlerini kronolojik olarak listeler.

        Args:
            model_name: Model adı.
            limit: Getirilecek azami sürüm sayısı.

        Returns:
            Model sürüm sözlükleri listesi.
        """
        if not _has_pg_env():
            return []

        try:
            from services.core.database import pg_fetch

            rows = await pg_fetch(
                """SELECT mv.version, mv.status, mv.confidence_score,
                          mv.target_horizon, mv.created_at, mv.champion_since
                   FROM model_versions mv
                   JOIN models m ON m.id = mv.model_id
                   WHERE m.name = $1
                   ORDER BY mv.created_at DESC
                   LIMIT $2""",
                model_name,
                limit,
            )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug("model_surumleri_listeleme_hatasi", model=model_name, hata=str(e))
            return []

    @classmethod
    def list_model_versions_polars(
        cls,
        model_name: str,
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> pl.DataFrame:
        """Model sürümlerini yerel DuckDB defterinden Polars DataFrame olarak çeker (GEMINI.md Kural 2).

        Args:
            model_name: Model adı.
            db_path: DuckDB dosya yolu.

        Returns:
            Sürümleri içeren Polars DataFrame.
        """
        empty_schema = {
            "model_name": pl.String,
            "version": pl.String,
            "target_horizon": pl.Int32,
            "confidence_score": pl.Float64,
            "artifact_path": pl.String,
            "status": pl.String,
            "created_at": pl.Datetime("us"),
        }
        target = Path(db_path)
        if not target.exists() or target.stat().st_size == 0:
            return pl.DataFrame(schema=empty_schema)

        try:
            with _duckdb_lock, duckdb.connect(db_path, read_only=True) as conn:
                return conn.execute(
                    """
                    SELECT model_name, version, target_horizon, confidence_score, artifact_path, status, created_at
                    FROM model_versions_offline
                    WHERE model_name = ?
                    ORDER BY created_at DESC
                    """,
                    [model_name],
                ).pl()
        except Exception as exc:
            logger.debug("duckdb_model_surumleri_polars_hatasi", hata=str(exc))
            return pl.DataFrame(schema=empty_schema)

    @classmethod
    @otel_trace("model_persistence.rollback_champion")
    async def rollback_champion(
        cls,
        model_name: str,
        db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
    ) -> tuple[bool, str]:
        """Canlıda anomali üreten şampiyon modeli geri alıp önceki istikrarlı sürüme döner (Self-Healing / Kural 6).

        Args:
            model_name: Model adı.
            db_path: Yerel DuckDB yolu.

        Returns:
            (basarili_mi, aciklama) ikilisi.
        """
        # DuckDB üzerinden önceki sürümleri ara
        target = Path(db_path)
        if not target.exists() or target.stat().st_size == 0:
            return False, "Yerel model kayıt defteri bulunamadı"

        try:
            with _duckdb_lock, duckdb.connect(db_path) as conn:
                configure_duckdb_wal(conn)
                # Mevcut şampiyonu bul
                current = conn.execute(
                    "SELECT version FROM model_versions_offline WHERE model_name = ? AND status = 'CHAMPION'",
                    [model_name],
                ).fetchone()
                current_ver = current[0] if current else None

                # Bir önceki adayı veya eski şampiyonu bul
                previous = conn.execute(
                    """
                    SELECT version FROM model_versions_offline
                    WHERE model_name = ? AND status != 'CHAMPION' AND status != 'REJECTED'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    [model_name],
                ).fetchone()

                if not previous:
                    return False, "Geri dönülecek uygun yedek model sürümü bulunamadı"

                prev_ver = previous[0]

                # Mevcut şampiyonu 'REJECTED' yap
                if current_ver:
                    conn.execute(
                        "UPDATE model_versions_offline SET status = 'REJECTED' WHERE model_name = ? AND version = ?",
                        [model_name, current_ver],
                    )

                # Önceki sürümü 'CHAMPION' yap
                conn.execute(
                    "UPDATE model_versions_offline SET status = 'CHAMPION' WHERE model_name = ? AND version = ?",
                    [model_name, prev_ver],
                )

            # PostgreSQL varsa orada da güncelle
            if _has_pg_env():
                with contextlib.suppress(Exception):
                    from services.core.database import pg_execute, pg_fetchval

                model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", model_name)
                if model_id is not None:
                    if current_ver:
                        await pg_execute(
                            "UPDATE model_versions SET status = 'REJECTED' WHERE model_id = $1 AND version = $2",
                            model_id,
                            current_ver,
                        )
                    await pg_execute(
                        "UPDATE model_versions SET status = 'CHAMPION', champion_since = NOW() WHERE model_id = $1 AND version = $2",
                        model_id,
                        prev_ver,
                    )

            logger.warning(
                "model_otomatik_geri_alindi",
                model=model_name,
                eski_hatali_surum=current_ver,
                yeni_aktif_surum=prev_ver,
            )
            return True, f"Model başarıyla {prev_ver} sürümüne geri alındı (önceki: {current_ver})"

        except Exception as exc:
            logger.error("model_geri_alma_hatasi", model=model_name, hata=str(exc))
            return False, f"Geri alma işlemi başarısız: {exc}"

    @classmethod
    def generate_contract_hash(cls, feature_names: list[str]) -> str:
        """Özellik sözleşmesi için deterministik SHA256 kontrol özeti üretir."""
        return hashlib.sha256(
            orjson.dumps(sorted(feature_names), option=orjson.OPT_SORT_KEYS)
        ).hexdigest()[:16]


def export_model_versions_to_orjson_bytes(
    model_name: str,
    db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
) -> bytes:
    """Model sürümlerini orjson serileştirilmiş ikili bayt dizisi olarak döndürür."""
    df = ModelPersistence.list_model_versions_polars(model_name=model_name, db_path=db_path)
    return orjson.dumps(df.to_dicts(), default=str)


def clear_model_metadata_duckdb(
    db_path: str = DEFAULT_MODEL_METADATA_DB_PATH,
) -> None:
    """DuckDB çevrimdışı model kayıt tablosundaki tüm kayıtları siler."""
    target = Path(db_path)
    if not target.exists():
        return

    with _duckdb_lock, duckdb.connect(db_path) as conn:
        configure_duckdb_wal(conn)
        conn.execute("DROP TABLE IF EXISTS model_versions_offline")


# Global tekil nesne ve kolaylık fonksiyonları
model_persistence: Final[ModelPersistence] = ModelPersistence()
save_model_metadata = ModelPersistence.save_model_metadata
get_champion_model = ModelPersistence.get_champion_model
promote_to_champion = ModelPersistence.promote_to_champion
verify_feature_contract = ModelPersistence.verify_feature_contract
list_model_versions = ModelPersistence.list_model_versions
list_model_versions_polars = ModelPersistence.list_model_versions_polars
rollback_champion = ModelPersistence.rollback_champion
generate_contract_hash = ModelPersistence.generate_contract_hash

__all__: Final[list[str]] = [
    "DEFAULT_MODEL_METADATA_DB_PATH",
    "ModelPersistence",
    "clear_model_metadata_duckdb",
    "configure_duckdb_wal",
    "export_model_versions_to_orjson_bytes",
    "generate_contract_hash",
    "get_champion_model",
    "list_model_versions",
    "list_model_versions_polars",
    "model_persistence",
    "otel_trace",
    "promote_to_champion",
    "rollback_champion",
    "save_model_metadata",
    "verify_feature_contract",
]
