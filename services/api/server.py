from typing import Any
"""
⚠️  DEPRECATED — Bu dosya production DEĞİLDİR ve artık canonical değildir.

Canonical production server: services/api/app.py
Canonical redirect (geriye uyumluluk): services/api/main.py
Bu dosya sadece development/testing amaçlıdır (SQLite dev_db kullanır).

Kullanım:
    # Eski (DEPRECATED — bu dosya):
    uvicorn services.api.server:app

    # Canonical:
    uvicorn services.api.app:app

    # Geriye uyumlu redirect:
    uvicorn services.api.main:app

---

ALPHA BIST — FastAPI Development Server v2.0

Endpoints:
- GET /health → Sistem sağlığı
- GET /api/market → Piyasa verisi
- GET /api/opportunities → Fırsatlar
- GET /api/portfolio → Portföy
- GET /api/decisions → Kararlar
- GET /api/learning → Öğrenme
- GET /api/signals → Sinyaller
- GET /api/features/{ticker} → Feature'lar
- GET /api/regime → Rejim durumu
- GET /api/risk → Risk metrikleri
- GET /api/notifications → Bildirimler
- GET /api/audit → Audit log
- GET /api/stats → İstatistikler
- WebSocket /ws → Gerçek zamanlı güncellemeler
"""

import asyncio
import os
import warnings
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

warnings.warn(
    "services.api.server is DEPRECATED. Use services.api.app instead. "
    "This file exists only for development/testing purposes.",
    DeprecationWarning,
    stacklevel=2,
)

# Internal imports
from services.core.alerting import alerting
from services.core.logging import logger
from services.core.monitoring import portfolio_monitor
from services.core.monitoring_security import extract_api_key, extract_bearer_token, monitoring_auth
from services.core.observability import (
    health_checker,
    performance_monitor,
    prometheus_metrics,
)
from services.features.store import feature_store


# ===================== LIFESPAN =====================
@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Uygulama başlangıç/bitiş yönetimi."""
    logger.info("🚀 ALPHA BIST API Server başlatılıyor...")

    # Health check kayıtları
    health_checker.register("database")
    health_checker.register("feature_store")
    health_checker.register("opportunity_engine")
    health_checker.register("decision_engine")
    health_checker.register("portfolio_manager")
    health_checker.register("learning_system")

    # Başlangıç durumları
    health_checker.update_status("database", "HEALTHY", "SQLite dev_db aktif")
    health_checker.update_status("feature_store", "HEALTHY", "In-memory store aktif")
    health_checker.update_status("opportunity_engine", "HEALTHY", "Tarama motoru hazır")
    health_checker.update_status("decision_engine", "HEALTHY", "Karar motoru hazır")
    health_checker.update_status("portfolio_manager", "HEALTHY", "Portföy yöneticisi aktif")
    health_checker.update_status("learning_system", "HEALTHY", "Öğrenme sistemi aktif")

    logger.info("✅ Tüm servisler hazır")
    yield

    logger.info("🛑 API Server kapatılıyor...")


# ===================== APP =====================
app = FastAPI(
    title="ALPHA BIST API",
    description="BIST-100 Algoritmik Trading Sistemi API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS
allowed_origins = os.environ.get("CORS_ORIGINS", "").split(",")
if not allowed_origins or allowed_origins == [""]:
    allowed_origins = ["http://localhost:3000"]  # Default: sadece local dev

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key middleware (FAZ 5)
_PUBLIC_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/api/health"}


@app.middleware("http")
async def api_key_middleware(request: Request, call_next) -> Any:
    """API key kontrolü — public path'ler hariç."""
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/ws"):
        return await call_next(request)

    # Production'da API key zorunlu
    from services.core.config import settings

    if settings.is_production:
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return JSONResponse(status_code=401, content={"error": "API key required", "header": "X-API-Key"})

    return await call_next(request)


