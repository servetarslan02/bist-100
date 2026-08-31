from typing import Any

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

import asyncio
import os
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

try:
    import orjson
except ImportError:
    import orjson as orjson
import functools

import structlog
from fastapi.responses import Response as FastAPIResponse
from opentelemetry import trace

from ..core.database import check_db_health, init_databases
from ..core.otel import setup_telemetry
from .rate_limiter import rate_limiter
from .v1 import v1_router

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.api_app")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


async def _startup_services(app: FastAPI = None) -> asyncio.Task | None:
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
    setup_telemetry(service_name="alpha-api", endpoint=otel_endpoint, app=app)
    return refresh_task


_bg_tasks = set()


def _start_background_tasks(refresh_task) -> dict:
    """Arka plan görevlerini başlat."""
    from .background_tasks import (
        auto_storage_optimizer,
        ml_learning_scheduler,
        paper_trading_scheduler,
        radar_cache_refresher,
    )

    tasks = {
        "radar": asyncio.create_task(radar_cache_refresher()),
        "ml": asyncio.create_task(ml_learning_scheduler()),
        "storage": asyncio.create_task(auto_storage_optimizer()),
        "paper": asyncio.create_task(paper_trading_scheduler()),
    }

    global _bg_tasks
    for task in tasks.values():
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    return tasks


@otel_trace("api.start_grpc")
async def _start_grpc() -> Any:
    """gRPC sunucusunu başlat."""
    try:
        from ..grpc.server import start_grpc_server

        grpc_port = int(os.environ.get("GRPC_PORT", "50051"))
        server = await start_grpc_server(port=grpc_port)
        if server:
            logger.info("grpc_server_started", port=grpc_port)
        return server
    except Exception as e:
        logger.warning("grpc_server_failed", error=str(e))
        return None


@otel_trace("api.start_nats")
async def _start_nats() -> Any:
    """NATS bağlantısını başlat."""
    try:
        from ..nats.client import nats_client

        await nats_client.connect()
    except Exception as e:
        logger.warning("nats_connection_failed", error=str(e))


@otel_trace("api.start_service_mesh")
async def _start_service_mesh() -> Any:
    """Service mesh başlat."""
    try:
        from ..core.service_mesh import init_service_mesh, service_mesh

        init_service_mesh()
        return asyncio.create_task(service_mesh.start_monitoring())
    except Exception as e:
        logger.warning("service_mesh_failed", error=str(e))
        return None


@otel_trace("api.shutdown")
async def _shutdown(background_tasks: dict, refresh_task, mesh_task, grpc_server) -> Any:
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


async def lifespan(app: FastAPI) -> Any:
    """Application lifespan — DB lifecycle dahil."""
    logger.info("ALPHA BIST API starting (canonical production server)")

    refresh_task = await _startup_services(app)
    background_tasks = _start_background_tasks(refresh_task)
    grpc_server = await _start_grpc()
    await _start_nats()
    mesh_task = await _start_service_mesh()

    yield

    await _shutdown(background_tasks, refresh_task, mesh_task, grpc_server)


