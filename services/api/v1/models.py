"""Models API — 6 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("")
async def all_models(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"models": [], "active": None}

@router.get("/{model_id}")
async def model_detail(model_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"model_id": model_id}

@router.get("/{model_id}/performance")
async def model_performance(model_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"model_id": model_id, "metrics": {}}

@router.get("/compare")
async def compare(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"comparison": {}}

@router.get("/ensemble")
async def ensemble(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"ensemble": {}}

@router.post("/{model_id}/promote")
async def promote(model_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"model_id": model_id, "status": "promoted"}
