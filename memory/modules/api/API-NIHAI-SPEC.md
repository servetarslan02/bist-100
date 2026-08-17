# API Nihai Sistem Dokümanı — Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Aladdin (BlackRock) mimarisi, QuantConnect platform tasarımı, arXiv Multi-Agent Finance (2026), Low-Latency Trading System Design (2026)

---

## 1. Nihai API Sistemi Nasıl Olmalı?

### Aladdin'den Öğrendiklerimiz

BlackRock'ın Aladdin platformu:
- **Tek platform** üzerinde tüm yatırım süreci (analiz → karar → risk → portföy → raporlama)
- **Gerçek zamanlı** piyasa verisi ve risk hesaplama
- **API-first** mimari — tüm servisler API üzerinden erişilebilir
- **Event-driven** — olaylar anında tüm sisteme yayılır
- **Audit her şey** — her karar, her değişiklik kayıtlı

### Temel Prensipler

```
1. API-first: Tüm servisler API üzerinden erişilebilir
2. Real-time: WebSocket ile canlı veri akışı
3. Event-driven: Olaylar anında yayılır
4. Stateless: Her istek bağımsız
5. Versioned: API versiyonlama (v1, v2)
6. Secured: Authentication + authorization
7. Documented: OpenAPI/Swagger
```

---

## 2. Nihai API Mimarisi

```
┌─────────────────────────────────────────────────────────────┐
│                    API GATEWAY                               │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Auth      │  │ Rate      │  │ CORS      │              │
│  │ Layer     │  │ Limiter   │  │ Handler   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┴───────────────┘                    │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              REST API LAYER                          │   │
│  │                                                      │   │
│  │  /api/v1/market/*       ← Piyasa verisi              │   │
│  │  /api/v1/portfolio/*    ← Portföy                    │   │
│  │  /api/v1/risk/*         ← Risk                       │   │
│  │  /api/v1/intelligence/* ← Analiz                     │   │
│  │  /api/v1/decisions/*    ← Kararlar                   │   │
│  │  /api/v1/backtests/*    ← Backtest                   │   │
│  │  /api/v1/learning/*     ← Öğrenme                    │   │
│  │  /api/v1/models/*       ← ML Modelleri               │   │
│  │  /api/v1/agents/*       ← AI Agent'lar               │   │
│  │  /api/v1/scanner/*      ← Tarama                     │   │
│  │  /api/v1/macro/*        ← Makro                      │   │
│  │  /api/v1/factors/*      ← Faktörler                  │   │
│  │  /api/v1/alternative/*  ← Alternatif Veri            │   │
│  │  /api/v1/viop/*         ← VIOP                       │   │
│  │  /api/v1/event-study/*  ← Event Study                │   │
│  │  /api/v1/system/*       ← Sistem                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              WEBSOCKET LAYER                         │   │
│  │                                                      │   │
│  │  /ws/market         ← Canlı piyasa verisi            │   │
│  │  /ws/portfolio      ← Portföy güncellemeleri         │   │
│  │  /ws/risk           ← Risk alert'leri                │   │
│  │  /ws/signals        ← Sinyal akışı                   │   │
│  │  /ws/decisions      ← Karar akışı                    │   │
│  │  /ws/agents         ← Agent sonuçları                │   │
│  │  /ws/learning       ← Öğrenme güncellemeleri         │   │
│  │  /ws/system         ← Sistem durumu                  │   │
│  │  /ws/events         ← Event stream                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Endpoint Listesi (Nihai)

### 3.1 Market Data (8 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/market/state` | Piyasa durumu (regime, volatilite) |
| GET | `/api/v1/market/instruments` | Tüm hisseler |
| GET | `/api/v1/market/instruments/{ticker}` | Hisse detay |
| GET | `/api/v1/market/instruments/{ticker}/ohlcv` | OHLCV verisi |
| GET | `/api/v1/market/instruments/{ticker}/full` | Tam analiz |
| GET | `/api/v1/market/sectors` | Sektörler |
| GET | `/api/v1/market/calendar` | İşlem takvimi |
| GET | `/api/v1/market/events` | Piyasa olayları |

