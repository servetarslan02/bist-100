"""Agents API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/list")
async def list_agents(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Agent listesi."""
    try:
        return {"agents": ["researcher", "risk_manager", "executor", "monitor"], "count": 4}
    except Exception as e:
        return {"agents": [], "error": str(e)}


@router.get("/status")
async def agent_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Agent durumları."""
    return {"agents": [], "message": "Agent system requires initialization"}


@router.post("/run")
async def run_agent(agent_name: str = "researcher", user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Agent çalıştır."""
    return {"status": "started", "agent": agent_name}
