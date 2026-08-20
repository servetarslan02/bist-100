# 🔌 API BAĞLANTI RAPORU — BIST-100 Projesi

**Tarih:** 2026-08-21  
**Kapsam:** API katmanı ile servisler arasındaki bağlantıların durumu  
**Durum:** 3 Kritik, 5 Yüksek, 6 Orta, 4 Düşük seviye sorun tespit edildi

---

## ÖZET TABLO

| # | Önem | Konu | Durum |
|---|------|------|-------|
| 1 | 🔴 KRİTİK | 3 ayrı API entry point çakışması | Düzeltilmeli |
| 2 | 🔴 KRİTİK | JWT secret key hardcoded default | Düzeltilmeli |
| 3 | 🔴 KRİTİK | `/api/market` → gerçek veri yok (no_data_source) | Düzeltilmeli |
| 4 | 🟠 YÜKSEK | server.py → 20+ servis import'u (hepsi çalışmayabilir) | Kontrol edilmeli |
| 5 | 🟠 YÜKSEK | apps/api/main.py → lazy import'lar (501/404 riski) | Kontrol edilmeli |
| 6 | 🟠 YÜKSEK | Prometheus scrape → servisler /metrics sunmuyor | Düzeltilmeli |
| 7 | 🟠 YÜKSEK | Grafana dashboard sadece 1 datasource (market_state.json) | Düzeltilmeli |
| 8 | 🟠 YÜKSEK | Config hot-reload → runtime.json yok, singleton fallback | Kontrol edilmeli |
| 9 | 🟡 ORTA | WebSocket handler'lar farklı servislere bağlı (tutarsız) | İyileştirilmeli |
| 10 | 🟡 ORTA | DB connection pool → production'da yetersiz olabilir | İyileştirilmeli |
| 11 | 🟡 ORTA | Rate limiter in-memory (production'da Redis olmalı) | İyileştirilmeli |
| 12 | 🟡 ORTA | CORS → `allow_origins=["*"]` (production risk) | İyileştirilmeli |
| 13 | 🟡 ORTA | Migration runner sadece SQLite dev_db'de çalışıyor | Kontrol edilmeli |
| 14 | 🟡 ORTA | Backtest API → PostgreSQL gerektirir ama dev modda yok | Kontrol edilmeli |
| 15 | 🔵 DÜŞÜK | Health check → ClickHouse/Redis unavailable'da graceful | Tamam |
| 16 | 🔵 DÜŞÜK | Singleton pattern doğru uygulanmış (module-level) | Tamam |
| 17 | 🔵 DÜŞÜK | .env.example ile config.py uyumlu | Tamam |
| 18 | 🔵 DÜŞÜK | Servis başlatma sırası docker-compose'da doğru | Tamam |

---

## 1. API → SERVİS BAĞLANTILARI

### 1.1 Üç Ayrı Entry Point Çakışması

**[KRİTİK]** `services/api/app.py` (CANONICAL), `services/api/server.py` (DEV/LEGACY), `services/api/main.py` (DEPRECATED) ve `apps/api/main.py` (v3.0) olmak üzere **4 ayrı FastAPI uygulaması** var. Hepsi farklı servisleri import ediyor, farklı endpoint'ler sunuyor.

**Dosya:** `services/api/app.py` (satır 1-10, docstring)
```python
"""
NOT: Bu dosya CANONICAL production entry point'tir.
- server.py → DEV/legacy (SQLite)
- main.py → DEPRECATED (eski entry point)
"""
```

**Dosya:** `apps/api/main.py` (satır 1-10)
```python
"""
ALPHA BIST — FastAPI Backend v3.0
ROADMAP v3.0 FAZ 7:
- RESTful API endpoints
- WebSocket real-time updates
"""
```

**Sorun:**
- `app.py` → `services.core.database` (PostgreSQL/ClickHouse/Redis) kullanır
- `server.py` → `services.core.database_dev` (SQLite) kullanır, 20+ servis import eder
- `main.py` (services/api/) → `services.core.database` + `services.core.event_bus` kullanır
- `apps/api/main.py` → Lazy import'larla `services.core.orchestrator` kullanır

**Etki:** Hangi entry point'un çalıştırıldığına bağlı olarak tamamen farklı servis setleri aktif olur. Production'da `app.py` kullanılmalı ama `server.py` de çalışıyor olabilir.

**Önerilen Düzeltme:**
1. `server.py` ve `services/api/main.py` dosyalarına `DEPRECATED` uyarıları zaten var → `__main__` bloğunda `sys.exit(1)` zaten mevcut (main.py'de)
2. `apps/api/main.py` → ya kaldırılmalı ya da `app.py` ile birleştirilmeli
3. `docker-compose.yml`'de API servisi hangi entry point'u kullanıyor kontrol edilmeli

---

### 1.2 services/api/app.py Import Ağacı

**Dosya:** `services/api/app.py` (satır 20-27)
```python
from .v1 import v1_router
from .auth import jwt_handler, Role
from .rate_limiter import rate_limiter
from ..core.database import init_databases, close_databases, check_db_health
from ..core.otel import setup_telemetry, shutdown_telemetry
```

**Durum:** ✅ Tüm import edilen modüller mevcut. `services/core/otel.py` var.

**v1 Router Import'ları:** (`services/api/v1/__init__.py`)
```python
from .market import router as market_router
from .portfolio import router as portfolio_router
from .risk import router as risk_router
from .intelligence import router as intelligence_router
from .decisions import router as decisions_router
from .backtest import router as backtest_router
from .learning import router as learning_router
from .models import router as models_router
from .agents import router as agents_router
from .scanner import router as scanner_router
from .macro import router as macro_router
from .factors import router as factors_router
from .alternative import router as alternative_router
from .viop import router as viop_router
from .event_study import router as event_study_router
from .system import router as system_router
```

**Durum:** ✅ 16 router'ın tümü import ediliyor. Dosyalar mevcut.

---

### 1.3 services/api/server.py Import Ağarı (20+ Servis)

**Dosya:** `services/api/server.py` (satır 30-50)
```python
from services.core.database_dev import dev_db
from services.core.logging import logger
from services.core.audit_log import audit_log
from services.core.observability import (
    prometheus_metrics, distributed_tracing, performance_monitor,
    health_checker, config_manager
)
from services.core.infrastructure import (
    notification_system, snapshot_system, cache_system, job_queue
)
from services.ingestion.bist_universe import BISTUniverse
from services.features.store import feature_store
from services.intelligence.regime import regime_engine
from services.intelligence.signal_fusion import signal_fusion
from services.scanner.opportunity_engine import opportunity_engine
from services.ml.ranking_model import ranking_model
from services.core.decision_engine import decision_engine
from services.risk.position_sizing import position_sizer
from services.simulation.execution_simulator import execution_simulator
from services.portfolio.portfolio_manager import portfolio_manager
from services.core.monitoring import portfolio_monitor
from services.core.monitoring_security import monitoring_auth, extract_bearer_token, extract_api_key
from services.core.alerting import alerting
from services.learning.integrated_learning import learning_system
from services.learning.outcome_tracker import outcome_tracker
```

**[YÜKSEK]** Bu dosya **22 servis** import ediyor. Tümü module-level import (lazy değil), yani server.py import edildiğinde **hepsi** yüklenmeli. Eğer herhangi biri bağımlılık hatası verirse tüm server çöker.

**Önerilen Düzeltme:**
- Kritik olmayan import'lar lazy hale getirilmeli (fonksiyon içinde)
- Veya bu dosya zaten DEV/LEGACY olarak işaretli → production'da kullanılmamalı

---

### 1.4 apps/api/main.py Lazy Import'lar

**Dosya:** `apps/api/main.py` (çeşitli satırlar)
```python
# Health endpoint
from services.learning.super_intelligence import super_intelligence

# Regime endpoint
from services.core.regime_detector import regime_detector

# Opportunities endpoint
from services.ml.ranking_model import ranking_model
from services.core.orchestrator import orchestrator

# Portfolio endpoint
from services.core.orchestrator import orchestrator

# Backtest endpoint
from services.core.orchestrator import orchestrator

# Learning endpoint
from services.learning.continuous_learning import continuous_learning
```

**[YÜKSEK]** Lazy import'lar runtime'da hata fırlatabilir:
- `services.learning.super_intelligence` → `super_intelligence` singleton'ı var mı?
- `services.core.orchestrator` → `orchestrator` singleton'ı var mı?
- `services.learning.continuous_learning` → `continuous_learning` singleton'ı var mı?

**Dosya kontrolü:** ✅ Tüm dosyalar mevcut. Ama singleton'ların doğru oluşturulup oluşturulmadığı runtime'da test edilmeli.

---

## 2. DATA PIPELINE BAĞLANTILARI

### 2.1 /api/market → Gerçek Piyasa Verisi

**[KRİTİK]** `server.py` → `/api/market` endpoint'i:

**Dosya:** `services/api/server.py` (satır ~180)
```python
@app.get("/api/market")
async def get_market_data():
    result = {
        "bist_100": {"value": None, "change_pct": None, "change_points": None},
        "regime": {"current": regime.regime.value if regime else "UNKNOWN", ...},
        "breadth": {"advance_pct": None, "advancing": None, "declining": None},
        "volatility": {"vix_estimate": None, "status": None},
        "status": "no_data_source",
        "message": "Connect a real data source to populate this endpoint",
    }
```

**Sorun:** Tüm piyasa verisi alanları `None` ve `status: "no_data_source"`. Gerçek veri kaynağı bağlı değil.

**`app.py` → `/api/v1/market/state`:**
```python
@router.get("/state")
async def market_state(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    from ...intelligence.regime import regime_engine
    regime = regime_engine.get_current_regime() if hasattr(regime_engine, 'get_current_regime') else "UNKNOWN"
    return {"regime": regime, "status": "ok"}
```

**Sorun:** `regime_engine.get_current_regime()` → `RegimeEngine` sınıfında bu method var mı? `regime_engine` singleton'ı başlatıldığında veri yoksa "UNKNOWN" döner.

**`main.py` (services/api/) → `/api/market/state`:**
```python
@app.get("/api/market/state")
async def get_market_state():
    state = await redis_get("market_state")
    if state:
        return json.loads(state)
    return await _compute_live_market_state()
```

**Bu endpoint** Redis'ten okuyor, yoksa `yfinance` ile canlı hesaplama yapıyor. **En iyi implementasyon bu.**

**Önerilen Düzeltme:**
1. `app.py` canonical server'da da `_compute_live_market_state()` fallback'i eklenmeli
2. Veya Redis'te `market_state` key'inin scheduler tarafından yazıldığından emin olunmalı

---

### 2.2 /api/portfolio → Portföy Servisi

**Dosya:** `services/api/v1/portfolio.py`
```python
def _get_pm():
    from ...portfolio.portfolio_manager import portfolio_manager
    return portfolio_manager
```

**Durum:** ✅ `portfolio_manager` singleton'ı (`services/portfolio/portfolio_manager.py` satır 1180) doğru oluşturulmuş. Tüm endpoint'ler bu singleton'a bağlı.

**Endpoint'ler:** summary, positions, trades, pnl, equity-curve, risk-metrics, metrics, accounting, cash-ledger, position-history, equity-snapshots, drawdown, attribution, tax, tca, rebalance, status → **17 endpoint, tümü bağlı.**

---

### 2.3 /api/scanner → Scanner Servisi

**Dosya:** `services/api/v1/scanner.py`
```python
def _get_scan_api():
    from ...scanner.scan_api import scan_api
    return scan_api

def _get_engine():
    from ...scanner.alpha_engine import alpha_engine
    return alpha_engine
```

**Durum:** ✅ `scan_api` (satır 234) ve `alpha_engine` (satır 482) singleton'ları doğru oluşturulmuş.

**Endpoint'ler:** status, dashboard, results, opportunities, signals, tiers, history, performance, alerts, filters, dedup, scheduler, trigger, event → **14 endpoint, tümü bağlı.**

---

### 2.4 /api/learning → Learning Servisi

**Dosya:** `services/api/v1/learning.py`
```python
@router.get("/status")
async def learning_status(...):
    from ...risk.calibration import ScoreCalibrator
    return {"status": "active", "calibrator": "available"}
```

**[ORTA]** Learning endpoint'leri aslında `risk.calibration` servisine bağlı, `learning` servisine değil. `learning_system` ve `outcome_tracker` sadece `server.py`'de import ediliyor.

**Endpoint'ler:** status, calibration, drift, champion-challenger → **4 endpoint.** Drift ve champion-challenger henüz implemente edilmemiş (placeholder response).

---

### 2.5 /api/backtest → Backtest Servisi

**Dosya:** `services/api/v1/backtest.py`
```python
@router.post("/run")
async def run_backtest(...):
    from ...backtest.engine import BacktestEngine
    return {"status": "started", ...}

@router.get("/results/{backtest_id}")
async def get_result(backtest_id: str, ...):
    from ...core.database import pg_fetchrow
    row = await pg_fetchrow("SELECT * FROM backtests WHERE id = $1", backtest_id)
```

**[YÜKSEK]** Backtest endpoint'leri PostgreSQL gerektirir. `pg_fetchrow` asyncpg kullanır. Dev modda (SQLite) bu sorgular **çalışmaz** çünkü `$1` placeholder'ı SQLite'da `?` olmalı.

**Endpoint'ler:** run, results, list, walk-forward, deflated-sharpe, transaction-costs, trades, equity-curve → **8 endpoint.**

---

## 3. WEBSOCKET BAĞLANTILARI

### 3.1 WebSocket Handler'lar

**3 farklı WebSocket implementasyonu var:**

| Dosya | Endpoint | Bağlı Servis |
|-------|----------|---------------|
| `server.py` | `/ws` | feature_store, opportunity_engine (lazy) |
| `main.py` (services/api/) | `/ws/{channel}`, `/ws/live` | Redis pub/sub, yfinance |
| `apps/api/main.py` | `/ws` | orchestrator (lazy) |

**[ORTA]** Her entry point farklı WebSocket handler sunuyor. `server.py`'deki WebSocket:
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # subscribe, ping, get_ticker actions
    if action == "get_ticker":
        features = feature_store.get_all(ticker)
```

`main.py`'deki WebSocket:
```python
@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    # channel-based subscription

@app.websocket("/ws/live")
async def live_websocket(websocket: WebSocket):
    # live market data
```

**Sorun:** Real-time veri akışı için hangi WebSocket'in kullanılacağı belirsiz. `server.py`'deki heartbeat broadcast 5 saniyede bir çalışıyor ama sadece `server.py` çalıştırılırsa.

---

## 4. CONFIG BAĞLANTILARI

### 4.1 API Config (host, port, DB URL)

**Dosya:** `services/core/config.py`
```python
class Settings(BaseSettings):
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    # ...
    class Config:
        env_file = ".env"
```

**Durum:** ✅ `.env.example` ile `config.py` uyumlu. Tüm field'lar `.env.example`'deki değişkenlerle eşleşiyor.

### 4.2 .env.example Uyumluluğu

| .env.example | config.py field | Uyumlu |
|--------------|-----------------|--------|
| APP_HOST | app_host | ✅ |
| APP_PORT | app_port | ✅ |
| POSTGRES_HOST | postgres_host | ✅ |
| POSTGRES_PORT | postgres_port | ✅ |
| POSTGRES_DB | postgres_db | ✅ |
| POSTGRES_USER | postgres_user | ✅ |
| POSTGRES_PASSWORD | postgres_password | ✅ |
| REDIS_HOST | redis_host | ✅ |
| REDIS_PORT | redis_port | ✅ |
| SECRET_KEY | secret_key | ✅ |
| JWT_SECRET | jwt_secret | ✅ |

### 4.3 Config Hot-Reload

**Dosya:** `services/core/config_hot_reload.py`

**[YÜKSEK]** Singleton `_create_singleton()` fonksiyonu:
```python
def _create_singleton() -> "ConfigHotReload":
    candidates = ["config.json", "config/runtime.json", "config/hot_reload.json"]
    for path in candidates:
        if os.path.exists(path):
            return ConfigHotReload(path)
    return ConfigHotReload("config/runtime.json")  # fallback
```

**Sorun:** `config.json`, `config/runtime.json`, `config/hot_reload.json` dosyaları **hiçbiri yok**. Fallback olarak `config/runtime.json` kullanılıyor ama bu dosya da yok → `start()` çağrıldığında boş dosya yaratılacak.

**Önerilen Düzeltme:**
- `config/runtime.json` dosyası yaratılmalı (boş `{}` ile)
- Veya hot-reload devre dışı bırakılmalı (zaten `start()` çağrılmadığı sürece sorun yok)

---

## 5. DATABASE BAĞLANTILARI

### 5.1 DB Connection String

**Dosya:** `services/core/config.py`
```python
@property
def postgres_url(self) -> str:
    return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

@property
def redis_url(self) -> str:
    if self.redis_password:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
    return f"redis://{self.redis_host}:{self.redis_port}/0"
```

**Durum:** ✅ Connection string'ler doğru format'ta.

### 5.2 Connection Pool

**Dosya:** `services/core/database.py`
```python
_pg_pool = await asyncpg.create_pool(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    user=settings.postgres_user,
    password=settings.postgres_password,
    min_size=settings.db_pool_min,   # default: 2
    max_size=settings.db_pool_max,   # default: 10
    command_timeout=settings.db_command_timeout,  # default: 30
)
```

**[ORTA]** Pool ayarları:
- `DB_POOL_MIN=2`, `DB_POOL_MAX=10` → Production'da yetersiz olabilir (10 concurrent request limit)
- `DB_COMMAND_TIMEOUT=30` → Uzun sorgular için yeterli
- `.env.example`'da bu değerler mevcut ✅

### 5.3 Migration'lar

**Dosya:** `services/core/migrations/` → 7 migration dosyası (v001-v007)

**[ORTA]** Migration runner sadece `database_dev.py`'de çağrılıyor:
```python
async def _run_migrations(self):
    from .migrations.runner import MigrationRunner
    runner = MigrationRunner(self._db, dialect="sqlite")
    applied = await runner.run_pending()
```

**Sorun:** Production PostgreSQL için migration'lar `database.py`'de **çağrılmıyor**. Docker'da `database/init/001_schema.sql` kullanılıyor ama bu sadece ilk container creation'da çalışır.

**Önerilen Düzeltme:**
- Production'da migration runner `init_databases()` içinde de çağrılmalı
- Veya Alembic gibi bir migration tool kullanılmalı

### 5.4 Retry Mekanizması

**Dosya:** `services/core/database.py`
```python
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0

async def _retry_async(coro_factory, name: str, max_retries: int = _MAX_RETRIES):
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            await asyncio.sleep(delay)
```

**Durum:** ✅ Exponential backoff ile retry mekanizması doğru uygulanmış.

---

## 6. SERVİS BAŞLATMA SIRASI

### 6.1 Docker-Compose Bağımlılık Zinciri

**Dosya:** `docker-compose.yml`

```
postgres, clickhouse, redis, redpanda (data stores)
    ↓ (service_healthy)
api, ingestion, feature-engine, market-state, intelligence, simulation, risk, portfolio, learning
    ↓
dashboard (depends_on: api)
    ↓
prometheus, grafana, mlflow (monitoring)
```

**Durum:** ✅ Bağımlılık zinciri doğru. Data store'lar `service_healthy` condition ile bekleniyor.

### 6.2 Servis Başlatma Sırası (Docker-Compose)

1. **Katman 0:** postgres, clickhouse, redis, redpanda (paralel)
2. **Katman 1:** api, ingestion, feature-engine, market-state, intelligence, simulation, risk, portfolio, learning (paralel, Katman 0'a bağımlı)
3. **Katman 2:** dashboard (api'ye bağımlı)
4. **Katman 3:** prometheus, grafana, mlflow (bağımsız)

**[DÜŞÜK]** Katman 1'deki servisler kendi aralarında bağımlı olabilir (örn: `intelligence` → `feature-engine`'in önce veri üretmesi gerekebilir) ama docker-compose'da bu belirtilmemiş.

### 6.3 Singleton Pattern

Tüm kritik servisler module-level singleton kullanıyor:

| Servis | Dosya | Satır | Pattern |
|--------|-------|-------|---------|
| portfolio_manager | portfolio/portfolio_manager.py | 1180 | `portfolio_manager = PortfolioManager()` |
| scan_api | scanner/scan_api.py | 234 | `scan_api = ScanAPI()` |
| alpha_engine | scanner/alpha_engine.py | 482 | `alpha_engine = AlphaEngine()` |
| regime_engine | intelligence/regime.py | 407 | `regime_engine = RegimeEngine()` |
| rate_limiter | api/rate_limiter.py | ~100 | `rate_limiter = InMemoryRateLimiter()` |
| jwt_handler | api/auth.py | ~150 | `jwt_handler = JWTHandler()` |
| dev_db | core/database_dev.py | ~200 | `dev_db = DevDatabase()` |

**Durum:** ✅ Module-level singleton pattern doğru uygulanmış. Python module import garantisi sayesinde tek instance oluşur.

---

## 7. HEALTH CHECK

### 7.1 /health Endpoint

**`app.py` (CANONICAL):**
```python
@app.get("/health")
async def health():
    db_health = await check_db_health()
    all_healthy = all(v == "healthy" for v in db_health.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "version": "2.0.0",
        "server": "canonical (app.py)",
        "databases": db_health,
    }
```

**Durum:** ✅ PostgreSQL, ClickHouse ve Redis durumunu kontrol ediyor. Graceful degradation var.

**`server.py` (DEV):**
```python
@app.get("/health")
async def health_check():
    health = health_checker.check_all()
    return {**health, "latency_ms": ..., "version": "2.0.0"}
```

**Durum:** ✅ `HealthChecker` ile 6 servis kayıtlı (database, feature_store, opportunity_engine, decision_engine, portfolio_manager, learning_system).

**`main.py` (services/api/):**
```python
@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": ...}
```

**[DÜŞÜK]** Basit health check, servis durumunu kontrol etmiyor.

### 7.2 /health/detailed Endpoint

**`app.py`:**
```python
@app.get("/health/detailed")
async def health_detailed():
    db_health = await check_db_health()
    return {
        "status": ...,
        "databases": db_health,
        "endpoints": {"v1_router": "/api/v1", "docs": "/docs", "openapi": "/openapi.json"},
    }
```

**`server.py`:**
```python
@app.get("/health/detailed")
async def health_detailed():
    result = await portfolio_monitor.get_health_detailed()
    return result
```

**Durum:** ✅ Her iki entry point da detailed health sunuyor.

---

## 8. MONITORING

### 8.1 Prometheus Metrics

**`app.py` (CANONICAL):** ❌ `/metrics` endpoint'i **yok**.

**`server.py` (DEV):** ✅ `/metrics` endpoint'i var (Bearer token gerekli):
```python
@app.get("/metrics")
async def prometheus_metrics_endpoint(request: Request):
    text = await portfolio_monitor.get_prometheus_text()
    return JSONResponse(content=text, media_type="text/plain; version=0.0.4; charset=utf-8")
```

**`main.py` (services/api/):** ✅ `/metrics` endpoint'i var (Circuit breaker, DLQ, transaction, system governor metrikleri):
```python
@app.get("/metrics")
async def prometheus_metrics():
    # Circuit breaker, DLQ, transaction, system governor metrikleri
    return PlainTextResponse("\n".join(lines) + "\n", ...)
```

**[YÜKSEK]** `app.py` (CANONICAL production server) `/metrics` endpoint'i **sunmuyor**. Prometheus scrape `api:8000/metrics`'e bağlanamaz.

### 8.2 Prometheus Scrape Config

**Dosya:** `infrastructure/prometheus.yml`
```yaml
scrape_configs:
  - job_name: 'alpha-api'
    static_configs:
      - targets: ['api:8000']
    metrics_path: '/metrics'

  - job_name: 'alpha-services'
    static_configs:
      - targets:
          - 'ingestion:8000'
          - 'feature-engine:8000'
          - 'market-state:8000'
          - 'intelligence:8000'
          - 'simulation:8000'
          - 'risk:8000'
          - 'portfolio:8000'
          - 'learning:8000'
    metrics_path: '/metrics'
```

**[YÜKSEK]** `alpha-services` job'u 8 servisi scrape etmeye çalışıyor ama bu servislerin hiçbiri `/metrics` endpoint'i sunmuyor (sadece `server.py` ve `main.py`'de var, onlar da bu servisler değil).

**Önerilen Düzeltme:**
1. `app.py`'ye `/metrics` endpoint'i eklenmeli
2. Veya her servis kendi `/metrics` endpoint'ini sunmalı
3. Veya Prometheus config'i sadece API'yi scrape etmeli

### 8.3 Grafana Dashboard

**Dosya:** `monitoring/grafana_dashboard.json` → Portfolio & Lock Monitoring dashboard'u  
**Dosya:** `infrastructure/grafana/dashboards/market_state.json` → Market State dashboard'u

**[YÜKSEK]** Grafana provisioning sadece `infrastructure/grafana/dashboards/` dizinindeki dosyaları yükler. `monitoring/grafana_dashboard.json` bu dizinde değil → **yüklenmez**.

**Önerilen Düzeltme:**
- `monitoring/grafana_dashboard.json` → `infrastructure/grafana/dashboards/` dizinine kopyalanmalı
- Veya Grafana provisioning config'i `monitoring/` dizinini de kapsamalı

---

## 9. EK SORUNLAR

### 9.1 JWT Secret Key Hardcoded Default

**[KRİTİK]** `services/api/auth.py` (satır ~75):
```python
class JWTHandler:
    def __init__(self, secret_key: str = "alpha-bist-secret-key-change-in-production"):
        self.secret_key = secret_key
```

**Sorun:** JWT secret key hardcoded. `config.py`'deki `jwt_secret` field'ı kullanılmıyor. `auth.py`'deki `JWTHandler` bağımsız olarak bu default'u kullanıyor.

**Önerilen Düzeltme:**
```python
from ..core.config import settings

class JWTHandler:
    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or settings.jwt_secret
```

### 9.2 CORS → allow_origins=["*"]

**[ORTA]** Tüm API entry point'lerinde:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Sorun:** Production'da tüm origin'lere izin vermek güvenlik riski. `allow_credentials=True` ile `allow_origins=["*"]` birlikte kullanılamaz (browser reddeder).

**Önerilen Düzeltme:**
- Production'da `allow_origins` spesifik domain'lerle değiştirilmeli
- Veya `.env`'den okunmalı: `CORS_ORIGINS=http://localhost:3000,https://dashboard.example.com`

### 9.3 Rate Limiter In-Memory

**[ORTA]** `services/api/rate_limiter.py`:
```python
class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: Dict[str, Dict[str, any]] = defaultdict(lambda: {...})
```

**Sorun:** In-memory rate limiter. Multiple API instance (load balancer arkasında) çalıştırılırsa her instance kendi bucket'ını tutar → rate limit bypass.

**Önerilen Düzeltme:**
- Production'da Redis tabanlı rate limiter kullanılmalı
- Kodda zaten `"Production'da Redis tabanlı olmalı"` notu var

### 9.4 Backtest API → PostgreSQL Bağımlılığı

**[ORTA]** `services/api/v1/backtest.py`:
```python
@router.get("/results/{backtest_id}")
async def get_result(backtest_id: str, ...):
    from ...core.database import pg_fetchrow
    row = await pg_fetchrow("SELECT * FROM backtests WHERE id = $1", backtest_id)
```

**Sorun:** `$1` placeholder'ı PostgreSQL syntax'ı. SQLite dev modda bu çalışmaz (SQLite `?` kullanır). `database_dev.py`'deki `_translate_query` bunu çeviriyor ama `pg_fetchrow` doğrudan `database.py`'den import ediliyor, `database_dev.py`'den değil.

---

## 10. ÖNERİLEN DÜZELTMELER (Öncelik Sırasıyla)

### 🔴 KRİTİK (Hemen düzeltilmeli)

1. **`app.py`'ye `/metrics` endpoint'i ekleyin** — Prometheus scrape çalışması için şart
2. **JWT secret key'i config'den okuyun** — Hardcoded default güvenlik açığı
3. **`/api/market` endpoint'ine gerçek veri bağlayın** — Redis fallback veya yfinance

### 🟠 YÜKSEK (1 hafta içinde)

4. **Entry point çakışmasını çözün** — Tek canonical entry point, diğerleri kaldırılmalı veya netleştirilmeli
5. **Prometheus config'i düzeltin** — Servisler `/metrics` sunmuyor, scrape config'i güncellenmeli
6. **Grafana dashboard provisioning** — `monitoring/` dizinindeki dashboard'u da yükleyin
7. **Config hot-reload** — `config/runtime.json` dosyasını yaratın veya hot-reload'u devre dışı bırakın

### 🟡 ORTA (Sprint içinde)

8. **CORS origins** — Production'da spesifik domain'ler
9. **Rate limiter** — Redis tabanlıya geçin
10. **DB pool** — Production'da `DB_POOL_MAX=20-50` yapın
11. **Migration runner** — Production PostgreSQL için de çalıştırın
12. **WebSocket** — Tek canonical WebSocket endpoint'i belirleyin

### 🔵 DÜŞÜK (Backlog)

13. **Health check** — Basit endpoint'lerde de servis durumu kontrolü ekleyin
14. **Servis bağımlılıkları** — Docker-compose'da Katman 1 içi bağımlılıkları belirtin

---

## 11. BAĞLANTI DİYAGRAMI

```
┌─────────────────────────────────────────────────────────────┐
│                    ENTRY POINT'LER                          │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  app.py      │  server.py   │  main.py     │ apps/api/      │
│  (CANONICAL) │  (DEV)       │  (DEPRECATED)│  main.py (v3)  │
│  port:8000   │  port:8000   │  port:8000   │  port:8000     │
├──────────────┼──────────────┼──────────────┼────────────────┤
│  v1_router   │  20+ servis  │  DB+EventBus │  Orchestrator  │
│  (16 router) │  import      │  import      │  lazy import   │
│  /api/v1/*   │  /api/*      │  /api/*      │  /regime etc   │
│  /health     │  /health     │  /api/health │  /health       │
│  ❌ /metrics │  ✅ /metrics │  ✅ /metrics │  ❌ /metrics   │
│  ❌ /ws      │  ✅ /ws      │  ✅ /ws/*    │  ✅ /ws        │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬───────┘
       │              │              │                │
       ▼              ▼              ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                    SERVİS KATMANI                           │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  Portfolio   │  Scanner     │  Intelligence│  Learning      │
│  Manager     │  ScanAPI     │  RegimeEngine│  Calibrator    │
│  (singleton) │  (singleton) │  (singleton) │  (singleton)   │
├──────────────┼──────────────┼──────────────┼────────────────┤
│  Backtest    │  Risk        │  ML          │  Agents        │
│  Engine      │  PositionSizer│ RankingModel│  AgentSystem   │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬───────┘
       │              │              │                │
       ▼              ▼              ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATABASE KATMANI                         │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  PostgreSQL  │  ClickHouse  │  Redis       │  Redpanda      │
│  (asyncpg)   │  (sync)      │  (aioredis)  │  (Kafka)       │
│  port:5432   │  port:8123   │  port:6379   │  port:9092     │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

---

**Rapor Sonu**  
*Taranan dosya sayısı: 50+ Python dosyası*  
*Tespit edilen sorun: 18 (3 Kritik, 5 Yüksek, 6 Orta, 4 Düşük)*
