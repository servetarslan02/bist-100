"""ALPHA BIST — Model Persistence v1.0

FAZ 5.1: Model metadata DB persistence.
FAZ 4 model yapısını bozmaz; DB ile ilişkilendirme sağlar.
"""

import hashlib
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


class ModelPersistence:
    """Model metadata DB persistence.

    TrainedModel/MultiHorizonModel pickle olarak dosyaya kaydedilir.
    Bu sınıf metadata'sını DB'ye yazar (version, metrics, feature contract, vb.).
    """

    @staticmethod
    async def save_model_metadata(
        model_name: str,
        version: str,
        model_obj: Any,
        artifact_path: str,
        training_data_start: str | None = None,
        training_data_end: str | None = None,
    ) -> int | None:
        """Model metadata'sını DB'ye kaydet.

        Args:
            model_name: Model adı (örn: "alpha_bist_lgbm")
            version: Versiyon string (örn: "v4.5_fold3")
            model_obj: TrainedModel veya MultiHorizonModel
            artifact_path: Pickle dosya yolu

        Returns:
            model_versions.id veya None (DB yoksa)
        """
        try:
            from .database import pg_fetchval
        except Exception:
            logger.warning("DB not available, skipping model metadata save")
            return None

        # Model metadata çıkar
        feature_names = getattr(model_obj, "feature_names", [])
        cs_features = getattr(model_obj, "cs_features", [])
        validation_metrics = getattr(model_obj, "validation_metrics", {})
        confidence_score = getattr(model_obj, "confidence_score", 0)
        confidence_details = getattr(model_obj, "confidence_details", {})
        target_horizon = getattr(model_obj, "target_horizon", 5)
        train_samples = getattr(model_obj, "train_samples", 0)
        getattr(model_obj, "train_date_range", ("", ""))
        getattr(model_obj, "scaler_mean", None)
        getattr(model_obj, "scaler_std", None)
        getattr(model_obj, "impute_values", {})
        getattr(model_obj, "feature_importance", {})

        # Feature contract hash
        contract_hash = hashlib.sha256(
            orjson.dumps(sorted(feature_names), option=orjson.OPT_SORT_KEYS).decode()
        ).hexdigest()[:16]

        try:
            # Model kaydı var mı?
            model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", model_name)
            if model_id is None:
                model_id = await pg_fetchval(
                    """INSERT INTO models (name, model_type, framework, features, status)
                       VALUES ($1, 'lightgbm_ranking', 'lightgbm', $2, 'ACTIVE')
                       RETURNING id""",
                    model_name,
                    orjson.dumps(feature_names).decode(),
                )

            # Version kaydet (upsert)
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
                orjson.dumps(feature_names),
                orjson.dumps(cs_features).decode(),
                confidence_score,
                orjson.dumps(confidence_details).decode(),
                orjson.dumps(validation_metrics, default=str).decode(),
                artifact_path,
            )

            logger.info(
                "Model metadata saved",
                model=model_name,
                version=version,
                horizon=target_horizon,
                samples=train_samples,
                confidence=confidence_score,
                contract=contract_hash,
            )

            return version_id

        except Exception as e:
            logger.error("Failed to save model metadata", error=str(e))
            return None

    @staticmethod
    async def get_champion_model(model_name: str) -> dict[str, Any] | None:
        """Champion model metadata'sını getir."""
        try:
            from .database import pg_fetchrow
        except Exception:
            return None

        try:
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
            return None
        except Exception as e:
            logger.error("Failed to get champion model", error=str(e))
            return None

    @staticmethod
    async def promote_to_champion(model_name: str, version: str) -> bool:
        """Modeli champion yap (eski champion'ı candidate'a düşür)."""
        try:
            from .database import pg_execute, pg_fetchval
        except Exception:
            return False

        try:
            model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", model_name)
            if model_id is None:
                return False

            # Eski champion'ı düşür
            await pg_execute(
                """UPDATE model_versions SET status = 'CANDIDATE'
                   WHERE model_id = $1 AND status = 'CHAMPION'""",
                model_id,
            )

            # Yeni champion
            await pg_execute(
                """UPDATE model_versions SET status = 'CHAMPION', champion_since = NOW()
                   WHERE model_id = $1 AND version = $2""",
                model_id,
                version,
            )

            logger.info("Model promoted to champion", model=model_name, version=version)
            return True

        except Exception as e:
            logger.error("Failed to promote model", error=str(e))
            return False

    @staticmethod
    async def list_model_versions(model_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Model versiyonlarını listele."""
        try:
            from .database import pg_fetch
        except Exception:
            return []

        try:
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
            logger.error("Failed to list model versions", error=str(e))
            return []


# Singleton
model_persistence = ModelPersistence()
