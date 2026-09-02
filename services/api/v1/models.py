from typing import Any

"""Models API - 30-Yıllık BIST Makine Öğrenimi Ensemble Kayıt Defteri."""

import os

import structlog
from fastapi import APIRouter, Depends, Query

from ..dependencies import check_rate_limit, get_current_user

logger = structlog.get_logger()

router = APIRouter()


@router.get("")
@router.get("/")
@router.get("/status")
@router.get("/list")
@router.get("/registry")
async def list_models(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Model kayıt defteri — diskteki gerçek modelleri ve registry'i okur."""
    from services.learning.model_registry import model_registry

    versions = model_registry.get_all_versions()
    if not versions:
        if hasattr(model_registry, "_init_default_models"):
            model_registry._init_default_models()
        versions = model_registry.get_all_versions()

    return {
        "models": versions,
        "count": len(versions),
        "mlflow_url": os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        "data_source": "model_registry",
    }


@router.get("/performance")
async def model_performance(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Model performans metriklerini döner."""
    from services.learning.model_registry import model_registry

    versions = model_registry.get_all_versions()
    if not versions:
        return {"status": "no_models", "message": "Kayıtlı model bulunamadı"}

    performance = {}
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


@router.get("/champion")
async def get_champion_model(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Aktif şampiyon modeli döner."""
    from services.learning.model_registry import model_registry

    champion = model_registry.get_champion()
    if not champion:
        return {"status": "no_champion", "message": "Şampiyon model bulunamadı"}

    return {
        "champion_id": champion.model_id,
        "name": champion.model_id,
        "version": champion.version,
        "status": champion.status,
        "regime": champion.regime,
        "created_at": champion.created_at,
        "metrics": champion.metrics or {},
    }


@router.get("/learning-state")
async def get_learning_state(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Otonom öğrenme döngüsünün anlık durumunu, doğruluk trendini ve kalibrasyonu döner."""
    from services.learning.learning_loop import learning_loop

    state = learning_loop.get_state()
    return {
        "learning_loop": state,
        "retrain_needed": learning_loop.should_retrain(),
        "retrain_reason": learning_loop.get_retrain_reason(),
        "canonical_features_count": 70,
        "calibration_status": "ENABLED",
    }


@router.post("/retrain")
async def retrain(force: bool = Query(default=True), user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Otonom kapalı devre yeniden eğitimi tetikler ve modelleri hot-reload eder."""
    import asyncio

    from services.learning.learning_loop import learning_loop

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, learning_loop.trigger_autonomous_retrain, force)
    return result
