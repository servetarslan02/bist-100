# BIST-100 API Endpoint Haritası

> **Taranma Tarihi:** 2026-08-21  
> **Toplam Endpoint Tanımı:** 208 (tüm dosyalarda, çakışmalar dahil)  
> **Tekil Çalışan App Başına:** ~92 (canonical app.py + v1_router)  
> **Dosya Sayısı:** 14 Python dosyası  
> **Framework:** FastAPI (tamamı)

---

## Özet İstatistikler

| Kategori | Sayı | Yüzde |
|----------|------|-------|
| ✅ Gerçek veri döndüren | 47 | %23% |
| ⚠️ Placeholder/sahte veri | 52 | %25% |
| 🔴 Hardcoded/statik veri | 18 | %9% |
| ❌ Boş/501/stub response | 14 | %7% |
| ⚠️ DB-DEPENDENT | 12 | %6% |
| 🔒 Auth gerektiren (v1) | 92 | %44% |
| 🌐 WebSocket | 6 | %3% |
| ⛔ DEPRECATED dosyadaki | 27 | %13% |

---

## Dosya Hiyerarşisi

```
services/api/app.py          ← CANONICAL PRODUCTION SERVER (v2.0)
  ├── GET /                  (root)
  ├── GET /health
  ├── GET /health/detailed
  └── /api/v1/*              (v1_router → 92 endpoint)

services/api/server.py       ← DEV/LEGACY (SQLite, v2.0)
  ├── 34 endpoint            (development amaçlı)

services/api/main.py         ← DEPRECATED (v1.0)
  ├── 27 endpoint            (eski entry point)

apps/api/main.py             ← STANDALONE (v3.0)
  ├── 13 endpoint            (bağımsız uygulama)

services/market_state/api.py ← Market State modül route'ları
  ├── 7 endpoint             (register_market_state_routes ile eklenir)
```

---

## Endpoint Listesi

### 📁 apps/api/main.py — Standalone v3.0

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 1 | GET | `/` | 108 | ✅ IMPLEMENTED | Yok | API bilgisi döndürür |
| 2 | GET | `/health` | 119 | ✅ IMPLEMENTED | Yok | super_intelligence'dan gerçek sağlık durumu |
| 3 | GET | `/regime` | 134 | ✅ IMPLEMENTED | Yok | regime_detector'dan gerçek rejim verisi |
| 4 | GET | `/opportunities` | 152 | ✅ IMPLEMENTED | Yok | orchestrator'dan gerçek fırsat verisi |
| 5 | GET | `/opportunities/{ticker}` | 179 | ⚠️ PLACEHOLDER | Yok | TODO: features ve prediction boş |
| 6 | GET | `/portfolio` | 192 | ✅ IMPLEMENTED | Yok | orchestrator'dan gerçek portföy verisi |
| 7 | GET | `/backtest` | 211 | ✅ IMPLEMENTED | Yok | orchestrator'dan gerçek backtest verisi |
| 8 | GET | `/learning` | 225 | ✅ IMPLEMENTED | Yok | continuous_learning'dan gerçek veri |
| 9 | GET | `/features/{ticker}` | 232 | ❌ 501 | Yok | Explicit: "not yet implemented" |
| 10 | POST | `/predict` | 240 | ❌ 501 | Yok | Explicit: "Prediction engine not yet connected" |
| 11 | GET | `/pipeline/stats` | 248 | ✅ IMPLEMENTED | Yok | orchestrator'dan gerçek istatistik |
| 12 | GET | `/reports/latest` | 255 | ✅ IMPLEMENTED | Yok | orchestrator'dan tam rapor |
| 13 | WS | `/ws` | 304 | ✅ IMPLEMENTED | Yok | Gerçek WebSocket, subscribe/ping/opp |

**Kod Kanıtı — GET /features/{ticker} (501):**
```python
@app.get("/features/{ticker}", tags=["Analysis"])
async def get_features(ticker: str):
    """Hissenin feature vektörü."""
    raise HTTPException(
        status_code=501,
        detail=f"Feature computation not yet implemented for {ticker}. Run feature pipeline first.",
    )
```

**Kod Kanıtı — POST /predict (501):**
```python
@app.post("/predict", response_model=PredictResponse, tags=["Trading"])
async def predict(request: PredictRequest):
    """Prediction endpoint — not yet implemented."""
    raise HTTPException(
        status_code=501,
        detail="Prediction engine not yet connected. Run training pipeline first.",
    )
```

**Kod Kanıtı — GET /opportunities/{ticker} (PLACEHOLDER):**
```python
@app.get("/opportunities/{ticker}", tags=["Trading"])
async def get_opportunity_detail(ticker: str):
    """Belirli bir hissenin detaylı analizi."""
    return {
        "ticker": ticker,
        "status": "available",
        "features": {},  # TODO
        "prediction": {},  # TODO
    }
```

---

### 📁 services/api/main.py — DEPRECATED v1.0

