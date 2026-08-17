# API Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Aladdin (BlackRock) mimarisi, Low-Latency HFT System Design (Liu, 2026), ScienceDirect Modular Trading System (2026), QuantConnect platform tasarımı, CQRS/Event Sourcing patterns

---

## 0. Mevcut Durum (Kod Analizi)

### Modüller (3 dosya, 1,829 satır)

| Modül | Satır | Class | Fonksiyon | Durum |
|-------|-------|-------|-----------|-------|
| `server.py` | 871 | 1 | 42 | ✅ Dashboard + API (port 8000) |
| `main.py` | 716 | 1 | 21 | ✅ Backend API (port 8001) |
| `websocket.py` | 242 | 2 | 3 | ✅ WebSocket server |

### Mevcut Endpoint'ler (41 adet)

**main.py (16 endpoint):**
| Method | Endpoint | Servis |
|--------|----------|--------|
| GET | `/api/health` | infrastructure |
| GET | `/api/status` | orchestrator |
| GET | `/api/market/state` | market_state, features |
| GET | `/api/market/instruments` | bist_universe |
| GET | `/api/market/instrument/{ticker}/ohlcv` | yfinance |
| GET | `/api/market/instrument/{ticker}/full` | orchestrator |
| GET | `/api/market/instrument/{ticker}` | intelligence |
| GET | `/api/signals` | signal_fusion |
| GET | `/api/portfolio` | portfolio |
| GET | `/api/world/state` | world_state |
| GET | `/api/features/{ticker}` | calculator |
| GET | `/api/events` | event_bus |
| GET | `/api/models` | ranking_model |
| GET | `/api/alerts` | alerting |
| WS | `/ws/{channel}` | websocket |
| GET | `/api/stream/events` | event_bus |

**server.py (25 endpoint):**
| Method | Endpoint | Servis |
|--------|----------|--------|
| GET | `/` | Dashboard HTML |
| GET | `/health` | infrastructure |
| GET | `/api/market` | market_state |
| GET | `/api/opportunities` | opportunity_engine |
| GET | `/api/portfolio` | portfolio |
| GET | `/api/decisions` | decision_engine |
| GET | `/api/learning` | learning |
| GET | `/api/learning/predictions` | outcome_tracker |
| GET | `/api/signals` | signal_fusion |
| GET | `/api/features/{ticker}` | calculator |
| GET | `/api/regime` | regime |
| GET | `/api/risk` | risk |
| GET | `/api/notifications` | alerting |
| GET | `/api/audit` | audit_log |
| GET | `/api/stats` | observability |
| GET | `/api/tickers` | bist_universe |
| GET | `/health/detailed` | infrastructure |
| GET | `/metrics` | production_metrics |
| GET | `/admin/lock-metrics` | db_lock |
| GET | `/admin/portfolio` | portfolio |
| GET | `/admin/alerts` | alerting |
| GET | `/admin/auth-status` | monitoring_security |
| GET/POST | `/admin/policy` | policy |
| POST | `/admin/policy/rollback` | policy |
| GET | `/admin/policy/history` | policy |
| GET | `/admin/policy/audit` | policy |
| POST | `/admin/silence` | alerting |
| DELETE | `/admin/silence` | alerting |
| POST | `/admin/policy/diff` | policy |

### WebSocket Kanalları (7)

| Kanal | İçerik |
|-------|--------|
| `/ws` | Genel WebSocket |
| `/ws/market` | Piyasa verisi |
| `/ws/portfolio` | Portföy güncellemeleri |
| `/ws/risk` | Risk alert'leri |
| `/ws/signals` | Sinyal akışı |
| `/ws/decisions` | Karar akışı |
| `/ws/system` | Sistem durumu |

### Servis Bağlantıları

**main.py kullandığı servisler:**
- core: config, database, event_bus, logging
- ingestion: bist_universe
- features: calculator
- intelligence: spec_engine

**server.py kullandığı servisler:**
- core: database_dev, logging, audit_log, observability, infrastructure, monitoring, monitoring_security, alerting, config
- ingestion: bist_universe
- features: store
- intelligence: regime, signal_fusion
- scanner: opportunity_engine
- ml: ranking_model
- core: decision_engine
- risk: position_sizing
- simulation: execution_simulator
- portfolio: portfolio_manager
- learning: integrated_learning, outcome_tracker

### Eksik Entegrasyonlar (Kod Analizi)

