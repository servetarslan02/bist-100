# 🔒 ALPHA BIST API — Güvenlik ve Kalite Denetim Raporu

**Tarih:** 2026-08-21  
**Kapsam:** `services/api/` + `apps/api/` dizinlerindeki tüm API endpoint'leri  
**Toplam Endpoint:** ~92 REST + 10 WebSocket kanalı  
**Dosya Sayısı:** 22 Python dosyası tarandı

---

## ÖZET

| Önem Seviyesi | Sorun Sayısı |
|---|---|
| 🔴 KRİTİK | 5 |
| 🟠 YÜKSEK | 7 |
| 🟡 ORTA | 6 |
| 🟢 DÜŞÜK | 4 |
| **TOPLAM** | **22** |

---

## 1. AUTHENTICATION EKSİK

### 1.1 🔴 KRİTİK — Hardcoded JWT Secret Key

**Dosya:** `services/api/auth.py`, satır 71  
**Sorun:** JWT secret key varsayılan olarak hardcoded.

```python
def __init__(self, secret_key: str = "alpha-bist-secret-key-change-in-production"):
    self.secret_key = secret_key
```

**Risk:** Eğer `JWT_SECRET` environment variable set edilmezse, tüm token'lar bilinen bir key ile imzalanır. Saldırgan herhangi bir kullanıcı için token üretebilir.

**Önerilen Düzeltme:**
```python
import os

def __init__(self, secret_key: str = None):
    self.secret_key = secret_key or os.environ.get("JWT_SECRET")
    if not self.secret_key:
        raise RuntimeError("JWT_SECRET environment variable is required")
    self.algorithm = "HS256"
```

---

### 1.2 🔴 KRİTİK — Hardcoded API Key

**Dosya:** `services/api/auth.py`, satır 163-167  
**Sorun:** Varsayılan API key hardcoded.

```python
api_key_manager.register_key(
    "alpha-system-key-change-me",
    "system",
    ["GET", "POST", "PUT", "DELETE"],
)
```

**Risk:** Bu key bilinen bir string. Üretimde kullanılırsa herhangi birisi SYSTEM rolüyle tüm endpoint'lere erişebilir.

**Önerilen Düzeltme:**
```python
import os

_default_key = os.environ.get("SYSTEM_API_KEY")
if _default_key:
    api_key_manager.register_key(_default_key, "system", ["GET", "POST", "PUT", "DELETE"])
else:
    logger.warning("SYSTEM_API_KEY not set — inter-service auth disabled")
```

---

### 1.3 🟠 YÜKSEK — Deprecated main.py'de Auth Yok

**Dosya:** `services/api/main.py`, satır 1-790 (tüm dosya)  
**Sorun:** Bu dosyadaki **hiçbir endpoint** auth gerektirmiyor. `get_current_user` dependency hiç kullanılmamış.

**Etkilenen Endpoint'ler (13 adet):**
- `GET /api/health`
- `GET /metrics`
- `GET /api/status`
- `GET /api/market/state`
- `GET /api/market/instruments`
- `GET /api/market/instrument/{ticker}/ohlcv`
- `GET /api/market/instrument/{ticker}/full`
- `GET /api/market/instrument/{ticker}`
- `GET /api/signals`
- `GET /api/portfolio`
- `GET /api/world/state`
- `GET /api/features/{ticker}`
- `GET /api/events`
- `GET /api/models`
- `GET /api/alerts`
- `GET /api/stream/events`
- `WS /ws/{channel}`
- `WS /ws/live`

**Risk:** Bu dosya "deprecated" olarak işaretli ama çalışıyor olabilir. Eğer production'da kullanılıyorsa tüm veri katmanı açık.

**Önerilen Düzeltme:** Bu dosyayı tamamen kaldırın veya `app.py`'ye yönlendirin. Kullanılmayan kod = güvenlik riski.

---

### 1.4 🟠 YÜKSEK — apps/api/main.py'de Auth Yok