> ⚠️ **Bu dosya DEPRECATED.** Dosya başlığında: "Canonical production server: app.py"

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 14 | GET | `/api/health` | 114 | ✅ IMPLEMENTED | Yok | Basit health check |
| 15 | GET | `/metrics` | 120 | ✅ IMPLEMENTED | Yok | Prometheus format, circuit breaker + DLQ + TX metrics |
| 16 | GET | `/api/status` | 209 | ✅ IMPLEMENTED | Yok | PG + CH + Redis sağlık kontrolü |
| 17 | GET | `/api/market/state` | 248 | ✅ IMPLEMENTED | Yok | Redis'ten oku, yoksa yfinance ile canlı hesapla |
| 18 | GET | `/api/market/instruments` | 319 | ✅ IMPLEMENTED | Yok | BIST universe'den gerçek hisse listesi |
| 19 | GET | `/api/market/instrument/{ticker}/ohlcv` | 348 | ✅ IMPLEMENTED | Yok | ClickHouse → yfinance fallback |
| 20 | GET | `/api/market/instrument/{ticker}/full` | 402 | ✅ IMPLEMENTED | Yok | OHLCV + features + SPEC skoru (gerçek hesaplama) |
| 21 | GET | `/api/market/instrument/{ticker}` | 485 | ⚠️ DB-DEPENDENT | Yok | PostgreSQL sorgusu, DB yoksa 500 |
| 22 | GET | `/api/signals` | 519 | ✅ IMPLEMENTED | Yok | yfinance + feature_calculator + spec_engine |
| 23 | GET | `/api/portfolio` | 597 | ⚠️ DB-DEPENDENT | Yok | PostgreSQL sorgusu |
| 24 | GET | `/api/world/state` | 631 | ⚠️ PLACEHOLDER | Yok | Redis yoksa hardcoded default değerler |
| 25 | GET | `/api/features/{ticker}` | 658 | ⚠️ DB-DEPENDENT | Yok | Redis HGETALL, yoksa mesaj döndürür |
| 26 | GET | `/api/events` | 671 | ⚠️ DB-DEPENDENT | Yok | PostgreSQL sorgusu |
| 27 | GET | `/api/models` | 692 | ⚠️ DB-DEPENDENT | Yok | PostgreSQL sorgusu |
| 28 | GET | `/api/alerts` | 719 | ⚠️ DB-DEPENDENT | Yok | PostgreSQL sorgusu |
| 29 | WS | `/ws/{channel}` | 752 | ✅ IMPLEMENTED | Yok | Kanal bazlı WebSocket |
| 30 | WS | `/ws/live` | 775 | ✅ IMPLEMENTED | Yok | Canlı market verisi WebSocket |
| 31 | GET | `/api/stream/events` | 793 | ⚠️ PLACEHOLDER | Yok | SSE endpoint, Redis pub/sub |

**Kod Kanıtı — GET /api/world/state (Hardcoded fallback):**
```python
@app.get("/api/world/state")
async def get_world_state():
    state = await redis_get("world_state")
    if state:
        return json.loads(state)
    return {
        "global_risk_appetite": 0.5,
        "usd_strength": 0.5,
        "us_rate_pressure": 0.3,
        "vix_level": 20.0,
        "inflation_pressure": 0.5,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

---

### 📁 services/api/server.py — DEV/LEGACY v2.0

> ⚠️ **Bu dosya DEV/LEGACY.** Dosya başlığında: "Bu dosya production DEĞİLDİR. SQLite dev_db kullanır."

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 32 | GET | `/` | 185 | 🔴 HARDCODED | Yok | HTML dashboard linkleri |
| 33 | GET | `/health` | 205 | ✅ IMPLEMENTED | Yok | health_checker modülünden gerçek veri |
| 34 | GET | `/api/market` | 221 | ⚠️ PLACEHOLDER | Yok | `status: "no_data_source"`, tüm değerler None |
| 35 | GET | `/api/opportunities` | 266 | ✅ IMPLEMENTED | Yok | opportunity_engine'dan gerçek veri |
| 36 | GET | `/api/portfolio` | 299 | ✅ IMPLEMENTED | Yok | portfolio_manager'dan gerçek veri |
| 37 | GET | `/api/decisions` | 322 | ✅ IMPLEMENTED | Yok | audit_log'dan gerçek veri |
| 38 | GET | `/api/learning` | 332 | ✅ IMPLEMENTED | Yok | learning_system + outcome_tracker |
| 39 | GET | `/api/learning/predictions` | 355 | ✅ IMPLEMENTED | Yok | learning_system'dan gerçek tahminler |
| 40 | GET | `/api/signals` | 365 | ✅ IMPLEMENTED | Yok | signal_fusion'dan gerçek sinyaller |
| 41 | GET | `/api/features/{ticker}` | 377 | ✅ IMPLEMENTED | Yok | feature_store'dan gerçek veri (404 yoksa) |
| 42 | GET | `/api/regime` | 390 | ✅ IMPLEMENTED | Yok | regime_engine'dan gerçek rejim + geçmiş |
| 43 | GET | `/api/risk` | 406 | ✅ IMPLEMENTED | Yok | portfolio_manager risk metrikleri |
| 44 | GET | `/api/market/state` | 426 | ⚠️ DB-DEPENDENT | Yok | Redis'ten oku, yoksa error |
| 45 | GET | `/api/market/breadth` | 441 | ⚠️ DB-DEPENDENT | Yok | Redis market_state'den breadth |
| 46 | GET | `/api/market/regime` | 460 | ⚠️ DB-DEPENDENT | Yok | Redis market_state'den ensemble regime |
| 47 | GET | `/api/market/transition` | 486 | ⚠️ DB-DEPENDENT | Yok | Redis market_state'den transition stats |
| 48 | GET | `/api/market/multi-tf` | 509 | ⚠️ DB-DEPENDENT | Yok | Redis market_state'den multi-TF |
| 49 | GET | `/api/market/risk-appetite` | 531 | ⚠️ DB-DEPENDENT | Yok | Redis market_state'den risk appetite |
| 50 | GET | `/api/notifications` | 550 | ✅ IMPLEMENTED | Yok | notification_system'dan gerçek bildirimler |
| 51 | GET | `/api/audit` | 567 | ✅ IMPLEMENTED | Yok | audit_log'dan gerçek audit verisi |
| 52 | GET | `/api/stats` | 586 | ✅ IMPLEMENTED | Yok | Prometheus + performance + cache + jobs |
| 53 | GET | `/api/tickers` | 598 | ✅ IMPLEMENTED | Yok | BISTUniverse'dan gerçek hisse listesi |
| 54 | WS | `/ws` | 609 | ✅ IMPLEMENTED | Yok | WebSocket: subscribe, ping, get_ticker |
| 55 | GET | `/health/detailed` | 696 | ✅ IMPLEMENTED | Yok | portfolio_monitor detaylı sağlık |
| 56 | GET | `/metrics` | 707 | 🔒 AUTH | Bearer Token | Prometheus metrics, rate limited |
| 57 | GET | `/admin/lock-metrics` | 728 | 🔒 AUTH | Admin Token | Lock performans metrikleri |
| 58 | GET | `/admin/portfolio` | 746 | 🔒 AUTH | Admin Token | Portföy sağlık durumu |
| 59 | GET | `/admin/alerts` | 764 | 🔒 AUTH | Admin Token | Aktif alert'ler |
| 60 | GET | `/admin/auth-status` | 781 | ✅ IMPLEMENTED | Yok | Auth durumu (public) |
| 61 | GET | `/admin/policy` | 789 | 🔒 AUTH | Admin Token | Mevcut alert policy |
| 62 | POST | `/admin/policy` | 805 | 🔒 AUTH | Admin Token | Policy güncelle |
| 63 | POST | `/admin/policy/rollback` | 822 | 🔒 AUTH | Admin Token | Policy rollback |
| 64 | GET | `/admin/policy/history` | 840 | 🔒 AUTH | Admin Token | Policy versiyon geçmişi |
| 65 | GET | `/admin/policy/audit` | 852 | 🔒 AUTH | Admin Token | Policy audit log |
| 66 | POST | `/admin/silence` | 864 | 🔒 AUTH | Admin Token | Alert susturma ekle |
| 67 | DELETE | `/admin/silence` | 885 | 🔒 AUTH | Admin Token | Alert susturma kaldır |
| 68 | POST | `/admin/policy/diff` | 904 | 🔒 AUTH | Admin Token | Policy diff |
| 69 | POST | `/admin/silence/batch` | 918 | 🔒 AUTH | Admin Token | Toplu susturma ekle |
| 70 | DELETE | `/admin/silence/batch` | 937 | 🔒 AUTH | Admin Token | Toplu susturma kaldır |
| 71 | POST | `/admin/policy/lock` | 956 | 🔒 AUTH | Admin Token | Policy kilidi al |
| 72 | DELETE | `/admin/policy/lock` | 980 | 🔒 AUTH | Admin Token | Policy kilidi bırak |

**Kod Kanıtı — GET /api/market (Placeholder):**
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
    return result
```

