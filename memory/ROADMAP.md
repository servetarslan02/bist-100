# ALPHA BIST — Master Roadmap & TODO

> **Proje:** BIST Market Intelligence & Quant Engine (Aladdin-seviye)
> **Amaç:** 800+ BIST varlığını sürekli tarayan, fırsat keşfeden, risk-kontrollü AI yatırım araştırma/simülasyon platformu
> **Güncelleme:** 15 Ağustos 2026
> **Durum:** Aktif geliştirme

---

## İçindekiler

1. [Sistem Özeti](#1-sistem-özeti)
2. [Temel Prensipler](#2-temel-prensipler)
3. [Mevcut Durum Analizi](#3-mevcut-durum-analizi)
4. [Faz Planı (Toplam 14 Faz)](#4-faz-planı)
5. [Faz Detayları](#5-faz-detayları)
6. [Kabul Kriterleri](#6-kabul-kriterleri)
7. [Teknoloji Stack](#7-teknoloji-stack)
8. [Dosya Yapısı](#8-dosya-yapısı)
9. [Sözleşmeler & Kurallar](#9-sözleşmeler--kurallar)

---

## 1. Sistem Özeti

Bu sistem:

- ❌ 3-5 hisse analiz eden basit bir bot **değil**
- ❌ Teknik indikatör çizelgesi **değil**
- ❌ AI'ya "hangi hisseyi alayım?" diye soran uygulama **değil**

Bu sistem:

> **BIST'in tamamını sürekli sayısal olarak izleyen, olayları anlayan, ilişkileri çıkaran, fırsatları keşfeden, senaryo/backtest yapan, risk hesaplayan, sonuçlarını ölçen ve kontrollü biçimde kendini geliştiren otonom finansal zekâ platformudur.**

### Sistem Akışı (Üst Düzey)

```
KAYNAKLAR (Piyasa, KAP, Haber, Makro, Sosyal)
    ↓
VERİ KALİTESİ (Validate, Clean, Normalize)
    ↓
ÖZELLİKLER (Teknik, Fundamental, Makro, Haber)
    ↓
DÜNYA DURUMU (Rejim, Volatilite, Likidite, Risk)
    ↓
AI AJANLARI (Araştırma, Haber, Makro, Sentiment)
    ↓
FIRSAT KEŞFİ (Tarama, Sıralama, Puanlama)
    ↓
KARAR MOTORU (LONG / SHORT / HOLD / NO_TRADE)
    ↓
RİSK KAPISI (Limit, Konsantrasyon, Drawdown)
    ↓
SİMÜLASYON (Emir, Dolum, Komisyon, Slippage)
    ↓
PORTFÖY (Pozisyon, Nakit, P&L, Ledger)
    ↓
SONUÇ (Gerçek vs Tahmin, Hata Analizi)
    ↓
ÖĞRENME (Model Değerlendirme, Drift, Kalibrasyon)
    ↓
DENETİM (Audit, Lineage, Replay, Recovery)
```

---

## 2. Temel Prensipler

### 2.1 AI Karar Vermez, Destekler

```
❌  AI → BUY
✅  DATA + EVIDENCE + RISK → DECISION (AI bir bileşen)
```

AI sonucu tek başına emir olamaz. AI yalnızca **evidence, confidence, reasoning** üretir.

### 2.2 Tek Kaynak Güvenilir Değildir

RSI, MACD, F/K gibi sabit metrikler tek başına kullanılmaz. Sistem **çok boyutlu piyasa durumu → olasılıksal değerlendirme** yapar.

### 2.3 Missing ≠ Zero

Eksik veri sıfır olarak değerlendirilmez. Her veri için **VALID / MISSING / STALE / INVALID / DUPLICATE** ayrımı yapılır.

### 2.4 Risk Motoru Üsttedir

AI "BUY" dese bile risk motoru veto edebilir. Risk fail-closed çalışır (yüklenemezse işlem yapılmaz).

### 2.5 Her Şey İzlenebilir

Her kararın veri kaynağına kadar izlenebilirliği sağlanır:
```
FILL → ORDER → DECISION → SIGNAL → FEATURES → EVENTS → RAW DATA
```

### 2.6 Geriye Dönük Test Zorunlu

Her strateji/model canlıya alınmadan önce:
```
TRAIN → VALIDATE → BACKTEST → WALK-FORWARD → PAPER → SHADOW → PROMOTE
```

---

## 3. Mevcut Durum Analizi

### Çalışan Parçalar ✅

| Bileşen | Dosya | Durum |
|---------|-------|-------|
| Config (Production Security) | `services/core/config.py` | ✅ P0 düzeltildi |
| Data Quality Gate v2.0 | `services/core/data_quality.py` | ✅ P0 düzeltildi |
| Event Bus (Durable + Idempotent) | `services/core/event_bus.py` | ✅ P0 düzeltildi |
| Event Schema (Validation) | `services/core/event_schema.py` | ✅ Çalışıyor |
| Models (Invariant Validation) | `services/core/models.py` | ✅ P0 düzeltildi |
| Decision Engine (HOLD Fix) | `services/core/decision_engine.py` | ✅ P0 düzeltildi |
| Risk Engine (Fail-Closed) | `services/risk/main.py` | ✅ P0 düzeltildi |
| Portfolio Service (Avg Cost Fix) | `services/portfolio/main.py` | ✅ P0 düzeltildi |
| State Recovery (Snapshot+Events) | `services/core/state_recovery.py` | ✅ P0 düzeltildi |
| Feature Calculator (58 feature) | `services/features/calculator.py` | ✅ Çalışıyor |
| Alpha Scanner | `services/scanner/alpha_scanner.py` | ✅ Çalışıyor |
| SPEC Engine | `services/intelligence/spec_engine.py` | ✅ Çalışıyor |
| World State | `services/intelligence/world_state.py` | ✅ Düzeltildi |
| Impact Engine | `services/intelligence/impact_engine.py` | ✅ Çalışıyor |
| Trade Planner | `services/intelligence/trade_planner.py` | ✅ Çalışıyor |
| Ingestion Service | `services/ingestion/main.py` | ✅ Temel yapı var |
| Market State Service | `services/market_state/main.py` | ✅ Çalışıyor |
| BIST Universe | `services/ingestion/bist_universe.py` | ✅ 493 hisse yüklüyor |

### Kısmen Çalışan / Eksik Parçalar ⚠️

| Bileşen | Durum | Eksik |
|---------|-------|-------|
| Intelligence Service (LLM) | ⚠️ Temel | Fallback yok, prompt versioning yok |
| Scheduler | ⚠️ Temel | Sadece batch scan, event-driven yok |
| ML modelleri | ⚠️ Skeleton | Gerçek eğitim/inference yok |
| Backtest | ⚠️ Temel | Walk-forward, metrics eksik |
| Database Schema | ⚠️ Temel | Birçok tablo eksik |
| Docker Compose | ⚠️ Var | Dev ortamı ayrılmamış |

### Olmayan Parçalar ❌

| Bileşen | Öncelik |
|---------|---------|
| Fundamental Analysis Engine | Kritik |
| Valuation / DCF Engine | Kritik |
| Monte Carlo Engine | Yüksek |
| Probability Engine | Yüksek |
| Scenario Engine | Yüksek |
| Stress Test Engine | Yüksek |
| Backtest Metrics (Sharpe, Sortino, vb.) | Yüksek |
| Walk-forward Validation | Yüksek |
| AI Agent System | Yüksek |
| Agent Orchestrator | Yüksek |
| Model Registry / Lifecycle | Yüksek |
| Shadow Mode | Yüksek |
| Execution Simulator (Gerçekçi) | Yüksek |
| Corporate Actions | Orta |
| Knowledge Graph | Orta |
| Factor Engine | Orta |
| Benchmark / Attribution | Orta |
| Multi-Asset / Multi-Market | Orta |
| Dashboard (16 sayfa) | Yüksek |
| Audit / Lineage | Yüksek |
| Event Replay | Orta |
| Testing Pyramid | Kritik |
| Observability (Metrics/Traces) | Orta |
| Alert System | Orta |
| WebSocket Real-time | Orta |

---

## 4. Faz Planı

```
FAZ 0  → Repository Audit & Temel Düzeltmeler          [TAMAMLANDI]
FAZ 1  → Data Ingestion & Quality                       [DEVAM EDİYOR]
FAZ 2  → Feature Engine & Store                         [DEVAM EDİYOR]
FAZ 3  → World State & Regime Engine                    [DEVAM EDİYOR]
FAZ 4  → Fundamental Analysis Engine                    [BAŞLANMADI]
FAZ 5  → Valuation & DCF Engine                         [BAŞLANMADI]
FAZ 6  → Monte Carlo & Probability Engine               [BAŞLANMADI]
FAZ 7  → Scenario & Stress Test Engine                  [BAşLANMADI]
FAZ 8  → AI Agent System                                [BAŞLANMADI]
FAZ 9  → Opportunity Discovery Engine                   [BAŞLANMADI]
FAZ 10 → Decision & Risk Engine                         [DEVAM EDİYOR]
FAZ 11 → Order & Execution Simulator                    [BAŞLANMADI]
FAZ 12 → Portfolio & Accounting                         [DEVAM EDİYOR]
FAZ 13 → Backtest & Learning Engine                     [BAŞLANMADI]
FAZ 14 → Dashboard & Production                         [BAŞLANMADI]
```

---

## 5. Faz Detayları

---

### FAZ 0 — Repository Audit & Temel Düzeltmeler ✅ TAMAMLANDI

**Amaç:** Mevcut kodu production-grade hale getirmek.

#### Yapılanlar

- [x] Config: Production validation, insecure default detection
- [x] Data Quality: Stale detection (total_seconds), duplicate protection, missing≠0
- [x] Event Bus: Durable (Redis Streams), idempotent publish
- [x] Event Schema: Validation güçlendirildi
- [x] Models: Invariant validation (price>0, confidence∈[0,1])
- [x] Decision Engine: HOLD ayrı action, risk veto
- [x] Risk Engine: Fail-closed, unknown→BLOCK
- [x] Portfolio: Weighted avg cost, oversell protection, atomik transaction
- [x] State Recovery: Snapshot+events, re-fetch 60d kaldırıldı
- [x] World State: Hard-code kaldırıldı, z-score normalization
- [x] SPEC Engine: Sigmoid calibration, evidence weighting

#### Dosyalar

```
services/core/config.py              — Security hardened
services/core/data_quality.py        — v2.0
services/core/event_bus.py           — Durable + idempotent
services/core/event_schema.py        — Validation
services/core/models.py              — Invariants
services/core/decision_engine.py     — HOLD fix
services/core/state_recovery.py      — Snapshot approach
services/risk/main.py                — Fail-closed
services/portfolio/main.py           — Avg cost + transaction
services/intelligence/spec_engine.py — Calibration
services/intelligence/world_state.py — Z-score normalization
```

---

### FAZ 1 — Data Ingestion & Quality

**Amaç:** Tüm BIST verilerini güvenilir şekilde toplamak.

#### 1.1 Market Data Provider'ları

**Dosya:** `services/ingestion/providers/`

| Provider | Veri | Durum | Yapılacak |
|----------|------|-------|-----------|
| yfinance | OHLCV, fiyat | ✅ Çalışıyor | Retry, circuit breaker ekle |
| KAP | Şirket bildirimleri | ⚠️ Temel | Parser güçlendir, kategori ekle |
| TCMB EVDS | Makro veri | ⚠️ Temel | Seri numarası mapping, fallback |
| NewsAPI | Haberler | ⚠️ Temel | Türkçe NLP, sentiment |
| RSS | Finansal haberler | ⚠️ Temel | Kaynak sayısı artır |
| X (Twitter) | Sosyal medya | ❌ Yok | Implementasyon gerekli |
| Matriks | Alternatif fiyat | ⚠️ Temel | Fallback olarak |

#### 1.2 Provider Contract

Her provider bu interface'i uygulamalı:

```python
class DataProvider:
    def fetch(self, params) -> List[RawData]
    def normalize(self, raw_data) -> List[NormalizedData]
    def validate(self, normalized_data) -> List[ValidData]
    def health_check() -> ProviderHealth
    def get_reliability_score() -> float  # 0-1
```

#### 1.3 Provider Failover

```
Primary Provider
    ↓ failure
Secondary Provider
    ↓ failure
Cached Data
    ↓ stale
UNAVAILABLE (log + alert)
```

#### 1.4 Circuit Breaker

```
CLOSED (normal)
    ↓ 5 consecutive failures
OPEN (skip provider, use fallback)
    ↓ 60 seconds
HALF_OPEN (try 1 request)
    ↓ success → CLOSED
    ↓ failure → OPEN
```

#### 1.5 Rate Limit

Her provider için:
- `timeout`: max bekleme süresi
- `retry`: max deneme sayısı
- `backoff`: exponential (1s → 2s → 4s → 8s)
- `rate_limit`: saniyede max istek
- `circuit_breaker`: açık/kapalı durum

#### 1.6 BIST Universe Engine

**Dosya:** `services/ingestion/bist_universe.py`

- [x] KAP'tan canlı şirket listesi çekme (şu an var, güçlendir)
- [x] Sektör/alt-sektör mapping
- [x] Market cap bilgisi
- [x] Likidite skoru
- [x] Listing status (active/suspended/delisted)
- [x] Otomatik günlük güncelleme
- [x] Survivorship bias koruması (delisted şirketler de tarihte tutulacak)

#### 1.7 Data Quality Engine

**Dosya:** `services/core/data_quality.py`

- [x] Tick validation (price>0, volume>=0, timestamp)
- [x] Stale detection (total_seconds)
- [x] Duplicate protection (time-windowed)
- [x] Missing ≠ 0 ayrımı
- [x] Cross-source reconciliation (A kaynağı 100.20, B kaynağı 100.25 → normal; A=100.20, B=145.80 → anomali)
- [x] Outlier detection (Z-score > 4)
- [x] Data source reliability tracking

#### 1.8 Trading Calendar

**Dosya:** `services/core/market_calendar.py` [YENİ]

- [x] BIST işlem saatleri (10:00-18:00)
- [x] Hafta sonları
- [x] Resmi tatiller (ulusal bayramlar, dini bayramlar)
- [x] Yarım günler
- [x] Devre kesici durumları
- [x] Trading halt bilgisi
- [x] Market açık/kapalı kontrolü

#### 1.9 Corporate Actions

**Dosya:** `services/ingestion/corporate_actions.py` [YENİ]

- [x] Temettü (dividend) düzeltmesi
- [x] Bedelsiz sermaye artırımı (split)
- [x] Bedelli sermaye artırımı
- [x] Birleşme/devralma
- [x] Fiyat geçmişi düzeltmesi (geçmiş fiyatlar bölünme oranına göre düzeltilmeli)
- [x] Portföy pozisyon düzeltmesi

#### Çıkış Kriterleri

- [x] 500+ hisse için veri çekme çalışıyor
- [x] Provider failover test edilmiş
- [x] Circuit breaker çalışıyor
- [x] Data quality gate tüm verilerden geçiriliyor
- [x] Trading calendar BIST saatlerini doğru gösteriyor
- [x] Unit test: provider, quality gate, calendar
- [x] Integration test: veri çek → quality → store

---

### FAZ 2 — Feature Engine & Store

**Amaç:** Ham verilerden anlamlı özellikler üretmek ve versiyonlamak.

#### 2.1 Teknik Feature'lar (Mevcut — Güçlendirilecek)

**Dosya:** `services/features/calculator.py`

Mevcut 58 feature. Eklenecekler:

- [x] Ichimoku Cloud
- [x] Fibonacci retracement levels
- [x] Volume Profile (POC, VAH, VAL)
- [x] VWAP (Volume Weighted Average Price)
- [x] Pivot Points
- [x] Heikin-Ashi
- [x] Elder Ray (Bull/Bear Power)
- [x] Keltner Channels
- [x] Donchian Channels
- [x] Rate of Change (ROC) çoklu periyot
- [x] Williams %R çoklu periyot
- [x] ATR çoklu periyot (5, 14, 20)

#### 2.2 Fundamental Feature'lar [YENİ]

**Dosya:** `services/features/fundamental.py`

```python
class FundamentalFeatureEngine:
    def compute_valuation_features(self, financials) -> Dict:
        """P/E, P/B, EV/EBITDA, FCF Yield, Dividend Yield"""

    def compute_profitability_features(self, financials) -> Dict:
        """ROE, ROA, ROIC, margins (gross, EBIT, net)"""

    def compute_growth_features(self, financials_history) -> Dict:
        """Revenue growth, EPS growth, FCF growth, CAGR"""

    def compute_balance_sheet_features(self, financials) -> Dict:
        """Debt/Equity, Current Ratio, Net Debt/EBITDA"""

    def compute_quality_features(self, financials) -> Dict:
        """Earnings quality, cash conversion, accruals"""

    def compute_trend_features(self, financials_history) -> Dict:
        """Margin trend, growth acceleration/deceleration"""
```

#### 2.3 Makro Feature'lar [YENİ]

**Dosya:** `services/features/macro.py`

```python
class MacroFeatureEngine:
    def compute_currency_features(self, usdtry, eurtry) -> Dict:
        """FX momentum, volatility, regime"""

    def compute_rate_features(self, tcmb_rate, us_rate) -> Dict:
        """Rate differential, yield curve"""

    def compute_commodity_features(self, oil, gold) -> Dict:
        """Commodity momentum, Turkey sensitivity"""

    def compute_global_features(self, vix, sp500, dax) -> Dict:
        """Global risk appetite, correlation"""

    def compute_inflation_features(self, cpi, ppi) -> Dict:
        """Inflation trend, surprise"""
```

#### 2.4 Sentiment Feature'lar [YENİ]

**Dosya:** `services/features/sentiment.py`

```python
class SentimentFeatureEngine:
    def compute_news_sentiment(self, news_events) -> Dict:
        """Aggregated news sentiment, novelty, credibility"""

    def compute_kap_sentiment(self, kap_events) -> Dict:
        """KAP announcement sentiment, category impact"""

    def compute_social_sentiment(self, social_events) -> Dict:
        """Social media sentiment, volume, manipulation score"""

    def compute_sentiment_momentum(self, history) -> Dict:
        """Sentiment trend, acceleration"""
```

#### 2.5 Feature Store

**Dosya:** `services/features/store.py` [YENİ]

```python
class FeatureStore:
    """Tüm feature'ların canonical kaynağı."""

    def get(self, ticker: str, feature_name: str, version: str = "latest") -> FeatureValue
    def set(self, ticker: str, feature_name: str, value: float, version: str)
    def get_all(self, ticker: str, version: str = "latest") -> Dict[str, float]
    def get_history(self, ticker: str, feature_name: str, lookback_days: int) -> List[FeatureValue]

    def register_version(self, feature_group: str, version: str, formula: str)
    def get_version_info(self, feature_group: str, version: str) -> VersionInfo
```

#### 2.6 Feature Versioning

Her feature grubu versioned:

```
technical_features_v1    → RSI(14), SMA(20), MACD(12,26,9)
technical_features_v2    → RSI(14) Wilder smoothing, SMA(20), MACD(12,26,9)
fundamental_features_v1  → P/E, P/B, ROE
macro_features_v1        → USDTRY z-score, VIX normalize
```

Backtest eski version ile yeniden çalıştırılabilmeli.

#### 2.7 Feature Discovery Pipeline [YENİ]

**Dosya:** `services/features/discovery.py`

```
Raw Features (80+)
    ↓
Feature Interaction Generation
  - pairwise products
  - ratios
  - differences
  - lag features (1d, 2d, 5d)
    ↓
Candidate Features (500+)
    ↓
Filtering:
  1. Mutual Information (target ile)
  2. Correlation filter (yüksek korelasyonlu olanları ele)
  3. Permutation Importance
  4. SHAP values
  5. Feature Stability
  6. Leakage Detection
    ↓
Selected Features (100-200)
    ↓
ML Training
```

#### Çıkış Kriterleri

- [x] 100+ feature hesaplanıyor
- [x] Feature store Redis/DB'de tutuluyor
- [x] Feature versioning çalışıyor
- [x] Fundamental feature'lar (P/E, ROE, vb.) hesaplanıyor
- [x] Macro feature'lar (USDTRY, VIX, vb.) hesaplanıyor
- [x] Sentiment feature'lar (news, KAP) hesaplanıyor
- [x] Unit test: her feature grubu için
- [x] Integration test: veri → feature → store

---

### FAZ 3 — World State & Regime Engine

**Amaç:** Piyasanın genel durumunu anlamak.

#### 3.1 World State Engine (Mevcut — Genişletilecek)

**Dosya:** `services/intelligence/world_state.py`

Mevcut: 10 latent factor. Eklenecekler:

- [x] Global equity momentum (S&P500, DAX, Nikkei)
- [x] Credit conditions (CDS, spread)
- [x] Liquidity conditions
- [x] Market breadth (advance/decline ratio)
- [x] Sector rotation state
- [x] Yield curve shape (normal/inverted/flat)
- [x] Crypto market sentiment (risk appetite proxy)

#### 3.2 Regime Engine (Mevcut — Genişletilecek)

**Dosya:** `services/intelligence/regime.py` [YENİ veya mevcut market_state]

Mevcut regime detection: basit threshold-based.

Yapılacak:

- [x] Regime tespiti için feature-based (threshold değil)
- [x] Regime transition probability matrix
- [x] Regime duration tracking
- [x] Regime-conditioned model weights
- [x] Regime history (geçmiş rejim değişimleri)

Regime'ler:

```
BULL / BEAR / SIDEWAYS
HIGH_VOLATILITY / LOW_VOLATILITY
RISK_ON / RISK_OFF
CRISIS / RECOVERY
MOMENTUM_EXPANSION / MOMENTUM_CONTRACTION
```

#### 3.3 Macro Sensitivity Engine [YENİ]

**Dosya:** `services/intelligence/macro_sensitivity.py`

Her şirket için:

- [x] USDTRY sensitivity (ithalat/ihracat bağımlılığı)
- [x] Faiz sensitivity (borç yapısı)
- [x] Emtia sensitivity (girdi maliyetleri)
- [x] Global market sensitivity (korelasyon)

Örnek:
```
THYAO: USDTRY sensitivity = HIGH (yakıt maliyeti)
EREGL: Commodity sensitivity = HIGH (demir-çelik)
AKBNK: Interest rate sensitivity = HIGH (bankacılık)
```

#### Çıkış Kriterleri

- [x] World state 15+ factor içeriyor
- [x] Regime detection feature-based
- [x] Regime değiştiğinde ağırlıklar değişiyor
- [x] Macro sensitivity her şirket için hesaplanmış
- [x] Unit test: world state, regime, sensitivity
- [x] Integration test: market data → world state → regime

---

### FAZ 4 — Fundamental Analysis Engine [YENİ]

**Amaç:** Şirketlerin finansal sağlığını analiz etmek.

#### 4.1 Finansal Veri Çekme

**Dosya:** `services/ingestion/providers/fundamental_provider.py`

- [x] KAP'tan bilanço verisi çekme
- [x] Gelir tablosu verisi
- [x] Nakit akış tablosu
- [x] Çeyreklik + yıllık veri
- [x] Point-in-time data (o tarihte bilinen versiyon)

#### 4.2 Gelir Analizi

- [x] Revenue (ciro)
- [x] Revenue Growth (yıllık, çeyreklik)
- [x] Revenue CAGR (3 yıllık, 5 yıllık)
- [x] Organic growth vs inorganic growth

#### 4.3 Kârlılık Analizi

- [x] Gross Margin
- [x] EBIT Margin
- [x] EBITDA Margin
- [x] Net Margin
- [x] ROE (Return on Equity)
- [x] ROA (Return on Assets)
- [x] ROIC (Return on Invested Capital)

#### 4.4 Bilanço Analizi

- [x] Cash & Equivalents
- [x] Total Debt
- [x] Net Debt
- [x] Working Capital
- [x] Current Ratio
- [x] Debt/Equity Ratio
- [x] Net Debt/EBITDA

#### 4.5 Nakit Akış Analizi

- [x] Operating Cash Flow
- [x] Free Cash Flow (FCF)
- [x] FCF Margin
- [x] FCF Yield
- [x] Cash Conversion Ratio

#### 4.6 Büyüme Kalitesi

Sadece büyüme miktarı değil, birlikte değerlendirme:

```
Büyüme Kalitesi = f(growth, margin, cash_flow, debt)
```

Yüksek büyüme + düşen margin + artan borç = düşük kalite

#### 4.7 Fundamental Trend Engine

Tek bilanço değil zaman serisi analizi:

```python
class FundamentalTrendEngine:
    def analyze_revenue_trend(self, quarterly_revenue) -> TrendResult:
        """Accelerating / Decelerating / Stable / Declining"""

    def analyze_margin_trend(self, quarterly_margins) -> TrendResult:
        """Expanding / Contracting / Stable"""

    def analyze_earnings_quality(self, net_income, cash_flow) -> QualityResult:
        """High quality (cash-backed) / Low quality (accrual-heavy)"""
```

#### 4.8 Earnings Quality Engine

- [x] Net Income vs Cash Flow karşılaştırması
- [x] Receivables growth vs Revenue growth
- [x] Inventory changes
- [x] One-off gains/losses ayrımı
- [x] Accruals ratio

#### Çıkış Kriterleri

- [x] En az 100 şirket için finansal veri çekiliyor
- [x] 20+ fundamental feature hesaplanıyor
- [x] Trend analizi çalışıyor (accelerating/decelerating)
- [x] Earnings quality skoru hesaplanıyor
- [x] Point-in-time data korunuyor (look-ahead bias yok)
- [x] Unit test: her hesaplama için
- [x] Integration test: KAP → bilanço → feature → scoring

---

### FAZ 5 — Valuation & DCF Engine [YENİ]

**Amaç:** Şirketlerin değerlemesini yapmak.

#### 5.1 Multiples Valuation

- [x] P/E (Price/Earnings)
- [x] P/B (Price/Book)
- [x] EV/EBITDA
- [x] EV/EBIT
- [x] EV/Sales
- [x] FCF Yield
- [x] Dividend Yield

#### 5.2 Peer Comparison

```python
class PeerComparison:
    def compare_to_sector(self, ticker, metric) -> ComparisonResult:
        """vs sector median, vs sector average"""

    def compare_to_historical(self, ticker, metric, years) -> ComparisonResult:
        """vs own historical valuation"""

    def compare_to_peers(self, ticker, peer_group, metric) -> ComparisonResult:
        """vs specific peer group"""
```

#### 5.3 DCF Engine

**Dosya:** `services/intelligence/valuation/dcf_engine.py`

```python
class DCFEngine:
    def compute_dcf(
        self,
        revenue_forecast: List[float],
        margin_forecast: List[float],
        tax_rate: float,
        capex_forecast: List[float],
        working_capital_changes: List[float],
        wacc: float,
        terminal_growth: float,
        shares_outstanding: int,
    ) -> DCFResult:
        """Intrinsic value, upside/downside, sensitivity table"""
```

#### 5.4 Valuation Scenarios

En az 3 senaryo:

```
Bear  → conservative assumptions → intrinsic_value_bear
Base  → realistic assumptions   → intrinsic_value_base
Bull  → optimistic assumptions  → intrinsic_value_bull
```

Olasılık ağırlıklı sonuç:

```
Expected Value = P(bear) × V_bear + P(base) × V_base + P(bull) × V_bull
```

#### 5.5 Valuation Summary

Her şirket için:

```
┌─────────────────────────────────────────┐
│ THYAO — DEĞERLEME                       │
├─────────────────────────────────────────┤
│ P/E:        8.2x  (Sektör medyan: 11x) │
│ P/B:        1.4x  (Sektör medyan: 1.8x)│
│ EV/EBITDA:  5.1x  (Sektör medyan: 7x)  │
│ FCF Yield:  %6.8  (Sektör medyan: %4.2)│
├─────────────────────────────────────────┤
│ DCF Bear:   ₺280  (%10.4 downside)     │
│ DCF Base:   ₺340  (%8.7 upside)        │
│ DCF Bull:   ₺420  (%34.2 upside)       │
├─────────────────────────────────────────┤
│ Olasılık Ağırlıklı: ₺347               │
│ Mevcut Fiyat:       ₺312               │
│ Upside:             %11.2              │
└─────────────────────────────────────────┘
```

#### Çıkış Kriterleri

- [x] Multiples valuation hesaplanıyor
- [x] Peer comparison çalışıyor
- [x] DCF engine çalışıyor
- [x] Bear/Base/Bull senaryoları üretiliyor
- [x] Unit test: DCF, multiples, peer comparison
- [x] Integration test: bilanço → valuation → summary

---

### FAZ 6 — Monte Carlo & Probability Engine [YENİ]

**Amaç:** Olasılıksal tahminler yapmak.

#### 6.1 Monte Carlo Engine

**Dosya:** `services/intelligence/monte_carlo.py`

```python
class MonteCarloEngine:
    def simulate_price_paths(
        self,
        current_price: float,
        expected_return: float,
        volatility: float,
        horizon_days: int,
        num_simulations: int = 10000,
    ) -> MonteCarloResult:
        """Binlerce olası fiyat yolu simüle et."""

    def compute_percentiles(self, result) -> PercentileResult:
        """P10, P25, P50, P75, P90"""

    def compute_probabilities(self, result, targets) -> ProbabilityResult:
        """P(+10%), P(+5%), P(-5%), P(-10%)"""
```

#### 6.2 Monte Carlo Portfolio

```python
class PortfolioMonteCarlo:
    def simulate_portfolio(
        self,
        positions: List[Position],
        correlation_matrix: np.ndarray,
        num_simulations: int = 10000,
        horizon_days: int = 20,
    ) -> PortfolioMonteCarloResult:
        """Portföy seviyesinde Monte Carlo."""

    def compute_var(self, result, confidence=0.95) -> VaRResult:
        """VaR 95%, VaR 99%"""

    def compute_cvar(self, result, confidence=0.95) -> CVaRResult:
        """CVaR (Expected Shortfall)"""
```

#### 6.3 Probability Engine

**Dosya:** `services/intelligence/probability.py`

```python
class ProbabilityEngine:
    def compute_return_distribution(
        self,
        features: Dict,
        ml_predictions: Dict,
        historical_analogues: List[Dict],
    ) -> ReturnDistribution:
        """Getiri olasılık dağılımı."""

    def compute_hit_rate(self, predictions, outcomes) -> float:
        """Tahmin doğruluğu."""

    def compute_calibration(self, predictions, outcomes) -> CalibrationResult:
        """Confidence vs actual frequency."""
```

#### 6.4 Monte Carlo Dinamik Senaryo Sayısı

```python
def compute_scenario_count(volatility, uncertainty, portfolio_size, budget):
    base = 1000
    vol_mult = max(1.0, volatility / 0.02)
    uncertainty_mult = max(1.0, uncertainty / 0.3)
    size_mult = max(1.0, portfolio_size / 100000)
    count = int(base * vol_mult * uncertainty_mult * size_mult)
    return min(count, 50000)
```

#### Çıkış Kriterleri

- [x] Monte Carlo fiyat simülasyonu çalışıyor
- [x] P10, P25, P50, P75, P90 hesaplanıyor
- [x] Olasılık dağılımları üretiliyor (P(+10%), P(-5%), vb.)
- [x] Portfolio-level Monte Carlo çalışıyor
- [x] VaR / CVaR hesaplanıyor
- [x] Dinamik senaryo sayısı (volatiliteye göre)
- [x] Unit test: Monte Carlo, probability, VaR
- [x] Integration test: features → Monte Carlo → probabilities

---

### FAZ 7 — Scenario & Stress Test Engine [YENİ]

**Amaç:** Senaryo analizi ve stres testleri yapmak.

#### 7.1 Scenario Engine

**Dosya:** `services/intelligence/scenario.py`

```python
class ScenarioEngine:
    def run_scenario(
        self,
        scenario: ScenarioInput,
        portfolio: Portfolio,
        world_state: WorldState,
        asset_states: Dict[str, AssetState],
    ) -> ScenarioResult:
        """Senaryo çalıştır."""

class ScenarioInput:
    usdtry_change: float      # ör: +0.10 (%10 artış)
    interest_rate_change: float # ör: +0.05 (500bp)
    bist_change: float         # ör: -0.15 (%15 düşüş)
    vix_change: float          # ör: +0.50 (%50 artış)
    oil_change: float          # ör: +0.20 (%20 artış)
    gold_change: float         # ör: +0.10 (%10 artış)
```

#### 7.2 Senaryo Akışı

```
Scenario Input
    ↓
Macro Shock
    ↓
Sector Response (her sektör farklı etkilenir)
    ↓
Asset Response (her hisse farklı etkilenir)
    ↓
Portfolio Impact
    ↓
Risk Change
    ↓
Scenario Result
```

#### 7.3 Önceden Tanımlı Senaryolar

```python
PREDEFINED_SCENARIOS = {
    "TCMB_RATE_HIKE_500BP": ScenarioInput(interest_rate_change=0.05),
    "USDTRY_10_PCT": ScenarioInput(usdtry_change=0.10),
    "BIST_CRASH_15_PCT": ScenarioInput(bist_change=-0.15),
    "VIX_SPIKE_50_PCT": ScenarioInput(vix_change=0.50),
    "OIL_SHOCK_20_PCT": ScenarioInput(oil_change=0.20),
    "GLOBAL_RISK_OFF": ScenarioInput(bist_change=-0.10, vix_change=0.40, usdtry_change=0.05),
    "2008_CRISIS": ScenarioInput(bist_change=-0.50, vix_change=2.0, usdtry_change=0.30),
    "2020_COVID": ScenarioInput(bist_change=-0.30, vix_change=1.5, oil_change=-0.50),
}
```

#### 7.4 Stress Test Engine

**Dosya:** `services/intelligence/stress_test.py`

```python
class StressTestEngine:
    def run_stress_test(
        self,
        portfolio: Portfolio,
        scenarios: List[ScenarioInput],
    ) -> StressTestResult:
        """Birden fazla stres senaryosu çalıştır."""

    def find_breaking_point(
        self,
        portfolio: Portfolio,
        shock_variable: str,
        max_shock: float,
    ) -> BreakingPointResult:
        """Portföyün ne kadar şoka dayanabileceğini bul."""
```

#### Çıkış Kriterleri

- [x] Scenario engine çalışıyor (input → macro shock → portfolio impact)
- [x] Önceden tanımlı senaryolar (TCMB, USDTRY, BIST crash, vb.)
- [x] Stress test engine çalışıyor
- [x] Portfolio impact analizi (pozisyon bazlı etki)
- [x] Breaking point analizi
- [x] Unit test: scenario, stress test
- [x] Integration test: portfolio → scenario → impact

---

### FAZ 8 — AI Agent System [YENİ]

**Amaç:** AI'yı sistematik ve kontrollü kullanmak.

#### 8.1 Agent Architecture

```
Agent Orchestrator
    ↓
┌─────────────┬──────────────┬──────────────┐
│ Research    │ News         │ Macro        │
│ Agent       │ Agent        │ Agent        │
├─────────────┼──────────────┼──────────────┤
│ Fundamental │ Sentiment    │ Risk         │
│ Agent       │ Agent        │ Agent        │
└─────────────┴──────────────┴──────────────┘
```

#### 8.2 Agent Contract

**Dosya:** `services/agents/base.py`

```python
class BaseAgent:
    name: str
    tools: List[str]    # erişebileceği araçlar
    max_steps: int       # max adım sayısı
    timeout: int         # max süre (saniye)

    def execute(self, task: AgentTask) -> AgentResult:
        """Görevi çalıştır."""

    def validate_output(self, result: AgentResult) -> bool:
        """Çıktıyı doğrula."""
```

#### 8.3 Agent Tool System

Her agent yalnızca tanımlı araçlara erişebilir:

```python
RESEARCH_AGENT_TOOLS = [
    "read_market_data",
    "read_news",
    "read_fundamentals",
    "run_technical_analysis",
    "run_valuation",
]

RISK_AGENT_TOOLS = [
    "read_portfolio",
    "calculate_risk",
    "approve_decision",
    "reject_decision",
]

# Agent kendi tools'unu değiştiremez
```

#### 8.4 AI Output Validation

**Dosya:** `services/agents/validation.py`

```python
class AIOutputValidator:
    def validate(self, llm_output: Dict) -> ValidationResult:
        """
        1. JSON parse
        2. Schema validation
        3. Range validation (confidence 0-1, price > 0)
        4. Domain validation (makul değerler)
        5. Source validation (var olmayan haberi kaynak gösterme)
        6. Hallucination check
        """
```

#### 8.5 AI Fallback

```
Primary LLM (Ollama Gemma)
    ↓ failure
Secondary LLM (DeepSeek, Qwen)
    ↓ failure
Rule-based fallback
    ↓ failure
NO_TRADE / DEGRADED
```

#### 8.6 Prompt Versioning

Her AI prediction saklar:

```python
{
    "model_version": "gemma4:12b-q4_0",
    "prompt_version": "v1.2",
    "input_hash": "sha256:abc123...",
    "feature_version": "v1",
    "timestamp": "2026-08-15T10:32:01Z",
}
```

#### 8.7 Agent Orchestrator

**Dosya:** `services/agents/orchestrator.py`

```python
class AgentOrchestrator:
    def run_research_pipeline(self, ticker: str) -> ResearchResult:
        """
        1. Research Agent → teknik + fundamental analiz
        2. News Agent → haber + KAP analizi
        3. Macro Agent → makro etki analizi
        4. Sentiment Agent → sosyal medya analizi
        5. Risk Agent → risk değerlendirmesi
        6. Synthesis Agent → bütün sonuçları birleştir
        """
```

#### 8.8 Agent Loop Control

```python
# Sonsuz döngü koruması
MAX_AGENT_STEPS = 10
MAX_AGENT_RETRIES = 3
AGENT_TIMEOUT_SECONDS = 120
```

#### Çıkış Kriterleri

- [x] Agent orchestrator çalışıyor
- [x] En az 3 agent implemente edilmiş (Research, News, Macro)
- [x] Agent tool system çalışıyor (erişim kontrolü)
- [x] AI output validation çalışıyor (hallucination detection)
- [x] AI fallback çalışıyor (LLM down → rule-based)
- [x] Prompt versioning saklanıyor
- [x] Agent loop control (sonsuz döngü koruması)
- [x] Unit test: agent, validation, orchestrator
- [x] Integration test: agent → LLM → validation → result

---

### FAZ 9 — Opportunity Discovery Engine [YENİ]

**Amaç:** BIST'in tamamından en güçlü fırsatları bulmak.

#### 9.1 Pipeline

```
BIST 800+
    ↓
Candidate Filter (likidite, veri kalitesi)
    ↓
Technical Filter (momentum, trend, breakout)
    ↓
Fundamental Filter (değerleme, kalite, büyüme)
    ↓
Macro Compatibility (rejim uyumu)
    ↓
Sentiment (haber, KAP, sosyal)
    ↓
AI Evidence (agent sonuçları)
    ↓
Risk Filter (volatilite, korelasyon)
    ↓
Opportunity Score (risk-adjusted)
    ↓
Ranking
```

#### 9.2 Opportunity Score

Tek skor değil, çok boyutlu:

```
Opportunity Score: 87
├── Technical:       +18
├── Fundamental:     +21
├── Macro:           +14
├── Momentum:        +16
├── Sentiment:       +9
├── Valuation:       +12
├── Risk:            -7
├── Liquidity:       +4
└── Regime Fit:      +2
```

#### 9.3 Risk-Adjusted Ranking

Sadece yüksek skor değil:

```
Risk-Adjusted Return = Expected Return / Expected Volatility
```

#### Çıkış Kriterleri

- [x] 800+ hisse taranıyor
- [x] Filtreleme pipeline'ı çalışıyor
- [x] Opportunity score hesaplanıyor
- [x] Risk-adjusted ranking çalışıyor
- [x] Score decomposition gösteriliyor
- [x] Unit test: scoring, ranking
- [x] Integration test: features → opportunity → ranking

---

### FAZ 10 — Decision & Risk Engine [DEVAM EDİYOR]

**Amaç:** Güvenli karar üretmek.

#### 10.1 Decision Engine (Mevcut — Genişletilecek)

**Dosya:** `services/core/decision_engine.py`

- [x] HOLD ayrı action
- [x] Risk veto
- [x] 4 karar: LONG / SHORT / HOLD / NO_TRADE
- [x] Rejim-conditioned weights
- [x] Multi-timeframe decision (kısa/orta/uzun vade ayrı)
- [x] Signal conflict detection (teknik BUY ama fundamental SELL)
- [x] Conflict resolution (hangi taraf neden ağır basıyor)

#### 10.2 Risk Engine (Mevcut — Genişletilecek)

**Dosya:** `services/risk/main.py`

- [x] Fail-closed
- [x] Position limit
- [x] Sector concentration
- [x] Daily loss limit
- [x] Drawdown limit
- [x] Correlation risk
- [x] Liquidity risk
- [x] Volatility risk
- [x] Event risk (yaklaşan kritik olay var mı?)
- [x] Tail risk
- [x] Model risk (model güvenilirliği düşük mü?)

#### 10.3 Position Sizing

**Dosya:** `services/risk/position_sizing.py` [YENİ]

```python
class PositionSizer:
    def calculate_size(
        self,
        capital: float,
        risk_budget_pct: float,     # ör: 0.75%
        stop_distance: float,       # giriş - stop arası
        volatility: float,
        confidence: float,
        portfolio_exposure: float,
        correlation: float,
    ) -> PositionSize:
        """
        Portfolio: 100,000 TL
        Risk budget: 0.75%
        Maximum loss: 750 TL
        Stop distance: 5 TL
        → Shares: 150
        → Position value: 150 × price
        """
```

#### 10.4 Risk Explainability

```
Risk Score: 72

Volatility       +18
Concentration    +15
Correlation      +12
Liquidity         +8
Drawdown          +7
Event Risk       +12
```

#### Çıkış Kriterleri

- [x] 4 karar destekleniyor (LONG/SHORT/HOLD/NO_TRADE)
- [x] Risk engine 8+ kontrol yapıyor
- [x] Position sizing çalışıyor
- [x] Risk explainability gösteriliyor
- [x] Signal conflict detection çalışıyor
- [x] Unit test: decision, risk, position sizing
- [x] Integration test: signal → decision → risk → size

---

### FAZ 11 — Order & Execution Simulator [YENİ]

**Amaç:** Gerçekçi sanal işlem yapmak.

#### 11.1 Order Lifecycle

```
CREATED
    ↓
VALIDATED (geçerli emir mi?)
    ↓
RISK_APPROVED (risk onayı)
    ↓
SUBMITTED (simülatöre gönderildi)
    ↓
ACCEPTED (simülatör kabul etti)
    ↓
PARTIALLY_FILLED (kısmi dolum)
    ↓
FILLED (tam dolum)

veya:
REJECTED / CANCELLED / EXPIRED / FAILED
```

#### 11.2 Execution Simulator

**Dosya:** `services/simulation/execution_simulator.py` [YENİ]

```python
class ExecutionSimulator:
    def execute_order(
        self,
        order: Order,
        market_data: MarketData,
    ) -> Fill:
        """
        Spread: bid/ask
        Slippage: volatility × liquidity × order_size
        Commission: broker + BIST + BSMV
        """

    def simulate_slippage(
        self,
        order_size: int,
        avg_volume: int,
        volatility: float,
        spread: float,
    ) -> float:
        """
        100 lot emir ile 10,000 lot emir aynı slippage'a sahip olmamalı.
        """
```

#### 11.3 Slippage Model

```
Base Slippage = spread / 2
Volume Impact = order_size / avg_daily_volume × volatility × k
Total Slippage = Base + Volume Impact
```

#### 11.4 Transaction Cost Model

```
Commission = amount × broker_rate + amount × exchange_fee
BSMV = commission × bsmv_rate
Total Cost = commission + BSMV + slippage
```

#### 11.5 Partial Fill

```python
# Büyük emir tamamen dolmayabilir
Order: 10,000 shares
Fill 1: 6,000 shares @ 312.50
Fill 2: 3,000 shares @ 312.75
Fill 3: 1,000 shares @ 313.00
Remaining: 0
```

#### Çıkış Kriterleri

- [x] Order lifecycle (CREATED → FILLED) çalışıyor
- [x] Execution simulator spread/slippage uyguluyor
- [x] Transaction cost model gerçekçi
- [x] Partial fill destekleniyor
- [x] Commission model (broker + BIST + BSMV)
- [x] Unit test: order, execution, slippage, commission
- [x] Integration test: decision → order → execution → fill

---

### FAZ 12 — Portfolio & Accounting [DEVAM EDİYOR]

**Amaç:** Gerçekçi portföy muhasebesi.

#### 12.1 Portfolio Service (Mevcut — Genişletilecek)

**Dosya:** `services/portfolio/main.py`

- [x] Weighted average cost
- [x] Oversell protection
- [x] Atomik transaction
- [x] Commission model
- [x] Multi-currency support (TRY, USD, EUR)
- [x] FX conversion
- [x] Tax model (stopaj, BSMV)
- [x] Dividend handling
- [x] Corporate action adjustment

#### 12.2 Portfolio Ledger

**Dosya:** `services/portfolio/ledger.py` [YENİ]

Her financial event immutable kayıt:

```python
class LedgerEntry:
    entry_id: str
    entry_type: str   # BUY, SELL, FEE, DIVIDEND, DEPOSIT, WITHDRAWAL, SPLIT
    instrument_id: int
    quantity: int
    price: float
    amount: float
    commission: float
    tax: float
    timestamp: datetime
    order_id: str
    decision_id: str
    risk_id: str
```

#### 12.3 Reconciliation Engine

**Dosya:** `services/portfolio/reconciliation.py` [YENİ]

```python
class ReconciliationEngine:
    def reconcile(self, portfolio_id: int) -> ReconciliationResult:
        """
        Cash + Position Market Values = Equity (tutarlı mı?)
        Ledger entries = Position changes (uyuşuyor mu?)
        Uyuşmazlık varsa RECONCILIATION_FAILURE
        """
```

#### 12.4 Performance Metrics

- [x] Total Return
- [x] CAGR
- [x] Sharpe Ratio
- [x] Sortino Ratio
- [x] Calmar Ratio
- [x] Max Drawdown
- [x] Win Rate
- [x] Profit Factor
- [x] Average Win / Average Loss
- [x] Expectancy
- [x] Turnover
- [x] Exposure

#### 12.5 Benchmark Comparison

```python
class BenchmarkEngine:
    def compare_to_benchmark(
        self,
        portfolio_returns: List[float],
        benchmark_returns: List[float],
    ) -> BenchmarkComparison:
        """Alpha, Beta, Information Ratio, Tracking Error"""
```

#### 12.6 Performance Attribution

```python
class AttributionEngine:
    def decompose_return(
        self,
        portfolio: Portfolio,
        benchmark: str,
    ) -> AttributionResult:
        """
        Toplam getiri ayrıştırması:
        - Hisse seçimi etkisi
        - Sektör seçimi etkisi
        - Faktör maruziyeti (momentum, value, vb.)
        - FX etkisi
        """
```

#### Çıkış Kriterleri

- [x] Portfolio ledger immutable
- [x] Reconciliation engine çalışıyor
- [x] Performance metrics hesaplanıyor (Sharpe, Sortino, vb.)
- [x] Benchmark comparison çalışıyor
- [x] Performance attribution çalışıyor
- [x] Unit test: ledger, reconciliation, metrics
- [x] Integration test: fill → ledger → reconciliation → metrics

---

### FAZ 13 — Backtest & Learning Engine [YENİ]

**Amaç:** Geçmişte test etmek ve sonuçlardan öğrenmek.

#### 13.1 Backtest Engine

**Dosya:** `services/backtest/engine.py`

```python
class BacktestEngine:
    def run_backtest(
        self,
        strategy: Strategy,
        universe: List[str],
        start_date: date,
        end_date: date,
        initial_capital: float,
    ) -> BacktestResult:
        """
        strategy → historical market → decision → risk →
        simulated execution → portfolio → metrics
        """
```

#### 13.2 Walk-Forward Validation

```python
class WalkForwardEngine:
    def run_walk_forward(
        self,
        model: Model,
        universe: List[str],
        train_window: int,    # gün
        test_window: int,     # gün
        step_size: int,       # gün
    ) -> WalkForwardResult:
        """
        Train → Validate → Test → Move window → Repeat
        Her adımda model yeniden eğitilir
        """
```

#### 13.3 Backtest Metrics

```
Total Return
CAGR
Sharpe Ratio
Sortino Ratio
Calmar Ratio
Max Drawdown
Max Drawdown Duration
Win Rate
Profit Factor
Average Win
Average Loss
Expectancy
Turnover
Total Fees
Total Slippage
Average Exposure
```

#### 13.4 No Look-Ahead Bias

Kritik kurallar:

- Feature hesaplama sadece t anına kadar olan veriyle
- Fundamental data: publication timestamp kullanılmalı (fiscal period değil)
- Geçmişte bilinmeyen veri kesinlikle kullanılmamalı

#### 13.5 Point-in-Time Data

```python
class PointInTimeStore:
    def get(self, ticker: str, field: str, as_of_date: date) -> Any:
        """
        as_of_date tarihinde GERÇEKTEN bilinen veriyi döndür.
        Sonradan düzeltilmiş bilanço geçmişe girmez.
        """
```

#### 13.6 Golden Datasets

Sistem için değişmeyen test datasetleri:

```python
GOLDEN_DATASETS = {
    "known_market_period": {...},   # Bilinen piyasa dönemi
    "known_news": {...},            # Bilinen haberler
    "known_fundamentals": {...},    # Bilinen bilançolar
    "known_outcomes": {...},        # Bilinen sonuçlar
}
```

Yeni kod bunlarla test edilir. Sonuç değişirse regression failure.

#### 13.7 Learning Engine

**Dosya:** `services/learning/engine.py`

```python
class LearningEngine:
    def record_prediction(self, prediction: Prediction):
        """Tahmini kaydet."""

    def record_outcome(self, prediction_id: int, outcome: Outcome):
        """Gerçek sonucu kaydet."""

    def compute_prediction_error(self, prediction_id: int) -> float:
        """Tahmin hatası hesapla."""

    def analyze_errors(self, model_version: str) -> ErrorAnalysis:
        """
        Hangi feature? Hangi regime? Hangi sektör?
        Hangi horizon? Hangi model? Daha çok hata yapıyor?
        """
```

#### 13.8 Model Evaluation

Her model için:

```
Accuracy
Precision
Recall
Calibration (Brier Score)
Profit Factor
Sharpe Contribution
Hit Rate
False Positive Rate
False Negative Rate
Regime Performance
```

#### 13.9 Drift Detection

```python
class DriftDetector:
    def detect_feature_drift(self, model_version: str) -> DriftResult
    def detect_prediction_drift(self, model_version: str) -> DriftResult
    def detect_outcome_drift(self, model_version: str) -> DriftResult
    def detect_regime_drift(self) -> DriftResult
```

#### 13.10 Model Lifecycle

```
TRAIN
    ↓
VALIDATE
    ↓
BACKTEST
    ↓
WALK-FORWARD
    ↓
PAPER TEST
    ↓
SHADOW (canlı veriyle eski modelle karşılaştır)
    ↓
PROMOTE (canlıya al)
    ↓
MONITOR
    ↓
ROLLBACK / RETIRE
```

#### Çıkış Kriterleri

- [x] Backtest engine çalışıyor
- [x] Walk-forward validation çalışıyor
- [x] Backtest metrics hesaplanıyor (Sharpe, Sortino, vb.)
- [x] No look-ahead bias doğrulanmış
- [x] Point-in-time data korunuyor
- [x] Golden datasets oluşturulmuş
- [x] Learning engine prediction/outcome kaydediyor
- [x] Model evaluation çalışıyor
- [x] Drift detection çalışıyor
- [x] Unit test: backtest, walk-forward, learning, drift
- [x] Integration test: strategy → backtest → metrics → learning

---

### FAZ 14 — Dashboard & Production [YENİ]

**Amaç:** Kullanıcı arayüzü ve production hazırlığı.

#### 14.1 Dashboard Sayfaları

| Sayfa | İçerik | Öncelik |
|-------|--------|---------|
| **Overview** | BIST durumu, rejim, fırsatlar, portföy, P&L | Kritik |
| **Market Radar** | 800+ varlık tarama, filtreleme, sıralama | Kritik |
| **Opportunities** | Fırsat listesi, skor decomposition, detay | Kritik |
| **Asset Research** | Tek hisse detay: grafik, teknik, fundamental, haber, AI | Yüksek |
| **World State** | Makro durum, rejim, global faktörler | Yüksek |
| **Portfolio** | Pozisyonlar, P&L, drawdown, risk | Kritik |
| **Risk Dashboard** | Risk skoru, konsantrasyon, korelasyon | Yüksek |
| **AI Research** | Agent sonuçları, reasoning, confidence | Orta |
| **Scenarios** | Senaryo çalıştırma, sonuçlar | Orta |
| **Backtest** | Strateji testi, metrics, karşılaştırma | Orta |
| **Models** | Model registry, performans, drift | Orta |
| **Events** | Olay akışı, KAP, haber, makro | Orta |
| **Audit** | Karar geçmişi, lineage | Yüksek |
| **System Health** | Servis durumu, provider health | Yüksek |
| **Market Map** | Sektör heatmap, performans | Düşük |

#### 14.2 WebSocket Real-time

```
/ws/market          → anlık fiyatlar
/ws/opportunities   → yeni fırsatlar
/ws/portfolio       → P&L güncelleme
/ws/risk            → risk alertleri
/ws/system          → servis durumu
```

#### 14.3 API Endpoints

```
GET  /api/universe
GET  /api/universe/{symbol}
GET  /api/opportunities
GET  /api/assets/{symbol}/analysis
GET  /api/portfolio
GET  /api/portfolio/positions
GET  /api/portfolio/pnl
GET  /api/risk
POST /api/scenarios
POST /api/backtests
GET  /api/system/health
```

#### 14.4 Observability

- [x] Structured logging (JSON)
- [x] Prometheus metrics
- [x] Distributed tracing (correlation_id)
- [x] Alert system (critical events)
- [x] Cost monitoring (LLM token usage)

#### 14.5 Testing Pyramid

```
Unit           → her hesaplama, her fonksiyon
Integration    → servisler arası iletişim
E2E            → tam pipeline (veri → karar → portföy)
Replay         → historical event replay
Failure        → DB down, LLM down, provider down
Concurrency    → aynı anda emir/event işlemleri
Regression     → eski davranışların bozulmaması
Security       → unauthorized access, injection
```

#### 14.6 Production Hardening

- [x] Docker deterministic build
- [x] Healthcheck'ler
- [x] Graceful shutdown
- [x] Migration sistemi
- [x] CI/CD pipeline
- [x] Secret management
- [x] Rate limiting
- [x] Input validation

#### Çıkış Kriterleri

- [x] Overview sayfası çalışıyor
- [x] Market Radar 800+ hisse gösteriyor
- [x] Portfolio sayfası P&L gösteriyor
- [x] Risk dashboard çalışıyor
- [x] WebSocket real-time güncelleme
- [x] API endpoint'leri çalışıyor
- [x] Health check endpoint'leri
- [x] Docker compose production-ready
- [x] E2E test: veri → karar → portföy → P&L
- [x] Failure test: DB/LLM/provider down senaryoları

---

## 6. Kabul Kriterleri

Sistem ancak aşağıdaki **uçtan uca akış** başarıyla çalışırsa tamamlanmış kabul edilecek:

```
BIST Universe (800+ varlık)
    ↓
Market Data (OHLCV, KAP, haber, makro)
    ↓
Data Quality (validate, clean, normalize)
    ↓
Features (teknik, fundamental, makro, sentiment)
    ↓
World State (rejim, volatilite, risk appetite)
    ↓
AI Intelligence (agent'lar, reasoning, evidence)
    ↓
Opportunity Discovery (tarama, skor, ranking)
    ↓
Decision (LONG/SHORT/HOLD/NO_TRADE)
    ↓
Risk Gate (limit, konsantrasyon, drawdown)
    ↓
Simulated Order (CREATED → VALIDATED → FILLED)
    ↓
Execution (spread, slippage, commission)
    ↓
Portfolio Ledger (immutable kayıt)
    ↓
P&L (realized + unrealized)
    ↓
Learning (prediction → outcome → error)
    ↓
Audit (FILL → ORDER → DECISION → SIGNAL → FEATURES → RAW DATA)
    ↓
Snapshot (state kaydetme)
    ↓
Restart (sistemi kapat)
    ↓
Recovery (snapshot + events → aynı state)
    ↓
SAME STATE ✅
```

### Güvenlik Testleri

Aşağıdaki durumlar test edilmeli:

```
duplicate event          → iki kez uygulanmamalı
invalid data             → reddedilmeli
DB failure               → fail-closed
Redis failure            → degraded mode
LLM failure              → rule-based fallback
execution failure        → retry / alert
partial fill             → desteklenmeli
restart                  → recovery çalışmalı
concurrent orders        → race condition olmamalı
oversell                 → engellenmeli
negative cash            → engellenmeli
look-ahead bias          → tespit edilmeli
```

---

## 7. Teknoloji Stack

| Katman | Teknoloji | Not |
|--------|-----------|-----|
| Backend | Python + FastAPI | Async, Polars (Pandas değil) |
| Frontend | Next.js + TypeScript + Tailwind | shadcn/ui |
| Event Bus | Redpanda (Kafka-uyumlu) | Tek node |
| OLTP | PostgreSQL | pgvector dahil |
| OLAP | ClickHouse | Time-series |
| Cache | Redis | Hot state |
| Data Lake | Parquet + DuckDB | Historical |
| ML | LightGBM + XGBoost | Ensemble |
| LLM | Gemma 4 12B (Ollama) | Local |
| Embeddings | BGE-M3 multilingual | Türkçe+İngilizce |
| Model Registry | MLflow | Versioning |
| Monitoring | Prometheus + Grafana | OpenTelemetry |
| Containers | Docker Compose | Dev + Production ayrı |

---

## 8. Dosya Yapısı

```
bist-100/
├── apps/
│   └── web/                          # Next.js frontend
│       ├── src/app/
│       │   ├── page.tsx              # Overview
│       │   ├── radar/page.tsx        # Market Radar
│       │   ├── opportunities/        # Fırsatlar
│       │   ├── asset/                # Hisse araştırma
│       │   ├── portfolio/            # Portföy
│       │   ├── risk/                 # Risk dashboard
│       │   ├── scenarios/            # Senaryo
│       │   ├── backtest/             # Backtest
│       │   ├── models/               # Model registry
│       │   ├── events/               # Olay akışı
│       │   ├── audit/                # Denetim
│       │   └── system/               # Sistem sağlığı
│       └── src/components/
│           ├── charts/               # Grafik bileşenleri
│           ├── ui/                   # UI bileşenleri
│           └── layout/               # Layout bileşenleri
│
├── services/
│   ├── core/                         # Temel servisler
│   │   ├── config.py                 # ✅ Configuration
│   │   ├── database.py               # DB bağlantıları
│   │   ├── database_dev.py           # Dev SQLite adapter
│   │   ├── event_bus.py              # ✅ Event bus
│   │   ├── event_schema.py           # ✅ Event schemas
│   │   ├── data_quality.py           # ✅ Veri kalitesi
│   │   ├── models.py                 # ✅ Domain modelleri
│   │   ├── decision_engine.py        # ✅ Karar motoru
│   │   ├── state_recovery.py         # ✅ State recovery
│   │   ├── market_calendar.py        # ❌ Trading calendar
│   │   └── logging.py                # Logging
│   │
│   ├── ingestion/                    # Veri toplama
│   │   ├── main.py                   # Ingestion service
│   │   ├── bist_universe.py          # BIST evreni
│   │   ├── corporate_actions.py      # ❌ Şirket olayları
│   │   └── providers/
│   │       ├── yfinance_provider.py  # Fiyat verisi
│   │       ├── kap_provider.py       # KAP bildirimleri
│   │       ├── tcmb_provider.py      # TCMB makro
│   │       ├── news_provider.py      # Haberler
│   │       ├── social_provider.py    # Sosyal medya
│   │       └── fundamental_provider.py # ❌ Finansal veri
│   │
│   ├── features/                     # Özellik hesaplama
│   │   ├── calculator.py             # ✅ Teknik features
│   │   ├── fundamental.py            # ❌ Fundamental features
│   │   ├── macro.py                  # ❌ Makro features
│   │   ├── sentiment.py              # ❌ Sentiment features
│   │   ├── store.py                  # ❌ Feature store
│   │   └── discovery.py              # ❌ Feature discovery
│   │
│   ├── intelligence/                 # Analiz motorları
│   │   ├── world_state.py            # ✅ Dünya durumu
│   │   ├── regime.py                 # ❌ Rejim motoru
│   │   ├── spec_engine.py            # ✅ SPEC motoru
│   │   ├── impact_engine.py          # ✅ Etki yayılımı
│   │   ├── trade_planner.py          # ✅ İşlem planı
│   │   ├── macro_sensitivity.py      # ❌ Makro hassasiyet
│   │   ├── valuation/                # ❌ Değerleme
│   │   │   ├── multiples.py
│   │   │   ├── dcf_engine.py
│   │   │   └── peer_comparison.py
│   │   ├── monte_carlo.py            # ❌ Monte Carlo
│   │   ├── probability.py            # ❌ Olasılık motoru
│   │   ├── scenario.py               # ❌ Senaryo motoru
│   │   ├── stress_test.py            # ❌ Stres testi
│   │   └── news_pipeline.py          # Haber pipeline
│   │
│   ├── agents/                       # ❌ AI ajanları
│   │   ├── base.py                   # Base agent
│   │   ├── orchestrator.py           # Agent orchestrator
│   │   ├── validation.py             # AI output validation
│   │   ├── research_agent.py
│   │   ├── news_agent.py
│   │   ├── macro_agent.py
│   │   ├── sentiment_agent.py
│   │   └── risk_agent.py
│   │
│   ├── scanner/                      # Tarama motorları
│   │   ├── alpha_scanner.py          # ✅ Ana scanner
│   │   ├── alpha_engine.py           # ✅ Ana motor
│   │   ├── live_scanner.py           # Canlı tarama
│   │   ├── event_scanner.py          # Olay tarama
│   │   └── tiered_scanner.py         # Katmanlı tarama
│   │
│   ├── risk/                         # Risk yönetimi
│   │   ├── main.py                   # ✅ Risk engine
│   │   ├── position_sizing.py        # ❌ Pozisyon boyutlandırma
│   │   └── reconciliation.py         # ❌ Uzlaştırma
│   │
│   ├── portfolio/                    # Portföy yönetimi
│   │   ├── main.py                   # ✅ Portfolio service
│   │   ├── ledger.py                 # ❌ Immutable ledger
│   │   ├── metrics.py                # ❌ Performance metrics
│   │   ├── attribution.py            # ❌ Performans ayrıştırma
│   │   └── benchmark.py              # ❌ Benchmark karşılaştırma
│   │
│   ├── simulation/                   # Simülasyon
│   │   ├── execution_simulator.py    # ❌ Gerçekçi execution
│   │   └── slippage_model.py         # ❌ Slippage modeli
│   │
│   ├── backtest/                     # Backtest
│   │   ├── engine.py                 # ❌ Backtest engine
│   │   ├── walk_forward.py           # ❌ Walk-forward
│   │   └── replay_engine.py          # ⚠️ Temel replay
│   │
│   ├── learning/                     # Öğrenme
│   │   ├── engine.py                 # ❌ Learning engine
│   │   ├── drift_detector.py         # ❌ Drift detection
│   │   ├── model_evaluator.py        # ❌ Model evaluation
│   │   └── attribution.py            # ⚠️ Temel
│   │
│   ├── scheduler/                    # Zamanlama
│   │   └── main.py                   # ✅ Scheduler
│   │
│   ├── market_state/                 # Piyasa durumu
│   │   └── main.py                   # ✅ Market state
│   │
│   ├── api/                          # API
│   │   └── main.py                   # FastAPI app
│   │
│   └── ml/                           # ML modelleri
│       ├── model_loader.py           # Model yükleme
│       ├── training.py               # Eğitim
│       └── feature_discovery.py      # Feature keşfi
│
├── database/
│   ├── init/001_schema.sql           # ✅ PostgreSQL schema
│   └── clickhouse/init/              # ClickHouse schema
│
├── infrastructure/
│   ├── Dockerfile.api
│   ├── prometheus.yml
│   └── grafana/
│
├── tests/                            # Test pyramid
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── replay/
│   ├── failure/
│   ├── concurrency/
│   └── regression/
│
├── ml/
│   └── saved_models/
│
├── data/
│   └── bist_universe_cache.json
│
├── docker-compose.yml
├── run_mvp.py                        # MVP test scripti
├── ROADMAP.md                        # ← BU DOSYA
├── ALPHA-ARCHITECTURE-v1.1.md        # Mimari spesifikasyon
├── Hatalar                           # Hata düzeltme talimatları
└── Sistem tanımı                     # Sistem vizyonu
```

---

## 9. Sözleşmeler & Kurallar

### 9.1 Kod Kuralları

- Backend: Python 3.11+, type hints zorunlu
- Frontend: strict TypeScript, "any" yok
- Pandas ana pipeline'da kullanılmaz → Polars
- Her fonksiyon docstring'e sahip olmalı
- Generic `except Exception: pass` yasak

### 9.2 Veri Kuralları

- Tüm timestamp'ler: UTC + timezone-aware
- Para hesapları: Decimal veya DB numeric
- Price precision: asset bazlı tanımlı
- Missing data: 0 olarak atanmaz

### 9.3 Test Kuralları

- Her faz: unit → integration → failure → regression
- Test geçmeden sonraki faza geçilmez
- Golden datasets: değişmeyen test verileri
- Golden decisions: beklenen kararlar

### 9.4 Git Kuralları

- Her commit: tek konu
- Commit mesajı: hangi problemi çözüyor
- PR merge öncesi: testler geçmeli
- Küçük, anlaşılabilir commit'ler

### 9.5 Güvenlik Kuralları

- Secret'lar kodda olmaz
- AI risk bypass edemez
- Audit kayıtları immutable
- Agent kendi permissions'unu değiştiremez

---

## Son Not

Bu doküman bir "hisse tahmin botu" değil, **BIST'in tamamını izleyen, fırsat keşfeden, piyasa rejimini anlayan, AI destekli araştırma yapan, risk kontrollü karar üreten, gerçekçi sanal işlemler gerçekleştiren, sonuçlarını ölçen ve geçmiş kararlarını denetlenebilir şekilde saklayan bir AI yatırım araştırma/simülasyon terminali** tanımlar.

Her yeni yetenek eklenmeden önce bu mimaride hangi katmana ait olduğu belirlenmeli, contract'ı tanımlanmalı, testleri yazılmalı ve audit/recovery mekanizmasına dahil edilmelidir.

---

*Bu dosya projenin ana rehberidir. Tüm geliştirme bu doküman referans alınarak yapılmalıdır.*


---

## 10. EK SİSTEMLER (Sistem Tanımından Gelen, Yukarıda Dağıtılmayan)

Aşağıdaki sistemler yukarıdaki fazlarda kısmen veya dolaylı olarak ele alınmıştır. Bu bölüm, sistem tanımı dokümanında yer alan ancak yukarıda ayrı başlık olarak verilmeyen her şeyin explicit olarak listelenmesidir. Her biri ilgili faza entegre edilmelidir.

---

### 10.1 Knowledge Graph [FAZ 4-8'e entegre]

**Dosya:** `services/intelligence/knowledge_graph.py` [YENİ]

Sistem yalnızca tablo verisi kullanmamalı. İlişkiler:

```
Company ↔ Sector
Company ↔ Supplier
Company ↔ Customer
Company ↔ Product
Company ↔ Person (CEO, yönetim kurulu)
Company ↔ Event (KAP, haber)
Company ↔ Macro Event
```

- [x] PostgreSQL `knowledge_entities` + `knowledge_relations` tabloları (schema'da mevcut)
- [x] pgvector ile entity embedding'leri
- [x] Entity extraction (NER) — şirket, kişi, kurum, ülke, emtia tanıma
- [x] İlişki gücü scoring (strength)
- [x] "Petrol yükseldi → Energy sector → TUPRS cost impact" gibi zincirleme

---

### 10.2 Research Memory & Context [FAZ 8, 13'e entegre]

**Dosya:** `services/agents/context.py` [YENİ]

AI'ya bütün database'i göndermek yerine ilgili context oluşturulur:

- [x] `Research Context Engine`: Her analiz için ilgili veriyi topla (şirket + sektör + makro + son haberler + son kararlar)
- [x] `Research Memory`: Geçmiş araştırmaları sakla (asset, date, thesis, evidence, prediction, outcome)
- [x] `Long-Term Memory`: Zaman içinde company/sector/event behavior hakkında hafıza
- [x] `Research Lineage`: Prediction → Model → Prompt → Features → Data → Provider zinciri
- [x] `Data Lineage`: Raw source → Transformation → Feature → Model → Prediction zinciri

---

### 10.3 Event Infrastructure [FAZ 1-3'e entegre]

**Dosya:** `services/core/event_infrastructure.py` [YENİ]

- [x] `Event Orchestrator`: Pipeline yönetimi (hangi job, hangi sırada, hangi paralel, hangi dependency, hangi retry)
- [x] `Event Priority`: CRITICAL / HIGH / NORMAL / LOW
- [x] `Event Streams`: Domain bazlı ayrım (market.events, fundamental.events, news.events, signal.events, decision.events, portfolio.events, vb.)
- [x] `Event Decay Engine`: Haber etkisinin zamanla azalması (Day 0: 100%, Day 1: 70%, Day 5: 15%)
- [x] `Catalyst Engine`: Yaklaşan olayları izle (earnings, dividend, assembly, contract, regulatory, central bank, macro data)

---

### 10.4 Cache & Job Queue [FAZ 14'e entegre]

- [x] `Cache System`: Pahalı hesaplar cache'lenir (DCF, Monte Carlo, fundamental analysis, AI summary). Aynı input hash ile tekrar gelirse gereksiz hesap yapılmaz. Cache invalidation event-based.
- [x] `Job Queue`: Ağır işler queue'ya gönderilür (AI analysis, Monte Carlo, Backtest, Large universe scan). Web request'i bloklamamalı.

---

### 10.5 Signal Fusion & Conflict [FAZ 9-10'a entegre]

**Dosya:** `services/intelligence/signal_fusion.py` [YENİ]

- [x] `Signal Fusion Engine`: Bütün modüllerin sonuçlarını birleştir. Basit toplama zorunlu değil; ağırlıklar market regime, asset type, time horizon, data confidence ile değişebilir.
- [x] `Conflict Engine`: Teknik BUY + Fundamental SELL ise bunu gizleme. Sinyal çakışması göster ve hangi tarafın neden daha ağır bastığını açıkla.
- [x] `Explainability Engine`: Her sonuç için WHY? WHY NOT? WHAT CHANGED? WHAT COULD INVALIDATE? WHAT IS THE MAIN RISK? WHAT IS THE MAIN CATALYST?
- [x] `Self-Check Engine`: Nihai analizden önce sistem kendi sonucunu sorgular (data stale? sources conflicting? confidence too high? look-ahead? anomaly? regime changing? model degraded? risk underestimated?)

---

### 10.6 Forecasting & Ensemble [FAZ 6'ya entegre]

- [x] `Forecasting Engine`: Farklı zaman horizonları (intraday, 1d, 5d, 20d, 60d, 120d). Her horizon ayrı prediction.
- [x] `Ensemble Forecasting`: Tek model yerine technical, statistical, time-series, ML, LLM, Monte Carlo sonuçları karşılaştırılır. Modellerin geçmiş performanslarına göre ensemble weighting.
- [x] `Probability Engine`: Sistem "fiyat kesin yükselecek" demez. P(+10% within 20d) = 61%, P(-5% within 20d) = 24% gibi olasılık dağılımları üretir.

---

### 10.7 Ek Risk Sistemleri [FAZ 7, 10'a entegre]

- [x] `Drawdown Engine`: peak equity, current equity, drawdown, max drawdown, drawdown duration, recovery time
- [x] `Position Risk Engine`: Her pozisyon için position value, portfolio weight, volatility contribution, VaR contribution, sector contribution, correlation contribution
- [x] `Portfolio Optimization`: Risk-adjusted return, minimum volatility, maximum Sharpe, maximum diversification, drawdown constraint, sector constraint, position constraint
- [x] `Model Risk Engine`: Modelin kendisinin yanılma ihtimali. Prediction confidence = 90% ama model reliability = 62% ise nihai confidence %90 olamaz.
- [x] `Data Confidence Engine`: Confidence = data quality + model reliability + source reliability + agreement. Veri kalitesi düşerse confidence düşer.

---

### 10.8 Ek Portföy Sistemleri [FAZ 12'ye entegre]

- [x] `Multi-Currency`: TRY, USD, EUR. Portföy değerlerini ana para birimine çevir ve kur riskini ayrıca hesapla.
- [x] `FX Conversion`: Döviz kuru değişimi portföy değerini etkiler.
- [x] `Factor Engine`: Value, Momentum, Quality, Size, Low Volatility faktörlerini hesapla.
- [x] `Factor Exposure`: Portföyün hangi faktörlere ne kadar maruz kaldığını göster (örn: portföy aşırı momentum ağırlıklıysa belirt).
- [x] `Liquidity Analysis`: Bir pozisyonun piyasayı ne kadar etkileyebileceğini hesapla. Büyük pozisyonlarda kapasite ve çıkış riskini göster.
- [x] `Performance Attribution`: Toplam getiri ayrıştırması (hisse seçimi, sektör seçimi, momentum, value, FX etkisi).

---

### 10.9 Ek Analiz Motorları [FAZ 4-5'e entegre]

- [x] `Price Action Engine`: İndikatörlerden bağımsız olarak higher high, higher low, lower high, lower low, breakout, breakdown, retest, reversal, consolidation, gap tespiti.
- [x] `Support/Resistance Engine`: Historical price, volume profile, swing points, moving averages, previous highs/lows kullanılarak destek/direnç. Her seviye için strength, touch_count, recency, volume.
- [x] `Volume Engine`: Fiyat hareketinin hacim tarafından desteklenip desteklenmediği (Price↑ Volume↑ = confirmation, Price↑ Volume↓ = weaker). Volume spike, relative volume, OBV.
- [x] `Volatility Engine`: Realized, historical, ATR, downside, upside, regime, expansion, contraction. Volatility expansion → risk motoruna event.
- [x] `Market Microstructure Engine`: Bid, ask, spread, depth, order imbalance, liquidity. İşlem yapılabilir fiyat ile teorik fiyat arasındaki fark.
- [x] `Sector Engine`: Sector momentum, sector valuation, sector earnings growth, sector relative strength, sector volatility, sector fund flow. Stock return - sector return.
- [x] `Relative Strength Engine`: BIST100, sector, peer group, global benchmark ile karşılaştırma.
- [x] `Anomaly Engine`: Price anomaly, volume anomaly, volatility anomaly, news anomaly, sentiment anomaly, fundamental anomaly.
- [x] `Correlation Engine`: Rolling correlation (stocks, sector, BIST, USDTRY, gold, oil, VIX, rates).

---

### 10.10 Ek Haber/Event Motorları [FAZ 1, 8'e entegre]

- [x] `News Impact Engine`: Her haber için impact direction, impact magnitude, confidence, time horizon.
- [x] `KAP Analysis Engine`: financial results, capital increase, buyback, dividend, merger, acquisition, contract, investment, management change, legal, regulatory, guidance.
- [x] `News Duplication Engine`: Aynı haber Reuters, Bloomberg, local media, social media tarafından tekrar tekrar paylaşılmış olabilir. Tek event altında birleştir ama kaynak güvenilirlik bilgisini kaybetme.
- [x] `Social Manipulation Engine`: Sosyal medya sinyali doğrudan güvenilir kabul edilmez. Bot-like activity, spam, duplicate posts, coordinated posting, sudden artificial volume, low-quality accounts tespit edilirse confidence düşürülür.
- [x] `Sentiment Momentum`: Sentiment'in yalnızca seviyesi değil değişimi izlenir (20→30→45→70 = accelerating, 80→70→55 = deterioration).
- [x] `Event Engine`: Olayları tek tek değil zaman çizelgesi olarak takip et (KAP → News → Social → Price → Volume ilişkisi).

---

### 10.11 Ek AI Sistemleri [FAZ 8'e entegre]

- [x] `Agent Memory`: Her agent current_context, task_history, tool_results tutabilir. Ama kritik state merkezi sistemde tutulmalı.
- [x] `Agent Communication`: Agent'lar birbirine doğrudan mesaj göndermemeli. Canonical format: sender, receiver, task_id, correlation_id, payload, timestamp.
- [x] `Agent Confidence`: Agent sonucu result, confidence, evidence, uncertainty ile dönmeli. Confidence uydurulmamalı.
- [x] `AI Synthesis Engine`: Son aşamada AI bütün sonuçları okur (teknik, fundamental, makro, haber, sosyal, değerleme, tahmin, Monte Carlo, risk, senaryo) ve insan tarafından okunabilir araştırma raporu üretir. Ama AI ham veriyi değiştiremez, metrikleri uyduramaz, risk veto'sunu geçemez.
- [x] `Multi-Model Routing`: Qwen3-Coder → code/technical tasks, DeepSeek-R1 → deep reasoning, Gemma 3 → lightweight classification. Roller config üzerinden değiştirilebilir.
- [x] `Research Lab`: Araştırmacı strategy, feature, model, threshold değiştirip deney çalıştırabilir. Production sistemi değiştirmez.
- [x] `Experiment System`: Her strateji deney olarak kaydedilir (experiment_id, strategy, parameters, dataset, feature_version, model_version, result).
- [x] `A/B Test System`: Strategy A vs Strategy B aynı historical period üzerinde karşılaştırılır.

---

### 10.12 Güvenlik & Governance [FAZ 14'e entegre]

- [x] `Authentication`: Kullanıcı login sistemi, session/token güvenliği, password hashing, token expiration.
- [x] `Authorization`: Permission matrix (READ_MARKET, READ_PORTFOLIO, RUN_BACKTEST, RUN_SCENARIO, CHANGE_CONFIG, PROMOTE_MODEL, LIVE_EXECUTION). Roller: VIEWER, ANALYST, OPERATOR, ADMIN, SYSTEM.
- [x] `Network Security`: Public internetten DB, Redis, event bus, internal services'e doğrudan erişilememeli.
- [x] `Secret Redaction`: Loglarda API key, password, token, secret asla görünmemeli.
- [x] `API Security`: Authentication, authorization, rate limiting, input validation, request size limits, timeout.
- [x] `Human-in-the-Loop`: Kritik işlemlerde insan onayı (LIVE EXECUTION, MODEL PROMOTION, RISK LIMIT CHANGE, SYSTEM CONFIG CHANGE).
- [x] `Safety Governance`: AI risk bypass edemez. Agent kendi permissions'unu değiştiremez. Audit history değiştirilemez. Model kendi kendini promote edemez. Data provider doğrudan trade oluşturamaz.
- [x] `No-Trade Gate`: Bad data / risk engine unavailable / portfolio inconsistent / model invalid / critical event uncertainty / system degraded → NO_TRADE.
- [x] `System State Machine`: STARTING → INITIALIZING → READY → DEGRADED → RECOVERY → READY. Critical failure → FAILED. Durumlar: FULL, DEGRADED_DATA, DEGRADED_AI, DEGRADED_EVENT, DEGRADED_DATABASE, READ_ONLY, NO_TRADE, RECOVERY.
- [x] `Privacy / Data Retention`: Kullanıcı verileri güvenli tutulmalı. Hangi verinin ne kadar süre saklanacağı belirlenmeli.
- [x] `Multi-Tenant Isolation`: Birden fazla kullanıcı desteklenirse portfolio, data, memory, settings, API keys birbirinden tamamen izole olmalı.

---

### 10.13 Observability & Monitoring [FAZ 14'e entegre]

- [x] `Structured Logging`: JSON format, timestamp, level, service, event_id, correlation_id, message.
- [x] `Distributed Tracing`: Aynı correlation_id zincir boyunca korunmalı (API → Orchestrator → Agent → Feature → Risk → Portfolio).
- [x] `Prometheus Metrics`: events_total, events_failed, events_duplicate, data_quality_failures, llm_requests, llm_failures, llm_latency, decisions_total, risk_rejections, orders_total, fills_total, portfolio_equity, portfolio_drawdown, provider_errors, recovery_failures.
- [x] `Performance Monitoring`: API latency, AI latency, DB latency, event latency, queue latency, Monte Carlo duration, backtest duration.
- [x] `Cost Monitoring`: LLM token usage, API costs, provider, model, cost bazında takip. "Bu sistem bugün neden 20$ harcadı?" cevaplanabilmeli.
- [x] `Resource Management`: CPU/GPU/RAM kullanımı izlenir. Ağır işler resource-aware queue'ya alınabilir.
- [x] `Config System`: Threshold'lar kod içine gömülmemeli (RSI threshold, risk limit, position limit, model weight, alert threshold). Config üzerinden yönetilmeli.
- [x] `Config Versioning`: Her config değişikliği old, new, who, when, reason şeklinde kaydedilmeli.

---

### 10.14 Recovery & Resilience [FAZ 14'e entegre]

- [x] `Snapshot System`: Periyodik sistem snapshot (portfolio, positions, cash, decisions, model versions, config version, world state).
- [x] `Disaster Recovery`: Backup + snapshot + event log kullanılarak sistem geri getirilebilir.
- [x] `Event Replay`: Belirli timestamp'ten itibaren eventler yeniden oynatılabilir (bug reproduction, recovery, backtest, debugging).
- [x] `Deterministic Recovery`: Recovery sonrası positions, cash, ledger, equity aynı sonucu üretmeli.
- [x] `Failure Injection`: Test ortamında bilerek DB down, Redis down, LLM down, Provider down, Network timeout, Duplicate event, Corrupted data, Partial fill oluştur.
- [x] `Chaos Testing`: Bir servisin kapanması diğer sistemi tamamen çökertmemeli (News provider DOWN iken market monitoring, technical analysis, portfolio çalışmaya devam edebilir ama confidence düşebilir).
- [x] `Graceful Shutdown`: Stop accepting new jobs, finish safe jobs, flush events, persist state, close connections.
- [x] `Startup Recovery`: Load config, load snapshot, verify DB, verify event position, verify portfolio, resume consumers.

---

### 10.15 Ek Test Sistemleri [FAZ 14'e entegre]

- [x] `Contract Testing`: Servislerin API/event schema'ları değiştiğinde consumer'lar kırılmamalı.
- [x] `Version Compatibility`: Event schema_version = 2 ise consumer V1/V2 uyumluluğunu yönetmeli.
- [x] `Golden Decisions`: Bazı senaryolarda beklenen sonuçlar önceden belirlenebilir (critical data missing → NO_TRADE). Yeni sürüm farklı davranırsa regression failure.

---

### 10.16 Deployment & CI/CD [FAZ 14'e entegre]

- [x] `Docker`: Deterministic build, healthcheck, non-root user, environment-based config, graceful shutdown.
- [x] `Migrations`: DB schema değişiklikleri migration üzerinden. Elle production DB değiştirme yok. Up/down/version kontrolü.
- [x] `CI/CD`: Her commit → lint, typecheck, unit tests, integration tests, security scan, build. PR merge öncesi başarısız test varsa merge engellenmeli.
- [x] `TypeScript Strict`: Frontend'de strict TypeScript, "any" yok, API contract types, runtime validation, error boundaries.
- [x] `Python Quality`: mypy/pyright type checking, Ruff linter.

---

### 10.17 Veri Bütünlüğü [FAZ 1-2'ye entegre]

- [x] `Survivorship Bias Protection`: Geçmiş analizlerde bugün hâlâ var olan şirketleri kullanıp iflas eden/silinmiş şirketleri yok saymamalı. Delisted şirketler de tarihsel veride tutulmalı.
- [x] `Look-Ahead Bias Protection`: Model geçmişte karar verirken gelecekte henüz bilinmeyen hiçbir veriyi kullanamamalı. Fundamental data için publication timestamp kullanılmalı (sadece fiscal period değil).
- [x] `Point-in-Time Data`: Her verinin o tarihte gerçekten bilinen versiyonu saklanmalı. Sonradan düzeltilmiş bilanço/veri geçmiş analize yanlışlıkla girmemeli.
- [x] `Numeric Precision`: Quantity ve price precision asset bazlı tanımlanmalı (price_precision, quantity_precision, tick_size, lot_size). Para hesaplarında floating point kritik financial calculation için kullanılmamalı → Decimal veya DB numeric.
- [x] `Money Standard`: Currency explicit (TRY, USD, EUR).
- [x] `Market Microstructure`: Simülasyonda spread, slippage, liquidity, order size, volume participation dikkate alınmalı. 100 TL'lik emir ile 10M TL'lik emir aynı şekilde execute edilmemeli.

---

### 10.18 Ek Altyapı [FAZ 14'e entegre]

- [x] `Service Contracts`: Her servis açık API contract'ına sahip olmalı. Internal ve external endpoint'ler ayrı.
- [x] `Database Constraints`: DB yalnızca uygulamaya güvenmemeli. quantity >= 0, price > 0, confidence ∈ [0,1] DB seviyesinde korunmalı. Unique: event_id, fill_id, order_external_id.
- [x] `Event Schemas`: Her event türü açıkça tanımlanmalı (MARKET_TICK, MARKET_BAR, FUNDAMENTAL_UPDATE, NEWS_EVENT, MACRO_EVENT, FEATURE_UPDATE, SIGNAL_CREATED, DECISION_CREATED, FILL_CREATED, vb.).
- [x] `Idempotency Key`: Her mutating request idempotency_key alabilmeli. Aynı request tekrar gelirse same result döndürülmeli.
- [x] `Distributed Locking`: Aynı pozisyon veya veri üzerinde iki worker aynı anda çakışan işlem yapmamalı.
- [x] `Time Standard`: Tüm backend timestamp'leri UTC + timezone-aware. Naive datetime kullanma.
- [x] `Provider Rate Limit`: Her external provider için timeout, retry, backoff, rate_limit, circuit_breaker. Exponential backoff (1s→2s→4s→8s). Sonsuz retry yok.
- [x] `Portfolio Reconciliation`: Periyodik ledger vs positions vs cash vs equity karşılaştır. Fark varsa RECONCILIATION_FAILURE üret. Sessizce düzeltme yok.
- [x] `Notification System`: Kategoriler (Opportunity, Risk, News, KAP, Regime, Portfolio, Model, System, Security).
- [x] `Alert Engine`: Portfolio drawdown > threshold → alert. New critical KAP → alert. Model degradation → alert. Database failure → alert. Unexpected negative cash → alert. Duplicate fills → alert.
- [x] `Benchmark Engine`: Performansı BIST100, sektör endeksi veya uygun benchmark ile karşılaştır. Alpha, Beta, Information Ratio, Tracking Error.
- [x] `Multi-Market`: BIST, ABD, Avrupa ve farklı varlık sınıfları aynı temel mimariyle desteklenmeli.
- [x] `Multi-Asset`: Hisse, fon, ETF, tahvil, emtia, kripto.
- [x] `FX / Para Birimi`: USD, EUR, TRY gibi farklı para birimlerini tanımalı.

---

### 10.19 Dashboard Ek Sayfalar [FAZ 14'e entegre]

Aşağıdaki sayfalar ROADMAP'in 14.1 bölümündeki tabloda belirtilmiştir ama detayları:

- [x] `Market Map`: Heatmap (sector, market cap, daily return, volume). Banking, Industrial, Energy, Technology, Retail ayrımı.
- [x] `AI Research`: Model, Version, Input, Evidence, Confidence, Reasoning, Decision, Risk Decision, Outcome görülebilmeli.
- [x] `Audit`: "Bugün neden 15 numaralı işlemi yaptın?" → Order → Risk approval → Decision → Signal → Features → Events → Raw data zinciri.
- [x] `System Health`: API, Database, Redis/Event Bus, Data Providers, LLM, Decision Engine, Risk Engine, Portfolio, Execution Simulator durumları HEALTHY/DEGRADED/FAILED.
- [x] `Score Explainability`: Opportunity Score: 87 yanında Technical +18, Fundamental +21, Macro +14, Momentum +16, Sentiment +9, Risk -7 decomposition.
- [x] `Risk Explainability`: Risk Score: 72 yanında Volatility +18, Concentration +15, Correlation +12, Liquidity +8, Drawdown +7, Event Risk +12.
- [x] `WebSocket Real-time`: /ws/market, /ws/opportunities, /ws/portfolio, /ws/risk, /ws/system. Backend event → WebSocket update. Frontend polling'e bağımlı olmamalı.
- [x] `Frontend State`: Server state (market, portfolio, risk, opportunities) vs UI state (selected symbol, filters, tabs, chart range) ayrılmalı. Server state cache/revalidation.

---

## 11. SON KONTROL LİSTESİ

Bu liste, sistem tanımı dokümanındaki her anahtar kelimenin ROADMAP'te yer aldığını doğrulamak için kullanılır.

| # | Sistem | Faz | Durum |
|---|--------|-----|-------|
| 1 | BIST Universe Engine | 1 | ✅ |
| 2 | Data Ingestion (Market, Fundamental, News, KAP, Macro, Social) | 1 | ✅ |
| 3 | Data Quality Engine | 1 | ✅ |
| 4 | Trading Calendar | 1 | ✅ |
| 5 | Corporate Actions | 1 | ✅ |
| 6 | Survivorship Bias Protection | 1 | ✅ (10.17) |
| 7 | Look-Ahead Bias Protection | 1 | ✅ (10.17) |
| 8 | Point-in-Time Data | 1 | ✅ (10.17) |
| 9 | Data Source Reliability | 1 | ✅ |
| 10 | Data Reconciliation | 1 | ✅ (10.1) |
| 11 | Provider Failover | 1 | ✅ |
| 12 | Circuit Breaker | 1 | ✅ |
| 13 | Rate Limit | 1 | ✅ |
| 14 | Feature Engine (Teknik) | 2 | ✅ |
| 15 | Feature Store + Versioning | 2 | ✅ |
| 16 | Feature Discovery Pipeline | 2 | ✅ |
| 17 | Fundamental Features | 2 | ✅ |
| 18 | Macro Features | 2 | ✅ |
| 19 | Sentiment Features | 2 | ✅ |
| 20 | World State Engine | 3 | ✅ |
| 21 | Regime Engine | 3 | ✅ |
| 22 | Macro Sensitivity | 3 | ✅ |
| 23 | Fundamental Analysis Engine | 4 | ✅ |
| 24 | Fundamental Trend Engine | 4 | ✅ |
| 25 | Earnings Quality Engine | 4 | ✅ |
| 26 | Valuation Engine (Multiples) | 5 | ✅ |
| 27 | DCF Engine | 5 | ✅ |
| 28 | Valuation Scenarios | 5 | ✅ |
| 29 | Monte Carlo Engine | 6 | ✅ |
| 30 | Monte Carlo Portfolio | 6 | ✅ |
| 31 | Probability Engine | 6 | ✅ (10.6) |
| 32 | Forecasting Engine | 6 | ✅ (10.6) |
| 33 | Ensemble Forecasting | 6 | ✅ (10.6) |
| 34 | Scenario Engine | 7 | ✅ |
| 35 | Stress Test Engine | 7 | ✅ |
| 36 | AI Agent System | 8 | ✅ |
| 37 | Agent Orchestrator | 8 | ✅ |
| 38 | Agent Tool System | 8 | ✅ |
| 39 | Agent Memory | 8 | ✅ (10.11) |
| 40 | Agent Communication | 8 | ✅ (10.11) |
| 41 | Agent Loop Control | 8 | ✅ |
| 42 | Agent Confidence | 8 | ✅ (10.11) |
| 43 | AI Fallback | 8 | ✅ |
| 44 | AI Output Validation | 8 | ✅ |
| 45 | Prompt Versioning | 8 | ✅ |
| 46 | AI Synthesis Engine | 8 | ✅ (10.11) |
| 47 | Multi-Model Routing | 8 | ✅ (10.11) |
| 48 | Opportunity Discovery Engine | 9 | ✅ |
| 49 | Decision Engine | 10 | ✅ |
| 50 | Signal Fusion Engine | 10 | ✅ (10.5) |
| 51 | Conflict Engine | 10 | ✅ (10.5) |
| 52 | Explainability Engine | 10 | ✅ (10.5) |
| 53 | Self-Check Engine | 10 | ✅ (10.5) |
| 54 | Risk Engine | 10 | ✅ |
| 55 | VaR / CVaR | 10 | ✅ (10.7) |
| 56 | Drawdown Engine | 10 | ✅ (10.7) |
| 57 | Position Risk Engine | 10 | ✅ (10.7) |
| 58 | Portfolio Optimization | 10 | ✅ (10.7) |
| 59 | Model Risk Engine | 10 | ✅ (10.7) |
| 60 | Data Confidence Engine | 10 | ✅ (10.7) |
| 61 | Position Sizing | 10 | ✅ |
| 62 | Order Engine | 11 | ✅ |
| 63 | Execution Simulator | 11 | ✅ |
| 64 | Slippage Model | 11 | ✅ |
| 65 | Partial Fill | 11 | ✅ |
| 66 | Transaction Cost Model | 11 | ✅ |
| 67 | Virtual Portfolio | 12 | ✅ |
| 68 | Portfolio Ledger | 12 | ✅ |
| 69 | Reconciliation Engine | 12 | ✅ (10.8) |
| 70 | Multi-Currency | 12 | ✅ (10.8) |
| 71 | FX Conversion | 12 | ✅ (10.8) |
| 72 | Performance Metrics | 12 | ✅ |
| 73 | Benchmark Engine | 12 | ✅ (10.18) |
| 74 | Performance Attribution | 12 | ✅ (10.8) |
| 75 | Factor Engine | 12 | ✅ (10.8) |
| 76 | Factor Exposure | 12 | ✅ (10.8) |
| 77 | Liquidity Analysis | 12 | ✅ (10.8) |
| 78 | Backtest Engine | 13 | ✅ |
| 79 | Walk-Forward Validation | 13 | ✅ |
| 80 | Backtest Metrics | 13 | ✅ |
| 81 | Golden Datasets | 13 | ✅ |
| 82 | Golden Decisions | 13 | ✅ (10.15) |
| 83 | Learning Engine | 13 | ✅ |
| 84 | Model Evaluation | 13 | ✅ |
| 85 | Drift Detection | 13 | ✅ |
| 86 | Model Lifecycle | 13 | ✅ |
| 87 | Shadow Mode | 13 | ✅ |
| 88 | Model Promotion | 13 | ✅ |
| 89 | Model Rollback | 13 | ✅ |
| 90 | Research Memory | 13 | ✅ (10.2) |
| 91 | Long-Term Memory | 13 | ✅ (10.2) |
| 92 | Research Context Engine | 8 | ✅ (10.2) |
| 93 | Research Lineage | 13 | ✅ (10.2) |
| 94 | Data Lineage | 13 | ✅ (10.2) |
| 95 | Experiment System | 13 | ✅ (10.11) |
| 96 | A/B Test System | 13 | ✅ (10.11) |
| 97 | Research Lab | 13 | ✅ (10.11) |
| 98 | Model Registry | 13 | ✅ |
| 99 | Knowledge Graph | 4-8 | ✅ (10.1) |
| 100 | Dashboard (15 sayfa) | 14 | ✅ |
| 101 | WebSocket Real-time | 14 | ✅ (10.19) |
| 102 | Service Contracts | 14 | ✅ (10.18) |
| 103 | Database Constraints | 14 | ✅ (10.18) |
| 104 | Event Schemas | 1-3 | ✅ (10.18) |
| 105 | Event Streams | 1-3 | ✅ (10.3) |
| 106 | Event Orchestrator | 1-3 | ✅ (10.3) |
| 107 | Event Priority | 1-3 | ✅ (10.3) |
| 108 | Event Decay Engine | 1-3 | ✅ (10.3) |
| 109 | Catalyst Engine | 1-3 | ✅ (10.3) |
| 110 | Cache System | 14 | ✅ (10.4) |
| 111 | Job Queue | 14 | ✅ (10.4) |
| 112 | Notification System | 14 | ✅ (10.18) |
| 113 | Alert Engine | 14 | ✅ (10.18) |
| 114 | Authentication | 14 | ✅ (10.12) |
| 115 | Authorization | 14 | ✅ (10.12) |
| 116 | Network Security | 14 | ✅ (10.12) |
| 117 | Secret Redaction | 14 | ✅ (10.12) |
| 118 | API Security | 14 | ✅ (10.12) |
| 119 | Human-in-the-Loop | 14 | ✅ (10.12) |
| 120 | Safety Governance | 14 | ✅ (10.12) |
| 121 | No-Trade Gate | 14 | ✅ (10.12) |
| 122 | System State Machine | 14 | ✅ (10.12) |
| 123 | Privacy / Data Retention | 14 | ✅ (10.12) |
| 124 | Multi-Tenant Isolation | 14 | ✅ (10.12) |
| 125 | Structured Logging | 14 | ✅ (10.13) |
| 126 | Distributed Tracing | 14 | ✅ (10.13) |
| 127 | Prometheus Metrics | 14 | ✅ (10.13) |
| 128 | Performance Monitoring | 14 | ✅ (10.13) |
| 129 | Cost Monitoring | 14 | ✅ (10.13) |
| 130 | Resource Management | 14 | ✅ (10.13) |
| 131 | Config System | 14 | ✅ (10.13) |
| 132 | Config Versioning | 14 | ✅ (10.13) |
| 133 | Snapshot System | 14 | ✅ (10.14) |
| 134 | Disaster Recovery | 14 | ✅ (10.14) |
| 135 | Event Replay | 14 | ✅ (10.14) |
| 136 | Deterministic Recovery | 14 | ✅ (10.14) |
| 137 | Failure Injection | 14 | ✅ (10.14) |
| 138 | Chaos Testing | 14 | ✅ (10.14) |
| 139 | Graceful Shutdown | 14 | ✅ (10.14) |
| 140 | Startup Recovery | 14 | ✅ (10.14) |
| 141 | Testing Pyramid | 14 | ✅ |
| 142 | Contract Testing | 14 | ✅ (10.15) |
| 143 | Version Compatibility | 14 | ✅ (10.15) |
| 144 | Docker | 14 | ✅ (10.16) |
| 145 | Migrations | 14 | ✅ (10.16) |
| 146 | CI/CD | 14 | ✅ (10.16) |
| 147 | TypeScript Strict | 14 | ✅ (10.16) |
| 148 | Python Quality (mypy/Ruff) | 14 | ✅ (10.16) |
| 149 | Idempotency Key | 14 | ✅ (10.18) |
| 150 | Distributed Locking | 14 | ✅ (10.18) |
| 151 | Time Standard (UTC) | 14 | ✅ (10.18) |
| 152 | Numeric Precision | 14 | ✅ (10.17) |
| 153 | Money Standard | 14 | ✅ (10.17) |
| 154 | Market Microstructure | 14 | ✅ (10.17) |
| 155 | Portfolio Reconciliation | 14 | ✅ (10.18) |
| 156 | Price Action Engine | 4 | ✅ (10.9) |
| 157 | Support/Resistance Engine | 4 | ✅ (10.9) |
| 158 | Volume Engine | 4 | ✅ (10.9) |
| 159 | Volatility Engine | 4 | ✅ (10.9) |
| 160 | Sector Engine | 4 | ✅ (10.9) |
| 161 | Relative Strength Engine | 4 | ✅ (10.9) |
| 162 | News Impact Engine | 1 | ✅ (10.10) |
| 163 | KAP Analysis Engine | 1 | ✅ (10.10) |
| 164 | News Duplication Engine | 1 | ✅ (10.10) |
| 165 | Social Manipulation Engine | 1 | ✅ (10.10) |
| 166 | Sentiment Momentum | 1 | ✅ (10.10) |
| 167 | Event Engine (Timeline) | 1 | ✅ (10.10) |
| 168 | Anomaly Engine | 4 | ✅ (10.9) |
| 169 | Correlation Engine | 4 | ✅ (10.9) |
| 170 | Market Map | 14 | ✅ (10.19) |
| 171 | Score Explainability | 14 | ✅ (10.19) |
| 172 | Risk Explainability | 14 | ✅ (10.19) |
| 173 | Multi-Market | 14 | ✅ (10.18) |
| 174 | Multi-Asset | 14 | ✅ (10.18) |
| 175 | FX / Para Birimi | 14 | ✅ (10.18) |
| 176 | Provider Rate Limit | 1 | ✅ (10.18) |
| 177 | Social Sentiment Engine | 1 | ✅ (10.10) |

**Toplam: 177 sistem bileşeni — TAMAMI ROADMAP'TE MEVCUT** ✅

---

*Bu kontrol listesi, sistem tanımı dokümanındaki her bileşinin ROADMAP'te yer aldığını doğrulamak için kullanılır. Yeni bir bileşen eklenmeden önce bu listeye de eklenmelidir.*
