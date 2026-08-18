"""Scanner API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/opportunities")
async def opportunities(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"opportunities": []}

@router.get("/alpha")
async def alpha(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"alpha_signals": []}

@router.get("/events")
async def events(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"events": []}

@router.post("/scan")
async def scan(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "started"}