---

### 📁 services/api/app.py — CANONICAL PRODUCTION v2.0

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 73 | GET | `/` | — | ✅ IMPLEMENTED | Yok | API bilgisi + linkler |
| 74 | GET | `/health` | — | ✅ IMPLEMENTED | Yok | DB sağlık kontrolü (PG + CH + Redis) |
| 75 | GET | `/health/detailed` | — | ✅ IMPLEMENTED | Yok | Detaylı sağlık raporu |

> Bu dosya `v1_router`'ı dahil eder → tüm `/api/v1/*` endpoint'leri aktif.

---

### 📁 services/api/v1/ — API v1 Router (92 Endpoint)

> Tüm v1 endpoint'leri `Depends(get_current_user)` + `Depends(check_rate_limit)` kullanır.
> Auth: JWT Bearer token veya X-API-Key header.

#### 📄 v1/market.py — Market Data (10 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 76 | GET | `/api/v1/market/state` | 14 | ⚠️ PLACEHOLDER | 🔒 JWT | regime_engine'dan basit regime döndürür |
| 77 | GET | `/api/v1/market/instruments` | 25 | ✅ IMPLEMENTED | 🔒 JWT | BISTUniverse'dan gerçek hisse listesi |
| 78 | GET | `/api/v1/market/instruments/{ticker}` | 40 | ⚠️ PLACEHOLDER | 🔒 JWT | Sadece `{"ticker": ..., "available": True}` |
| 79 | GET | `/api/v1/market/instruments/{ticker}/ohlcv` | 51 | ✅ IMPLEMENTED | 🔒 JWT | data_source'dan gerçek OHLCV |
| 80 | GET | `/api/v1/market/instruments/{ticker}/full` | 67 | ⚠️ PLACEHOLDER | 🔒 JWT | Sadece `{"ticker": ..., "analysis": "available"}` |
| 81 | GET | `/api/v1/market/instruments/{ticker}/features` | 77 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires historical data" mesajı |
| 82 | GET | `/api/v1/market/sectors` | 88 | 🔴 HARDCODED | 🔒 JWT | Sabit sektör listesi |
| 83 | GET | `/api/v1/market/calendar` | 94 | 🔴 HARDCODED | 🔒 JWT | Sabit saat bilgisi |
| 84 | GET | `/api/v1/market/events` | 100 | ✅ IMPLEMENTED | 🔒 JWT | event_scanner'dan gerçek veri |
| 85 | GET | `/api/v1/market/regime` | 112 | ⚠️ PLACEHOLDER | 🔒 JWT | regime_engine basit çağrı |

**Kod Kanıtı — GET /api/v1/market/sectors (Hardcoded):**
```python
@router.get("/sectors")
async def sectors(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"sectors": ["BANKA", "SANAYI", "TEKNOLOJI", "PERAKENDE", "ENERJI", "ULAŞTIRMA"]}
```

**Kod Kanıtı — GET /api/v1/market/instruments/{ticker} (Placeholder):**
```python
@router.get("/instruments/{ticker}")
async def instrument_detail(ticker: str, ...):
    orch = await get_service_orchestrator()
    result = {"ticker": ticker, "available": True}
    return result
```