def create_app() -> FastAPI:
    """FastAPI uygulamasını oluştur ve yapılandır."""
    from fastapi.responses import ORJSONResponse

    app = FastAPI(
        title="ALPHA BIST API",
        description="BIST Market Intelligence & Quant Engine — 92 endpoint, 10 WebSocket kanalı",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # CORS
    allowed_origins = os.environ.get("CORS_ORIGINS", "").split(",")
    if not allowed_origins or allowed_origins == [""]:
        allowed_origins = ["http://localhost:3000"]  # Default: sadece local dev

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # Otomatik GZip Sıkıştırma (1KB'dan büyük tüm yanıtları %85-90 sıkıştırır)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Request timing middleware
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        start = time.monotonic()
        response = await call_next(request)
        duration = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time-Ms"] = str(round(duration, 2))
        return response

    # Request ID middleware — her isteğe unique ID ata
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        import uuid as _uuid

        import structlog

        # Client'tan gelen X-Request-ID'yi kullan, yoksa üret
        request_id = request.headers.get("X-Request-ID") or str(_uuid.uuid4())

        # Context variable'a kaydet (distributed tracing ile uyumlu)
        try:
            from services.core.distributed_tracing import correlation_id_var

            correlation_id_var.set(request_id)
        except ImportError:
            logger.error("Exception caught", exc_info=True)

        # Structlog context'e ekle (tüm loglarda otomatik görünür)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Request state'e ekle (endpoint'lerden erişim için)
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Request timeout middleware — uzun süren istekleri kes
    @app.middleware("http")
    async def timeout_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        import asyncio

        # Timeout'suz endpoint'ler
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # WebSocket ve SSE endpoint'leri timeout'dan muaf (uzun ömürlü bağlantılar)
        if "/ws/" in request.url.path or request.url.path.endswith("/stream"):
            return await call_next(request)

        # Accept header'ı SSE ise timeout uygulama
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            return await call_next(request)

        try:
            return await asyncio.wait_for(call_next(request), timeout=30.0)
        except TimeoutError:
            request_id = getattr(request.state, "request_id", None)
            logger.error(
                "request_timeout",
                path=request.url.path,
                method=request.method,
                request_id=request_id,
            )
            return JSONResponse(
                status_code=504,
                content={
                    "success": False,
                    "error": "Gateway timeout",
                    "detail": "Request 30 saniye içinde tamamlanamadı.",
                    "status_code": 504,
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

    # Rate limit headers middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        client_id = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method

        # Local dev and internal docker proxy bypass
        if (
            client_id in ["127.0.0.1", "localhost", "testclient"]
            or client_id.startswith("172.")
            or client_id.startswith("192.168.")
            or client_id.startswith("10.")
        ):
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

    # Global exception handlers — structured error responses
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Any:
        """HTTP hatalarını structured ErrorResponse formatında döndür."""
        import uuid as _uuid

        request_id = getattr(request.state, "request_id", None) or str(_uuid.uuid4())
        logger.warning(
            "http_error",
            status_code=exc.status_code,
            detail=str(exc.detail),
            path=request.url.path,
            method=request.method,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": str(exc.detail),
                "status_code": exc.status_code,
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Any:
        """Validation hatalarını structured ErrorResponse formatında döndür."""
        import uuid as _uuid

        request_id = getattr(request.state, "request_id", None) or str(_uuid.uuid4())
        errors = exc.errors()
        logger.warning(
            "validation_error",
            errors=errors,
            path=request.url.path,
            method=request.method,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "Validation error",
                "detail": errors,
                "status_code": 422,
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> Any:
        """Beklenmedik hataları structured ErrorResponse formatında döndür."""
        import uuid as _uuid

        request_id = getattr(request.state, "request_id", None) or str(_uuid.uuid4())
        logger.error(
            "unhandled_exception",
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
            method=request.method,
            request_id=request_id,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "detail": str(exc) if os.environ.get("DEBUG") else None,
                "status_code": 500,
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    # API version header — tüm response'larda
    @app.middleware("http")
    async def api_version_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["X-API-Version"] = "1.0.0"
            response.headers["X-API-Deprecation-Policy"] = (
                "https://github.com/servetarslan02/bist-100/blob/main/API_CHANGELOG.md"
            )
        return response

    # Deprecation tracking — eski endpoint'ler için Sunset header
    DEPRECATED_ENDPOINTS: dict[str, str] = {
        # path: sunset_date (ISO 8601)
        # Örnek: "/api/v1/old endpoint": "2027-03-01",
    }

    @app.middleware("http")
    async def deprecation_middleware(request: Request, call_next) -> Any:
        """Otomatik eklendi."""
        response = await call_next(request)
        path = request.url.path
        if path in DEPRECATED_ENDPOINTS:
            response.headers["Sunset"] = DEPRECATED_ENDPOINTS[path]
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</api/v1/docs>; rel="successor-version"'
            logger.warning(
                "deprecated_endpoint_used",
                path=path,
                sunset=DEPRECATED_ENDPOINTS[path],
                request_id=getattr(request.state, "request_id", None),
            )
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
    async def dashboard() -> Any:
        """Otomatik eklendi."""
        dashboard_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "apps", "web", "dashboard.html"
        )
        if os.path.exists(dashboard_path):
            with open(dashboard_path, "rb") as f:
                content = f.read()
            return FastAPIResponse(content=content, media_type="text/html")
        return JSONResponse(content={"name": "ALPHA BIST API", "version": "2.0.0", "docs": "/docs"})

    @app.get("/health")
    @app.get("/api/health")
    async def health() -> Any:
        """Otomatik eklendi."""
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
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "2.0.0",
            "server": "canonical (app.py)",
            "services": all_services,
        }

    @app.get("/health/detailed")
    async def health_detailed() -> Any:
        """Detaylı sağlık raporu."""
        db_health = await check_db_health()
        return {
            "status": "healthy" if all(v == "healthy" for v in db_health.values()) else "degraded",
            "timestamp": datetime.now(UTC).isoformat(),
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
    async def metrics() -> Any:
        """Prometheus metrics endpoint."""
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except (ImportError, Exception):
            from ..core.observability import prometheus_metrics

            return FastAPIResponse(
                content=prometheus_metrics.get_prometheus_text().encode("utf-8"),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    return app


# Singleton app
app = create_app()
