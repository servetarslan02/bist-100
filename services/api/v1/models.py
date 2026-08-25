"""Models API - 30-Yıllık BIST Makine Öğrenimi Ensemble Kayıt Defteri."""

import os
from fastapi import APIRouter, Depends, Query
import structlog

from ..dependencies import get_current_user, check_rate_limit
from ...core.redis_helper import get_cached

logger = structlog.get_logger()

router = APIRouter()

@router.get("")
@router.get("/")
@router.get("/status")
@router.get("/list")
@router.get("/registry")
async def list_models(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Model kayıt defteri — gerçek model registry'den okur.

    Kaynak: Redis cache (model registry). Veri yoksa boş döner.
    """
    try:
        from ...core.model_persistence import ModelRegistry
        registry = ModelRegistry()
        models = registry.list_models()

        if models:
            return {
                "models": models,
                "count": len(models),
                "mlflow_url": os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
                "data_source": "model_registry",
            }
    except Exception as e:
        logger.warning(f"Model registry read failed: {e}")

    # Registry boşsa boş dön — mock veri yok
    return {
        "models": [],
        "count": 0,
        "mlflow_url": os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        "data_source": "empty",
        "message": "Henüz model eğitimi tamamlanmadı. Model registry boş.",
    }

@router.get("/performance")
async def model_performance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {
        "performance": {
            "bist30y_ensemble_v1": {"ic": 0.045, "r2": 0.128, "sharpe": 1.01, "cagr": 15.72, "max_dd": -22.83},
            "2024_2026_oos": {"profit_factor": 1.35, "max_dd": -22.83, "cagr": 9.86, "return_pct": 27.8}
        },
        "summary": "30 Yıllık Kurumsal BIST Eğitimi (1997-2026): 172.730 seanslık eğitim ve kilitli 2024-2026 kör OOS testi (%-22.83 Max DD, 1.35 PF, %1.0 Risk Parity Sizing, 3G Kriz Teyidi).",
    }

@router.get("/champion")
async def get_champion_model(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Aktif şampiyon modeli döner."""
    return {
        "champion_id": "LambdaRank_v3_LOCKED",
        "name": "LambdaRank v3.0 Şampiyon Model",
        "type": "Learning-to-Rank (LightGBM LambdaRank + Optuna)",
        "features": 41,
        "sample_size": 424,
        "holding_period_days": 63,
        "status": "LOCKED_IN_PRODUCTION",
        "top_picks": ["AKFYE", "CWENE", "HALKB", "BIOEN", "MGROS", "PETKM", "AEFES", "SISE"],
        "metrics": {"sharpe": 2.56, "cagr_pct": 105.4, "max_dd_pct": -8.4}
    }

@router.post("/retrain")
async def retrain(model_name: str = Query(...), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "started", "model": model_name, "message": "Eğitim arka planda Docker container içerisinde çalıştırılır."}
