"""Macro API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/indicators")
async def indicators(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"tcmb_rate": 0, "inflation": 0, "usdtry": 0, "cds": 0}

@router.get("/calendar")
async def calendar(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"events": []}

@router.get("/impact")
async def impact(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"impact": {}}

@router.get("/tcmb")
async def tcmb(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"rate": 0, "last_decision": None}
