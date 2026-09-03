"""Modeller API — 30 Yıllık BIST Makine Öğrenimi Ensemble Kayıt Defteri."""

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
@router.get("/")
@router.get("/status")
@router.get("/list")
@router.get("/registry")
async def list_models(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Model kayıt defterini döndürür — diskteki gerçek modelleri ve registry'i okur.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Model versiyonları, sayısı ve MLflow URL'si.

    Raises:
        HTTPException: Registry okunamazsa 500 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        versions = model_registry.get_all_versions()
        if not versions:
            if hasattr(model_registry, "init_default_models"):
                model_registry.init_default_models()
            elif hasattr(model_registry, "_init_default_models"):
                logger.warning("private_method_erisimi: _init_default_models kullanılıyor")
                model_registry._init_default_models()
            versions = model_registry.get_all_versions()

        return {
            "models": versions,
            "count": len(versions),
            "mlflow_url": os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
            "data_source": "model_registry",
        }
    except Exception as exc:
        logger.error("model_listesi_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Model listesi alınamadı: {exc}",
        ) from exc


@router.get("/performance")
async def model_performance(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Model performans metriklerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Model performans metrikleri ve sayısı.

    Raises:
        HTTPException: Performans verisi alınamazsa 500 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        versions = model_registry.get_all_versions()
        if not versions:
            return {"status": "no_models", "message": "Kayıtlı model bulunamadı."}

        performance: dict[str, Any] = {}
        for v in versions:
            model_id = v.get("model_id", "unknown")
            metrics = v.get("metrics", {})
            if metrics:
                performance[model_id] = metrics

        return {
            "performance": performance,
            "model_count": len(versions),
            "data_source": "model_registry",
        }
    except Exception as exc:
        logger.error("model_performans_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Model performans verisi alınamadı: {exc}",
        ) from exc


@router.get("/champion")
async def get_champion_model(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Aktif şampiyon modeli döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Şampiyon model bilgisi, versiyonu ve metrikleri.

    Raises:
        HTTPException: Şampiyon model bulunamazsa 404 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        champion = model_registry.get_champion()
        if not champion:
            raise HTTPException(
                status_code=404,
                detail="Şampiyon model bulunamadı.",
            )

        return {
            "champion_id": champion.model_id,
            "name": champion.model_id,
            "version": champion.version,
            "status": champion.status,
            "regime": champion.regime,
            "created_at": champion.created_at,
            "metrics": champion.metrics or {},
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sampiyon_model_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Şampiyon model bilgisi alınamadı: {exc}",
        ) from exc


@router.get("/learning-state")
async def get_learning_state(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Otonom öğrenme döngüsünün anlık durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Öğrenme döngüsü durumu, yeniden eğitim ihtiyacı ve kalibrasyon durumu.

    Raises:
        HTTPException: Öğrenme durumu alınamazsa 500 hatası döner.
    """
    try:
        from ...learning.learning_loop import learning_loop

        state = learning_loop.get_state()
        retrain_needed = learning_loop.should_retrain()
        retrain_reason = learning_loop.get_retrain_reason()

        # Feature sayısını gerçek veriden al
        canonical_features_count = 0
        if hasattr(learning_loop, "get_feature_count"):
            canonical_features_count = learning_loop.get_feature_count()
        elif hasattr(learning_loop, "canonical_features"):
            canonical_features_count = len(learning_loop.canonical_features)

        # Kalibrasyon durumunu gerçek veriden al
        calibration_status = "UNKNOWN"
        if hasattr(learning_loop, "get_calibration_status"):
            calibration_status = learning_loop.get_calibration_status()
        elif hasattr(learning_loop, "calibration_enabled"):
            calibration_status = "ENABLED" if learning_loop.calibration_enabled else "DISABLED"

        return {
            "learning_loop": state,
            "retrain_needed": retrain_needed,
            "retrain_reason": retrain_reason,
            "canonical_features_count": canonical_features_count,
            "calibration_status": calibration_status,
        }
    except Exception as exc:
        logger.error("ogrenme_durumu_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Öğrenme durumu alınamadı: {exc}",
        ) from exc


@router.post("/retrain")
async def retrain(
    force: bool = Query(default=True),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Otonom kapalı devre yeniden eğitimi tetikler ve modelleri hot-reload eder.

    Args:
        force: Zorla yeniden eğitim tetikleme.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yeniden eğitim sonucu.

    Raises:
        HTTPException: Yeniden eğitim tetiklenemezse 500 hatası döner.
    """
    try:
        from ...learning.learning_loop import learning_loop

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, learning_loop.trigger_autonomous_retrain, force)
        return result
    except Exception as exc:
        logger.error("yeniden_egitim_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Yeniden eğitim tetiklenemedi: {exc}",
        ) from exc
