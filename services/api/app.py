"""
ALPHA BIST — API Uygulaması v2.0 (CANONICAL ÜRETİM SUNUCUSU)

Tüm API bileşenlerini birleştiren ana uygulama.

Özellikler:
- 92 REST uç noktası (v1)
- 10 WebSocket kanalı
- JWT + RBAC kimlik doğrulama
- Hız sınırı
- OpenAPI/Swagger
- CORS
- Sağlık kontrolleri
- PostgreSQL + ClickHouse + Redis

NOT: Bu dosya CANONICAL üretim giriş noktasıdır.
- server.py → GELİŞTİRME/legacy (SQLite)
- main.py → KULLANIMDAN KALDIRILMIŞ (eski giriş noktası)
"""

import asyncio
import os
import time
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

import logging
from fastapi.responses import Response as FastAPIResponse
from opentelemetry import trace

from ..core.database import check_db_health, init_databases
from ..core.otel import setup_telemetry
from .rate_limiter import rate_limiter
from .v1 import v1_router
from services.core.otel import otel_trace
from services.core.alerting import alerting
from services.core.monitoring import portfolio_monitor
from services.core.monitoring_security import extract_api_key, extract_bearer_token, monitoring_auth

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("alpha-bist.api_app")
async def _startup_services(app: FastAPI = None) -> asyncio.Task | None:
    """Servisleri başlat, refresh task döndür."""
    await init_databases()

    try:
        from ..core.sharding import init_sharding

        await init_sharding()
    except Exception as e:
        logger.warning("sharding_baslatilamadi: hata=%s", e)

    refresh_task = None
    try:
        from ..core.cache_warmer import cache_warmer

        await cache_warmer.warm_all()
        refresh_task = asyncio.create_task(cache_warmer.refresh_hot_keys())
    except Exception as e:
        logger.warning("onbellek_isitma_basarisiz: hata=%s", e)

    try:
        from services.portfolio.main import portfolio_service

        await portfolio_service.start()
        logger.info("PortfolioService API yaşam döngüsünde başlatıldı")
    except Exception as e:
        logger.error("portfolio_service_baslatilamadi: hata=%s", e)

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
            logger.info("grpc_sunucusu_baslatildi: port=%s", grpc_port)
        return server
    except Exception as e:
        logger.warning("grpc_sunucusu_basarisiz: hata=%s", str(e))
        return None


@otel_trace("api.start_nats")
async def _start_nats() -> Any:
    """NATS bağlantısını başlat."""
    try:
        from ..nats.client import nats_client

        await nats_client.connect()
    except Exception as e:
        logger.warning("nats_baglantisi_basarisiz: hata=%s", str(e))


@otel_trace("api.start_service_mesh")
async def _start_service_mesh() -> Any:
    """Service mesh başlat."""
    try:
        from ..core.service_mesh import init_service_mesh, service_mesh

        init_service_mesh()
        return asyncio.create_task(service_mesh.start_monitoring())
    except Exception as e:
        logger.warning("servis_mesh_basarisiz: hata=%s", str(e))
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
        logger.info("Durum deposu tampon belleği kapatmada temizlendi")
    except Exception as e:
        logger.warning("kapatmada_durum_deposu_basarisiz: hata=%s", e)

    try:
        from ..core.offline_queue import offline_queue

        await offline_queue.flush()
        logger.info("Çevrimdışı kuyruk kapatmada temizlendi")
    except Exception as e:
        logger.warning("kapatmada_cevrimdisi_kuyruk_basarisiz: hata=%s", e)

    if grpc_server:
        try:
            await grpc_server.stop(grace=5)
            logger.info("gRPC sunucusu durduruldu")
        except Exception as e:
            logger.warning("grpc_durdurma_hatasi: hata=%s", str(e))

    try:
        from ..nats.client import nats_client

        await nats_client.close()
    except Exception:
        logger.warning("nats_kapatma_basarisiz", exc_info=True)

    logger.info("ALPHA BIST API kapatma tamamlandı")


