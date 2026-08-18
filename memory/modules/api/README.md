# API

**Modül sayısı:** 25 | **Test:** 27/27 passed | **Endpoint:** 102

## Modüller

| Modül | Satır | Açıklama |
|-------|-------|----------|
| `app.py` | ~130 | Ana uygulama (CORS, timing, rate limit) |
| `auth.py` | ~180 | JWT + RBAC (5 rol) |
| `rate_limiter.py` | ~110 | Token bucket rate limiting (5 grup) |
| `dependencies.py` | ~130 | FastAPI dependency injection |
| `main.py` | 716 | Backend API (mevcut) |
| `server.py` | 871 | Production server (mevcut) |
| `websocket.py` | 242 | WebSocket server (mevcut) |
| `v1/market.py` | ~130 | 10 endpoint |
| `v1/portfolio.py` | ~70 | 10 endpoint |
| `v1/risk.py` | ~50 | 8 endpoint |
| `v1/intelligence.py` | ~75 | 12 endpoint |
| `v1/decisions.py` | ~40 | 6 endpoint |
| `v1/backtest.py` | ~40 | 6 endpoint |
| `v1/learning.py` | ~45 | 8 endpoint |
| `v1/models.py` | ~40 | 6 endpoint |
| `v1/agents.py` | ~30 | 4 endpoint |
| `v1/scanner.py` | ~25 | 4 endpoint |
| `v1/macro.py` | ~25 | 4 endpoint |
| `v1/factors.py` | ~25 | 4 endpoint |
| `v1/alternative.py` | ~30 | 4 endpoint |
| `v1/viop.py` | ~25 | 4 endpoint |
| `v1/event_study.py` | ~25 | 4 endpoint |
| `v1/system.py` | ~35 | 8 endpoint |

## Endpoint Dağılımı (102)

| Grup | Endpoint | Method |
|------|----------|--------|
| Market | 10 | GET |
| Portfolio | 10 | GET/POST |
| Risk | 8 | GET/POST |
| Intelligence | 12 | GET |
| Decisions | 6 | GET/POST |
| Backtest | 6 | GET/POST |
| Learning | 8 | GET |
| Models | 6 | GET/POST |
| Agents | 4 | GET/POST |
| Scanner | 4 | GET/POST |
| Macro | 4 | GET |
| Factors | 4 | GET |
| Alternative | 4 | GET |
| VIOP | 4 | GET/POST |
| Event Study | 4 | GET/POST |
| System | 8 | GET/POST |

## Güvenlik

| Özellik | Durum |
|---------|-------|
| JWT Authentication | ✅ HMAC-SHA256 |
| RBAC | ✅ VIEWER/ANALYST/OPERATOR/ADMIN/SYSTEM |
| Rate Limiting | ✅ 5 grup |
| CORS | ✅ |
| OpenAPI/Swagger | ✅ /docs |
| Rate Limit Headers | ✅ X-RateLimit-* |
| Request Timing | ✅ X-Process-Time-Ms |

## Kullanım

```python
from services.api import app

# uvicorn ile başlat
# uvicorn services.api.app:app --host 0.0.0.0 --port 8000

# Swagger UI: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc
```
