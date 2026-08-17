# ALPHA BIST — Production Readiness GAP Audit
# Tarih: 2026-08-18
# Kapsam: Repository tamamı (89,912 satır Python, 263 dosya, 78 test dosyası)
# FAZ 4.1–4.9: KAPALI (185/185 passed, tekrar açılmayacak)

---

## ÖZET

| Sınıf | Sayı |
|-------|------|
| A — Production Blocker | 4 |
| B — Production öncesi zorunlu | 11 |
| C — Production sonrası yapılabilir | 14 |
| D — Nice-to-have | 7 |
| **Toplam bulgu** | **36** |

**Production Readiness: %42 — HAZIR DEĞİL**

---

## A — PRODUCTION BLOCKER (4)

### A-1. Broker/Order Abstraction Yok

| Alan | Execution |
|------|-----------|
| Dosya | `services/paper_trading/paper_execution.py`, `services/simulation/execution_simulator.py` |
| Mevcut durum | Sadece paper trading ve simulation var. Gerçek broker entegrasyonu yok. |
| Eksik | IBKR/Gedik/İş Yatırım API, order state machine, partial fill, rejected order, retry, duplicate prevention, idempotency, order reconciliation |
| Etki | **CRITICAL** — Gerçek emir gönderilemez |
| Neden | Sinyal üretilir ama execute edilemez |
| Bağımlılık | Broker API credentials, SPK uyumluluk |
| Çözüm | Broker abstraction interface + en az 1 concrete implementation (paper/live) |
| Kabul kriteri | Paper order → broker API → fill → portfolio update zinciri çalışmalı |

### A-2. Live Scheduler / Worker Altyapısı Yok

| Alan | Scheduling |
|------|-----------|
| Dosya | `services/scheduler/main.py` |
| Mevcut durum | `AlphaScheduler` class var ama async loop içinde sadece `await asyncio.sleep`. Worker queue, retry, timeout, job persistence yok. |
| Eksik | Celery/RQ/Dramatiq veya custom worker, job queue, retry, timeout, idempotency, failed job recovery, concurrent execution, market-open/close workflows |
| Etki | **CRITICAL** — Sistem kendi kendine çalışmaz |
| Neden | Market açıkken tarama yapılamaz |
| Bağımlılık | Redis/RabbitMQ |
| Çözüm | Worker altyapısı + market session scheduler |
| Kabul kriteri | Market açıkken otomatik tarama + model yeniden eğitim döngüsü çalışmalı |

### A-3. Database Entegrasyonu Çalışmıyor

| Alan | Database |
|------|----------|
| Dosya | `database/init/001_schema.sql`, `services/core/migrations/`, `docker-compose.yml` |
| Mevcut durum | Schema SQL'leri var, docker-compose var, ama Python kodunda asyncpg/aiosqlite import'ları sadece `services/api/main.py`'de health check'te. Feature storage, prediction storage, signal persistence DB'ye yazılmıyor. |
| Eksik | DB connection pool, ORM/repository layer, feature storage, prediction storage, signal storage, model metadata storage, retention policy, backup/recovery |
| Etki | **CRITICAL** — Veri kalıcı değil, restart'ta her şey kaybolur |
| Neden | Historical analysis, backtest, model training için veri lazım |
| Bağımlılık | PostgreSQL + ClickHouse docker ayağa kalkmalı |
| Çözüm | DB repository layer + feature/signal/prediction persistence |
| Kabul kriteri | Feature → DB → query → model pipeline çalışmalı |

### A-4. Production Config/Secrets Yönetimi Yok

| Alan | Configuration |
|------|-------------|
| Dosya | `.env.example`, `config/alpha_config.json`, `services/core/config.py` |
| Mevcut durum | `.env.example`'da `POSTGRES_PASSWORD=alpha_secure_2026` hardcoded. `SECRET_KEY=change_this_to_a_random_string`. Config validation yok. Dev/prod ayrımı yok. |
| Eksik | Secret management (Vault/env), config validation, production/dev separation, credential rotation, exposed credential scanning |
| Etki | **CRITICAL** — Güvenlik açığı, credential leak |
| Neden | Production'da hardcoded şifreler tehlikeli |
| Bağımlılık | — |
| Çözüm | .env ile config separation, secret validation, production defaults |
| Kabul kriteri | `git grep "alpha_secure_2026"` → 0 sonuç, .env gitignore'da |

---

## B — PRODUCTION ÖNCESİ ZORUNLU (11)

### B-1. KAP Veri Pipeline Entegrasyonu

| Dosya | `services/ingestion/providers/kap_provider.py`, `services/intelligence/kap_extractor.py` |
|-------|---|
| Mevcut | KAP provider class'ları var ama canlı KAP çekimi test edilmemiş, retry/timeout yok |
| Eksik | Canlı KAP API entegrasyonu, retry, duplicate detection, timestamp/PIT, failure fallback |
| Etki | HIGH |
| Çözüm | KAP provider'ı production-ready yap, integration test yaz |

