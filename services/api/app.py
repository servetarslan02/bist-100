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
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import orjson
from fastapi.responses import Response as FastAPIResponse

from .v1 import v1_router
from .auth import jwt_handler, Role
from .rate_limiter import rate_limiter
from ..core.database import init_databases, close_databases, check_db_health
from ..core.otel import setup_telemetry, shutdown_telemetry

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — DB lifecycle dahil."""
    import asyncio
    logger.info("ALPHA BIST API starting (canonical production server)")

    # Database connections başlat
    await init_databases()

    # OpenTelemetry başlat
    otel_endpoint = os.getenv("OTEL_ENDPOINT")
    setup_telemetry(service_name="alpha-api", endpoint=otel_endpoint)

    # Radar cache arka plan yenileme görevi
    async def _radar_cache_refresher():
        """Her 2 dakikada bir radar verisini yfinance'den çekip Redis'e yazar."""
        await asyncio.sleep(10)  # API hazır olana kadar bekle
        while True:
            try:
                from .v1.market import _fetch_radar_fresh
                logger.info("radar_cache: yenileniyor...")
                await _fetch_radar_fresh(limit=200)
                logger.info("radar_cache: güncellendi")
            except Exception as e:
                logger.warning(f"radar_cache: hata — {e}")
            await asyncio.sleep(120)  # 2 dakika

    # Model Öğrenme & Telafi (Catch-Up) Arka Plan Görevi
    async def _ml_learning_scheduler():
        """PC kapalı kaldığında kaçırılan eğitimleri anında tamamlar ve 4 saatte bir otonom öğrenir."""
        await asyncio.sleep(15)  # API ve veritabanı tam hazır olana kadar bekle
        
        # 1. Başlangıç Telafi Kontrolü
        try:
            from ..learning.learning_pipeline import LearningPipeline
            pipeline = LearningPipeline()
            loop = asyncio.get_event_loop()
            logger.info("ml_scheduler: Başlangıç eksik eğitim/veri telafi kontrolü yapılıyor...")
            await loop.run_in_executor(None, pipeline.check_and_catchup_if_needed)
            logger.info("ml_scheduler: Başlangıç telafi kontrolü tamamlandı.")
        except Exception as e:
            logger.warning(f"ml_scheduler startup catchup error: {e}")
            
        # 2. Düzenli Otonom Öğrenme Döngüsü (Her 4 saatte bir)
        while True:
            await asyncio.sleep(4 * 3600)
            try:
                from ..learning.learning_pipeline import LearningPipeline
                pipeline = LearningPipeline()
                loop = asyncio.get_event_loop()
                logger.info("ml_scheduler: Periyodik öğrenme döngüsü başlatılıyor...")
                await loop.run_in_executor(None, pipeline.run_learning_cycle)
                logger.info("ml_scheduler: Periyodik öğrenme başarıyla tamamlandı.")
            except Exception as e:
                logger.warning(f"ml_scheduler periodic error: {e}")

    # Otonom Veri Sıkıştırma ve Disk Koruma Arka Plan Görevi (Her 12 saatte bir)
    async def _auto_storage_optimizer():
        """Arka planda otomatik ClickHouse ZSTD sıkıştırma ve önbellek temizliği yapar."""
        while True:
            await asyncio.sleep(12 * 3600)
            try:
                from ..core.database import ch_execute
                ch_execute("OPTIMIZE TABLE bist_ticks FINAL")
                logger.info("auto_storage_optimizer: Periyodik ZSTD disk sıkıştırması ve temizliği tamamlandı.")
            except Exception as e:
                logger.warning(f"auto_storage_optimizer: {e}")

    task = asyncio.create_task(_radar_cache_refresher())
    ml_task = asyncio.create_task(_ml_learning_scheduler())
    storage_task = asyncio.create_task(_auto_storage_optimizer())

    yield

    task.cancel()
    ml_task.cancel()
    storage_task.cancel()

    # OpenTelemetry kapat
    shutdown_telemetry()

    # Database connections kapat
    await close_databases()
    logger.info("ALPHA BIST API stopped")


class ORJSONResponse(FastAPIResponse):
    """ORJSON tabanlı response — json'dan daha hızlı."""
    media_type = "application/json"

    def render(self, content: any) -> bytes:
        return orjson.dumps(content)


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

    # Legacy router aliases for backward test compatibility
    from .v1.learning import router as learning_router
    app.include_router(learning_router, prefix="/api/learning", tags=["Learning Legacy"])

    # Root endpoints
    @app.get("/")
    async def root():
        return {
            "name": "ALPHA BIST API",
            "version": "2.0.0",
            "docs": "/docs",
            "health": "/health",
            "api_v1": "/api/v1",
        }

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        from datetime import datetime, timezone
        db_health = await check_db_health()
        all_healthy = all(v == "healthy" for v in db_health.values())
        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "server": "canonical (app.py)",
            "services": db_health,
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

    return app


# Singleton app
app = create_app()
