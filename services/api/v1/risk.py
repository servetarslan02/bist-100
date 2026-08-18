"""Risk API — 8 endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/overview")
async def risk_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"risk_level": "LOW", "risk_score": 0}

@router.get("/portfolio")
async def portfolio_risk(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"var_95": 0, "cvar_95": 0, "max_drawdown": 0}

@router.get("/positions")
async def position_risks(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"positions": []}

@router.get("/limits")
async def risk_limits(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"max_position_pct": 10, "max_sector_pct": 30, "max_drawdown_pct": 15}

@router.post("/check")
async def pre_trade_check(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"approved": True, "risk_level": "LOW"}

@router.get("/compliance")
async def compliance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"compliant": True, "violations": []}

@router.get("/var")
async def var(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"var_95": 0, "cvar_95": 0, "var_99": 0}

@router.get("/stress-test")
async def stress_test(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"scenarios": [], "worst_case": 0}
