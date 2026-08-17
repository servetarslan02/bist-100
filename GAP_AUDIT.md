# ALPHA BIST — Production Readiness GAP Audit
**Tarih:** 2026-08-18
**Kapsam:** Repository tamamı (89,912 satır Python, 263 dosya, 78 test dosyası)
**Kaynak:** MIMARI_GAP_ANALIZ.md + ROADMAP-v4.md + mevcut kod doğrulaması
**FAZ 4.1–4.9:** KAPALI (185/185 passed, tekrar açılmayacak)

---

## ÖZET

| Sınıf | Sayı |
|-------|------|
| A — Production Blocker | 5 |
| B — Production öncesi zorunlu | 8 |
| C — Production sonrası yapılabilir | 10 |
| D — Nice-to-have | 7 |
| **Toplam doğrulanmış bulgu** | **30** |

**Production Readiness: %35 — HAZIR DEĞİL**

---

## A — PRODUCTION BLOCKER (5)

### A-1. Production Config/Secrets Yönetimi

| Alan | Configuration |
|------|-------------|
| Dosya | `.env.example`, `config/alpha_config.json`, `services/core/config.py` |
| Mevcut durum | `.env.example`'da `POSTGRES_PASSWORD=alpha_…026` hardcoded. `SECRET_KEY=change…ng`. Config validation yok. Dev/prod ayrımı yok. |
| Eksik | Secret management (Vault/env), config validation, production/dev separation, credential rotation |
| Etki | **CRITICAL** — Güvenlik açığı, credential leak |
| Neden | Production'da hardcoded şifreler tehlikeli |
| Bağımlılık | — |
| Çözüm | .env ile config separation, secret validation, production defaults, gitignore |
| Kabul kriteri | `git grep "alpha_secure_2026"` → 0 sonuç, .env gitignore'da |

### A-2. Database Entegrasyonu Çalışmıyor

| Alan | Database |
|------|----------|
| Dosya | `database/init/001_schema.sql`, `services/core/migrations/`, `docker-compose.yml`, `services/core/database.py` |
| Mevcut durum | Schema SQL'leri var (4 migration), docker-compose var, `database.py`'de asyncpg pool code var. Ama production'da aktif değil, feature/signal/prediction DB'ye yazılmıyor. |
| Eksik | DB connection pool production'da aktif, feature storage, prediction storage, signal storage, model metadata storage, retention, backup/recovery |
| Etki | **CRITICAL** — Veri kalıcı değil, restart'ta her şey kaybolur |
| Neden | Historical analysis, backtest, model training için veri lazım |
| Bağımlılık | Docker |
| Çözüm | DB repository layer + feature/signal/prediction persistence |
| Kabul kriteri | Feature → DB → query → model pipeline çalışmalı |

### A-3. Broker/Order Abstraction Yok

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

### A-4. Live Scheduler/Worker Altyapısı Yok

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

### A-5. 17 Intelligence Modülü Bağlı Değil

| Alan | Intelligence |
|------|-------------|
| Dosya | `services/intelligence/*.py` (17 modül) |
| Mevcut durum | signal_fusion, trade_planner, forecasting, probability, monte_carlo, spec_engine, evidence_engine, factor_engine, knowledge_graph, impact_engine, kap_extractor, analysis_engines, macro_sensitivity, research_memory, scenario, valuation, world_state — hiçbiri orchestrator'a bağlı değil |
| Eksik | Orchestrator pipeline entegrasyonu, veri besleme, output tüketimi |
| Etki | **CRITICAL** — Prediction layer, decision quality, intelligence features üretilemez |
| Neden | Sistem sadece teknik feature'lardan skor üretiyor, intelligence katmanı tamamen pasif |
| Bağımlılık | Motor besleme (A-2 sonrası) |
| Çözüm | Orchestrator'da intelligence modül entegrasyonu (öncelik: signal_fusion, trade_planner, forecasting) |
| Kabul kriteri | Intelligence modülleri orchestrator'dan çağrılıyor ve output üretiyor |

---

## B — PRODUCTION ÖNCESİ ZORUNLU (8)

### B-1. Motor 1/4/5/6/9 Veri Beslemesi

| Dosya | `services/core/orchestrator.py`, `services/features/seven_motors.py` |
|-------|---|
| Mevcut | Orchestrator'da `benchmark_close`, `market_return`, `sector_close`, `peer_closes` besleniyor. Ama `fundamentals`, `kap_events`, `news_events`, `upcoming_events`, `llm_analysis` hâlâ None. Motor 1 (RS) çalışıyor, Motor 4/5/6/9 veri alamıyor. |
| Etki | HIGH — 5 motor feature üretmiyor |
| Çözüm | Fundamental, KAP, news, catalyst veri akışını orchestrator'a bağla |