### B-2. News Pipeline Entegrasyonu

| Dosya | `services/ingestion/providers/news_provider.py`, `services/intelligence/news_pipeline.py` |
|-------|---|
| Mevcut | feedparser + aiohttp yüklü, provider class var. Ama canlı çekim test edilmemiş, embedding pipeline eksik |
| Eksik | Canlı haber çekimi, duplicate detection, embedding/feature pipeline, failure fallback |
| Etki | HIGH |
| Çözüm | News provider integration test + embedding pipeline |

### B-3. Model Registry / Versioning

| Dosya | `services/ml/lightgbm_trainer.py` |
|-------|---|
| Mevcut | `TrainedModel.save()/load()` var ama versioning, registry, promotion/rollback yok |
| Eksik | Model version tracking, champion/challenger promotion, rollback, metadata storage |
| Etki | HIGH |
| Çözüm | Model registry class + DB persistence |

### B-4. Live Feature Calculation Pipeline

| Dosya | `services/features/calculator.py`, `services/backtest/engine_v4.py` |
|-------|---|
| Mevcut | FeatureCalculator var, backtest'te kullanılıyor. Ama canlı inference scheduling, stale feature detection, missing data handling yok |
| Eksik | Live feature scheduler, stale detection, missing data fallback, feature freshness check |
| Etki | HIGH |
| Çözüm | Live feature pipeline + freshness monitoring |

### B-5. Signal Deduplication / Expiry

| Dosya | `services/core/decision_engine.py` |
|-------|---|
| Mevcut | Decision engine var ama signal deduplication, expiry, ranking universe filtering yok |
| Eksik | Signal cache, duplicate prevention, TTL/expiry, universe filtering |
| Etki | HIGH |
| Çözüm | Signal cache with TTL + deduplication |

### B-6. Position Sizing → Risk Gate Bağlantısı

| Dosya | `services/risk/position_sizing.py`, `services/risk/enhanced_risk.py` |
|-------|---|
| Mevcut | PositionSizer class var (Kelly), risk module var ama live pipeline'a bağlı değil |
| Eksik | Risk gate'in live scoring pipeline ile entegrasyonu, sector exposure, concentration limits |
| Etki | HIGH |
| Çözüm | Risk gate middleware + live pipeline integration |

### B-7. Circuit Breaker / Kill Switch

| Dosya | `services/core/circuit_breaker.py`, `services/paper_trading/paper_risk_gate.py` |
|-------|---|
| Mevcut | CircuitBreaker class var, paper trading'de kill switch var. Ama live execution'da kullanılmıyor |
| Eksik | Live execution'da circuit breaker, emergency stop, model confidence ile risk bağlantısı |
| Etki | HIGH |
| Çözüm | Live risk gate + circuit breaker integration |

### B-8. Structured Logging + Monitoring

| Dosya | `services/core/monitoring.py`, `services/core/observability.py` |
|-------|---|
| Mevcut | structlog kullanılıyor, Prometheus metrics var. Ama live'da metric collection, alert routing, audit trail eksik |
| Eksik | Live metric collection, alert routing (Slack/email), audit trail, latency tracking |
| Etki | HIGH |
| Çözüm | Monitoring pipeline + alert integration |

### B-9. API Authentication/Authorization

| Dosya | `services/api/server.py` |
|-------|---|
| Mevcut | Monitoring endpoint'lerinde Bearer token var. Ama genel API auth yok |
| Eksik | API-wide auth, rate limiting, CORS, input validation |
| Etki | HIGH |
| Çözüm | API middleware (auth + rate limit + validation) |

### B-10. Corporate Actions Handling

| Dosya | — |
|-------|---|
| Mevcut | **YOK.** Split, dividend, ticker change, delist handling yok |
| Eksik | Corporate action detection, price adjustment, universe update, survivorship bias correction |
| Etki | HIGH |
| Çözüm | Corporate action handler + price adjustment pipeline |

### B-11. Deployment / Docker Production Config

| Dosya | `docker-compose.yml`, `infrastructure/Dockerfile.api` |
|-------|---|
| Mevcut | docker-compose var ama production resource limits, health checks, restart policy, startup ordering eksik |
| Eksik | Production docker-compose, resource limits, health checks, startup ordering, deployment/rollback |
| Etki | HIGH |
| Çözüm | Production docker-compose + deployment script |

---

## C — PRODUCTION SONRASI YAPILABİLİR (14)