# ===================== WEBSOCKET MANAGER =====================
class ConnectionManager:
    """WebSocket bağlantı yöneticisi."""

    def __init__(self):
        """Otomatik eklendi."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> Any:
        """Otomatik eklendi."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket bağlantısı", connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> Any:
        """Otomatik eklendi."""
        self.active_connections.remove(websocket)
        logger.info("WebSocket bağlantısı kapandı", connections=len(self.active_connections))

    async def broadcast(self, message: dict) -> Any:
        """Tüm bağlı client'lara mesaj gönder."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

    async def send_personal(self, message: dict, websocket: WebSocket) -> Any:
        """Tek bir client'a mesaj gönder."""
        await websocket.send_json(message)


manager = ConnectionManager()


# ===================== BACKGROUND TASK =====================
async def broadcast_updates() -> Any:
    """Periyodik olarak tüm client'lara güncelleme gönder."""
    while True:
        await asyncio.sleep(5)
        if manager.active_connections:
            await manager.broadcast(
                {
                    "type": "heartbeat",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "connections": len(manager.active_connections),
                }
            )


# ===================== ENDPOINTS =====================


@app.get("/", response_class=HTMLResponse)
async def root() -> Any:
    """Root endpoint — Dashboard'a yönlendir."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>ALPHA BIST API</title></head>
    <body style="font-family: Inter, sans-serif; background: #0a0e1a; color: #e2e8f0; padding: 40px;">
        <h1>🚀 ALPHA BIST API v2.0</h1>
        <p>BIST-100 Algoritmik Trading Sistemi</p>
        <ul>
            <li><a href="/docs" style="color: #3b82f6;">📚 API Dokümantasyonu (Swagger)</a></li>
            <li><a href="/redoc" style="color: #3b82f6;">📖 API Dokümantasyonu (ReDoc)</a></li>
            <li><a href="/health" style="color: #3b82f6;">💓 Health Check</a></li>
            <li><a href="/api/market" style="color: #3b82f6;">📊 Piyasa Verisi</a></li>
        </ul>
    </body>
    </html>
    """


@app.get("/health")
async def health_check() -> Any:
    """Sistem sağlık kontrolü."""
    start = datetime.now(UTC)
    health = health_checker.check_all()
    latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000

    performance_monitor.record_latency("health_check", latency_ms)
    prometheus_metrics.inc("health_check_total")

    return {
        **health,
        "latency_ms": round(latency_ms, 2),
        "version": "2.0.0",
    }


# NOTE: /api/market endpoint removed — canonical: v1/market.py via app.py

# NOTE: /api/opportunities endpoint removed — canonical: v1/scanner.py via app.py

# NOTE: /api/portfolio endpoint removed — canonical: v1/portfolio.py via app.py

# NOTE: /api/decisions endpoint removed — canonical: v1/decisions.py via app.py

# NOTE: /api/learning endpoints removed — canonical: v1/learning.py via app.py

# NOTE: /api/signals endpoint removed — canonical: v1/scanner.py via app.py

# NOTE: /api/features/{ticker} endpoint removed — canonical: v1/intelligence.py via app.py

# NOTE: /api/regime endpoint removed — canonical: v1/market.py via app.py

# NOTE: /api/risk endpoint removed — canonical: v1/risk.py via app.py


# =====================================================
# Market State Engine v2.0 Endpoints
# =====================================================

# NOTE: /api/market/state endpoint removed — canonical: v1/market.py via app.py


# NOTE: /api/market/breadth endpoint removed — canonical: v1/market.py via app.py


# NOTE: /api/market/regime endpoint removed — canonical: v1/market.py via app.py


# NOTE: /api/market/transition endpoint removed — canonical: v1/market.py via app.py


# NOTE: /api/market/multi-tf endpoint removed — canonical: v1/market.py via app.py


# NOTE: /api/market/risk-appetite endpoint removed — canonical: v1/market.py via app.py

# NOTE: /api/notifications endpoint removed — no v1 equivalent; use admin/alerts instead

# NOTE: /api/audit endpoint removed — canonical: v1/system.py via app.py

# NOTE: /api/stats endpoint removed — canonical: v1/system.py via app.py