**Dosya:** `apps/api/main.py`, satır 1-250  
**Sorun:** Bu dosyadaki hiçbir endpoint auth gerektirmiyor. Pydantic modeller var ama auth dependency yok.

**Etkilenen Endpoint'ler (10 adet):**
- `GET /health`
- `GET /regime`
- `GET /opportunities`
- `GET /opportunities/{ticker}`
- `GET /portfolio`
- `GET /backtest`
- `GET /learning`
- `GET /features/{ticker}`
- `POST /predict`
- `GET /pipeline/stats`
- `GET /reports/latest`
- `WS /ws`

**Önerilen Düzeltme:** Bu dosyayı kaldırın veya auth middleware ekleyin.

---

### 1.5 🟡 ORTA — server.py'de API Key Middleware Yetersiz

**Dosya:** `services/api/server.py`, satır 113-127  
**Sorun:** API key middleware sadece production modunda çalışıyor ve key doğrulaması yapmıyor (sadece varlığını kontrol ediyor).

```python
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/ws"):
        return await call_next(request)

    from services.core.config import settings
    if settings.is_production:
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "API key required", "header": "X-API-Key"}
            )
    return await call_next(request)
```

**Risk:** 
1. Development modunda auth tamamen devre dışı
2. Production'da sadece key'in varlığını kontrol ediyor, geçerliliğini değil
3. WebSocket endpoint'leri auth bypass ediyor

**Önerilen Düzeltme:**
```python
if settings.is_production:
    api_key = request.headers.get("X-API-Key", "")
    key_info = api_key_manager.verify_key(api_key)
    if not key_info:
        return JSONResponse(status_code=401, content={"error": "Invalid API key"})
```

---

### 1.6 🟡 ORTA — System Health Endpoint Auth Bypass

**Dosya:** `services/api/v1/system.py`, satır 9-10  
**Sorun:** `/api/v1/system/health` endpoint'i auth gerektirmiyor.

```python
@router.get("/health")
async def health():
    return {"status": "healthy"}
```

**Risk:** Düşük — sadece "healthy" döndürüyor ama bilgi sızıntısı olarak kullanılabilir.

**Önerilen Düzeltme:** Auth dependency ekleyin veya public endpoint olarak kasıtlı bırakın (karar verin).

---

## 2. RATE LIMITING

### 2.1 🟠 YÜKSEK — In-Memory Rate Limiter (Production Uygun Değil)

**Dosya:** `services/api/rate_limiter.py`, satır 44-85  
**Sorun:** Rate limiter in-memory çalışıyor. Multi-instance deployment'da her instance kendi limit'ini tutar.

```python
class InMemoryRateLimiter:
    """In-memory token bucket rate limiter.
    Production'da Redis tabanlı olmalı.
    """
    def __init__(self):
        self._buckets: Dict[str, Dict[str, any]] = defaultdict(lambda: {
            "tokens": 100,
            "last_refill": time.monotonic(),
        })
```