| ID | Alan | Açıklama | Etki |
|----|------|----------|------|
| C-1 | WebSocket streaming | Canlı fiyat stream'i (WebSocket) | MEDIUM |
| C-2 | Grafana dashboard | Monitoring dashboard (grafana provision var ama aktif değil) | MEDIUM |
| C-3 | Backtest performance | Büyük dataset'te backtest yavaşlaması | MEDIUM |
| C-4 | Feature caching | Feature hesaplama cache (per-ticker, per-date) | MEDIUM |
| C-5 | Database migrations runner | Migration runner var ama CLI integration yok | LOW |
| C-6 | Redpanda/Kafka event bus | Event bus kodu var ama production'da aktif değil | MEDIUM |
| C-7 | LLM integration | Ollama config var ama KAP extraction LLM pipeline eksik | MEDIUM |
| C-8 | Multi-instance deployment | Birden fazla instance çalıştırma | LOW |
| C-9 | Historical data backfill | Eski veriyi DB'ye doldurma scripti | MEDIUM |
| C-10 | Operational runbook | Operasyonel prosedür dokümantasyonu | LOW |
| C-11 | Performance profiling | CPU/RAM/latency profiling | LOW |
| C-12 | Load testing | Eşzamanlı ticker işleme testi | MEDIUM |
| C-13 | Disaster recovery | DB backup/restore prosedürü | MEDIUM |
| C-14 | API versioning | API v1/v2 ayrımı | LOW |

---

## D — NICE-TO-HAVE (7)

| ID | Alan | Açıklama |
|----|------|----------|
| D-1 | FinRL/FinGPT entegrasyonu | ROADMAP'te vaat edilmiş (FAZ 29) |
| D-2 | Alternative data | Satellite, social media, web scraping |
| D-3 | Options/VIOP | ROADMAP'te vaat edilmiş (FAZ 32) |
| D-4 | Global market expansion | Sadece BIST değil, global |
| D-5 | Autonomous research brain | ROADMAP FAZ 13 |
| D-6 | Governed autonomous coding | ROADMAP FAZ 14 |
| D-7 | Long-run autonomous paper proof | ROADMAP FAZ 16 |

---

## ROADMAP vs KOD GAP ANALİZİ

| Roadmap FAZ | Durum | Açıklama |
|-------------|-------|----------|
| FAZ 0 (Truth Audit) | ✅ Yapıldı | — |
| FAZ 1 (Canonical Runtime) | ⚠️ Kısmen | Entry point var ama single runtime yok |
| FAZ 2 (Universe/Entity) | ⚠️ Kısmen | `bist_universe.py` var ama PIT universe snapshot yok |
| FAZ 3 (Raw Data + PIT) | ⚠️ Kısmen | yfinance var ama PIT store, mask-first partial |
| FAZ 4 (Event Intelligence) | ✅ FAZ 4.1–4.9 kapatıldı | — |
| FAZ 5 (World State) | ⚠️ Kısmen | `WorldStateManager` var ama live besleme yok |
| FAZ 6 (Feature Platform) | ⚠️ Kısmen | FeatureCalculator var ama 9 family eksik |
| FAZ 7 (Label/Dataset) | ❌ Yok | Label generator, dataset manifest yok |
| FAZ 8 (Model Zoo) | ⚠️ Kısmen | LightGBM var ama model zoo, benchmark yok |
| FAZ 9 (Governance) | ⚠️ Kısmen | Paper trading'de champion/challenger var ama live'da yok |
| FAZ 10 (Paper Trading OS) | ⚠️ Kısmen | Paper trading modülü var ama persistent OS yok |
| FAZ 11 (Risk/Safe Mode) | ⚠️ Kısmen | Risk modülleri var ama live'a bağlı değil |
| FAZ 12 (Performance/Attribution) | ❌ Yok | Performance attribution yok |
| FAZ 13–16 | ❌ Yok | Autonomous research, coding, global expansion yok |

---

## SONUÇ

| Metric | Değer |
|--------|-------|
| Production Blocker | 4 |
| Production öncesi zorunlu | 11 |
| Production sonrası | 14 |
| Nice-to-have | 7 |
| **Production Readiness** | **%42** |
| **Karar** | **HAZIR DEĞİL** |

### Production'a Çıkışı Engelleyen 4 Blocker

1. **Broker/Order abstraction** — Gerçek emir gönderilemez
2. **Live scheduler/worker** — Sistem kendi kendine çalışmaz
3. **Database entegrasyonu** — Veri kalıcı değil
4. **Production config/secrets** — Güvenlik açığı

### Önerilen Uygulama Sırası

1. **Sprint 1 (1 hafta):** A-4 (secrets) + A-3 (DB) + B-11 (docker production)
2. **Sprint 2 (2 hafta):** A-2 (scheduler) + B-4 (live feature pipeline) + B-8 (monitoring)
3. **Sprint 3 (2 hafta):** A-1 (broker abstraction) + B-6 (risk gate) + B-7 (circuit breaker)
4. **Sprint 4 (1 hafta):** B-1 (KAP) + B-2 (news) + B-3 (model registry) + B-5 (signal dedup)
5. **Sprint 5 (1 hafta):** B-9 (API auth) + B-10 (corporate actions) + integration tests
6. **Sonrası:** C serisi + D serisi

**Tahmini production-ready süre: 7-8 sprint (8-10 hafta)**