# NOTE: /api/tickers endpoint removed — canonical: v1/market.py via app.py


# ===================== WEBSOCKET =====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)) -> Any:
    """Gerçek zamanlı WebSocket bağlantısı — token doğrulama gerekli."""
    if not token:
        await websocket.close(code=4001, reason="Authentication required: pass ?token=YOUR_API_KEY")
        return

    # API key veya JWT token doğrulama
    authenticated = False
    try:
        from services.core.monitoring_security import monitoring_auth

        if monitoring_auth.verify_admin_token(token) or monitoring_auth.verify_metrics_token(token):
            authenticated = True
    except Exception as e:
        logger.debug("WS auth: monitoring token check failed", error=str(e))

    if not authenticated:
        try:
            from services.api.auth import jwt_handler

            payload = jwt_handler.verify_token(token)
            if payload:
                authenticated = True
        except Exception as e:
            logger.debug("WS auth: JWT check failed", error=str(e))

    if not authenticated:
        await websocket.close(code=4003, reason="Invalid or expired token")
        return

    await manager.connect(websocket)

    try:
        # İlk bağlantıda mevcut durumu gönder
        await manager.send_personal(
            {
                "type": "init",
                "message": "ALPHA BIST WebSocket bağlantısı aktif",
                "timestamp": datetime.now(UTC).isoformat(),
            },
            websocket,
        )

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")

                if action == "subscribe":
                    channels = msg.get("channels", [])
                    await manager.send_personal(
                        {
                            "type": "subscribed",
                            "channels": channels,
                        },
                        websocket,
                    )

                elif action == "ping":
                    await manager.send_personal(
                        {
                            "type": "pong",
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        websocket,
                    )

                elif action == "get_ticker":
                    ticker = msg.get("ticker")
                    features = feature_store.get_all(ticker)
                    await manager.send_personal(
                        {
                            "type": "ticker_data",
                            "ticker": ticker,
                            "data": features,
                        },
                        websocket,
                    )

                else:
                    await manager.send_personal(
                        {
                            "type": "error",
                            "message": f"Bilinmeyen action: {action}",
                        },
                        websocket,
                    )

            except json.JSONDecodeError:
                await manager.send_personal(
                    {
                        "type": "error",
                        "message": "Geçersiz JSON",
                    },
                    websocket,
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        manager.disconnect(websocket)


# ===================== ERROR HANDLERS =====================
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc) -> Any:
    """Otomatik eklendi."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc) -> Any:
    """Otomatik eklendi."""
    logger.error("Unhandled exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal server error",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


# ===================== MONITORING ENDPOINTS =====================


@app.get("/health/detailed")
async def health_detailed() -> Any:
    """Detaylı sağlık raporu (portfolio + locks + components)."""
    start = datetime.now(UTC)
    result = await portfolio_monitor.get_health_detailed()
    latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000
    result["latency_ms"] = round(latency_ms, 2)
    prometheus_metrics.inc("health_detailed_total")
    return result


@app.get("/metrics")
async def prometheus_metrics_endpoint(request: Request) -> Any:
    """Prometheus text format metrics (Bearer token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_metrics_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")

    text = await portfolio_monitor.get_prometheus_text()
    return JSONResponse(
        content=text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/admin/lock-metrics")
async def admin_lock_metrics(request: Request) -> Any:
    """Lock performans metrikleri (admin — token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Admin access required")

    prometheus_metrics.inc("admin_lock_metrics_total")
    return await portfolio_monitor.get_lock_metrics_api()


@app.get("/admin/portfolio")
async def admin_portfolio(request: Request) -> Any:
    """Portfolio sağlık ve muhasebe durumu (admin — token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Admin access required")

    prometheus_metrics.inc("admin_portfolio_total")
    return await portfolio_monitor.get_portfolio_api()


@app.get("/admin/alerts")
async def admin_alerts(request: Request) -> Any:
    """Aktif alert'ler (admin — token gerekli)."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {
        "summary": alerting.get_alert_summary(),
        "active": alerting.get_active_alerts(),
        "recent": alerting.get_all_alerts(limit=50),
    }


@app.get("/admin/auth-status")
async def admin_auth_status() -> Any:
    """Authentication durumu (public)."""
    return monitoring_auth.get_auth_status()


# ===================== POLICY MANAGEMENT ENDPOINTS =====================


@app.get("/admin/policy")
async def admin_policy_get(request: Request) -> Any:
    """Mevcut alert policy."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {
        "policy": alerting.get_policy_info(),
        "active_silences": alerting.get_active_silences(),
    }


@app.post("/admin/policy")
async def admin_policy_update(request: Request) -> Any:
    """Policy güncelle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    result = alerting.update_policy(body, actor=f"api:{client_ip}")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("errors", ["Update failed"]))
    return result


@app.post("/admin/policy/rollback")
async def admin_policy_rollback(request: Request) -> Any:
    """Policy rollback."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    target = body.get("version", 0)
    result = alerting.rollback_policy(target, actor=f"api:{client_ip}")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Rollback failed"))
    return result


@app.get("/admin/policy/history")
async def admin_policy_history(request: Request) -> Any:
    """Policy versiyon geçmişi."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {"history": alerting.get_policy_history()}


@app.get("/admin/policy/audit")
async def admin_policy_audit(request: Request) -> Any:
    """Policy audit log."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {"audit_log": alerting.get_policy_audit_log()}


@app.post("/admin/silence")
async def admin_silence_add(request: Request) -> Any:
    """Alert susturma ekle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    result = alerting.add_silence(
        alert_type=body.get("alert_type"),
        fingerprint=body.get("fingerprint"),
        duration_s=body.get("duration_s", 3600),
        reason=body.get("reason", ""),
        created_by=f"api:{client_ip}",
    )
    return result


@app.delete("/admin/silence")
async def admin_silence_remove(request: Request) -> Any:
    """Alert susturma kaldır."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    removed = alerting.remove_silence(
        fingerprint=body.get("fingerprint"),
        alert_type=body.get("alert_type"),
        actor=f"api:{client_ip}",
    )
    return {"removed": removed}


@app.post("/admin/policy/diff")
async def admin_policy_diff(request: Request) -> Any:
    """Policy diff (uygulamadan)."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    diff = alerting.compute_policy_diff(body)
    return {"diff": diff.to_dict()}


@app.post("/admin/silence/batch")
async def admin_silence_batch_add(request: Request) -> Any:
    """Toplu susturma ekle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    rules = body.get("rules", [])
    if not rules:
        raise HTTPException(status_code=400, detail="rules array required")

    results = alerting.batch_add_silences(rules, created_by=f"api:{client_ip}")
    return {"results": results, "total": len(rules)}


@app.delete("/admin/silence/batch")
async def admin_silence_batch_remove(request: Request) -> Any:
    """Toplu susturma kaldır."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    filters = body.get("filters", [])
    if not filters:
        raise HTTPException(status_code=400, detail="filters array required")

    result = alerting.batch_remove_silences(filters, actor=f"api:{client_ip}")
    return result


@app.post("/admin/policy/lock")
async def admin_policy_lock(request: Request) -> Any:
    """Policy düzenleme kilidi al."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    timeout = body.get("timeout_s", 30)
    owner = f"api:{client_ip}"

    acquired = alerting._policy.acquire_edit_lock(owner, timeout)
    if not acquired:
        lock_info = alerting._policy.get_lock_info()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Policy is locked by another user",
                "lock_info": lock_info,
            },
        )
    return {"success": True, "owner": owner, "timeout_s": timeout}


@app.delete("/admin/policy/lock")
async def admin_policy_unlock(request: Request) -> Any:
    """Policy düzenleme kilidi bırak."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    owner = f"api:{client_ip}"
    released = alerting._policy.release_edit_lock(owner)
    if not released:
        raise HTTPException(status_code=409, detail="Lock not owned by you")
    return {"success": True}


# ===================== MAIN =====================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        log_level="info",
    )
