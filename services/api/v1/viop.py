"""VIOP API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/options")
async def options(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"options": []}

@router.get("/greeks")
async def greeks(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"greeks": {}}

@router.post("/hedge")
async def hedge(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"hedge": {}}

@router.get("/strategies")
async def strategies(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"strategies": []}