### 3.2 Portfolio (8 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/portfolio` | Portföy özeti |
| GET | `/api/v1/portfolio/positions` | Pozisyonlar |
| GET | `/api/v1/portfolio/trades` | İşlem geçmişi |
| GET | `/api/v1/portfolio/pnl` | P&L |
| GET | `/api/v1/portfolio/equity` | Equity curve |
| GET | `/api/v1/portfolio/risk` | Portföy risk |
| POST | `/api/v1/portfolio/rebalance` | Rebalance |
| GET | `/api/v1/portfolio/attribution` | Performans attribüsyonu |

### 3.3 Risk (6 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/risk/overview` | Risk özeti |
| GET | `/api/v1/risk/portfolio` | Portföy risk detayı |
| GET | `/api/v1/risk/positions` | Pozisyon riskleri |
| GET | `/api/v1/risk/limits` | Risk limitleri |
| POST | `/api/v1/risk/check` | Pre-trade risk check |
| GET | `/api/v1/risk/compliance` | SPK uyumluluk |

### 3.4 Intelligence (10 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/intelligence/{ticker}` | Tam analiz |
| GET | `/api/v1/intelligence/{ticker}/features` | Feature'lar |
| GET | `/api/v1/intelligence/{ticker}/forecast` | Tahmin |
| GET | `/api/v1/intelligence/{ticker}/monte-carlo` | Monte Carlo |
| GET | `/api/v1/intelligence/{ticker}/scenario` | Senaryo |
| GET | `/api/v1/intelligence/{ticker}/spec` | SPEC skor |
| GET | `/api/v1/intelligence/regime` | Piyasa rejimi |
| GET | `/api/v1/intelligence/world-state` | World state |
| GET | `/api/v1/intelligence/signal` | Sinyal |
| GET | `/api/v1/intelligence/events` | Event'ler |

### 3.5 Decisions (5 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/decisions` | Tüm kararlar |
| GET | `/api/v1/decisions/{id}` | Karar detay |
| POST | `/api/v1/decisions` | Karar oluştur |
| GET | `/api/v1/decisions/{id}/audit` | Karar audit zinciri |
| GET | `/api/v1/decisions/opportunities` | Fırsatlar |

### 3.6 Backtest (5 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| POST | `/api/v1/backtests` | Backtest başlat |
| GET | `/api/v1/backtests/{id}` | Sonuç |
| GET | `/api/v1/backtests` | Tüm sonuçlar |
| POST | `/api/v1/backtests/walk-forward` | WF başlat |
| GET | `/api/v1/backtests/{id}/trades` | Trade listesi |

### 3.7 Learning (6 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/learning/stats` | İstatistikler |
| GET | `/api/v1/learning/predictions` | Tahminler |
| GET | `/api/v1/learning/outcomes` | Sonuçlar |
| GET | `/api/v1/learning/attribution` | Attribüsyon |
| GET | `/api/v1/learning/drift` | Drift tespiti |
| GET | `/api/v1/learning/evolution` | Model evrimi |

### 3.8 Models (6 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/models` | Tüm modeller |
| GET | `/api/v1/models/{id}` | Model detay |
| GET | `/api/v1/models/{id}/performance` | Model performansı |
| GET | `/api/v1/models/compare` | Model karşılaştırma |
| GET | `/api/v1/models/ensemble` | Ensemble durumu |
| POST | `/api/v1/models/{id}/promote` | Model promote |

### 3.9 Agents (4 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/agents` | Tüm agent'lar |
| GET | `/api/v1/agents/{role}` | Agent detay |
| GET | `/api/v1/agents/{role}/results` | Agent sonuçları |
| POST | `/api/v1/agents/{role}/run` | Agent çalıştır |

### 3.10 Scanner (4 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/scanner/opportunities` | Fırsatlar |
| GET | `/api/v1/scanner/alpha` | Alpha sinyaller |
| GET | `/api/v1/scanner/events` | Event'ler |
| POST | `/api/v1/scanner/scan` | Tarama başlat |