### B-2. Prediction Layer (Direction/Return/Confidence)

| Dosya | `services/intelligence/forecasting.py`, `services/intelligence/probability.py` |
|-------|---|
| Mevcut | Sistem sadece "skor" üretiyor. Yön tahmini, beklenen getiri, zaman ufku, confidence, risk/reward, kalite sınıfı yok. `forecasting.py`'de `HORIZONS = [1, 5, 20, 60, 120]` tanımlı ama hiç kullanılmıyor. |
| Etki | HIGH — Trading kalitesi düşük |
| Bağımlılık | FAZ 4 ML pipeline (mevcut) |
| Çözüm | Direction model (classification), return model (regresyon + CI), calibration (Platt scaling) |

### B-3. Signal-to-Decision Pipeline Kopuk

| Dosya | `services/intelligence/signal_fusion.py`, `services/intelligence/trade_planner.py` |
|-------|---|
| Mevcut | Mevcut: features → ranking → top_20 → rapor. Hedef: features → ranking → direction → expected_return → confidence → risk/reward → trade_plan. signal_fusion ve trade_planner var ama bağlı değil. |
| Etki | HIGH |
| Bağımlılık | Prediction layer (B-2) |
| Çözüm | Orchestrator'da signal fusion + trade planner entegrasyonu |

### B-4. Model Registry / Versioning

| Dosya | `services/ml/lightgbm_trainer.py` |
|-------|---|
| Mevcut | `TrainedModel.save()/load()` var (pickle), `MultiHorizonModel` var ama versioning, champion/challenger promotion, rollback, DB persistence yok. |
| Etki | HIGH |
| Çözüm | Model registry class + DB persistence + promotion/rollback |

### B-5. Calibrasyon Eğitilmemiş

| Dosya | `services/risk/calibration.py`, `services/risk/position_sizing.py` |
|-------|---|
| Mevcut | `calibrator._fitted = False`. Position sizing cold-start policy'de. Kelly devre dışı. |
| Etki | HIGH — Score-based weight çalışıyor ama optimal değil |
| Çözüm | Calibrator'ı historical trade data ile eğit, Kelly'yi aktif et |

### B-6. KAP/News Canlı Pipeline

| Dosya | `services/ingestion/providers/kap_provider.py`, `services/ingestion/providers/news_provider.py` |
|-------|---|
| Mevcut | `fetch_disclosures()`, `fetch_newsapi()` method'ları var ama canlı test edilmemiş, orchestrator'a bağlı değil, embedding pipeline yok, retry/timeout yok. |
| Etki | HIGH |
| Çözüm | Canlı KAP/news çekimi + orchestrator entegrasyonu + embedding pipeline |

### B-7. Corporate Actions (Split/Dividend)

| Dosya | — |
|-------|---|
| Mevcut | **YOK.** Split, dividend, ticker change, delist handling yok. |
| Etki | HIGH — Fiyat verisi bozulur, backtest sonuçları yanıltır |
| Çözüm | Corporate action handler + price adjustment pipeline |

### B-8. Risk Gate + Circuit Breaker Live

| Dosya | `services/risk/enhanced_risk.py`, `services/core/circuit_breaker.py`, `services/paper_trading/paper_risk_gate.py` |
|-------|---|
| Mevcut | Risk modülleri ve CircuitBreaker class var ama live execution'da aktif değil. Paper trading'de kill switch var. |
| Etki | HIGH — Live'da risk kontrolü yok |
| Çözüm | Risk gate middleware + circuit breaker live pipeline entegrasyonu |

---

## C — PRODUCTION SONRASI YAPILABİLİR (10)

| # | Alan | Açıklama | Etki |
|---|------|----------|------|
| C-1 | API auth/rate limiting | Monitoring endpoint'lerinde Bearer token var ama genel API auth yok | MEDIUM |
| C-2 | Monitoring/alert routing | structlog + Prometheus var ama live metric collection, alert routing eksik | MEDIUM |
| C-3 | Docker production config | docker-compose var ama production resource limits, health checks eksik | MEDIUM |
| C-4 | Regime sistemi tutarsızlığı | `regime_detector.py` (aktif) ve `regime.py` (pasif) farklı rejim tipleri üretiyor | LOW |
| C-5 | WebSocket streaming | API'de WebSocket endpoint var ama canlı fiyat stream'i yok | MEDIUM |
| C-6 | Historical data backfill | Eski veriyi DB'ye doldurma scripti yok | MEDIUM |
| C-7 | Feature caching | Feature hesaplama cache (per-ticker, per-date) yok | MEDIUM |
| C-8 | Grafana dashboard | Grafana provision var ama aktif değil | LOW |
| C-9 | Disaster recovery | DB backup/restore prosedürü yok | MEDIUM |
| C-10 | Operational runbook | Operasyonel prosedür dokümantasyonu yok | LOW |

