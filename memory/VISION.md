# ALPHA BIST — Vizyon ve Sistem Dokümanı

**Son güncelleme:** 2026-08-18

---

## 1. Vizyon

BIST'teki 800+ varlığı sürekli izleyen, piyasa rejimini anlayan, haber/makro/teknik/fundamental/AI verilerini birleştiren, fırsatları sıralayan, risklerini hesaplayan ve bunları sanal portföy üzerinde test eden otonom bir yatırım araştırma ve simülasyon platformu.

**Temel Prensip:** AI → BUY şeklinde çalışmayacak. Doğru mimari:

```
DATA → DATA QUALITY → FEATURES → MARKET STATE → ASSET ANALYSIS
→ OPPORTUNITY ENGINE → DECISION ENGINE → RISK ENGINE
→ PORTFOLIO SIMULATOR → OUTCOME → LEARNING
```

AI bu sistemin bir bileşeni. Sistemin sahibi AI değil, kurallar + veri + risk motoru + state machine.

---

## 2. Mevcut Sistem (217 modül)

### Katmanlar

| Katman | Modül | Satır | Durum |
|--------|-------|-------|-------|
| Core | 28 | 12,647 | ✅ |
| Ingestion | 20 | 5,278 | ✅ |
| Features | 14 | 5,802 | ✅ |
| Intelligence | 23 | 7,527 | ✅ |
| Risk | 5 | 1,654 | ✅ |
| Portfolio | 3 | 2,040 | ✅ |
| Learning | 6 | 2,309 | ✅ |
| ML | 12 | 3,052 | ✅ |
| Backtest | 8 | 3,961 | ✅ |
| Agents | 1 | 532 | ✅ |
| Scanner | 8 | 2,936 | ✅ |
| Scheduler | 3 | 468 | ✅ |
| Simulation | 2 | 601 | ✅ |
| API | 3 | 1,829 | ✅ |
| Market State | 1 | 354 | ✅ |
| Alternative | 5 | 65 | ⚠️ Basit |
| Macro | 7 | 116 | ⚠️ Basit |
| Factors | 7 | 135 | ⚠️ Basit |
| Event Study | 7 | 77 | ⚠️ Basit |
| VIOP | 6 | 82 | ⚠️ Basit |
| **TOPLAM** | **217** | **~50,000** | |

### Test Durumu

- 83 test dosyası
- 75+ test geçiyor
- 160+ modül import başarılı

### Düzeltilen Bug'lar (14)

1. Decision Engine — HOLD üretilmiyor ✅
2. ATR approximation (price×0.02) ✅
3. Event Bus — InMemoryRedis durable değil ✅
4. Duplicate event koruması restart sonrası ✅
5. Backtest — hard-coded komisyon ✅
6. World State decay 0.5'e sabit ✅
7. SPEC Engine dead configuration ✅
8. Signal Fusion sabit ağırlıklar ✅
9. Portfolio DB failure sessizce geçiliyor ✅
10. Data Quality v1 vs v2 ikisi birden ✅
11. BIST-30 → BIST-50 (açığa satış) ✅
12. İşlem saatleri (tek seans 10:00-18:00) ✅
13. Fiyat limitleri (pazara göre) ✅
14. Temettü stopajı %10 → %15 ✅

---

## 3. Nihai Sistem (Vizyon)

### 3.1 Agent Mimarisi (28 agent)

```
ORCHESTRATOR
    ↓
SYNTHESIS (2) ─── Research Manager + Explanation
    ↓
ANALYSIS (6) ─── Valuation, Forecasting, Monte Carlo, Scenario, Event Study, Factor
    ↓
RESEARCH (6) ─── Technical, Fundamental, News, Macro, Sentiment, KAP
    ↓
DECISION (3) ─── Signal Fusion, Ranking, Trade Planner
    ↓
RISK (4) ─── Risk Gate, Compliance, Position Sizing, Hedging
    ↓
PORTFOLIO (3) ─── Execution, Rebalancing, Accounting
    ↓
LEARNING (4) ─── Outcome Tracker, Drift Detector, Model Evolution, Attribution
```

### 3.2 Feature Mimarisi (120+ feature)

