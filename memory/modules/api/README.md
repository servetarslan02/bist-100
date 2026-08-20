# API

**Modül sayısı:** 25 | **Toplam satır:** 5,331 | **Test sayısı:** 34

## Spec Uyumu: 14/14 TAM

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| JWT Authentication | ✅ TAM | HMAC-SHA256, token create/verify/expire |
| RBAC (5 rol) | ✅ TAM | VIEWER/ANALYST/OPERATOR/ADMIN/SYSTEM |
| Rate Limiting | ✅ TAM | 6 grup, spec eşikleriyle uyumlu |
| OpenAPI/Swagger | ✅ TAM | /docs, /redoc, /openapi.json |
| API Versioning | ✅ TAM | /api/v1 prefix |
| CORS | ✅ TAM | middleware |
| Health Check | ✅ TAM | /health |
| Request Timing | ✅ TAM | X-Process-Time-Ms header |
| v1 Router (16 grup) | ✅ TAM | 126 endpoint (spec hedefi: 92'yi aşıyor) |
| WebSocket | ✅ TAM | 7+ kanal |

## Düzeltilen Bug'lar

1. FastAPI `regex` deprecation → `pattern=` ile değiştirildi
