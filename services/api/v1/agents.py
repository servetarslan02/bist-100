"""Ajanlar API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import check_rate_limit, get_current_user

router = APIRouter()


@router.get("/list")
async def list_agents(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> dict:
    """Mevcut ajanların listesini döndürür."""
    try:
        from ...agents.agent_system import AgentRole

        agents = [role.value for role in AgentRole]
        return {"agents": agents, "count": len(agents)}
    except ImportError:
        raise HTTPException(status_code=503, detail="Ajan sistemi mevcut değil")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ajan listesi alınamadı: {e}")


@router.get("/status")
async def agent_status(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> dict:
    """Ajanların çalışma durumunu döndürür."""
    try:
        from ...agents.agent_system import agent_system

        return {"agents": agent_system.get_status()}
    except ImportError:
        return {"agents": [], "message": "Ajan sistemi başlatılmamış"}
    except Exception as e:
        return {"agents": [], "message": f"Durum alınamadı: {e}"}


@router.post("/run")
async def run_agent(agent_name: str = "researcher", user=Depends(get_current_user), _=Depends(check_rate_limit)) -> dict:
    """Belirtilen ajanı çalıştırır."""
    try:
        from ...agents.agent_system import agent_system

        result = await agent_system.run(agent_name)
        return {"status": "started", "agent": agent_name, "result": result}
    except ImportError:
        raise HTTPException(status_code=503, detail="Ajan sistemi mevcut değil")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Ajan bulunamadı: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ajan çalıştırılamadı: {e}")