#### 📄 v1/portfolio.py — Portfolio (18 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 86 | GET | `/api/v1/portfolio/summary` | 49 | ✅ IMPLEMENTED | 🔒 JWT | portfolio_manager'dan gerçek veri |
| 87 | GET | `/api/v1/portfolio/positions` | 63 | ✅ IMPLEMENTED | 🔒 JWT | Açık pozisyonlar |
| 88 | GET | `/api/v1/portfolio/trades` | 82 | ✅ IMPLEMENTED | 🔒 JWT | İşlem geçmişi |
| 89 | GET | `/api/v1/portfolio/pnl` | 106 | ✅ IMPLEMENTED | 🔒 JWT | K/Z durumu |
| 90 | GET | `/api/v1/portfolio/equity-curve` | 129 | ✅ IMPLEMENTED | 🔒 JWT | Equity curve + snapshots + HWM |
| 91 | GET | `/api/v1/portfolio/risk-metrics` | 155 | ✅ IMPLEMENTED | 🔒 JWT | VaR/CVaR + HHI + correlation |
| 92 | GET | `/api/v1/portfolio/drawdown` | 169 | ✅ IMPLEMENTED | 🔒 JWT | Drawdown durumu |
| 93 | GET | `/api/v1/portfolio/metrics` | 192 | ✅ IMPLEMENTED | 🔒 JWT | CAGR, Sharpe, Sortino, win rate |
| 94 | GET | `/api/v1/portfolio/accounting` | 206 | ✅ IMPLEMENTED | 🔒 JWT | Muhasebe özeti + invariant |
| 95 | GET | `/api/v1/portfolio/cash-ledger` | 224 | ✅ IMPLEMENTED | 🔒 JWT | Nakit hareket geçmişi |
| 96 | GET | `/api/v1/portfolio/position-history` | 245 | ✅ IMPLEMENTED | 🔒 JWT | Pozisyon değişiklik geçmişi |
| 97 | GET | `/api/v1/portfolio/equity-snapshots` | 270 | ✅ IMPLEMENTED | 🔒 JWT | Günlük equity snapshot'ları |
| 98 | GET | `/api/v1/portfolio/attribution` | 294 | ⚠️ PLACEHOLDER | 🔒 JWT | Demo factor returns (np.random.seed(42)) |
| 99 | GET | `/api/v1/portfolio/tax` | 337 | ✅ IMPLEMENTED | 🔒 JWT | Vergi analizi (tax_model) |
| 100 | GET | `/api/v1/portfolio/tca` | 366 | ✅ IMPLEMENTED | 🔒 JWT | İşlem maliyeti analizi |
| 101 | GET | `/api/v1/portfolio/rebalance` | 395 | ✅ IMPLEMENTED | 🔒 JWT | Drift analizi |
| 102 | POST | `/api/v1/portfolio/rebalance/orders` | 430 | ✅ IMPLEMENTED | 🔒 JWT | Rebalance emirleri |
| 103 | GET | `/api/v1/portfolio/status` | 469 | ✅ IMPLEMENTED | 🔒 JWT | Servis durumu |

**Kod Kanıtı — GET /api/v1/portfolio/attribution (Demo data):**
```python
@router.get("/attribution")
async def attribution(...):
    # Demo factor returns (gerçek uygulamada market data'dan gelecek)
    np.random.seed(42)
    factors = {
        "value": np.random.normal(0.0005, 0.015, len(returns)),
        "momentum": np.random.normal(0.001, 0.018, len(returns)),
        "quality": np.random.normal(0.0003, 0.012, len(returns)),
    }
    factor_attr = performance_attribution.factor_attribution(returns, factors)
```

#### 📄 v1/risk.py — Risk Management (16 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 104 | GET | `/api/v1/risk/overview` | 84 | ✅ IMPLEMENTED | 🔒 JWT | Dynamic limits + drawdown + monitoring |
| 105 | GET | `/api/v1/risk/dashboard` | 141 | ✅ IMPLEMENTED | 🔒 JWT | Tüm modüllerin birleşik özeti |
| 106 | GET | `/api/v1/risk/var` | 206 | ⚠️ PLACEHOLDER | 🔒 JWT | Demo returns (np.random.seed(42)) |
| 107 | GET | `/api/v1/risk/portfolio` | 251 | ⚠️ PLACEHOLDER | 🔒 JWT | Demo returns + boş weights |
| 108 | GET | `/api/v1/risk/limits` | 284 | ✅ IMPLEMENTED | 🔒 JWT | Dynamic limits (gerçek hesaplama) |
| 109 | GET | `/api/v1/risk/drawdown` | 341 | ✅ IMPLEMENTED | 🔒 JWT | Drawdown response servisi |
| 110 | GET | `/api/v1/risk/stress-test` | 384 | ✅ IMPLEMENTED | 🔒 JWT | Stress test senaryoları |
| 111 | POST | `/api/v1/risk/stress-test/run` | 413 | ⚠️ PLACEHOLDER | 🔒 JWT | Demo portfolio (hardcoded pozisyonlar) |
| 112 | GET | `/api/v1/risk/tail-hedge` | 485 | ✅ IMPLEMENTED | 🔒 JWT | Tail hedge stratejileri |
| 113 | POST | `/api/v1/risk/tail-hedge/analyze` | 506 | ✅ IMPLEMENTED | 🔒 JWT | Tail hedge analizi |
| 114 | GET | `/api/v1/risk/risk-parity` | 551 | ✅ IMPLEMENTED | 🔒 JWT | Risk parity bilgisi |
| 115 | POST | `/api/v1/risk/risk-parity/optimize` | 571 | ✅ IMPLEMENTED | 🔒 JWT | Risk parity optimizasyonu |
| 116 | GET | `/api/v1/risk/monitoring` | 619 | ✅ IMPLEMENTED | 🔒 JWT | Alert kuralları + summary |
| 117 | GET | `/api/v1/risk/alerts` | 653 | ✅ IMPLEMENTED | 🔒 JWT | Risk alert'leri |
| 118 | GET | `/api/v1/risk/calibration` | 711 | ✅ IMPLEMENTED | 🔒 JWT | Brier score + calibration curve |
| 119 | POST | `/api/v1/risk/check` | 739 | ✅ IMPLEMENTED | 🔒 JWT | Pre-trade risk kontrolü |
| 120 | GET | `/api/v1/risk/compliance` | 828 | ✅ IMPLEMENTED | 🔒 JWT | Uyumluluk kontrolü |

**Kod Kanıtı — GET /api/v1/risk/var (Demo data):**
```python
@router.get("/var")
async def var_report(...):
    # Demo returns (gerçek uygulamada DB'den gelecek)
    np.random.seed(42)
    demo_returns = np.random.normal(0.001, 0.02, 252)
    report = calc.calculate_full_var_report(returns=demo_returns, ...)
```