**Risk:** 
1. Multi-instance'da rate limiting bypass edilebilir
2. Server restart'ta tüm limit sıfırlanır
3. Memory leak (bucket'lar asla temizlenmiyor)

**Önerilen Düzeltme:** Redis tabanlı rate limiter implementasyonu:
```python
class RedisRateLimiter:
    async def check(self, client_id: str, group: str) -> tuple[bool, dict]:
        key = f"ratelimit:{client_id}:{group}"
        config = RATE_LIMITS[group]
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, config.window_seconds)
        if current > config.max_requests:
            return False, {"retry_after": await self.redis.ttl(key)}
        return True, {"remaining": config.max_requests - current}
```

---

### 2.2 🟡 ORTA — Rate Limit Bucket Temizliği Yok

**Dosya:** `services/api/rate_limiter.py`, satır 44-85  
**Sorun:** `_buckets` dictionary'si büyümeye devam eder, TTL veya cleanup mekanizması yok.

**Risk:** Uzun süre çalışan sunucularda bellek tüketimi artar.

**Önerilen Düzeltme:** Periyodik cleanup task'ı ekleyin:
```python
async def _cleanup_stale_buckets(self, max_age_seconds: int = 3600):
    now = time.monotonic()
    stale_keys = [k for k, v in self._buckets.items() 
                  if now - v["last_refill"] > max_age_seconds]
    for k in stale_keys:
        del self._buckets[k]
```

---

### 2.3 🟢 DÜŞÜK — Rate Limit Header'ları Eksik

**Dosya:** `services/api/app.py`, satır 97-115  
**Sorun:** Rate limit middleware'i `X-RateLimit-Remaining` header'ını ekliyor ama `X-RateLimit-Reset` eklemiyor.

**Önerilen Düzeltme:**
```python
response.headers["X-RateLimit-Reset"] = str(int(time.time()) + info.get("reset_seconds", 60))
```

---

## 3. INPUT VALIDATION

### 3.1 🟠 YÜKSEK — Path Parameter Validation Eksik (SQL Injection Riski)

**Dosya:** `services/api/main.py`, satır 330-345  
**Sorun:** `ticker` parametresi doğrudan SQL sorgusuna giriyor (parametrize edilmiş ama validation yok).

```python
@app.get("/api/market/instrument/{ticker}/ohlcv")
async def get_instrument_ohlcv(ticker: str, period: str = "60d", interval: str = "1d"):
    # ...
    result = ch_execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv
        WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = %(ticker)s)
    """, parameters={"ticker": ticker})
```

**Risk:** Parametrize edilmiş sorgu kullanıldığı için SQL injection riski düşük, ama `ticker` değeri hiçbir validation'dan geçmiyor. Çok uzun string'ler veya special karakterler sorun yaratabilir.

**Önerilen Düzeltme:**
```python
import re

def validate_ticker(ticker: str) -> str:
    if not re.match(r'^[A-Z]{2,6}$', ticker):
        raise HTTPException(400, "Invalid ticker format")
    return ticker
```

---

### 3.2 🟡 ORTA — Query Parameter Validation Eksik

**Dosya:** `services/api/main.py`, satır 230-235  
**Sorun:** `limit` parametresi için üst sınır yok.

```python
@app.get("/api/market/instruments")
async def get_instruments(sector: Optional[str] = None, limit: int = 50, offset: int = 0):
```

**Risk:** `limit=999999` ile tüm veritabanı tablosunu çekmek mümkün.

**Önerilen Düzeltme:**
```python
limit: int = Query(default=50, ge=1, le=500)
```

---

### 3.3 🟡 ORTA — Request Body Validation Eksik (POST Endpoint'leri)

**Dosya:** `services/api/v1/decisions.py`, satır 28-30  
**Sorun:** POST endpoint'leri Pydantic model kullanmıyor.

```python
@router.post("/create")
async def create_decision(ticker: str = Query(...), action: str = Query(...), ...):
    return {"status": "created", "ticker": ticker, "action": action}
```

**Risk:** `action` parametresi için validasyon yok. Herhangi bir string kabul edilir.

**Önerilen Düzeltme:**
```python
from pydantic import BaseModel, Field
from enum import Enum

class ActionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class CreateDecisionRequest(BaseModel):
    ticker: str = Field(..., pattern=r'^[A-Z]{2,6}$')
    action: ActionType
    amount: float = Field(..., gt=0)

@router.post("/create")
async def create_decision(request: CreateDecisionRequest, ...):
```

---

### 3.4 🟢 DÜŞÜK — Pydantic Model Kullanımı İyi (apps/api/main.py)

**Dosya:** `apps/api/main.py`, satır 38-55  
**Durum:** ✅ Bu dosyada Pydantic modelleri doğru kullanılmış (`OpportunityResponse`, `PredictRequest` vb.)

---

## 4. ERROR HANDLING

### 4.1 🔴 KRİTİK — Stack Trace Dışarı Sızıyor (15+ endpoint)

**Dosya:** `services/api/main.py`, satır 345, 399, 482, 512, 590, 624, 655, 668, 689, 712, 745  
**Dosya:** `services/api/server.py`, satır 264, 297, 320, 353  
**Sorun:** Exception mesajları doğrudan response'a gönderiliyor.

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

**Risk:** 
1. Veritabanı hata mesajları (tablo adları, sütun adları) dışarı sızar
2. Dosya yolları ve sistem bilgisi açığa çıkar
3. Saldırgan için sistem mimarisi hakkında bilgi sağlar

**Etkilenen Endpoint'ler:**
- `GET /api/market/instruments` → `detail=str(e)`
- `GET /api/market/instrument/{ticker}/ohlcv` → `detail=str(e)`
- `GET /api/market/instrument/{ticker}/full` → `detail=str(e)`
- `GET /api/market/instrument/{ticker}` → `detail=str(e)`
- `GET /api/signals` → `detail=str(e)`
- `GET /api/portfolio` → `detail=str(e)`
- `GET /api/world/state` → `detail=str(e)`
- `GET /api/features/{ticker}` → `detail=str(e)`
- `GET /api/events` → `detail=str(e)`
- `GET /api/models` → `detail=str(e)`
- `GET /api/alerts` → `detail=str(e)`
- `GET /api/market` → `detail=str(e)`
- `GET /api/opportunities` → `detail=str(e)`
- `GET /api/portfolio` → `detail=str(e)`
- `GET /api/learning` → `detail=str(e)`

**Önerilen Düzeltme:**
```python
import uuid

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    error_id = str(uuid.uuid4())[:8]
    logger.error("Unhandled exception", error_id=error_id, error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal server error",
            "error_id": error_id,  # Support için referans
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
```

---

### 4.2 🟠 YÜKSEK — Global Exception Handler Eksik (app.py)

**Dosya:** `services/api/app.py`  
**Sorun:** Canonical production server'da global exception handler tanımlanmamış. `server.py`'de var ama `app.py`'de yok.

**Önerilen Düzeltme:**
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = str(uuid.uuid4())[:8]
    logger.error("Unhandled exception", error_id=error_id, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": True, "detail": "Internal server error", "error_id": error_id},
    )
```

---

### 4.3 🟡 ORTA — Silent Exception Swallowing

**Dosya:** `services/api/main.py`, satır 758  
**Dosya:** `services/api/server.py`, satır 665  
**Sorun:** Bazı exception'lar tamamen yutuluyor (log bile yok).

```python
# main.py:758
except Exception as e:
    pass  # Intentional: silent error handling

# server.py:665 (WebSocket broadcast)
except Exception as e:
    pass  # Intentional: silent error handling
```

**Risk:** Hatalar gizlenir, debug imkansızlaşır.

**Önerilen Düzeltme:** En azından debug log ekleyin:
```python
except Exception as e:
    logger.debug("Handled exception", error=str(e), context="websocket_broadcast")
```

---

## 5. CORS

### 5.1 🔴 KRİTİK — Wildcard CORS (4 dosya)

**Dosya:** `services/api/app.py`, satır 86  
**Dosya:** `services/api/main.py`, satır 66  
**Dosya:** `services/api/server.py`, satır 108  
**Dosya:** `apps/api/main.py`, satır 98  

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Risk:**
1. `allow_origins=["*"]` + `allow_credentials=True` = **Güvenlik açığı**. Herhangi bir web sitesi authenticated istek gönderebilir.
2. CSRF saldırılarına açık
3. `allow_methods=["*"]` = DELETE ve PUT da serbest

**Önerilen Düzeltme:**
```python
import os

ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
```

---

## 6. WEBSOCKET GÜVENLİK

### 6.1 🔴 KRİTİK — WebSocket Auth Yok

**Dosya:** `services/api/main.py`, satır 752-780  
**Dosya:** `services/api/server.py`, satır 640-670  
**Dosya:** `services/api/websocket.py`, satır 70-95  
**Dosya:** `apps/api/main.py`, satır 218-250  

**Sorun:** Hiçbir WebSocket endpoint'i authentication gerektirmiyor.

```python
@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    await manager.connect(websocket, channel)  # Auth yok!
    try:
        while True:
            data = await websocket.receive_text()
```

**Risk:**
1. Herkes WebSocket'e bağlanabilir
2. Real-time piyasa verilerine ücretsiz erişim
3. DoS saldırısı (çok fazla bağlantı)
4. `channel` parametresi validate edilmiyor

**Önerilen Düzeltme:**
```python
@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    # Token query param'dan al
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return
    
    user = jwt_handler.verify_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    if channel not in ALLOWED_CHANNELS:
        await websocket.close(code=4004, reason="Invalid channel")
        return
    
    await manager.connect(websocket, channel)
```

---

### 6.2 🟠 YÜKSEK — WebSocket Message Validation Yok

**Dosya:** `services/api/main.py`, satır 752-780  
**Sorun:** Client'tan gelen mesajlar sadece JSON parse ediliyor, içerik validation yok.

```python
data = await websocket.receive_text()
try:
    msg = json.loads(data)
    if msg.get("action") == "subscribe":
        await websocket.send_json({"type": "subscribed", "channel": msg.get("channel", channel)})
```

**Risk:** 
1. Büyük mesajlar ile bellek tüketimi
2. Enjekte edilmiş `channel` değerleri
3. Rate limiting yok (mesaj bazında)

**Önerilen Düzeltme:**
```python
MAX_MESSAGE_SIZE = 4096  # bytes
MAX_MESSAGES_PER_SECOND = 10

data = await websocket.receive_text()
if len(data) > MAX_MESSAGE_SIZE:
    await websocket.send_json({"type": "error", "message": "Message too large"})
    continue

msg = json.loads(data)
action = msg.get("action")
if action not in ALLOWED_ACTIONS:
    await websocket.send_json({"type": "error", "message": "Invalid action"})
    continue
```

---

## 7. SENSITIVE DATA

### 7.1 🟠 YÜKSEK — Database Hata Mesajları Dışarı Sızıyor

**Dosya:** `services/api/main.py`, satır 345, 399, 482  
**Sorun:** PostgreSQL ve ClickHouse hata mesajları doğrudan response'a gidiyor.

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

**Risk:** Hata mesajlarında şunlar görülebilir:
- Tablo ve sütun isimleri
- Veritabanı bağlantı string'leri
- Dosya yolları
- Internal IP adresleri

**Önerilen Düzeltme:** Production'da generic hata mesajı, development'da detaylı:
```python
import os

if os.environ.get("APP_ENV") == "production":
    raise HTTPException(500, detail="Internal server error")
else:
    raise HTTPException(500, detail=str(e))
```

---

### 7.2 🟡 ORTA — Health Endpoint Bilgi Sızıntısı

**Dosya:** `services/api/app.py`, satır 120-135  
**Sorun:** `/health/detailed` endpoint'i veritabanı bağlantı durumlarını gösteriyor.

```python
@app.get("/health/detailed")
async def health_detailed():
    db_health = await check_db_health()
    return {
        "status": "healthy" if all_healthy else "degraded",
        "databases": db_health,  # DB bağlantı bilgileri
        "endpoints": {"v1_router": "/api/v1", "docs": "/docs"},
    }
```

**Risk:** Veritabanı türleri ve bağlantı durumları hakkında bilgi sızıntısı.

**Önerilen Düzeltme:** Bu endpoint'i auth gerektirin veya sadece internal network'e açın.

---

### 7.3 🟢 DÜŞÜK — Metrics Endpoint Auth Eksik (main.py)

**Dosya:** `services/api/main.py`, satır 140-210  
**Sorun:** `/metrics` endpoint'i auth gerektirmiyor. Prometheus metrikleri sistem hakkında bilgi içerir.

**Not:** `server.py`'deki `/metrics` endpoint'i auth gerektiriyor (iyi), ama `main.py`'deki gerektirmiyor.

---

## 8. API VERSIONING

### 8.1 🟡 ORTA — Version Prefix Tutarlılığı

**Dosya:** `services/api/v1/__init__.py`  
**Durum:** ✅ v1 router doğru şekilde `/api/v1` prefix'i kullanıyor.

**Sorun:** Ama `main.py` ve `server.py`'deki endpoint'ler version prefix'i kullanmıyor:
- `/api/market/state` (v1 prefix yok)
- `/api/portfolio` (v1 prefix yok)
- `/api/signals` (v1 prefix yok)

**Risk:** API versioning stratejisi tutarsız. Client'lar hangi version'ı kullanacağını bilemez.

**Önerilen Düzeltme:** Tüm endpoint'leri `/api/v1/` altına taşıyın veya legacy endpoint'leri kaldırın.

---

### 8.2 🟢 DÜŞÜK — Backward Compatibility Planı Yok

**Sorun:** v2 endpoint'leri eklenirse v1 nasıl deprecated edilecek? Bir plan yok.

**Önerilen Düzeltme:** API versioning politikası oluşturun:
```python
# Deprecation header
@app.get("/api/v1/market/state", deprecated=True)
async def market_state_v1():
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-01"
    response.headers["Link"] = '</api/v2/market/state>; rel="successor-version"'
```

---

## 9. OPENAPI/SWAGGER

### 9.1 🟢 DÜŞÜK — OpenAPI Dokümantasyonu Production'da Açık

**Dosya:** `services/api/app.py`, satır 78-80  
**Sorun:** Swagger ve ReDoc production'da açık.

```python
app = FastAPI(
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
```

**Risk:** API yapısı ve endpoint'ler herkes tarafından görülebilir.

**Önerilen Düzeltme:**
```python
import os

docs_url = "/docs" if os.environ.get("APP_ENV") != "production" else None
redoc_url = "/redoc" if os.environ.get("APP_ENV") != "production" else None
openapi_url = "/openapi.json" if os.environ.get("APP_ENV") != "production" else None

app = FastAPI(docs_url=docs_url, redoc_url=redoc_url, openapi_url=openapi_url)
```

---

### 9.2 🟢 DÜŞÜK — Response Model Tanımları Eksik

**Dosya:** `services/api/v1/` dizinindeki tüm endpoint'ler  
**Sorun:** v1 endpoint'lerinin çoğu `response_model` kullanmıyor. Bu, OpenAPI schema'larında response yapısının belirsiz olmasına neden oluyor.

**Önerilen Düzeltme:** Kritik endpoint'ler için response model ekleyin:
```python
class MarketStateResponse(BaseModel):
    regime: str
    status: str
    timestamp: str

@router.get("/state", response_model=MarketStateResponse)
async def market_state(...):
```

---

## 10. EK GÜVENLİK SORUNLARI

### 10.1 🟠 YÜKSEK — SQL Injection Riski (Düşük Seviye)

**Dosya:** `services/api/main.py`, satır 695-710  
**Sorun:** `event_type` parametresi SQL sorgusuna giriyor.

```python
@app.get("/api/events")
async def get_events(event_type: Optional[str] = None, limit: int = 50):
    query = "SELECT * FROM system_events"
    params = []
    if event_type:
        query += " WHERE event_type = $1"
        params.append(event_type)
    query += " ORDER BY created_at DESC"
    params.append(limit)
    query += f" LIMIT ${len(params)}"
```

**Risk:** Parametrize edilmiş sorgu kullanıldığı için SQL injection riski düşük, ama `f" LIMIT ${len(params)}"` pattern'i tehlikeli. `len(params)` integer olduğu için güvenli, ama bu pattern alışkanlık yaratır.

**Önerilen Düzeltme:** String formatlama yerine parametre kullanın:
```python
query += " LIMIT $2"
params.append(limit)
```

---

### 10.2 🟡 ORTA — CORS + Credentials Kombinasyonu

**Dosya:** 4 dosya (yukarıda belirtildi)  
**Sorun:** `allow_origins=["*"]` + `allow_credentials=True` birlikte kullanıldığında, tarayıcılar bu kombinasyonu reddeder (CORS spec gereği). Ama bazı eski tarayıcılar kabul edebilir.

**Risk:** Cookie-based auth kullanılıyorsa, herhangi bir site authenticated istek gönderebilir.

---

### 10.3 🟡 ORTA — Admin Endpoint'lerde Rate Limiting Eksik

**Dosya:** `services/api/server.py`, satır 570-700  
**Sorun:** Admin endpoint'leri (`/admin/*`) için özel rate limiting yok. Brute-force saldırılarına açık.

**Önerilen Düzeltme:** Admin endpoint'leri için daha sıkı rate limiting:
```python
ADMIN_RATE_LIMIT = RateLimitConfig(max_requests=10, window_seconds=60)
```

---

### 10.4 🟢 DÜŞÜK — WebSocket Connection Limit Yok

**Dosya:** `services/api/main.py`, satır 720-740  
**Sorun:** `ConnectionManager` maksimum bağlantı sayısı kontrol etmiyor.

```python
async def connect(self, websocket: WebSocket, channel: str):
    await websocket.accept()
    self.active_connections[channel].append(websocket)  # Limit yok!
```

**Risk:** DoS saldırısı ile tüm bellek tüketilebilir.

**Önerilen Düzeltme:**
```python
MAX_CONNECTIONS = 1000

async def connect(self, websocket: WebSocket, channel: str):
    total = sum(len(conns) for conns in self.active_connections.values())
    if total >= MAX_CONNECTIONS:
        await websocket.close(code=4008, reason="Connection limit reached")
        return
    await websocket.accept()
```

---

## ÖNCELİKLİ DÜZELTME PLANI

### Acil (Bu Hafta)
1. ✅ Hardcoded JWT secret key → Environment variable zorunlu yap
2. ✅ Hardcoded API key → Environment variable zorunlu yap
3. ✅ CORS wildcard → Specific origins
4. ✅ Stack trace sızıntısı → Generic error handler

### Kısa Vadeli (2 Hafta)
5. WebSocket auth implementasyonu
6. Deprecated dosyaları kaldır (`main.py`, `server.py`, `apps/api/main.py`)
7. Global exception handler ekle (`app.py`)
8. Redis tabanlı rate limiter

### Orta Vadeli (1 Ay)
9. Input validation (Pydantic modelleri)
10. API versioning politikası
11. OpenAPI schema'ları tamamla
12. Admin endpoint rate limiting

---

## DOSYA BAZLI ÖZET

| Dosya | Sorun Sayısı | En Kritik |
|---|---|---|
| `services/api/auth.py` | 2 | 🔴 Hardcoded secrets |
| `services/api/app.py` | 3 | 🔴 CORS wildcard |
| `services/api/main.py` | 8 | 🔴 Auth yok, stack trace |
| `services/api/server.py` | 4 | 🟠 Auth yetersiz |
| `services/api/rate_limiter.py` | 2 | 🟠 In-memory |
| `services/api/websocket.py` | 1 | 🔴 Auth yok |
| `services/api/v1/*.py` | 2 | 🟡 Validation eksik |
| `apps/api/main.py` | 2 | 🟠 Auth yok |

---

## SONUÇ

API güvenlik altyapısı (`auth.py`, `dependencies.py`, `rate_limiter.py`) iyi tasarlanmış ama **tutarlı uygulanmamış**. Ana sorunlar:

1. **3 farklı API entry point'i** var (app.py, main.py, server.py, apps/api/main.py) ve güvenlik uygulaması tutarsız
2. **Hardcoded secrets** production'da ciddi risk
3. **CORS wildcard** + credentials = CSRF riski
4. **Stack trace sızıntısı** 15+ endpoint'te
5. **WebSocket auth** tamamen eksik

En kritik adım: **Deprecated dosyaları kaldırın** ve tek canonical entry point (`app.py`) üzerinde güvenlik politikasını tutarlı uygulayın.

---

*Rapor: 2026-08-21 tarihinde otomatik güvenlik taraması ile oluşturulmuştur.*
