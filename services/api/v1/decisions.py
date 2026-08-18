"""Decisions API — 6 endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("")
async def decisions(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"decisions": []}

@router.get("/{decision_id}")
async def decision_detail(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"decision_id": decision_id, "detail": {}}

@router.post("")
async def create_decision(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "created"}

@router.get("/{decision_id}/audit")
async def decision_audit(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"decision_id": decision_id, "audit": []}

@router.get("/opportunities")
async def opportunities(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"opportunities": []}

@router.get("/trade-plan")
async def trade_plan(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"plan": []}
