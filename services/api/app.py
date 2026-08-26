"""
ALPHA BIST — API Application v2.0 (CANONICAL PRODUCTION SERVER)

Tüm API bileşenlerini birleştiren ana uygulama.

Özellikler:
- 92 REST endpoint (v1)
- 10 WebSocket kanalı
- JWT + RBAC authentication
- Rate limiting
- OpenAPI/Swagger
- CORS
- Health checks
- PostgreSQL + ClickHouse + Redis

NOT: Bu dosya CANONICAL production entry point'tir.
- server.py → DEV/legacy (SQLite)
- main.py → DEPRECATED (eski entry point)
"""

import os
import time
import asyncio
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
try:
    import orjson
except ImportError:
    import orjson as orjson
import structlog
from fastapi.responses import Response as FastAPIResponse

from .v1 import v1_router
from .rate_limiter import rate_limiter
from ..core.database import init_databases, close_databases, check_db_health
from ..core.otel import setup_telemetry, shutdown_telemetry

logger = structlog.get_logger()


@asynccontextmanager
async def _startup_services() -> Optional[asyncio.Task]:
    """Servisleri başlat, refresh task döndür."""
    await init_databases()

    try:
        from ..core.sharding import init_sharding
        await init_sharding()
    except Exception as e:
        logger.warning(f"Sharding not started: {e}")

    refresh_task = None
    try:
        from ..core.cache_warmer import cache_warmer
        await cache_warmer.warm_all()
        refresh_task = asyncio.create_task(cache_warmer.refresh_hot_keys())
    except Exception as e:
        logger.warning(f"Cache warming failed: {e}")

    try:
        from services.portfolio.main import portfolio_service
        await portfolio_service.start()
        logger.info("PortfolioService started in API lifespan")
    except Exception as e:
        logger.error(f"PortfolioService baslatilamadi: {e}")

    otel_endpoint = os.getenv("OTEL_ENDPOINT")
    setup_telemetry(service_name="alpha-api", endpoint=otel_endpoint)
    return refresh_task


def _start_background_tasks(refresh_task) -> dict:
    """Arka plan görevlerini başlat."""
    from .background_tasks import (
        radar_cache_refresher, ml_learning_scheduler,
        auto_storage_optimizer, paper_trading_scheduler,
    )
    return {
        "radar": asyncio.create_task(radar_cache_refresher()),
        "ml": asyncio.create_task(ml_learning_scheduler()),
        "storage": asyncio.create_task(auto_storage_optimizer()),
        "paper": asyncio.create_task(paper_trading_scheduler()),
    }


async def _start_grpc():
    """gRPC sunucusunu başlat."""
    try:
        from ..grpc.server import start_grpc_server
        grpc_port = int(os.environ.get("GRPC_PORT", "50051"))
        server = await start_grpc_server(port=grpc_port)
        if server:
            logger.info("gRPC server started", port=grpc_port)
        return server
    except Exception as e:
        logger.warning("gRPC server not started", error=str(e))
        return None


async def _start_nats():
    """NATS bağlantısını başlat."""
    try:
        from ..nats.client import nats_client
        await nats_client.connect()
    except Exception as e:
        logger.warning("NATS not connected", error=str(e))


async def _start_service_mesh():
    """Service mesh başlat."""
    try:
        from ..core.service_mesh import service_mesh, init_service_mesh
        init_service_mesh()
        return asyncio.create_task(service_mesh.start_monitoring())
    except Exception as e:
        logger.warning(f"Service mesh not started: {e}")
        return None


async def _shutdown(background_tasks: dict, refresh_task, mesh_task, grpc_server):
    """Tüm servisleri düzgün şekilde kapat."""
    for task in background_tasks.values():
        task.cancel()
    if refresh_task:
        refresh_task.cancel()
    if mesh_task:
        mesh_task.cancel()

    try:
        from ..core.state_store import state_store
        state_store.flush()
        logger.info("State store buffer flushed on shutdown")
    except Exception as e:
        logger.warning(f"State store flush on shutdown failed: {e}")

    try:
        from ..core.offline_queue import offline_queue
        await offline_queue.flush()
        logger.info("Offline queue flushed on shutdown")
    except Exception as e:
        logger.warning(f"Offline queue flush on shutdown failed: {e}")

    if grpc_server:
        try:
            await grpc_server.stop(grace=5)
            logger.info("gRPC server stopped")
        except Exception as e:
            logger.warning("gRPC stop error", error=str(e))

    try:
        from ..nats.client import nats_client
        await nats_client.close()
    except Exception:
        logger.warning("Caught Exception in _shutdown", exc_info=True)

    logger.info("ALPHA BIST API shutdown complete")


