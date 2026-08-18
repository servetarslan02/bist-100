"""Backtest API — 6 endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.post("")
async def start_backtest(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "started", "backtest_id": "bt-001"}

@router.get("/{backtest_id}")
async def backtest_result(backtest_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"backtest_id": backtest_id, "status": "pending"}

@router.get("")
async def all_backtests(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"backtests": []}

@router.post("/walk-forward")
async def walk_forward(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "started", "type": "walk-forward"}

@router.get("/{backtest_id}/trades")
async def backtest_trades(backtest_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"backtest_id": backtest_id, "trades": []}

@router.get("/{backtest_id}/equity")
async def backtest_equity(backtest_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"backtest_id": backtest_id, "equity_curve": []}