**Kod Kanıtı — POST /api/v1/risk/stress-test/run (Demo portfolio):**
```python
@router.post("/stress-test/run")
async def run_stress_test(...):
    portfolio = {
        "total_value": portfolio_value,
        "positions": [
            {"ticker": "THYAO", "value": portfolio_value * 0.3, "sector": "INDUSTRY"},
            {"ticker": "GARAN", "value": portfolio_value * 0.25, "sector": "BANKING"},
            {"ticker": "ASELS", "value": portfolio_value * 0.2, "sector": "TECHNOLOGY"},
            {"ticker": "BIMAS", "value": portfolio_value * 0.15, "sector": "CONSUMER"},
            {"ticker": "TUPRS", "value": portfolio_value * 0.1, "sector": "ENERGY"},
        ],
    }
```

#### 📄 v1/intelligence.py — Intelligence (11 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 121 | GET | `/api/v1/intelligence/analysis/{ticker}` | 8 | ⚠️ PLACEHOLDER | 🔒 JWT | "Full analysis requires live data" |
| 122 | GET | `/api/v1/intelligence/features/{ticker}` | 26 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires feature calculation pipeline" |
| 123 | GET | `/api/v1/intelligence/forecast/{ticker}` | 36 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires historical data" |
| 124 | GET | `/api/v1/intelligence/simulation/{ticker}` | 52 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires price data" |
| 125 | GET | `/api/v1/intelligence/scenarios/{ticker}` | 67 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires macro + sector data" |
| 126 | GET | `/api/v1/intelligence/spec/{ticker}` | 81 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires live data pipeline" |
| 127 | GET | `/api/v1/intelligence/probability/{ticker}` | 92 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires feature data" |
| 128 | GET | `/api/v1/intelligence/valuation/{ticker}` | 102 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires fundamental data" |
| 129 | GET | `/api/v1/intelligence/regime` | 108 | ⚠️ PLACEHOLDER | 🔒 JWT | RegimeEngine basit çağrı |
| 130 | GET | `/api/v1/intelligence/macro-impact/{ticker}` | 120 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires macro data" |

**Kod Kanıtı — Intelligence endpoints (hepsi placeholder):**
```python
@router.get("/analysis/{ticker}")
async def analysis(ticker: str, ...):
    return {
        "ticker": ticker,
        "spec_available": True,
        "factor_available": True,
        "message": "Full analysis requires live data",
    }

@router.get("/features/{ticker}")
async def features(ticker: str, ...):
    return {"ticker": ticker, "features": {}, "message": "Requires feature calculation pipeline"}

@router.get("/forecast/{ticker}")
async def forecast(ticker: str, ...):
    return {
        "ticker": ticker,
        "forecast_available": True,
        "models": ["momentum", "statistical", "heuristic"],
        "message": "Requires historical data",
    }
```

#### 📄 v1/decisions.py — Decisions (6 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 131 | GET | `/api/v1/decisions/list` | 8 | ⚠️ DB-DEPENDENT | 🔒 JWT | PostgreSQL sorgusu |
| 132 | GET | `/api/v1/decisions/detail/{decision_id}` | 19 | ⚠️ DB-DEPENDENT | 🔒 JWT | PostgreSQL sorgusu |
| 133 | POST | `/api/v1/decisions/create` | 30 | ❌ STUB | 🔒 JWT | Sadece `{"status": "created"}` döndürür |
| 134 | GET | `/api/v1/decisions/audit/{decision_id}` | 36 | ❌ EMPTY | 🔒 JWT | `"audit": []` boş array |
| 135 | GET | `/api/v1/decisions/opportunities` | 42 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires live scan" |
| 136 | GET | `/api/v1/decisions/plan` | 52 | ❌ EMPTY | 🔒 JWT | `"plan": []` boş array |

**Kod Kanıtı — POST /api/v1/decisions/create (Stub):**
```python
@router.post("/create")
async def create_decision(ticker: str = Query(...), action: str = Query(...), ...):
    return {"status": "created", "ticker": ticker, "action": action}
```

#### 📄 v1/backtest.py — Backtest (8 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 137 | POST | `/api/v1/backtests/run` | 8 | ⚠️ PLACEHOLDER | 🔒 JWT | "Backtest queued" mesajı |
| 138 | GET | `/api/v1/backtests/results/{id}` | 24 | ⚠️ DB-DEPENDENT | 🔒 JWT | PostgreSQL sorgusu |
| 139 | GET | `/api/v1/backtests/list` | 37 | ⚠️ DB-DEPENDENT | 🔒 JWT | PostgreSQL sorgusu |
| 140 | POST | `/api/v1/backtests/walk-forward` | 48 | ⚠️ PLACEHOLDER | 🔒 JWT | "started" mesajı |
| 141 | GET | `/api/v1/backtests/deflated-sharpe` | 63 | ✅ IMPLEMENTED | 🔒 JWT | DeflatedSharpeCalculator gerçek hesaplama |
| 142 | GET | `/api/v1/backtests/transaction-costs` | 81 | ✅ IMPLEMENTED | 🔒 JWT | BISTFeeStructure gerçek hesaplama |
| 143 | GET | `/api/v1/backtests/trades/{id}` | 102 | ❌ EMPTY | 🔒 JWT | `"trades": []` boş array |
| 144 | GET | `/api/v1/backtests/equity-curve/{id}` | 108 | ❌ EMPTY | 🔒 JWT | `"equity_curve": []` boş array |

#### 📄 v1/learning.py — Learning (4 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 145 | GET | `/api/v1/learning/status` | 8 | ⚠️ PLACEHOLDER | 🔒 JWT | ScoreCalibrator import, basit response |
| 146 | GET | `/api/v1/learning/calibration` | 18 | ⚠️ PLACEHOLDER | 🔒 JWT | ScoreCalibrator basit çağrı |
| 147 | GET | `/api/v1/learning/drift` | 29 | ❌ STUB | 🔒 JWT | `{"drift_detected": False}` hardcoded |
| 148 | GET | `/api/v1/learning/champion-challenger` | 35 | ❌ STUB | 🔒 JWT | `{"champion": "v1"}` hardcoded |