async def lifespan(app: FastAPI):
    """Application lifespan — DB lifecycle dahil."""
    logger.info("ALPHA BIST API starting (canonical production server)")

    refresh_task = await _startup_services()
    background_tasks = _start_background_tasks(refresh_task)
    grpc_server = await _start_grpc()
    await _start_nats()
    mesh_task = await _start_service_mesh()

    yield

    await _shutdown(background_tasks, refresh_task, mesh_task, grpc_server)

def create_app() -> FastAPI:
    """FastAPI uygulaması oluştur."""
    app = FastAPI(
        title="ALPHA BIST API",
        description="BIST Market Intelligence & Quant Engine — 92 endpoint, 10 WebSocket kanalı",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
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

    # Otomatik GZip Sıkıştırma (1KB'dan büyük tüm yanıtları %85-90 sıkıştırır)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Request timing middleware
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time-Ms"] = str(round(duration, 2))
        return response

    # Rate limit headers middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        client_id = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method

        # Local dev and internal docker proxy bypass
        if client_id in ["127.0.0.1", "localhost", "testclient"] or client_id.startswith("172.") or client_id.startswith("192.168.") or client_id.startswith("10."):
            allowed = True
            info = {"limit": 10000, "remaining": 9999, "retry_after": 0}
        else:
            group = rate_limiter.get_endpoint_group(path, method)
            allowed, info = await rate_limiter.check(client_id, group)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Retry after {info.get('retry_after', 60)}s"},
                headers={
                    "Retry-After": str(info.get("retry_after", 60)),
                    "X-RateLimit-Limit": str(info.get("limit", 100)),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(info.get("limit", 100))
        response.headers["X-RateLimit-Remaining"] = str(info.get("remaining", 0))
        return response

    # v1 router
    app.include_router(v1_router)
    from .v1.ws import router as root_ws_router
    app.include_router(root_ws_router, prefix="/ws", tags=["WebSockets (Root)"])

    # mTLS health endpoint
    try:
        from ..core.mtls import create_mtls_health_endpoint
        app.include_router(create_mtls_health_endpoint(), tags=["mTLS"])
        logger.info("mTLS health endpoint registered")
    except Exception as e:
        logger.debug("mTLS health endpoint not registered", error=str(e))

    # Root endpoints & Web UI Dashboard
    @app.get("/", response_class=FastAPIResponse)
    @app.get("/dashboard", response_class=FastAPIResponse)
    async def dashboard():
        dashboard_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "apps", "web", "dashboard.html")
        if os.path.exists(dashboard_path):
            with open(dashboard_path, "rb") as f:
                content = f.read()
            return FastAPIResponse(content=content, media_type="text/html")
        return JSONResponse(content={"name": "ALPHA BIST API", "version": "2.0.0", "docs": "/docs"})

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        from datetime import datetime, timezone
        db_health = await check_db_health()

        # NATS sağlık kontrolü
        nats_status = "unavailable"
        try:
            from ..nats.client import nats_client
            if nats_client.is_connected:
                nats_status = "healthy"
        except Exception:
            logger.warning("Caught Exception in health", exc_info=True)

        # gRPC sağlık kontrolü
        grpc_status = "unavailable"
        try:
            from ..grpc.server import HAS_GRPC
            grpc_status = "healthy" if HAS_GRPC else "unavailable"
        except Exception:
            logger.warning("Caught Exception in health", exc_info=True)

        # mTLS sağlık kontrolü
        mtls_status = "unavailable"
        try:
            from ..core.mtls import get_mtls_status
            mtls_info = get_mtls_status()
            mtls_status = "healthy" if mtls_info.get("enabled") else "disabled"
        except Exception:
            logger.warning("Caught Exception in health", exc_info=True)

        all_services = {**db_health, "nats": nats_status, "grpc": grpc_status, "mtls": mtls_status}
        all_healthy = all(v in ("healthy", "disabled") for v in all_services.values())
        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "server": "canonical (app.py)",
            "services": all_services,
        }

    @app.get("/health/detailed")
    async def health_detailed():
        """Detaylı sağlık raporu."""
        from datetime import datetime, timezone
        db_health = await check_db_health()
        return {
            "status": "healthy" if all(v == "healthy" for v in db_health.values()) else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "server": "canonical (app.py)",
            "services": db_health,
            "endpoints": {
                "v1_router": "/api/v1",
                "docs": "/docs",
                "openapi": "/openapi.json",
            },
        }

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


# Singleton app
app = create_app()