- Teknik: 30+ (trend, momentum, volatilite, volume, price action)
- Fundamental: 25+ (değerleme, kârlılık, büyüme, bilanço, nakit akışı)
- Macro: 20+ (döviz, faiz, enflasyon, VIX, emtia, global)
- Sentiment: 20+ (haber, KAP, sosyal medya, manipülasyon)
- Cross-sectional: 15+ (rank, sektör, breadth, peer)
- BIST-specific: 10+ (kur hassasiyeti, enflasyon, faiz, sektör momentum)

### 3.3 ML Mimarisi (6+ model)

- LightGBM (primary)
- XGBoost
- CatBoost
- LSTM
- Transformer
- Ensemble (stacking)
- Regime-aware model selection

### 3.4 Risk Mimarisi

- Pre-trade risk gate (9 check + BIST kuralları)
- Kelly criterion (regime-conditioned)
- Volatility targeting
- Ledoit-Wolf covariance
- VaR/CVaR
- Dynamic risk limits
- Stress test (8+ senaryo)
- Tail risk hedging

### 3.5 Backtest Mimarisi

- 5 bias koruması (look-ahead, survivorship, data-snooping, optimization, overfitting)
- Walk-forward + purge/embargo
- Realistic transaction cost (spread, slippage, market impact)
- Deflated Sharpe Ratio
- Event replay + deterministic recovery

### 3.6 Learning Mimarisi

- Prediction/outcome tracking
- Attribution (factor, sector, security selection)
- Drift detection (PSI, KS, Page-Hinkley, ADWIN)
- Calibration (Brier score, overconfidence detection)
- Champion-challenger (shadow mode, A/B test)
- Auto-retrain

---

## 4. BIST Kuralları (Özet)

| Kural | Değer |
|-------|-------|
| İşlem saatleri | 10:00-18:00 (tek seans) |
| Fiyat limitleri | Yıldız ±%20, Ana ±%15, Alt ±%10 |
| Açığa satış | BIST-50, yukarı adım kuralı |
| Komisyon | Broker %0.03-0.2 + BIST %0.0056 + MKK %0.00109 + BSMV %5 |
| Temettü stopajı | %15 (2025) |
| SPK bildirim | %5 eşik |
| Brüt takas | Açığa satış yasak, T+0 |

---

## 5. Teknoloji Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python 3.11+, FastAPI, asyncio |
| Database | PostgreSQL, SQLite, Redis, ClickHouse |
| ML | LightGBM, XGBoost, scikit-learn, PyTorch |
| LLM | Ollama (tek model, local) |
| Event Bus | Redis Streams + PostgreSQL fallback |
| Monitoring | Prometheus, structlog |
| Dashboard | Next.js (apps/web/) |
| Container | Docker, docker-compose |

---

## 6. Dosya Yapısı

```
bist-100/
├── services/                    ← 217 Python modülü
│   ├── core/                    ← Temel altyapı (28)
│   ├── ingestion/               ← Veri toplama (20)
│   ├── features/                ← Feature hesaplama (14)
│   ├── intelligence/            ← Analiz ve tahmin (23)
│   ├── risk/                    ← Risk yönetimi (5)
│   ├── portfolio/               ← Portföy yönetimi (3)
│   ├── learning/                ← Öğrenme sistemi (6)
│   ├── ml/                      ← Makine öğrenmesi (12)
│   ├── backtest/                ← Backtest motoru (8)
│   ├── agents/                  ← AI agent (1)
│   ├── scanner/                 ← Tarama motoru (8)
│   ├── scheduler/               ← Zamanlayıcı (3)
│   ├── simulation/              ← Simülasyon (2)
│   ├── api/                     ← API (3)
│   ├── market_state/            ← Piyasa durumu (1)
│   ├── alternative/             ← Alternatif veri (5)
│   ├── macro/                   ← Makro ekonomi (7)
│   ├── factors/                 ← Factor investing (7)
│   ├── event_study/             ← Event study (7)
│   └── viop/                    ← VIOP/opsiyon (6)
├── tests/                       ← 83 test dosyası
├── memory/                      ← Dokümantasyon (95 dosya)
│   ├── documentation/           ← Proje dokümantasyonu (12)
│   ├── system/                  ← Sistem tanımı + 32 bölüm
│   └── modules/                 ← 20 katman nihai spec
├── apps/web/                    ← Dashboard (Next.js)
├── config/                      ← Konfigürasyon
├── main.py                      ← Ana entry point
├── start.py                     ← Start script
├── run_all_imports.py           ← Import testi (160+ modül)
└── alpha                        ← Yönetim scripti
```
