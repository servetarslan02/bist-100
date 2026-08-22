# API Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 12 |
| Toplam satır | ~3,200 |
| Endpoint sayısı | 92 REST + 10 WebSocket |
| Router sayısı | 16 (v1 alt router) |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| app.py (CANONICAL) | ✅ TAM | FastAPI factory, lifespan, middleware |
| auth.py | ✅ TAM | JWT + RBAC (5 rol) |
| rate_limiter.py | ✅ TAM | Token bucket, 6 endpoint grubu |
| dependencies.py | ✅ TAM | DI: auth, rate limit, role check |
| websocket.py | ✅ TAM | 5 kanal, connection manager |
| v1/__init__.py | ✅ TAM | 16 router, /api/v1 prefix |
| v1/schemas.py | ✅ TAM | Pydantic response modelleri |
| v1/market.py | ✅ TAM | Piyasa endpoint'leri |
| v1/portfolio.py | ✅ TAM | Portföy endpoint'leri |
| v1/risk.py | ✅ TAM | Risk endpoint'leri |
| server.py | ⚠️ DEPRECATED | Dev/test server (SQLite) |
| main.py | ⚠️ DEPRECATED | Geriye uyumluluk redirect'i |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| In-memory rate limiter | P1 | Production'da Redis tabanlı olmalı |
| JWT secret zorunlu | P1 | `JWT_SECRET` yoksa RuntimeError |
| Background task lifecycle | P2 | Restart'ta sıfırdan başlar |
| WebSocket auth sadece bağlantıda | P2 | Bağlantı sonrası token yenileme yok |
| Dev server farklı DB | P2 | SQLite vs PostgreSQL farkı |
