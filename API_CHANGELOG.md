# ALPHA BIST — API Changelog

Bu dosya, API'deki değişiklikleri takip eder.
Backward compatibility kuralları:
- Breaking change → major version artır (v1 → v2)
- Yeni endpoint → minor version artır
- Bug fix → patch version artır
- Deprecated endpoint → `Sunset` header + 6 ay bekleme

---

## v1.0.0 (2026-08-25)

### İlk Yayın

- `/api/v1/market/` — Piyasa verisi endpoint'leri
- `/api/v1/portfolio/` — Portföy yönetimi
- `/api/v1/risk/` — Risk metrikleri
- `/api/v1/intelligence/` — AI/ML zeka servisleri
- `/api/v1/decisions/` — Karar motoru
- `/api/v1/backtests/` — Backtest servisleri
- `/api/v1/learning/` — Sürekli öğrenme
- `/api/v1/models/` — Model yönetimi
- `/api/v1/events/` — Olay akışı (KAP, haber)
- `/api/v1/scanner/` — Fırsat tarama
- `/api/v1/factors/` — Faktör analizi
- `/api/v1/holidays/` — Tatil yönetimi
- `/api/v1/health/` — Sistem sağlık durumu

### Altyapı

- FastAPI + Pydantic v2
- JWT authentication
- Rate limiting (IP-based)
- Structured error responses (request_id, timestamp)
- Request timeout (30s)
- X-Request-ID middleware
- GZip compression

---

## v1.1.0 (2026-08-28)

### İyileştirmeler

- **Structured Error Responses**: Tüm hatalar artık `ErrorResponse` formatında döner
  - `request_id` field eklendi
  - `timestamp` field eklendi
- **Request Timeout**: 30 saniye global timeout
- **Correlation ID**: NATS ve gRPC'de tam zincir propagasyonu
- **OpenAPI Contract Testing**: CI'da schemathesis ile otomatik API testi

### Değişiklik Yok

- Mevcut endpoint'lerin hiçbiri değiştirilmedi veya kaldırılmadı
- Tüm değişiklikler additive (backward compatible)

---

## Gelecek Planlanan

### v1.2.0

- [ ] WebSocket v2 (binary Protobuf + sequence number)
- [ ] Pagination standardizasyonu (cursor-based)
- [ ] Rate limit header standardizasyonu

### v2.0.0 (Breaking Changes)

- [ ] OAuth2 authentication (JWT yerine)
- [ ] Response envelope standardizasyonu
- [ ] Error code sistemi (string error → numeric code)