async def lifespan(app: FastAPI) -> Any:
    """Application lifespan — DB lifecycle dahil."""
    logger.info("ALPHA BIST API başlatılıyor (canonical üretim sunucusu)")

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

    # İstek zamanlama middleware
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next) -> Any:
        """Her isteğin işlenme süresini ölçer ve X-Process-Time-Ms başlığı olarak ekler."""
        start = time.monotonic()
        response = await call_next(request)
        duration = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time-Ms"] = str(round(duration, 2))
        return response

    # İstek kimliği middleware — her isteğe benzersiz ID ata
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Any:
        """Her isteğe benzersiz bir X-Request-ID atar, dağıtık izleme ile uyumlu."""
        # İstemciden gelen X-Request-ID'yi kullan, yoksa üret
        request_id = request.headers.get("X-Request-ID") or str(_uuid.uuid4())

        # Context değişkenine kaydet (dağıtık izleme ile uyumlu)
        try:
            from services.core.distributed_tracing import correlation_id_var

            correlation_id_var.set(request_id)
        except ImportError:
            logger.debug("dağıtık_izleme_modülü_mevcut_değil")

        # Structlog bağlamına ekle (tüm loglarda otomatik görünür)
        # structlog.contextvars yerine request.state kullanılıyor

        # İstek durumuna ekle (uç noktalardan erişim için)
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # İstek zaman aşımı middleware — uzun süren istekleri kes
    @app.middleware("http")
    async def timeout_middleware(request: Request, call_next) -> Any:
        """30 saniyeyi aşan istekleri zaman aşımına uğratır, WebSocket/SSE hariç."""
        # Zaman aşımı olmayan uç noktalar
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # WebSocket ve SSE uç noktaları zaman aşımından muaf (uzun ömürlü bağlantılar)
        if "/ws/" in request.url.path or request.url.path.endswith("/stream"):
            return await call_next(request)

        # Accept header'ı SSE ise zaman aşımı uygulama
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

    # Hız sınırı başlıkları middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next) -> Any:
        """İstemci bazlı hız sınırı uygular, yerel ve dahili istekleri baypas eder."""
        client_id = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method

        # Yerel geliştirme ve dahili docker proxy baypası
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

    # Yapısal hata yanıtları — global istisna işleyicileri
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Any:
        """HTTP hatalarını structured ErrorResponse formatında döndür."""
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

    # API sürüm başlığı — tüm yanıtlarda
    @app.middleware("http")
    async def api_version_middleware(request: Request, call_next) -> Any:
        """API uç noktalarına X-API-Version ve deprecation politikası başlıkları ekler."""
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["X-API-Version"] = "1.0.0"
            response.headers["X-API-Deprecation-Policy"] = (
                "https://github.com/servetarslan02/bist-100/blob/main/API_CHANGELOG.md"
            )
        return response

    # Kullanımdan kaldırma takibi — eski uç noktalar için Sunset başlığı
    KULLANIMDAN_KALDIRILAN_UCT_NOKTALAR: dict[str, str] = {
        # yol: sunset_tarihi (ISO 8601)
        # Örnek: "/api/v1/eski_uct_nokta": "2027-03-01",
    }

    @app.middleware("http")
    async def deprecation_middleware(request: Request, call_next) -> Any:
        """Kullanımdan kaldırılan uç noktalar için Sunset ve Deprecation başlıkları ekler."""
        response = await call_next(request)
        path = request.url.path
        if path in KULLANIMDAN_KALDIRILAN_UCT_NOKTALAR:
            response.headers["Sunset"] = KULLANIMDAN_KALDIRILAN_UCT_NOKTALAR[path]
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</api/v1/docs>; rel="successor-version"'
            logger.warning(
                "deprecated_endpoint_used",
                path=path,
                sunset=KULLANIMDAN_KALDIRILAN_UCT_NOKTALAR[path],
                request_id=getattr(request.state, "request_id", None),
            )
        return response

    # v1 yönlendirici
    app.include_router(v1_router)
    from .v1.ws import router as root_ws_router

    app.include_router(root_ws_router, prefix="/ws", tags=["WebSockets (Root)"])

    # mTLS sağlık uç noktası
    try:
        from ..core.mtls import create_mtls_health_endpoint

        app.include_router(create_mtls_health_endpoint(), tags=["mTLS"])
        logger.info("mTLS sağlık uç noktası kaydedildi")
    except Exception as e:
        logger.debug("mtls_saglik_uct_noktasi_kaydedilmedi: hata=%s", str(e))

    # Kök uç noktalar ve Web UI Gösterge Paneli
    @app.get("/", response_class=FastAPIResponse)
    @app.get("/dashboard", response_class=FastAPIResponse)
    async def dashboard() -> Any:
        """Ana sayfa ve gösterge paneli — HTML dosyası veya JSON bilgi döndürür."""
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
        """Tüm servislerin sağlık durumunu kontrol eder."""
        db_health = await check_db_health()

        # NATS sağlık denetimi
        nats_status = "unavailable"
        try:
            from ..nats.client import nats_client

            if nats_client.is_connected:
                nats_status = "healthy"
        except Exception:
            logger.warning("nats_saglik_denetimi_basarisiz", exc_info=True)

        # gRPC sağlık denetimi
        grpc_status = "unavailable"
        try:
            from ..grpc.server import HAS_GRPC

            grpc_status = "healthy" if HAS_GRPC else "unavailable"
        except Exception:
            logger.warning("grpc_saglik_denetimi_basarisiz", exc_info=True)

        # mTLS sağlık denetimi
        mtls_status = "unavailable"
        try:
            from ..core.mtls import get_mtls_status

            mtls_info = get_mtls_status()
            mtls_status = "healthy" if mtls_info.get("enabled") else "disabled"
        except Exception:
            logger.warning("mtls_saglik_denetimi_basarisiz", exc_info=True)

        all_services = {**db_health, "nats": nats_status, "grpc": grpc_status, "mtls": mtls_status}
        core_service_keys = ["postgres", "clickhouse", "redis", "questdb", "nats", "grpc", "mtls"]
        all_healthy = all(all_services.get(k) in ("healthy", "disabled") for k in core_service_keys)
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

    # ===================== YÖNETİCİ UÇ NOKTALARI (server.py'den taşındı) =====================

    @app.get("/admin/lock-metrics")
    async def admin_lock_metrics(request: Request) -> Any:
        """Lock performans metrikleri (admin — token gerekli)."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            monitoring_auth.record_failed_attempt(client_ip)
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return await portfolio_monitor.get_lock_metrics_api()

    @app.get("/admin/portfolio")
    async def admin_portfolio(request: Request) -> Any:
        """Portfolio sağlık ve muhasebe durumu (admin — token gerekli)."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            monitoring_auth.record_failed_attempt(client_ip)
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return await portfolio_monitor.get_portfolio_api()

    @app.get("/admin/alerts")
    async def admin_alerts(request: Request) -> Any:
        """Aktif alert'ler (admin — token gerekli)."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return {
            "summary": alerting.get_alert_summary(),
            "active": alerting.get_active_alerts(),
            "recent": alerting.get_all_alerts(limit=50),
        }

    @app.get("/admin/auth-status")
    async def admin_auth_status() -> Any:
        """Authentication durumu (public)."""
        return monitoring_auth.get_auth_status()

    @app.get("/admin/policy")
    async def admin_policy_get(request: Request) -> Any:
        """Mevcut alert policy."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return {
            "policy": alerting.get_policy_info(),
            "active_silences": alerting.get_active_silences(),
        }

    @app.post("/admin/policy")
    async def admin_policy_update(request: Request) -> Any:
        """Policy güncelle."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json()
        result = alerting.update_policy(body, actor=f"api:{client_ip}")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("errors", ["Güncelleme başarısız"]))
        return result

    @app.post("/admin/policy/rollback")
    async def admin_policy_rollback(request: Request) -> Any:
        """Policy rollback."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        target = body.get("version", 0)
        result = alerting.rollback_policy(target, actor=f"api:{client_ip}")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Geri alma başarısız"))
        return result

    @app.get("/admin/policy/history")
    async def admin_policy_history(request: Request) -> Any:
        """Policy versiyon geçmişi."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return {"history": alerting.get_policy_history()}

    @app.get("/admin/policy/audit")
    async def admin_policy_audit(request: Request) -> Any:
        """Policy audit log."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        return {"audit_log": alerting.get_policy_audit_log()}

    @app.post("/admin/silence")
    async def admin_silence_add(request: Request) -> Any:
        """Alert susturma ekle."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

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
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

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
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json()
        diff = alerting.compute_policy_diff(body)
        return {"diff": diff.to_dict()}

    @app.post("/admin/silence/batch")
    async def admin_silence_batch_add(request: Request) -> Any:
        """Toplu susturma ekle."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json()
        rules = body.get("rules", [])
        if not rules:
            raise HTTPException(status_code=400, detail="rules dizisi gerekli")

        results = alerting.batch_add_silences(rules, created_by=f"api:{client_ip}")
        return {"results": results, "total": len(rules)}

    @app.delete("/admin/silence/batch")
    async def admin_silence_batch_remove(request: Request) -> Any:
        """Toplu susturma kaldır."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        filters = body.get("filters", [])
        if not filters:
            raise HTTPException(status_code=400, detail="filters dizisi gerekli")

        result = alerting.batch_remove_silences(filters, actor=f"api:{client_ip}")
        return result

    @app.post("/admin/policy/lock")
    async def admin_policy_lock(request: Request) -> Any:
        """Policy düzenleme kilidi al."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        timeout = body.get("timeout_s", 30)
        owner = f"api:{client_ip}"

        acquired = alerting._policy.acquire_edit_lock(owner, timeout)
        if not acquired:
            lock_info = alerting._policy.get_lock_info()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Policy başka bir kullanıcı tarafından kilitli",
                    "lock_info": lock_info,
                },
            )
        return {"success": True, "owner": owner, "timeout_s": timeout}

    @app.delete("/admin/policy/lock")
    async def admin_policy_unlock(request: Request) -> Any:
        """Policy düzenleme kilidi bırak."""
        client_ip = request.client.host if request.client else "unknown"
        if not monitoring_auth.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Hız sınırı aşıldı")

        token = extract_bearer_token(request.headers.get("authorization"))
        api_key = extract_api_key(dict(request.headers))
        if not (monitoring_auth.verify_admin_token(token or "") or monitoring_auth.verify_admin_token(api_key or "")):
            raise HTTPException(status_code=401, detail="Yönetici erişimi gerekli")

        owner = f"api:{client_ip}"
        released = alerting._policy.release_edit_lock(owner)
        if not released:
            raise HTTPException(status_code=409, detail="Kilit size ait değil")
        return {"success": True}

    return app


# Tekil uygulama
app = create_app()