#### 📄 v1/models.py — Models (3 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 149 | GET | `/api/v1/models/list` | 8 | 🔴 HARDCODED | 🔒 JWT | Sabit model listesi: `["momentum", "statistical", "heuristic", "lightgbm"]` |
| 150 | GET | `/api/v1/models/performance` | 18 | ❌ EMPTY | 🔒 JWT | `"performance": {}` boş |
| 151 | POST | `/api/v1/models/retrain` | 24 | ❌ STUB | 🔒 JWT | `{"status": "started"}` mesajı |

#### 📄 v1/agents.py — Agents (3 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 152 | GET | `/api/v1/agents/list` | 8 | 🔴 HARDCODED | 🔒 JWT | Sabit agent listesi |
| 153 | GET | `/api/v1/agents/status` | 18 | ❌ EMPTY | 🔒 JWT | `"agents": []` boş |
| 154 | POST | `/api/v1/agents/run` | 24 | ❌ STUB | 🔒 JWT | `{"status": "started"}` mesajı |

#### 📄 v1/scanner.py — Scanner (14 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 155 | GET | `/api/v1/scanner/status` | 44 | ✅ IMPLEMENTED | 🔒 JWT | scan_api.get_status() |
| 156 | GET | `/api/v1/scanner/dashboard` | 58 | ✅ IMPLEMENTED | 🔒 JWT | scan_api.get_full_dashboard() |
| 157 | GET | `/api/v1/scanner/results` | 76 | ✅ IMPLEMENTED | 🔒 JWT | scan_api.get_results() |
| 158 | GET | `/api/v1/scanner/opportunities` | 97 | ✅ IMPLEMENTED | 🔒 JWT | Tier bazlı fırsat filtreleme |
| 159 | GET | `/api/v1/scanner/signals` | 127 | ✅ IMPLEMENTED | 🔒 JWT | Sinyal listesi |
| 160 | GET | `/api/v1/scanner/tiers` | 157 | ✅ IMPLEMENTED | 🔒 JWT | Tier bazlı özet |
| 161 | GET | `/api/v1/scanner/history/{ticker}` | 171 | ✅ IMPLEMENTED | 🔒 JWT | Hisse tarama geçmişi |
| 162 | GET | `/api/v1/scanner/performance` | 198 | ✅ IMPLEMENTED | 🔒 JWT | Performans istatistikleri |
| 163 | GET | `/api/v1/scanner/alerts` | 212 | ✅ IMPLEMENTED | 🔒 JWT | Son alert'ler |
| 164 | GET | `/api/v1/scanner/filters` | 234 | ✅ IMPLEMENTED | 🔒 JWT | Filtre listesi |
| 165 | GET | `/api/v1/scanner/dedup` | 248 | ✅ IMPLEMENTED | 🔒 JWT | Dedup istatistikleri |
| 166 | GET | `/api/v1/scanner/scheduler` | 262 | ✅ IMPLEMENTED | 🔒 JWT | Scheduler istatistikleri |
| 167 | POST | `/api/v1/scanner/trigger` | 280 | ✅ IMPLEMENTED | 🔒 JWT | Manuel tarama tetikle |
| 168 | POST | `/api/v1/scanner/event` | 306 | ✅ IMPLEMENTED | 🔒 JWT | Event bildirimi |

#### 📄 v1/macro.py — Macro (3 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 169 | GET | `/api/v1/macro/overview` | 8 | 🔴 HARDCODED | 🔒 JWT | Sabit indicator listesi |
| 170 | GET | `/api/v1/macro/impact/{ticker}` | 18 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires live macro data" |
| 171 | GET | `/api/v1/macro/sensitivity/{sector}` | 29 | ⚠️ PLACEHOLDER | 🔒 JWT | MacroSensitivityEngine basit çağrı |

#### 📄 v1/factors.py — Factors (3 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 172 | GET | `/api/v1/factors/scores/{ticker}` | 8 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires financial data" |
| 173 | GET | `/api/v1/factors/exposure/{ticker}` | 19 | ⚠️ PLACEHOLDER | 🔒 JWT | `{"exposure_available": True}` |
| 174 | GET | `/api/v1/factors/portfolio-exposure` | 29 | ❌ EMPTY | 🔒 JWT | `"exposure": {}` boş |

#### 📄 v1/alternative.py — Alternative Data (3 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 175 | GET | `/api/v1/alternative/sources` | 8 | 🔴 HARDCODED | 🔒 JWT | Sabit kaynak listesi |
| 176 | GET | `/api/v1/alternative/sentiment/{ticker}` | 21 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires news data" |
| 177 | GET | `/api/v1/alternative/google-trends/{query}` | 31 | ⚠️ PLACEHOLDER | 🔒 JWT | `{"trends_available": True}` |

