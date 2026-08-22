# API — REST & WebSocket Katmanı

## Giriş

API modülü, ALPHA BIST sisteminin dış dünyaya açılan kapısıdır. FastAPI tabanlı 92 REST endpoint ve 10 WebSocket kanalı sunar. JWT + RBAC kimlik doğrulama, token bucket rate limiting, OpenAPI/Swagger dokümantasyonu, CORS, GZip sıkıştırma ve orjson tabanlı hızlı response üretimi sağlar. Production'da PostgreSQL + ClickHouse + Redis kullanır.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────┐
│                    app.py (CANONICAL)                        │
│                    FastAPI Application Factory                │
│  Lifespan: DB init, OpenTelemetry, background tasks          │
│  Middleware: CORS, GZip, timing, rate limit headers          │
├─────────────────────────────────────────────────────────────┤
│                    v1/__init__.py (Router)                    │
│  /api/v1 prefix ile 16 alt router                           │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────────┤
│market│port- │risk  │intel-│deci- │back- │learn-│ models     │
│      │folio │      │ligen-│sions │test  │ing   │            │
│      │      │      │ce    │      │      │      │            │
├──────┼──────┼──────┼──────┼──────┼──────┼──────┼────────────┤
│agents│scan- │macro │factor│alter-│viop  │event │ system     │
│      │ner   │      │s     │native│      │study │            │
├──────┴──────┴──────┴──────┴──────┴──────┴──────┴────────────┤
│                    dependencies.py                            │
│  get_current_user · check_rate_limit · require_role           │
├──────────┬──────────────┬───────────────────────────────────┤
│ auth.py  │ rate_limiter │ websocket.py                       │
│ JWT+RBAC │ Token bucket │ WebSocketServer                    │
│          │              │ 5 kanal: market/portfolio/risk/... │
├──────────┴──────────────┴───────────────────────────────────┤
│  server.py (DEPRECATED — dev/test) │ main.py (DEPRECATED)    │
└─────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| FastAPI | Async native, OpenAPI otomatik dokümantasyon, Pydantic validasyon, yüksek performans |
| Canonical app.py | server.py (SQLite dev) ve main.py (deprecated) ayrılmış; production tek entry point |
| JWT + RBAC | 5 rol (VIEWER/ANALYST/OPERATOR/ADMIN/SYSTEM) ile endpoint bazlı erişim kontrolü |
| Token bucket rate limiting | Farklı endpoint grupları için farklı limitler (analiz 10/dk, backtest 5/dk, scanner 3/dk) |
| ORJSONResponse | json.dumps'dan ~3x daha hızlı serialization |
| GZip middleware | 1KB+ yanıtları otomatik sıkıştırır; bandwidth tasarrufu |
| Background tasks | Radar cache yenileme (2 dk/10 dk), ML öğrenme (4 saat), disk optimizasyonu (12 saat) |
| WebSocket kanalları | Gerçek zamanlı fiyat, fırsat, portföy, risk, sistem durumu yayını |
| v1 router prefix | API versioning — gelecekte v2 eklenebilir, mevcut endpoint'ler bozulmaz |

## Uçtan Uca Veri Akışı

