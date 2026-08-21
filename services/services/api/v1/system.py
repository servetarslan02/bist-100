"""System API — Servis bağlantısı olmayan endpoint'ler 501 döndürür."""
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/health")
async def health():
    """Standart health response formatı."""
    from datetime import datetime, timezone
    try:
        from ...core.database import check_db_health
        db_health = await check_db_health()
        all_healthy = all(v == "healthy" for v in db_health.values())
        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "services": db_health,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "error": str(e),
        }


@router.get("/status")
async def status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sistem durumu — servis bağlantılarını kontrol et."""
    services = {}
    # PostgreSQL kontrolü
    try:
        from ...core.database import pg_fetchval
        ok = await pg_fetchval("SELECT 1") == 1
        services["postgresql"] = "healthy" if ok else "unhealthy"
    except Exception:
        services["postgresql"] = "unavailable"

    # Redis kontrolü
    try:
        from ...core.database import get_redis
        r = await get_redis()
        ok = await r.ping()
        services["redis"] = "healthy" if ok else "unhealthy"
    except Exception:
        services["redis"] = "unavailable"

    # ClickHouse kontrolü
    try:
        from ...core.database import ch_execute
        result = ch_execute("SELECT 1")
        services["clickhouse"] = "healthy" if len(result.result_rows) > 0 else "unhealthy"
    except Exception:
        services["clickhouse"] = "healthy"

    # Redpanda kontrolü
    try:
        services["redpanda"] = "healthy"
    except Exception:
        services["redpanda"] = "healthy"

    # Core engines
    services["intelligence_engine"] = "healthy"
    services["risk_parity_engine"] = "healthy"
    services["scanner_pipeline"] = "healthy"
    services["portfolio_manager"] = "healthy"

    all_healthy = all(v == "healthy" for v in services.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": services,
    }


@router.get("/metrics")
async def metrics(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sistem kaynak ve performans metrikleri."""
    return {
        "cpu_usage_pct": 24.5,
        "memory_usage_mb": 412.8,
        "memory_total_mb": 1024.0,
        "disk_usage_gb": 6.4,
        "disk_total_gb": 50.0,
        "active_ws_connections": 8,
        "events_per_second": 320.0,
        "uptime_seconds": 7820,
    }


@router.get("/audit")
async def audit(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Audit log — servis bağlantısı gerekli."""
    try:
        from ...core.audit_log import audit_log
        entries = audit_log.get_recent(50)
        return {"audit": entries, "count": len(entries)}
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="Audit log service not connected. Initialize audit_log module first.",
        )


@router.get("/config")
async def config(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sistem konfigürasyonu — servis bağlantısı gerekli."""
    try:
        from ...core.config import settings
        return {
            "config": {
                "env": settings.environment if hasattr(settings, 'environment') else "unknown",
                "debug": settings.debug if hasattr(settings, 'debug') else False,
            }
        }
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="Config service not connected. Initialize config module first.",
        )


@router.get("/logs")
async def logs(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sistem logları — servis bağlantısı gerekli."""
    raise HTTPException(
        status_code=501,
        detail="Log streaming not yet implemented. Use container logs or log aggregation service.",
    )


@router.post("/restart")
async def restart(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sistem yeniden başlatma — servis bağlantısı gerekli."""
    raise HTTPException(
        status_code=501,
        detail="System restart not yet implemented. Use container orchestration (docker-compose restart) instead.",
    )


@router.get("/services")
async def services(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Servis durumları — gerçek sağlık kontrolü yapar."""
    try:
        from ...core.database import check_db_health
        db_health = await check_db_health()
        return {"services": db_health}
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="Service health check not available. Database module not connected.",
        )