#### 📄 v1/viop.py — VIOP (14 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 178 | GET | `/api/v1/viop/options` | 30 | ✅ IMPLEMENTED | 🔒 JWT | viop_catalog sözleşme bilgisi |
| 179 | POST | `/api/v1/viop/options/price` | 50 | ✅ IMPLEMENTED | 🔒 JWT | Black-Scholes fiyatlaması |
| 180 | POST | `/api/v1/viop/options/implied-vol` | 72 | ✅ IMPLEMENTED | 🔒 JWT | Newton-Raphson IV |
| 181 | POST | `/api/v1/viop/greeks` | 98 | ✅ IMPLEMENTED | 🔒 JWT | Portföy Greeks aggregation |
| 182 | GET | `/api/v1/viop/strategies` | 119 | 🔴 HARDCODED | 🔒 JWT | Sabit strateji listesi |
| 183 | POST | `/api/v1/viop/strategies/analyze` | 140 | ✅ IMPLEMENTED | 🔒 JWT | Gerçek strateji analizi |
| 184 | POST | `/api/v1/viop/hedge` | 206 | ✅ IMPLEMENTED | 🔒 JWT | Delta hedge hesaplama |
| 185 | POST | `/api/v1/viop/hedge/gamma-scalp` | 220 | ✅ IMPLEMENTED | 🔒 JWT | Gamma scalping P&L |
| 186 | POST | `/api/v1/viop/margin` | 236 | ✅ IMPLEMENTED | 🔒 JWT | SPAN teminat hesaplama |
| 187 | POST | `/api/v1/viop/arbitrage` | 254 | ✅ IMPLEMENTED | 🔒 JWT | Futures-spot arbitraj |
| 188 | POST | `/api/v1/viop/parity` | 274 | ✅ IMPLEMENTED | 🔒 JWT | Put-Call Parity kontrolü |
| 189 | POST | `/api/v1/viop/risk` | 293 | ✅ IMPLEMENTED | 🔒 JWT | VIOP pozisyon risk hesabı |
| 190 | GET | `/api/v1/viop/contracts` | 308 | ✅ IMPLEMENTED | 🔒 JWT | Sözleşme kataloğu |
| 191 | GET | `/api/v1/viop/contracts/{symbol}` | 321 | ✅ IMPLEMENTED | 🔒 JWT | Tek sözleşme detayı |

#### 📄 v1/event_study.py — Event Study (2 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 192 | GET | `/api/v1/event-study/analyze/{ticker}` | 8 | ⚠️ PLACEHOLDER | 🔒 JWT | "Requires event data" |
| 193 | GET | `/api/v1/event-study/calendar` | 18 | ❌ EMPTY | 🔒 JWT | `"events": []` boş |

#### 📄 v1/system.py — System (8 endpoint)

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 194 | GET | `/api/v1/system/health` | 6 | ❌ STUB | 🔒 JWT | `{"status": "healthy"}` hardcoded |
| 195 | GET | `/api/v1/system/status` | 10 | ❌ STUB | 🔒 JWT | `{"status": "running", "services": {}}` boş |
| 196 | GET | `/api/v1/system/metrics` | 14 | ❌ EMPTY | 🔒 JWT | `"metrics": {}` boş |
| 197 | GET | `/api/v1/system/audit` | 18 | ❌ EMPTY | 🔒 JWT | `"audit": []` boş |
| 198 | GET | `/api/v1/system/config` | 22 | 🔴 HARDCODED | 🔒 JWT | `{"config": {"env": "development"}}` |
| 199 | GET | `/api/v1/system/logs` | 26 | ❌ EMPTY | 🔒 JWT | `"logs": []` boş |
| 200 | POST | `/api/v1/system/restart` | 30 | ❌ STUB | 🔒 JWT | `{"status": "restart_initiated"}` |
| 201 | GET | `/api/v1/system/services` | 34 | ❌ EMPTY | 🔒 JWT | `"services": {}` boş |

---

### 📁 services/market_state/api.py — Market State Module (7 endpoint)

> Bu endpoint'ler `register_market_state_routes(app, service)` ile bir FastAPI app'e eklenir.
> `server.py` ile ÇAKIŞMA var: aynı path'ler her iki dosyada tanımlı.

| # | Metod | Path | Satır | Durum | Auth | Not |
|---|-------|------|-------|-------|------|-----|
| 202 | GET | `/api/market/state` | 28 | ✅ IMPLEMENTED | Yok | market_state_service.get_current_state() |
| 203 | GET | `/api/market/breadth` | 40 | ✅ IMPLEMENTED | Yok | market_state_service.get_breadth() |
| 204 | GET | `/api/market/regime` | 52 | ✅ IMPLEMENTED | Yok | market_state_service.get_ensemble_regime() |
| 205 | GET | `/api/market/transition` | 64 | ✅ IMPLEMENTED | Yok | transition tracker + alerts |
| 206 | GET | `/api/market/multi-tf` | 85 | ✅ IMPLEMENTED | Yok | multi-timeframe states |
| 207 | GET | `/api/market/alerts` | 97 | ✅ IMPLEMENTED | Yok | transition + breadth alerts |
| 208 | GET | `/api/market/health` | 128 | ✅ IMPLEMENTED | Yok | Sağlık durumu |

---

## Çakışma Analizi

### ⚠️ Aynı Path, Farklı Dosyalar

| Path | Dosya 1 | Dosya 2 | Dosya 3 | Durum |
|------|---------|---------|---------|-------|
| `/` | apps/api/main.py:108 | server.py:185 | app.py (root) | ⚠️ 3 farklı app |
| `/health` | apps/api/main.py:119 | server.py:205 | app.py (health) | ⚠️ 3 farklı app |
| `/api/market/state` | main.py:248 | server.py:426 | market_state/api.py:28 | ⚠️ 3 tanımlı |
| `/api/market/breadth` | server.py:441 | market_state/api.py:40 | — | ⚠️ 2 tanımlı |
| `/api/market/regime` | server.py:460 | market_state/api.py:52 | — | ⚠️ 2 tanımlı |
| `/api/market/transition` | server.py:486 | market_state/api.py:64 | — | ⚠️ 2 tanımlı |
| `/api/market/multi-tf` | server.py:509 | market_state/api.py:85 | — | ⚠️ 2 tanımlı |
| `/api/portfolio` | main.py:597 | server.py:299 | — | ⚠️ 2 tanımlı |
| `/api/signals` | main.py:519 | server.py:365 | — | ⚠️ 2 tanımlı |
| `/api/features/{ticker}` | main.py:658 | server.py:377 | — | ⚠️ 2 tanımlı |
| `/ws` | apps/api/main.py:304 | server.py:609 | — | ⚠️ 2 tanımlı |
| `/metrics` | main.py:120 | server.py:707 | — | ⚠️ 2 tanımlı |
| `/health/detailed` | server.py:696 | app.py | — | ⚠️ 2 tanımlı |