```
1. İstek → FastAPI
2. Middleware zinciri:
   a. CORS kontrolü
   b. GZip sıkıştırma (1KB+)
   c. Timing middleware (X-Process-Time-Ms header)
   d. Rate limit middleware (token bucket, X-RateLimit-* headers)
3. Router → v1 alt router → endpoint
4. Dependencies:
   a. get_current_user() → JWT veya API key doğrulama
   b. check_rate_limit() → endpoint grubu bazlı limit kontrolü
   c. require_role() → RBAC yetki kontrolü
5. Endpoint handler → servis katmanı çağrısı
6. ORJSONResponse → serialize → GZip → HTTP response

WebSocket akışı:
1. /ws?token=JWT → token doğrulama
2. ConnectionManager → bağlantı kabul
3. Client → {"action": "subscribe", "channels": ["market"]}
4. Server → periyodik broadcast (heartbeat, fiyat, fırsat)
5. Client → {"action": "get_ticker", "ticker": "THYAO"} → feature_store'dan veri
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `app.py` | **CANONICAL production server** — FastAPI factory (create_app), lifespan (DB init, OpenTelemetry, background tasks: radar cache, ML learning, storage optimizer), CORS/GZip/timing/rate-limit middleware, ORJSONResponse, health endpoint'leri, v1 router entegrasyonu |
| `server.py` | **DEPRECATED** — Development/test server (SQLite), legacy endpoint'ler (çoğu kaldırılmış), WebSocket /ws endpoint, admin endpoint'leri (policy, silence, lock metrics), monitoring (Prometheus /metrics) |
| `main.py` | **DEPRECATED** — Geriye uyumluluk redirect'i; `from .app import app` |
| `auth.py` | JWTHandler (HMAC-SHA256 token oluşturma/doğrulama), APIKeyManager (servisler arası), RBACChecker (rol bazlı erişim), Role enum (VIEWER/ANALYST/OPERATOR/ADMIN/SYSTEM), ROLE_PERMISSIONS mapping |
| `rate_limiter.py` | InMemoryRateLimiter — token bucket, 6 endpoint grubu (default 100/dk, analysis 10/dk, backtest 5/dk, scanner 3/dk, websocket 100/sn, auth 5/dk), stale bucket cleanup |
| `dependencies.py` | FastAPI dependency injection — get_client_id (X-Forwarded-For/X-Real-IP), get_current_user (JWT + API key + dev fallback), check_rate_limit, require_role, get_service_orchestrator |
| `websocket.py` | WebSocketServer — 5 kanal (market/opportunities/portfolio/risk/system), WebSocketConnection, broadcast queue, client mesaj işleme (ping/subscribe/get_ticker) |
| `v1/__init__.py` | v1_router — 16 alt router'ı /api/v1 prefix ile birleştirir |
| `v1/schemas.py` | Pydantic response modelleri — BaseResponse, ErrorResponse, PaginatedResponse, InstrumentInfo, OHLCVData, MarketStateResponse, PortfolioSummary, RiskOverview, VaRResult, OpportunityInfo, BacktestResult, OptionPrice, GreeksResult, SystemStatus, HealthCheck |
| `v1/market.py` | Piyasa verisi endpoint'leri — radar, regime, breadth, state, multi-tf, risk-appetite |
| `v1/portfolio.py` | Portföy endpoint'leri — summary, positions, trades, metrics, rebalance |
| `v1/risk.py` | Risk endpoint'leri — overview, VaR, stress test |
| `v1/intelligence.py` | Zeka endpoint'leri — features, regime, simulation |
| `v1/decisions.py` | Karar endpoint'leri — list, detail, approve/reject |
| `v1/backtest.py` | Backtest endpoint'leri — run, results, compare |
| `v1/learning.py` | Öğrenme endpoint'leri — status, cycles, drift |
| `v1/models.py` | Model endpoint'leri — list, versions, promote |
| `v1/agents.py` | Agent endpoint'leri — run pipeline, results, memory |
| `v1/scanner.py` | Scanner endpoint'leri — scan, opportunities, signals |
| `v1/macro.py` | Makro endpoint'leri — indicators, regime |
| `v1/factors.py` | Faktör endpoint'leri — list, values, correlation |
| `v1/alternative.py` | Alternative data endpoint'leri — features, sources, status |
| `v1/viop.py` | VIOP endpoint'leri — price, greeks, strategies, margin |
| `v1/event_study.py` | Event study endpoint'leri — analyze, results |
| `v1/system.py` | Sistem endpoint'leri — status, health, audit, stats |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Auth zorunlu** — `AUTH_STRICT=true` ortamda token yoksa 401; dev ortamda varsayılan VIEWER rolü.
2. **Rate limit bypass** — Local IP'ler (127.0.0.1, 172.*, 192.168.*, 10.*) rate limit'ten muaf.
3. **RBAC katı** — `/admin/*` endpoint'leri sadece ADMIN ve SYSTEM; write endpoint'leri OPERATOR+.
4. **API key header** — Servisler arası iletişimde `X-API-Key` header'ı kullanılır.
5. **WebSocket auth** — Token query parametresi (`?token=JWT`) ile doğrulama; token yoksa 4001 ile kapatılır.
6. **Response timing** — Her response'da `X-Process-Time-Ms` header'ı.
7. **ORJSON** — Varsayılan response class'ı ORJSONResponse; json.dumps'dan ~3x hızlı.
8. **Background task izolasyonu** — Radar cache, ML learning, storage optimizer ayrı asyncio task'ları; biri çökse diğerleri devam eder.

## Bilinen Sınırlamalar

- **In-memory rate limiter** — Production'da Redis tabanlı olmalı; restart sonrası sayaç sıfırlanır.
- **JWT secret zorunlu** — `JWT_SECRET` environment variable yoksa RuntimeError.
- **Background task lifecycle** — API restart'ta radar cache ve ML learning sıfırdan başlar.
- **WebSocket auth sadece bağlantıda** — Bağlantı sonrası token yenileme yok.
- **16 router dosyası** — Her yeni endpoint grubu için yeni dosya + v1/__init__.py güncellemesi gerekir.
- **Dev server (server.py) farklı DB** — SQLite kullanır; production PostgreSQL ile farklı sonuçlar verebilir.

## Cross-Reference

- **Agent System** → `v1/agents.py` → AgentPipelineOrchestrator çağrısı
- **Alternative Data** → `v1/alternative.py` → feature engine durumu ve feature listesi
- **VIOP** → `v1/viop.py` → opsiyon fiyatlaması, Greeks, strateji endpoint'leri
- **Scheduler** → `scheduler_api.py` → scheduler durumu ve manuel tetikleme endpoint'leri (ayrı servis)
- **Scanner** → `v1/scanner.py` → opportunity engine tarama sonuçları
- **Portfolio** → `v1/portfolio.py` → portföy yönetimi ve rebalance
- **Learning** → `v1/learning.py` → model drift ve öğrenme döngüsü durumu
