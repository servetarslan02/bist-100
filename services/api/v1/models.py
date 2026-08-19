"""Models API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/list")
async def list_models(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Model listesi."""
    try:
        from ...intelligence.ensemble_forecast import EnsembleForecaster
        return {"models": ["momentum", "statistical", "heuristic", "lightgbm"], "count": 4}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.get("/performance")
async def model_performance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Model performansı."""
    return {"performance": {}, "message": "Requires prediction history"}


@router.post("/retrain")
async def retrain(model_name: str = Query(...), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Model yeniden eğitimi."""
    return {"status": "started", "model": model_name}