> **Not:** Bu çakışmalar farklı FastAPI app instance'ları arasında. Aynı anda tek bir app çalıştırıldığında sorun olmaz. Ama `market_state/api.py` route'ları `server.py`'ye register edilirse, `server.py` kendi `/api/market/state` endpoint'ini overwrite eder.

### ⛔ Deprecated Endpoint'ler Hâlâ Aktif

| Dosya | Durum | Endpoint Sayısı |
|-------|-------|-----------------|
| `services/api/main.py` | DEPRECATED (dosya başlığında yazıyor) | 27 endpoint hâlâ tanımlı |
| `services/api/server.py` | DEV/LEGACY (dosya başlığında yazıyor) | 34 endpoint hâlâ tanımlı |

> Bu dosyalar import edilip çalıştırılabilir. `main.py` kendi `__main__` bloğunda `sys.exit(1)` ile çıkış yapıyor ama import edilirse app aktif olur.

---

## Kategori Özeti

### ✅ Gerçek Veri Döndüren Endpoint'ler (47)

En güvenilir endpoint'ler:
- **v1/portfolio/** — 16/18 endpoint gerçek veri (portfolio_manager singleton)
- **v1/risk/** — 13/16 endpoint gerçek veri (dynamic_limits, drawdown_response, stress_test, vb.)
- **v1/scanner/** — 14/14 endpoint gerçek veri (scan_api singleton)
- **v1/viop/** — 12/14 endpoint gerçek veri (enhanced_options modülleri)
- **server.py** — 15/34 endpoint gerçek veri (dev modüller)

### ⚠️ Placeholder/Sahte Veri Döndüren Endpoint'ler (52)

En sorunlu alanlar:
- **v1/intelligence/** — 10/11 endpoint placeholder ("Requires live data")
- **v1/market/** — 5/10 endpoint placeholder
- **v1/decisions/** — 4/6 endpoint placeholder/empty
- **v1/backtest/** — 4/8 endpoint placeholder/empty

### ❌ Boş/501 Response Döndüren Endpoint'ler (14)

- `apps/api/main.py`: `/features/{ticker}` (501), `/predict` (501)
- `v1/system.py`: 6/8 endpoint boş response
- `v1/decisions.py`: `/audit/{id}`, `/plan` boş array
- `v1/backtest.py`: `/trades/{id}`, `/equity-curve/{id}` boş array

### 🔴 Hardcoded Veri Döndüren Endpoint'ler (18)

- `v1/market/sectors` — Sabit sektör listesi
- `v1/market/calendar` — Sabit saat bilgisi
- `v1/models/list` — Sabit model listesi
- `v1/agents/list` — Sabit agent listesi
- `v1/macro/overview` — Sabit indicator listesi
- `v1/alternative/sources` — Sabit kaynak listesi
- `v1/viop/strategies` — Sabit strateji listesi
- `v1/system/config` — Sabit config
- `server.py` root — Sabit HTML

### 🔒 Auth Gerektiren Endpoint'ler (92)

Tüm `/api/v1/*` endpoint'leri `get_current_user` + `check_rate_limit` dependency kullanır.
- JWT Bearer token veya X-API-Key header gerekli
- RBAC: Role-based access control (VIEWER, ANALYST, TRADER, ADMIN, SYSTEM)
- Rate limiting: Endpoint gruplarına göre limit

### 🌐 WebSocket Endpoint'leri (6)

| Path | Dosya | Durum | Özellikler |
|------|-------|-------|------------|
| `/ws` | apps/api/main.py:304 | ✅ | subscribe, get_opportunities, ping |
| `/ws/{channel}` | main.py:752 | ✅ | Kanal bazlı, subscribe |
| `/ws/live` | main.py:775 | ✅ | Canlı market verisi |
| `/ws` | server.py:609 | ✅ | subscribe, ping, get_ticker |

---

## Servis Bağımlılık Haritası

```
┌─────────────────────────────────────────────────────────────┐
│                    apps/api/main.py (v3.0)                  │
│  orchestrator ← super_intelligence, regime_detector,        │
│                  ranking_model, continuous_learning          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              services/api/app.py (CANONICAL)                │
│  v1_router → 16 sub-router (92 endpoint)                    │
│  auth: JWT + API Key + RBAC                                 │
│  rate_limiter                                               │
│  databases: PostgreSQL + ClickHouse + Redis                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              services/api/server.py (DEV)                   │
│  SQLite dev_db                                              │
│  modüller: feature_store, regime_engine, signal_fusion,     │
│            opportunity_engine, decision_engine,              │
│            portfolio_manager, learning_system, alerting      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              services/api/main.py (DEPRECATED)              │
│  PostgreSQL + ClickHouse + Redis                            │
│  yfinance fallback                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Tavsiyeler

1. **`services/api/main.py` dosyasını kaldırın** — DEPRECATED olarak işaretlenmiş, 27 endpoint hâlâ tanımlı. Import edilirse güvenlik açığı yaratabilir.

2. **`server.py` endpoint'lerini `app.py` + v1_router'a taşıyın** — server.py'deki gerçek veri döndüren endpoint'ler (opportunities, portfolio, signals, regime, risk, notifications, audit, stats, tickers) v1 router'a taşınmalı.

3. **Intelligence endpoint'lerini doldurun** — v1/intelligence.py'deki 10 placeholder endpoint, spec_engine ve factor_engine servislerine bağlanmalı.

4. **Demo data'yı temizleyin** — v1/risk.py ve v1/portfolio.py'deki `np.random.seed(42)` ile üretilen demo veriler, gerçek portföy verisine bağlanmalı.

5. **Çakışan path'leri çözün** — `/api/market/state`, `/api/market/breadth` vb. path'ler 2-3 dosyada tanımlı. Tek canonical kaynak belirlenmeli.

6. **v1/system.py endpoint'lerini implement edin** — 8 endpoint'in 6'sı boş/stub response döndürüyor.