---

## D — NICE-TO-HAVE (7)

| # | Alan | Açıklama |
|---|------|----------|
| D-1 | FinRL/FinGPT entegrasyonu | ROADMAP FAZ 29 |
| D-2 | Alternative data | Satellite, social media, web scraping |
| D-3 | Options/VIOP | ROADMAP FAZ 32 |
| D-4 | Global market expansion | Sadece BIST değil, global |
| D-5 | Autonomous research brain | ROADMAP FAZ 13 |
| D-6 | Governed autonomous coding | ROADMAP FAZ 14 |
| D-7 | Long-run autonomous paper proof | ROADMAP FAZ 16 |

---

## FAZ 4 İLE KAPATILANLAR (Tekrar iş olarak yazılmaz)

| Madde | FAZ 4.x |
|-------|---------|
| Multi-sample training dataset | 4.1 |
| Training dataset kalite kontrolü | 4.2 |
| Production-grade ML validation | 4.3 |
| Date-space purge gap | 4.4 |
| Multi-horizon target (1d/5d/20d/60d) | 4.4-4.5 |
| Feature registry/contract (76 feature) | 4.5 |
| CS normalization live parity | 4.6 |
| Adapter parity-safe | 4.7 |
| Tüm scoring path'leri parity-safe | 4.8-4.9 |
| Scalar feature guard | 4.8 |
| Future-data mutation protection | 4.1-4.9 |
| Deterministic training/replay | 4.1-4.9 |

---

## ROADMAP vs KOD GAP

| Roadmap FAZ | Durum | Açıklama |
|-------------|-------|----------|
| FAZ 0 (Truth Audit) | ✅ Tamamlandı | — |
| FAZ 1 (Canonical Runtime) | ⚠️ Kısmen | Entry point var ama single runtime yok |
| FAZ 2 (Universe/Entity) | ⚠️ Kısmen | `bist_universe.py` var ama PIT universe snapshot yok |
| FAZ 3 (Raw Data + PIT) | ⚠️ Kısmen | yfinance var ama PIT store, mask-first partial |
| FAZ 4 (ML Pipeline) | ✅ FAZ 4.1–4.9 kapatıldı | — |
| FAZ 5 (World State) | ⚠️ Kısmen | `WorldStateManager` var ama live besleme yok |
| FAZ 6 (Feature Platform) | ⚠️ Kısmen | FeatureCalculator var ama 9 family eksik (Motor 1/4/5/6/9) |
| FAZ 7 (Label/Dataset) | ❌ Yok | Label generator, dataset manifest yok |
| FAZ 8 (Model Zoo) | ⚠️ Kısmen | LightGBM var ama model zoo, benchmark yok |
| FAZ 9 (Governance) | ⚠️ Kısmen | Paper trading'de champion/challenger var ama live'da yok |
| FAZ 10 (Paper Trading OS) | ⚠️ Kısmen | Paper trading modülü var ama persistent OS yok |
| FAZ 11 (Risk/Safe Mode) | ⚠️ Kısmen | Risk modülleri var ama live'a bağlı değil |
| FAZ 12 (Performance/Attribution) | ❌ Yok | Performance attribution yok |
| FAZ 13–16 | ❌ Yok | Autonomous research, coding, global expansion yok |

---

## BAĞIMLILIK SIRASI

```
Sprint 1: A-1 (config/secrets) + A-2 (DB) + C-3 (docker production)
    ↓
Sprint 2: A-4 (scheduler) + B-1 (motor besleme) + C-2 (monitoring)
    ↓
Sprint 3: A-3 (broker) + B-8 (risk gate live) + B-7 (corporate actions)
    ↓
Sprint 4: A-5 (intelligence bağlama) + B-2 (prediction layer) + B-6 (KAP/news)
    ↓
Sprint 5: B-3 (signal-to-decision) + B-4 (model registry) + B-5 (calibration)
    ↓
Sprint 6: C-1 (API auth) + C-4 (regime) + integration tests
    ↓
Sonrası: C serisi + D serisi
```

---

## SONUÇ

| Metric | Değer |
|--------|-------|
| Toplam doğrulanmış bulgu | 30 |
| FAZ 4 ile kapatılan | 12 (tekrar açılmayacak) |
| Hâlâ gerçek eksik | 18 |
| Production Blocker (A) | 5 |
| Production öncesi (B) | 8 |
| Sonraya bırakılabilir (C+D) | 17 |
| **Production Readiness** | **%35** |
| **Karar** | **HAZIR DEĞİL** |
| **Tahmini production-ready süre** | **6 sprint (8-10 hafta)** |
| **İlk uygulanması gereken** | **Config/Secrets + DB + Docker (Sprint 1)** |
