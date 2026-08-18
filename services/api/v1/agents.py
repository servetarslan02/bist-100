"""Agents API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("")
async def all_agents(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    from ...agents.agent_system import AgentRole
    return {"agents": [r.value for r in AgentRole], "total": len(AgentRole)}

@router.get("/{role}")
async def agent_detail(role: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"role": role, "status": "active"}

@router.get("/{role}/results")
async def agent_results(role: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"role": role, "results": []}

@router.post("/{role}/run")
async def run_agent(role: str, ticker: str = "THYAO", user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"role": role, "ticker": ticker, "status": "started"}