| Servis | Neden Kullanılmalı | Durum |
|--------|-------------------|-------|
| intelligence/monte_carlo.py | `/api/scenarios` endpoint'inde | ❌ |
| intelligence/scenario.py | `/api/scenarios` endpoint'inde | ❌ |
| intelligence/probability.py | `/api/instrument/{ticker}/forecast` endpoint'inde | ❌ |
| intelligence/prediction_layer.py | `/api/predictions` endpoint'inde | ❌ |
| intelligence/kap_llm_extractor.py | `/api/events` endpoint'inde | ❌ |
| intelligence/pipeline.py | `/api/intelligence` endpoint'inde | ❌ |
| risk/enhanced_risk.py | `/api/risk/portfolio` endpoint'inde | ❌ |
| risk/calibration.py | `/api/models/calibration` endpoint'inde | ❌ |
| learning/attribution.py | `/api/learning/attribution` endpoint'inde | ❌ |
| learning/continuous_learning.py | `/api/learning/status` endpoint'inde | ❌ |
| ml/model_comparator.py | `/api/models/compare` endpoint'inde | ❌ |
| ml/ensemble.py | `/api/models/ensemble` endpoint'inde | ❌ |
| backtest/engine.py | `/api/backtests` endpoint'inde | ❌ |
| agents/agent_system.py | `/api/agents` endpoint'inde | ❌ |
| scanner/alpha_engine.py | `/api/scanner/alpha` endpoint'inde | ❌ |
| simulation/execution_simulator.py | `/api/orders` endpoint'inde | ❌ |
| alternative/* | `/api/alternative` endpoint'inde | ❌ |
| macro/* | `/api/macro` endpoint'inde | ❌ |
| factors/* | `/api/factors` endpoint'inde | ❌ |
| event_study/* | `/api/event-study` endpoint'inde | ❌ |
| viop/* | `/api/viop` endpoint'inde | ❌ |
| features/technical_features.py | `/api/features/{ticker}` endpoint'inde | ❌ |
| features/feature_selector.py | `/api/features/select` endpoint'inde | ❌ |

---

## 1. Kurumsal Trading Platformu Mimarisi (Araştırma Bazlı)

### Aladdin (BlackRock) Bileşenleri

BlackRock'ın Aladdin platformu $21 trilyon varlığı yönetiyor. Temel bileşenler:

```
ALADDIN ARCHITECTURE
├── Portfolio Management    ← Pozisyon takibi, P&L, risk
├── Trading                 ← Emir yönetimi, execution
├── Compliance              ← Kurallara uyumluluk
├── Risk Analytics          ← VaR, stress test, senaryo
├── Data Management         ← Veri toplama, doğrulama
├── Reporting               ← Raporlama, dashboard
└── AI/ML Layer             ← Tahmin, anomaly detection
```

**Temel Prensipler:**
- **Tek platform** — tüm yatırım süreci tek çatı altında
- **Gerçek zamanlı** — anlık risk hesaplama
- **API-first** — tüm servisler API üzerinden erişilebilir
- **Event-driven** — olaylar anında tüm sisteme yayılır
- **Audit her şey** — her karar, her değişiklik kayıtlı

### HFT System Design (Liu, 2026)

```
HFT ARCHITECTURE
├── Market Data Infrastructure  ← Gerçek zamanlı veri
├── Order Matching Engine       ← Emir eşleştirme
├── Risk Management System      ← Pre-trade risk
├── FIX Protocol Gateway        ← Standart protokol
├── Persistence Layer           ← Veri saklama
└── Monitoring & Observability  ← İzleme
```

**Temel Prensipler:**
- **Low-latency** — milisaniye hassasiyet
- **Event-driven** — olay tabanlı mimari
- **Microservices** — bağımsız servisler
- **CQRS** — Command Query Responsibility Segregation
- **Event Sourcing** — tüm değişiklikler event olarak saklanır

---

## 2. Nihai API Mimarisi (Araştırma Bazlı)

### 2.1 Katmanlı Mimari

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENT LAYER                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Web       │  │ Mobile    │  │ CLI       │              │
│  │ Dashboard │  │ App       │  │ Tool      │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────┐
│                    API GATEWAY                               │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Auth      │  │ Rate      │  │ CORS      │              │
│  │ JWT+RBAC  │  │ Limiter   │  │ Handler   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────┐
│                    API LAYER (REST + WebSocket)              │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              READ PATH (Query)                       │   │
│  │  GET /api/v1/*  →  Cache  →  Database  →  Response  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              WRITE PATH (Command)                    │   │
│  │  POST/PUT/*  →  Validation  →  Event  →  Store      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              STREAM PATH (WebSocket)                 │   │
│  │  /ws/*  →  Subscribe  →  Push  →  Client            │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────┐
│                    SERVICE LAYER                             │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Market    │  │ Portfolio │  │ Risk      │              │
│  │ Service   │  │ Service   │  │ Service   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │Intelligence│ │ Decision  │  │ Learning  │              │
│  │ Service   │  │ Service   │  │ Service   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Scanner   │  │ Backtest  │  │ Agent     │              │
│  │ Service   │  │ Service   │  │ Service   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────┐
│                    DATA LAYER                                │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ PostgreSQL│  │ Redis     │  │ Event     │              │
│  │ (State)   │  │ (Cache)   │  │ Store     │              │
│  └───────────┘  └───────────┘  └───────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 CQRS Pattern (Command Query Responsibility Segregation)

**Neden?** Read ve write path'leri farklı optimize edilebilir.

```
WRITE PATH (Command):
POST /api/v1/decisions
  → Validate input
  → Create DecisionCreated event
  → Store in event store
  → Update read model (async)
  → Return 201 Created

READ PATH (Query):
GET /api/v1/decisions/{id}
  → Read from read model (cache'den)
  → Return decision
```

### 2.3 Event Sourcing Pattern

**Neden?** Tüm değişiklikler event olarak saklanır → audit, replay, recovery.

```
Event Store:
┌─────────────────────────────────────────────────┐
│ Event ID | Type              | Data    | Time   │
├─────────────────────────────────────────────────┤
│ evt-001  | DecisionCreated   | {...}   | T1     │
│ evt-002  | RiskApproved      | {...}   | T2     │
│ evt-003  | OrderCreated      | {...}   | T3     │
│ evt-004  | FillCreated       | {...}   | T4     │
│ evt-005  | PortfolioUpdated  | {...}   | T5     │
└─────────────────────────────────────────────────┘

Herhangi bir noktaya geri dönülebilir.
Event replay ile state yeniden oluşturulabilir.
```

---

## 3. Endpoint Listesi (Nihai — Araştırma Bazlı)

### 3.1 Market Data (10 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/market/state` | Piyasa durumu | market_state |
| GET | `/api/v1/market/instruments` | Tüm hisseler | bist_universe |
| GET | `/api/v1/market/instruments/{ticker}` | Hisse detay | intelligence |
| GET | `/api/v1/market/instruments/{ticker}/ohlcv` | OHLCV | yfinance |
| GET | `/api/v1/market/instruments/{ticker}/full` | Tam analiz | orchestrator |
| GET | `/api/v1/market/instruments/{ticker}/features` | Feature'lar | calculator |
| GET | `/api/v1/market/sectors` | Sektörler | cross_sectional |
| GET | `/api/v1/market/calendar` | İşlem takvimi | market_calendar |
| GET | `/api/v1/market/events` | Piyasa olayları | event_bus |
| GET | `/api/v1/market/regime` | Piyasa rejimi | regime |

### 3.2 Portfolio (10 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/portfolio` | Portföy özeti | portfolio |
| GET | `/api/v1/portfolio/positions` | Pozisyonlar | portfolio |
| GET | `/api/v1/portfolio/trades` | İşlem geçmişi | portfolio |
| GET | `/api/v1/portfolio/pnl` | P&L | portfolio |
| GET | `/api/v1/portfolio/equity` | Equity curve | portfolio |
| GET | `/api/v1/portfolio/risk` | Portföy risk | risk |
| GET | `/api/v1/portfolio/attribution` | Performans attribüsyonu | attribution |
| POST | `/api/v1/portfolio/rebalance` | Rebalance | portfolio |
| GET | `/api/v1/portfolio/reconciliation` | Uzlaştırma | reconciliation |
| GET | `/api/v1/portfolio/comparison` | Benchmark karşılaştırma | benchmark |

### 3.3 Risk (8 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/risk/overview` | Risk özeti | risk |
| GET | `/api/v1/risk/portfolio` | Portföy risk detayı | enhanced_risk |
| GET | `/api/v1/risk/positions` | Pozisyon riskleri | position_risk |
| GET | `/api/v1/risk/limits` | Risk limitleri | risk_gate |
| POST | `/api/v1/risk/check` | Pre-trade risk check | risk_gate |
| GET | `/api/v1/risk/compliance` | SPK uyumluluk | compliance |
| GET | `/api/v1/risk/var` | VaR/CVaR | enhanced_risk |
| GET | `/api/v1/risk/stress-test` | Stress test | scenario |

### 3.4 Intelligence (12 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/intelligence/{ticker}` | Tam analiz | orchestrator |
| GET | `/api/v1/intelligence/{ticker}/features` | Feature'lar | calculator |
| GET | `/api/v1/intelligence/{ticker}/forecast` | Tahmin | forecasting |
| GET | `/api/v1/intelligence/{ticker}/monte-carlo` | Monte Carlo | monte_carlo |
| GET | `/api/v1/intelligence/{ticker}/scenario` | Senaryo | scenario |
| GET | `/api/v1/intelligence/{ticker}/spec` | SPEC skor | spec_engine |
| GET | `/api/v1/intelligence/{ticker}/probability` | Olasılık | probability |
| GET | `/api/v1/intelligence/{ticker}/valuation` | Değerleme | valuation |
| GET | `/api/v1/intelligence/regime` | Piyasa rejimi | regime |
| GET | `/api/v1/intelligence/world-state` | World state | world_state |
| GET | `/api/v1/intelligence/signal` | Sinyal | signal_fusion |
| GET | `/api/v1/intelligence/events` | Event'ler | event_bus |

### 3.5 Decisions (6 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/decisions` | Tüm kararlar | decision_engine |
| GET | `/api/v1/decisions/{id}` | Karar detay | decision_engine |
| POST | `/api/v1/decisions` | Karar oluştur | decision_engine |
| GET | `/api/v1/decisions/{id}/audit` | Audit zinciri | audit_log |
| GET | `/api/v1/decisions/opportunities` | Fırsatlar | opportunity_engine |
| GET | `/api/v1/decisions/trade-plan` | İşlem planı | trade_planner |

### 3.6 Backtest (6 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| POST | `/api/v1/backtests` | Backtest başlat | backtest |
| GET | `/api/v1/backtests/{id}` | Sonuç | persistence |
| GET | `/api/v1/backtests` | Tüm sonuçlar | persistence |
| POST | `/api/v1/backtests/walk-forward` | WF başlat | walk_forward |
| GET | `/api/v1/backtests/{id}/trades` | Trade listesi | persistence |
| GET | `/api/v1/backtests/{id}/equity` | Equity curve | persistence |

### 3.7 Learning (8 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/learning/stats` | İstatistikler | learning |
| GET | `/api/v1/learning/predictions` | Tahminler | outcome_tracker |
| GET | `/api/v1/learning/outcomes` | Sonuçlar | outcome_tracker |
| GET | `/api/v1/learning/attribution` | Attribüsyon | attribution |
| GET | `/api/v1/learning/drift` | Drift tespiti | (yok) |
| GET | `/api/v1/learning/evolution` | Model evrimi | (yok) |
| GET | `/api/v1/learning/calibration` | Kalibrasyon | calibration |
| GET | `/api/v1/learning/performance` | Model performansı | ranking_model |

### 3.8 Models (6 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/models` | Tüm modeller | ranking_model |
| GET | `/api/v1/models/{id}` | Model detay | ranking_model |
| GET | `/api/v1/models/{id}/performance` | Performans | ranking_model |
| GET | `/api/v1/models/compare` | Karşılaştırma | model_comparator |
| GET | `/api/v1/models/ensemble` | Ensemble durumu | ensemble |
| POST | `/api/v1/models/{id}/promote` | Promote | (yok) |

### 3.9 Agents (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/agents` | Tüm agent'lar | agent_system |
| GET | `/api/v1/agents/{role}` | Agent detay | agent_system |
| GET | `/api/v1/agents/{role}/results` | Sonuçlar | agent_system |
| POST | `/api/v1/agents/{role}/run` | Çalıştır | agent_system |

### 3.10 Scanner (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/scanner/opportunities` | Fırsatlar | opportunity_engine |
| GET | `/api/v1/scanner/alpha` | Alpha sinyaller | alpha_engine |
| GET | `/api/v1/scanner/events` | Event'ler | event_scanner |
| POST | `/api/v1/scanner/scan` | Tarama başlat | tiered_scanner |

### 3.11 Macro (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/macro/indicators` | Makro göstergeler | macro |
| GET | `/api/v1/macro/calendar` | Makro takvim | calendar |
| GET | `/api/v1/macro/impact` | Makro etki | macro_sensitivity |
| GET | `/api/v1/macro/tcmb` | TCMB verisi | tcmb |

### 3.12 Factors (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/factors/{ticker}` | Faktör skorları | factor_engine |
| GET | `/api/v1/factors/ranking` | Sıralama | ranking |
| GET | `/api/v1/factors/performance` | Performans | performance |
| GET | `/api/v1/factors/anomalies` | Anomaliler | bist_anomalies |

### 3.13 Alternative Data (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/alternative/{ticker}` | Alternatif veri | alternative |
| GET | `/api/v1/alternative/sources` | Veri kaynakları | alternative |
| GET | `/api/v1/alternative/features` | Feature'lar | alternative |
| GET | `/api/v1/alternative/social` | Sosyal medya | social |

### 3.14 VIOP (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/viop/options` | Opsiyonlar | options_pricing |
| GET | `/api/v1/viop/greeks` | Greeks | greeks |
| POST | `/api/v1/viop/hedge` | Hedge önerisi | hedging |
| GET | `/api/v1/viop/strategies` | Stratejiler | strategies |

### 3.15 Event Study (4 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| POST | `/api/v1/event-study/analyze` | Event analiz | event_study |
| GET | `/api/v1/event-study/{ticker}` | Hisse event'leri | event_study |
| GET | `/api/v1/event-study/impact` | Etki skorları | impact |
| GET | `/api/v1/event-study/macro` | Makro event | macro_event |

### 3.16 System (8 endpoint)

| Method | Endpoint | Açıklama | Servis |
|--------|----------|----------|--------|
| GET | `/api/v1/system/health` | Sağlık | infrastructure |
| GET | `/api/v1/system/status` | Durum | orchestrator |
| GET | `/api/v1/system/metrics` | Metrikler | observability |
| GET | `/api/v1/system/audit` | Audit log | audit_log |
| GET | `/api/v1/system/config` | Konfigürasyon | config |
| GET | `/api/v1/system/logs` | Loglar | logging |
| POST | `/api/v1/system/restart` | Restart | infrastructure |
| GET | `/api/v1/system/services` | Servis durumu | orchestrator |

---

## 4. WebSocket Kanalları (Nihai)

| Kanal | İçerik | Frekans | Servis |
|-------|--------|---------|--------|
| `/ws/market` | Piyasa verisi | Tick bazlı | market_state |
| `/ws/portfolio` | Portföy güncellemeleri | İşlem bazlı | portfolio |
| `/ws/risk` | Risk alert'leri | Alert bazlı | risk |
| `/ws/signals` | Sinyal akışı | Event bazlı | signal_fusion |
| `/ws/decisions` | Karar akışı | Event bazlı | decision_engine |
| `/ws/agents` | Agent sonuçları | Event bazlı | agent_system |
| `/ws/learning` | Öğrenme güncellemeleri | Periyodik | learning |
| `/ws/system` | Sistem durumu | Periyodik | infrastructure |
| `/ws/events` | Event stream | Event bazlı | event_bus |
| `/ws/backtest` | Backtest ilerleme | Event bazlı | backtest |

---

## 5. Güvenlik Mimarisi (Nihai)

### 5.1 Authentication

```
┌─────────────────────────────────────────┐
│           AUTH FLOW                      │
│                                          │
│  Client → API Key / JWT Token → Gateway  │
│                                          │
│  JWT Payload:                            │
│  {                                       │
│    "sub": "user_id",                     │
│    "role": "ANALYST",                    │
│    "permissions": ["read", "analyze"],   │
│    "exp": 1234567890                     │
│  }                                       │
└─────────────────────────────────────────┘
```

### 5.2 Authorization (RBAC)

```
VIEWER    → GET (dashboard, raporlar)
ANALYST   → GET + POST (analiz çalıştır)
OPERATOR  → GET + POST + PUT (emir, rebalance)
ADMIN     → Tüm endpoint'ler
SYSTEM    → Servisler arası (API key)
```

### 5.3 Rate Limiting

| Endpoint Grubu | Limit | Pencere |
|---------------|-------|---------|
| Genel | 100 istek | 1 dakika |
| Analiz | 10 istek | 1 dakika |
| Backtest | 5 istek | 1 dakika |
| Scanner | 3 istek | 1 dakika |
| WebSocket | 100 mesaj | 1 saniye |

---

## 6. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| REST endpoint | 16 | 92 |
| WebSocket kanalı | 7 | 10 |
| Authentication | ⚠️ Basit | ✅ JWT + RBAC |
| Rate limiting | ❌ | ✅ |
| API versioning | ❌ | ✅ (v1) |
| OpenAPI/Swagger | ❌ | ✅ |
| CQRS pattern | ❌ | ✅ |
| Event sourcing | ⚠️ Kısmen | ✅ Tam |
| Cache layer | ❌ | ✅ Redis |
| Service discovery | ❌ | ✅ |
| Health checks | ⚠️ Basit | ✅ Detaylı |
| Metrics (Prometheus) | ⚠️ Kısmen | ✅ Tam |
| Distributed tracing | ❌ | ✅ |
| Audit logging | ⚠️ Kısmen | ✅ Tam |
