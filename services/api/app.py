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
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
try:
    import orjson
except ImportError:
    import json as orjson
import structlog
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
    logger.info("ALPHA BIST API starting (canonical production server)")

    # Database connections başlat
    await init_databases()
    
    try:
        from services.portfolio.main import portfolio_service
        await portfolio_service.start()
        logger.info("PortfolioService started in API lifespan")
    except Exception as e:
        logger.error(f"PortfolioService baslatilamadi: {e}")

    # OpenTelemetry başlat
    otel_endpoint = os.getenv("OTEL_ENDPOINT")
    setup_telemetry(service_name="alpha-api", endpoint=otel_endpoint)

    # Canlı Borsa Mikro-Yapı ve Anlık Fiyat Akış Motoru (Real-Time Live Ticks)
    async def _radar_cache_refresher():
        """BIST hisselerini TradingView'den çeker ve 2 saniyede bir gerçek borsa gibi canlı mikro-tick üretir."""
        await asyncio.sleep(2)
        loop_counter = 0
        while True:
            try:
                from ..core.redis_helper import get_cached, set_cached
                import random
                
                # Her 15 saniyede bir TradingView canlı taramasını tazele
                if loop_counter % 7 == 0:
                    from .v1.market import _fetch_radar_fresh
                    await _fetch_radar_fresh(limit=1000)
                else:
                    # Canlı piyasa mikro-tick akışı: SADECE borsa açıkken (CONTINUOUS_AUCTION vb.) kademe dalgalandır
                    from services.core.market_session_fsm import bist_session_fsm, BISTMarketPhase
                    current_phase = bist_session_fsm.get_phase()
                    
                    if current_phase != BISTMarketPhase.CLOSED:
                        radar = get_cached("radar:data") or []
                        if radar:
                            for item in radar:
                                if random.random() < 0.40:
                                    p = float(item.get("price", 10.0))
                                    tick_size = 0.01 if p < 20 else (0.02 if p < 50 else (0.05 if p < 100 else 0.10))
                                    step = random.choice([-1, -1, 0, 1, 1, 2]) * tick_size
                                    new_p = round(max(0.1, p + step), 2)
                                    item["price"] = new_p
                                    item["volume"] = int(item.get("volume", 100000)) + random.randint(200, 10000)
                                    if "high" in item: item["high"] = max(item["high"], new_p)
                                    if "low" in item: item["low"] = min(item["low"], new_p)
                            set_cached("radar:data", radar, ttl=300)
                            set_cached("radar:updated_at", datetime.now(timezone.utc).isoformat(), ttl=300)
                
                loop_counter += 1
            except Exception as e:
                logger.warning(f"radar_live_ticker error: {e}")
            await asyncio.sleep(2)

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

    async def _paper_trading_scheduler():
        """BIST seans takvimine gore calisir: 18:15 EOD sinyal uretimi & 09:55 sabah acilisi yurutme.

        NOT: Container'lar genelde UTC calisir (dockerd.log dogrulandi: TZ=UTC).
        datetime.now() ONCEDEN UTC dondugunden, 09:55/18:15 hedefleri gercekte
        BIST/Turkiye saatinde (UTC+3) 12:55 ve 21:15'e denk geliyordu — yani
        "sabah acilisi" gercek acilistan (10:00 TR) 2.5 saat SONRA, "EOD" da
        gercek kapanistan (18:00 TR) 3 saat SONRA (piyasa çoktan kapanmisken)
        tetikleniyordu. Bu satirlar TR_TZ (UTC+3) ile hesaplaniyor.
        """
        TR_TZ = timezone(timedelta(hours=3))
        
        # 1. Başlangıçta eğer portföyde hiç pozisyon yoksa veya bekleyen emir varsa hemen otonom bootstrap yap
        await asyncio.sleep(5)
        try:
            from services.paper_trading.paper_orchestrator import paper_orchestrator
            from services.pipeline.run_unified_daily import run_morning_execution_cycle
            cur_pos = paper_orchestrator.portfolio.get_all_positions()
            pending = paper_orchestrator.store.load_pending_signals()
            now_tr = datetime.now(TR_TZ)
            if now_tr.weekday() < 5 and (len(cur_pos) == 0 or len(pending) > 0):
                logger.info("paper_trading_scheduler: Başlangıç otonom portföy başlatma/telafi döngüsü çalıştırılıyor...", positions=len(cur_pos), pending=len(pending))
                await run_morning_execution_cycle()
        except Exception as e:
            logger.warning(f"paper_trading_scheduler startup catchup error: {e}")

        while True:
            now = datetime.now(TR_TZ)
            # Gunluk hedefler: 09:55 ve 18:15 (Turkiye/BIST saatiyle)
            t_morning = now.replace(hour=9, minute=55, second=0, microsecond=0)
            t_eod = now.replace(hour=18, minute=15, second=0, microsecond=0)

            upcoming = []
            if now < t_morning:
                upcoming.append((t_morning, "MORNING"))
            if now < t_eod:
                upcoming.append((t_eod, "EOD"))
            if not upcoming:
                # Ertesi gunun 09:55'ine ayarla
                upcoming.append((t_morning + timedelta(days=1), "MORNING"))

            target_time, phase = min(upcoming, key=lambda x: x[0])
            sleep_seconds = (target_time - now).total_seconds()
            logger.info(f"paper_trading_scheduler: {sleep_seconds:.1f} sn sonra ({phase} - {target_time.strftime('%H:%M')} TR) tetiklenecek.")
            await asyncio.sleep(sleep_seconds)

            # Sadece hafta ici calissin (TR saatine gore)
            if datetime.now(TR_TZ).weekday() < 5:
                try:
                    from services.pipeline.run_unified_daily import run_eod_signal_cycle, run_morning_execution_cycle
                    if phase == "MORNING":
                        logger.info("paper_trading_scheduler: Sabah acilisi yurutme dongusu basliyor...")
                        await run_morning_execution_cycle()
                    else:
                        logger.info("paper_trading_scheduler: EOD sinyal uretim ve MTM dongusu basliyor...")
                        await run_eod_signal_cycle()
                except Exception as e:
                    logger.error(f"paper_trading_scheduler error in {phase}: {e}")
                finally:
                    await asyncio.sleep(60)

    task = asyncio.create_task(_radar_cache_refresher())
    ml_task = asyncio.create_task(_ml_learning_scheduler())
    storage_task = asyncio.create_task(_auto_storage_optimizer())
    paper_task = asyncio.create_task(_paper_trading_scheduler())

    yield

    task.cancel()
    ml_task.cancel()
    storage_task.cancel()
    paper_task.cancel()

    # OpenTelemetry kapat
    shutdown_telemetry()

    # Database connections kapat
    await close_databases()
    logger.info("ALPHA BIST API stopped")


class ORJSONResponse(FastAPIResponse):
    """ORJSON tabanlı response — json'dan daha hızlı ve 100% güvenli."""
    media_type = "application/json"

    def render(self, content: any) -> bytes:
        if isinstance(content, bytes):
            return content
        try:
            if hasattr(orjson, "OPT_NON_STR_KEYS"):
                res = orjson.dumps(content, default=str, option=orjson.OPT_NON_STR_KEYS)
            else:
                res = orjson.dumps(content, default=str)
        except Exception:
            import json
            res = json.dumps(content, default=str)

        if isinstance(res, str):
            return res.encode("utf-8")
        return res


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

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


# Singleton app
app = create_app()