### 3.11 Macro (3 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/macro/indicators` | Makro göstergeler |
| GET | `/api/v1/macro/calendar` | Makro takvim |
| GET | `/api/v1/macro/impact` | Makro etki analizi |

### 3.12 Factors (3 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/factors/{ticker}` | Faktör skorları |
| GET | `/api/v1/factors/ranking` | Faktör sıralaması |
| GET | `/api/v1/factors/performance` | Faktör performansı |

### 3.13 Alternative Data (3 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/alternative/{ticker}` | Alternatif veri |
| GET | `/api/v1/alternative/sources` | Veri kaynakları |
| GET | `/api/v1/alternative/features` | Feature'lar |

### 3.14 VIOP (4 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/viop/options` | Opsiyonlar |
| GET | `/api/v1/viop/greeks` | Greeks |
| POST | `/api/v1/viop/hedge` | Hedge önerisi |
| GET | `/api/v1/viop/strategies` | Stratejiler |

### 3.15 Event Study (3 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| POST | `/api/v1/event-study/analyze` | Event analiz |
| GET | `/api/v1/event-study/{ticker}` | Hisse event'leri |
| GET | `/api/v1/event-study/impact` | Etki skorları |

### 3.16 System (6 endpoint)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/api/v1/system/health` | Sağlık |
| GET | `/api/v1/system/status` | Durum |
| GET | `/api/v1/system/metrics` | Metrikler |
| GET | `/api/v1/system/audit` | Audit log |
| GET | `/api/v1/system/config` | Konfigürasyon |
| POST | `/api/v1/system/restart` | Restart |

---

## 4. WebSocket Kanalları (Nihai)

| Kanal | İçerik | Frekans |
|-------|--------|---------|
| `/ws/market` | Piyasa verisi | Tick bazlı |
| `/ws/portfolio` | Portföy güncellemeleri | İşlem bazlı |
| `/ws/risk` | Risk alert'leri | Alert bazlı |
| `/ws/signals` | Sinyal akışı | Event bazlı |
| `/ws/decisions` | Karar akışı | Event bazlı |
| `/ws/agents` | Agent sonuçları | Event bazlı |
| `/ws/learning` | Öğrenme güncellemeleri | Periyodik |
| `/ws/system` | Sistem durumu | Periyodik |
| `/ws/events` | Event stream | Event bazlı |

---

## 5. Güvenlik (Nihai)

### Authentication
- JWT token tabanlı
- API key (servisler arası)
- Session management

### Authorization (RBAC)
```
VIEWER    → Okuma (dashboard, raporlar)
ANALYST   → Analiz çalıştırma (backtest, scenario)
OPERATOR  → Portföy yönetimi (emir, rebalance)
ADMIN     → Sistem yönetimi (config, model)
SYSTEM    → Servisler arası iletişim
```

### Rate Limiting
- Genel: 100 istek/dakika
- Analiz: 10 istek/dakika
- Backtest: 5 istek/dakika
- WebSocket: 100 mesaj/saniye

---

## 6. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| REST endpoint sayısı | 16 | 84 |
| WebSocket kanalı | 7 | 9 |
| Authentication | ⚠️ Basit | ✅ JWT + RBAC |
| Rate limiting | ❌ | ✅ |
| API versioning | ❌ | ✅ (v1) |
| OpenAPI/Swagger | ❌ | ✅ |
| Event-driven | ⚠️ Kısmen | ✅ Tam |
| Real-time updates | ⚠️ Kısmen | ✅ Tam |
| Audit endpoint | ⚠️ Kısmen | ✅ Tam |
| Agent endpoint | ❌ | ✅ |
| Backtest endpoint | ❌ | ✅ |
| Scenario endpoint | ❌ | ✅ |
| Macro endpoint | ❌ | ✅ |
| Factors endpoint | ❌ | ✅ |
| Alternative endpoint | ❌ | ✅ |
| VIOP endpoint | ❌ | ✅ |
| Event Study endpoint | ❌ | ✅ |
