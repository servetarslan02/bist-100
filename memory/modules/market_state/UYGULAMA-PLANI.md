# 🚀 Market State Engine — Nihai Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:**
- Gupta et al. (2025) — "A forest of opinions: Multi-model ensemble-HMM voting framework" (DSFE 5(4):466-501)
- Springer Regime-Aware Adaptive Forecasting (2026)
- Two Sigma — ML Approach to Regime Modeling
- arXiv RMATS (2026) — Hierarchical HMM for regime boundary detection
- MDPI Regime-Aware LightGBM (2026) — Rolling HMM her 63 günde yeniden eğitim
- StockCharts — McClellan Oscillator, Summation Index, TRIN

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Entegrasyon Noktaları](#3-entegrasyon-noktaları)
4. [Nihai Mimari Tasarım](#4-nihai-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 En Olgun Referans: Multi-Model Ensemble-HMM Voting (Gupta et al. 2025)

**Kaynak:** https://doi.org/10.3934/DSFE.2025019

**Mimari:**
- **3 yöntem** ensemble: Bagging (Random Forest), Boosting (XGBoost/LightGBM), HMM
- **Hybrid Voting Classifier**: HMM + ensemble model oylaması
- **Feature set**: Makroekonomik + teknik göstergeler (geniş feature set)
- **Rejimler**: Bull, Bear, Neutral (3 rejim)
- **Sonuç**: Regime-aware strateji, S&P 500 ve Russell 3000'de başarılı

**Kritik Tasarım Kararları:**
| Karar | Gupta | Bizim Uygulama |
|-------|-------|----------------|
| Ensemble yöntemi | Voting classifier | Weighted voting (ağırlıklı oylama) |
| HMM rolü | Oy veren 1 | Ana matematiksel model + oy |
| Feature sayısı | 15+ | 20+ (mevcut + yeni) |
| Rejim sayısı | 3 | 11 (mevcut) → 4 HMM + 11 skor bazlı |
| Rolling window | Sabit | 63 gün (quarterly) |

**Dersler:**
- ✅ **Ensemble > tek model** — HMM tek başına yetersiz, ensemble gerekli
- ✅ **Voting classifier** — basit ama etkili consensus mekanizması
- ✅ **Geniş feature set** — makro + teknik birlikte daha iyi
- ⚠️ **3 rejim yetersiz** — BIST için 11 rejim daha uygun (mevcut sistem doğru yolda)

### 1.2 Two Sigma — ML Approach to Regime Modeling

**Kaynak:** https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/

**Yaklaşım:**
- Gaussian Mixture Model (GMM) ile faktör bazlı rejim tespiti
- Factor-level regime detection (her faktör kendi rejimini tespit eder)
- Cross-sectional regime (tüm piyasa değil, sektörel)

**Dersler:**
- ✅ **GMM alternatif olarak** — HMM'ye göre daha basit, daha hızlı
- ✅ **Factor-level regime** — tek piyasa rejimi yerine faktör bazlı
- ⚠️ **GMM eksikliği** — temporal dependency yok (HMM var)

### 1.3 Regime-Aware Adaptive Forecasting (Springer 2026)

**Kaynak:** Springer (2026)

**Yaklaşım:**
- Regime detection → regime-specific forecasting model
- Meta-learning: farklı rejimlerde farklı model ağırlıkları
- Rolling HMM: her 63 günde yeniden eğitim

**Dersler:**
- ✅ **Regime-specific model weights** — zaten mevcut (`get_regime_weights()`)
- ✅ **Rolling 63 gün** — quarterly re-training optimal
- ✅ **Meta-learning** — rejime göre strateji değişimi

### 1.4 Market Breadth — En İyi Uygulama

**Kaynak:** StockCharts, Blueberry Markets

**Göstergeler:**

| Gösterge | Formül | Yorum |
|----------|--------|-------|
| **AD Line** | Cumulative(Advancing - Declining) | Trend confirmation |
| **AD Ratio** | Advancing / Declining | >2 = aşırı, <0.5 = aşırı satım |
| **McClellan Oscillator** | EMA(19) of Net Advances - EMA(39) of Net Advances | Momentum breadth |
| **McClellan Summation** | Cumulative(McClellan Oscillator) | Uzun vadeli breadth |
| **TRIN (Arms Index)** | (AD Ratio) / (Volume Ratio) | <1 = bullish, >1 = bearish |
| **New Highs - New Lows** | 52-week high yapan - low yapan | Güçlü breadth teyidi |
| **Breadth Thrust** | Advancing / (Advancing + Declining) | >0.615 = strong thrust |

### 1.5 BIST-Specific Bulgular

**Kaynak:** ScienceDirect, MDPI

**BIST'e özgü zorluklar:**
- **Yüksek döviz volatilitesi** — USD/TRY rejimleri doğrudan etkiler
- **Siyasi risk premium** — jeopolitik risk BIST'te belirgin
- **Enflasyonist ortam** — reel faiz negatif olduğunda farklı dinamik
- **Sektörel konsantrasyon** — bankacılık %35+ ağırlık
- **Düşük likidite** — küçük hisselerde breadth göstergeleri yanıltıcı

**Çözüm:** BIST-specific eşikler ve normalize yöntemleri

---

## 2. Mevcut Sistem Analizi

### 2.1 Dosya Yapısı

```
services/market_state/
├── __init__.py
└── main.py                  # 354 satır — MarketStateService

services/intelligence/
├── regime.py                # 357 satır — RegimeEngine (11 rejim, skor bazlı)
├── hmm_regime.py            # 280 satır — HMMRegimeDetector (4 rejim, HMM)
└── world_state.py           # 294 satır — WorldStateManager (10 latent factor)

services/macro/
└── regime_detector.py       # Macro regime detection (referenced but not examined)
```

### 2.2 Mevcut Durum Özeti

| Bileşen | Dosya | Satır | Durum | Açıklama |
|---------|-------|-------|-------|----------|
| **MarketStateService** | main.py | 354 | ⚠️ Basit | Tek başına çalışıyor, basit breadth/regime |
| **RegimeEngine** | regime.py | 357 | ✅ İyi | 11 rejim, skor bazlı, transition matrix |
| **HMMRegimeDetector** | hmm_regime.py | 280 | ✅ İyi | 4 rejim, rolling HMM, rule-based fallback |
| **WorldStateManager** | world_state.py | 294 | ✅ İyi | 10 latent factor, event-driven güncelleme |
| **Macro Regime** | regime_detector.py | ? | ⚠️ Bilinmiyor | Referans var, entegrasyon zayıf |

### 2.3 Güçlü Yönler ✅

1. **RegimeEngine — 11 rejim tanımı**: BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL, RISK_ON, RISK_OFF, CRISIS, RECOVERY, MOMENTUM_EXPANSION, MOMENTUM_CONTRACTION
2. **HMM entegrasyonu zaten var**: `hmm_regime.py` — rolling 63 gün, 4 rejim, rule-based fallback
3. **Regime-conditioned model weights**: `get_regime_weights()` — her rejimde farklı strateji ağırlıkları
4. **Transition matrix**: `get_transition_matrix()` — rejim geçiş olasılıkları
5. **WorldStateManager**: 10 latent factor, event-driven güncelleme, decay mekanizması
6. **RegimeEngine zaten HMM ile entegre**: `detect_regime()` içinde HMM skorlarını rule-based ile birleştiriyor (%30 HMM, %70 rule-based)

### 2.4 Kritik Eksiklikler ❌

| # | Eksiklik | Etki | Öncelik |
|---|----------|------|---------|
| 1 | **İki ayrı regime detection** — main.py `_detect_regime()` vs regime.py `RegimeEngine` | Tutarsız rejim | 🔴 Kritik |
| 2 | **Market breadth çok basit** — sadece advancing/declining oranı | Breadth derinliği eksik | 🔴 Kritik |
| 3 | **Liquidity state yok** | Likidite krizi geç tespit | 🟡 Yüksek |
| 4 | **Sentiment state yok** | Fear/greed indeksi eksik | 🟡 Yüksek |
| 5 | **Regime transition tracking eksik** | Rejim kararlılığı bilinmiyor | 🟡 Yüksek |
| 6 | **Multi-timeframe state yok** | Farklı zaman ufuklarında farklı state | 🟠 Orta |
| 7 | **Macro → Market State entegrasyonu zayıf** | Makro ortam yansımıyor | 🟡 Yüksek |
| 8 | **Ensemble voting yok** | Tek yöntem yetersiz | 🟠 Orta |
| 9 | **Anomaly state basit** | Anomaly derinliği eksik | 🟠 Orta |
| 10 | **BIST-specific normalize yok** | Döviz volatilitesi yanlış etki | 🟡 Yüksek |

### 2.5 İki Ayrı Regime Detection Sorunu

**Sorun:** `market_state/main.py`'de `_detect_regime()` basit threshold-based, `intelligence/regime.py`'de `RegimeEngine` gelişmiş skor bazlı. İkisi farklı sonuçlar verebilir.

**main.py._detect_regime():**
```python
def _detect_regime(self, breadth, momentum, volatility, rsi) -> str:
    if breadth < 20 and volatility > 40: return "PANIC"
    if breadth < 35: return "RISK-OFF"
    if volatility > 35: return "HIGH-VOLATILITY"
    if breadth > 65 and momentum > 0: return "TRENDING-UP"
    # ... basit threshold'lar
```

**regime.py.RegimeEngine.detect_regime():**
```python
# 11 rejim için skor hesapla, en yüksek skorlu rejimi seç
# HMM entegrasyonu, macro entegrasyonu
# Confidence = en yüksek - ikinci skor arası fark
```

**Çözüm:** main.py'deki `_detect_regime()`'yi kaldır, `RegimeEngine`'i canonical yap.

---

## 3. Entegrasyon Noktaları

### 3.1 Mevcut Pipeline

```
market_data → features → regime → signal_fusion → decision → risk → portfolio
                   ↑           ↑
              (63+ feature)  (RegimeEngine)
```

### 3.2 Hedef Pipeline

```
market_data → features → [MARKET STATE ENGINE] → signal_fusion → decision → risk → portfolio
                              ↑
                    ┌─────────┴─────────┐
                    │  MarketStateService │
                    │  - Breadth Engine   │
                    │  - Momentum State   │
                    │  - Volatility State │
                    │  - Volume State     │
                    │  - RSI State        │
                    │  - Liquidity State  │  ← YENİ
                    │  - Sentiment State  │  ← YENİ
                    │  - Macro State      │
                    │  - Anomaly State    │
                    │  - Ensemble Regime  │  ← YENİ
                    │  - Transition Track │  ← YENİ
                    │  - Multi-TF State   │  ← YENİ
                    └─────────┬─────────┘
                              ↓
                    market_state_changed event
                              ↓
                    signal_fusion, decision_engine, risk_gate
```

### 3.3 Event Bus Entegrasyonu

```python
# Mevcut event types
EventType.MARKET_STATE_CHANGED  # Zaten var

# Yeni event types eklenecek
EventType.BREADTH_ALERT         # Breadth aşırı seviyede
EventType.LIQUIDITY_ALERT       # Likidite krizi
EventType.REGIME_TRANSITION     # Rejim değişimi
EventType.ANOMALY_CLUSTER       # Anomaly kümesi tespit
```

### 3.4 Config Entegrasyonu

```python
# services/core/config.py'ya eklenecek
class MarketStateSettings(BaseModel):
    # Breadth
    breadth_mcclellan_ema_short: int = 19
    breadth_mcclellan_ema_long: int = 39
    breadth_thrust_threshold: float = 0.615

    # Regime
    regime_hmm_weight: float = 0.3
    regime_score_weight: float = 0.7
    regime_rolling_window: int = 63
    regime_confidence_min: float = 0.3

    # Liquidity
    liquidity_spread_threshold: float = 0.02
    liquidity_volume_participation_min: float = 0.005

    # Sentiment
    sentiment_news_weight: float = 0.5
    sentiment_social_weight: float = 0.3
    sentiment_options_weight: float = 0.2

    # Risk appetite (ağırlıklar)
    risk_appetite_breadth_weight: float = 0.30
    risk_appetite_momentum_weight: float = 0.20
    risk_appetite_volatility_weight: float = 0.20
    risk_appetite_rsi_weight: float = 0.10
    risk_appetite_sentiment_weight: float = 0.10
    risk_appetite_macro_weight: float = 0.10

    # Multi-timeframe
    multi_tf_intraday_interval: str = "15min"
    multi_tf_daily_interval: str = "1d"
    multi_tf_weekly_interval: str = "1w"
    multi_tf_monthly_interval: str = "1M"

    # Transition tracking
    transition_history_max: int = 1000
    transition_stability_window: int = 20
```

---

## 4. Nihai Mimari Tasarım

### 4.1 Market State Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MARKET STATE ENGINE v2.0                          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  DATA INPUTS                                                 │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │  Ticks   │ │ Features │ │  Macro   │ │  News    │       │   │
│  │  │ (800+)   │ │ (63+)    │ │ (15+)    │ │ Sentiment│       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MARKET BREADTH ENGINE (YENİ — Genişletilmiş)                │   │
│  │  - Advance-Decline Line (cumulative)                         │   │
│  │  - AD Ratio (advancing / declining)                          │   │
│  │  - McClellan Oscillator (EMA19 - EMA39 of net advances)     │   │
│  │  - McClellan Summation Index (cumulative McClellan)          │   │
│  │  - TRIN / Arms Index (AD ratio / volume ratio)              │   │
│  │  - New Highs - New Lows (52-week)                           │   │
│  │  - Breadth Thrust (advancing / total)                        │   │
│  │  - Breadth State: BROAD / NEUTRAL / NARROW                  │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  COMPONENT STATES (Her biri ayrı hesaplanır)                 │   │
│  │                                                              │   │
│  │  Momentum State: avg momentum, ROC, ADX, trend strength     │   │
│  │  Volatility State: avg realized vol, VIX, vol regime        │   │
│  │  Volume State: avg volume z-score, volume trend, OBV        │   │
│  │  RSI State: avg RSI, % overbought, % oversold              │   │
│  │  Liquidity State: spread, depth, participation ← YENİ       │   │
│  │  Sentiment State: news, social, fear/greed ← YENİ           │   │
│  │  Macro State: macro regime, macro risk appetite             │   │
│  │  Anomaly State: count, severity, sector clustering          │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  ENSEMBLE REGIME DETECTION (YENİ — 3 Yöntem)                │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │   │
│  │  │  HMM     │  │  Skor    │  │  GMM     │                  │   │
│  │  │  Model   │  │  Bazlı   │  │ (YENİ)   │                  │   │
│  │  │  (%30)   │  │  (%50)   │  │  (%20)   │                  │   │
│  │  └──────────┘  └──────────┘  └──────────┘                  │   │
│  │       ↓              ↓              ↓                       │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Ensemble Voting (weighted majority)                  │  │   │
│  │  │  - Her yöntem oy verir                               │  │   │
│  │  │  - Ağırlıklar: skor %50, HMM %30, GMM %20           │  │   │
│  │  │  - Consensus yoksa → en yüksek confidence            │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                              │   │
│  │  Rejimler: 11 (BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL,   │   │
│  │            RISK_ON, RISK_OFF, CRISIS, RECOVERY,             │   │
│  │            MOMENTUM_EXPANSION, MOMENTUM_CONTRACTION)        │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  REGIME TRANSITION TRACKER (YENİ)                            │   │
│  │  - Transition history (ne zaman değişti)                     │   │
│  │  - Average duration (ortalama süre)                          │   │
│  │  - Stability score (kararlılık skoru)                        │   │
│  │  - Transition probability matrix                             │   │
│  │  - Regime confidence trend (artıyor mu azalıyor mu)          │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  RISK APPETITE (Gelişmiş — 6 Faktör)                        │   │
│  │  - Breadth katkısı (0.30)                                    │   │
│  │  - Momentum katkısı (0.20)                                   │   │
│  │  - Volatility katkısı (0.20)                                 │   │
│  │  - RSI katkısı (0.10)                                        │   │
│  │  - Sentiment katkısı (0.10) ← YENİ                          │   │
│  │  - Macro katkısı (0.10) ← YENİ                              │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MULTI-TIMEFRAME STATE (YENİ)                                │   │
│  │  - Intraday state (15 dakikalık)                             │   │
│  │  - Daily state (günlük)                                      │   │
│  │  - Weekly state (haftalık)                                   │   │
│  │  - Monthly state (aylık)                                     │   │
│  │  - Cross-timeframe comparison (uyumsuzluk tespiti)           │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             ↓                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MARKET STATE OUTPUT                                         │   │
│  │  {                                                           │   │
│  │    "timestamp": "2026-08-19T04:00:00Z",                     │   │
│  │    "regime": "BULL",                                         │   │
│  │    "regime_confidence": 0.78,                                │   │
│  │    "regime_method": "ensemble_voting",                       │   │
│  │    "regime_stability": 0.85,                                 │   │
│  │    "regime_duration_days": 15,                               │   │
│  │    "breadth": {                                              │   │
│  │      "pct_advancing": 68.5,                                  │   │
│  │      "ad_line": 145,                                         │   │
│  │      "ad_ratio": 2.18,                                       │   │
│  │      "mcclellan_osc": 45.2,                                  │   │
│  │      "mcclellan_summation": 1234,                            │   │
│  │      "trin": 0.85,                                           │   │
│  │      "new_highs": 45,                                        │   │
│  │      "new_lows": 12,                                         │   │
│  │      "breadth_thrust": 0.685,                                │   │
│  │      "breadth_state": "BROAD"                                │   │
│  │    },                                                        │   │
│  │    "momentum_state": "POSITIVE",                             │   │
│  │    "volatility_state": "NORMAL",                             │   │
│  │    "volume_state": "ABOVE_AVERAGE",                          │   │
│  │    "rsi_state": "NEUTRAL",                                   │   │
│  │    "liquidity_state": "NORMAL",                              │   │
│  │    "sentiment_state": "POSITIVE",                            │   │
│  │    "macro_state": "EXPANSION",                               │   │
│  │    "risk_appetite": 0.72,                                    │   │
│  │    "anomaly_count": 3,                                       │   │
│  │    "daily_state": {...},                                     │   │
│  │    "weekly_state": {...},                                    │   │
│  │    "hmm_probabilities": {                                    │   │
│  │      "BULL": 0.65, "BEAR": 0.10,                            │   │
│  │      "HIGH_VOL": 0.15, "LOW_VOL": 0.10                      │   │
│  │    }                                                         │   │
│  │  }                                                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Dosya Yapısı (Hedef)

```
services/market_state/
├── __init__.py
├── main.py                    # REFACTOR — MarketStateService (ana orkestratör)
├── breadth_engine.py          # YENİ — Market Breadth (AD, McClellan, TRIN)
├── component_states.py        # YENİ — Momentum, Vol, Volume, RSI, Liquidity, Sentiment
├── ensemble_regime.py         # YENİ — Ensemble Regime Detection (HMM + Skor + GMM)
├── transition_tracker.py      # YENİ — Regime Transition Tracking
├── risk_appetite.py           # YENİ — 6 faktörlü risk appetite
├── multi_timeframe.py         # YENİ — Multi-timeframe state
└── output_formatter.py        # YENİ — Market state output formatı

services/intelligence/
├── regime.py                  # MEVCUT — Canonical regime engine (düzenlenecek)
├── hmm_regime.py              # MEVCUT — HMM regime detector (düzenlenecek)
└── world_state.py             # MEVCUT — World state manager (entegre edilecek)
```

---

## 5. Faz Planı

### FAZ 0: Temel Altyapı ve Refactor (1-2 gün)

**Amaç:** İki ayrı regime detection sorununu çöz, temel altyapıyı hazırla.

#### 0.1 — Canonical Regime Detection
- [ ] `market_state/main.py`'deki `_detect_regime()`'yi kaldır
- [ ] `_compute_market_state()`'de `RegimeEngine`'i kullan
- [ ] API endpoint'lerini tek kaynağa bağla
- [ ] Test: iki farklı yerden aynı rejim çıktığını doğrula

#### 0.2 — Config Tanımları
- [ ] `MarketStateSettings` ekle (`services/core/config.py`)
- [ ] Breadth eşikleri, regime ağırlıkları, risk appetite ağırlıkları
- [ ] Multi-timeframe interval ayarları

#### 0.3 — Event Schema Genişletme
- [ ] Yeni event type'ları: `BREADTH_ALERT`, `LIQUIDITY_ALERT`, `REGIME_TRANSITION`
- [ ] Event payload şemaları

**Teslimat:** `pytest tests/test_market_state_faz0.py` — canonical regime, config, events

---

### FAZ 1: Market Breadth Engine (2-3 gün)

**Amaç:** Breadth göstergelerini genişlet.

#### 1.1 — Breadth Engine
```python
# services/market_state/breadth_engine.py

class MarketBreadthEngine:
    """Piyasa genişliği hesaplama — 7 gösterge."""

    def compute(self, instrument_states: List[Dict],
                ad_history: List[int] = None) -> BreadthResult:
        """
        Hesaplanan göstergeler:
        1. Advance-Decline Line (cumulative)
        2. AD Ratio (advancing / declining)
        3. McClellan Oscillator (EMA19 - EMA39 of net advances)
        4. McClellan Summation Index (cumulative McClellan)
        5. TRIN / Arms Index
        6. New Highs - New Lows
        7. Breadth Thrust
        """
        ...

    def _compute_mcclellan(self, net_advances: List[int],
                           short_ema: int = 19,
                           long_ema: int = 39) -> float:
        """McClellan Oscillator = EMA(19) - EMA(39) of net advances."""
        ...

    def _compute_trin(self, advancing: int, declining: int,
                      advancing_vol: float, declining_vol: float) -> float:
        """TRIN = (AD Ratio) / (Volume Ratio). <1 bullish, >1 bearish."""
        ...
```

#### 1.2 — Breadth Alert System
- [ ] Breadth aşırı seviyelerde alert üret
- [ ] McClellan > +100 veya < -100 → alert
- [ ] TRIN > 1.5 veya < 0.5 → alert
- [ ] Breadth Thrust > 0.615 → strong thrust alert

#### 1.3 — BIST-Specific Normalize
- [ ] BIST'te düşük likidite olan hisseleri hariç tut (volume eşiği)
- [ ] Sektörel breadth (bankacılık, sanayi, teknoloji ayrı)
- [ ] Döviz etkisini breadth'den izole et

**Teslimat:** `pytest tests/test_market_state_faz1.py` — breadth hesaplama, alert, normalize

---

### FAZ 2: Component States (2-3 gün)

**Amaç:** Her bileşen için ayrı state hesaplama.

#### 2.1 — Component States Modülü
```python
# services/market_state/component_states.py

class ComponentStateEngine:
    """Piyasa bileşenlerinin ayrı ayrı state hesaplaması."""

    def compute_momentum_state(self, instrument_states: List[Dict]) -> str:
        """POSITIVE / NEGATIVE / NEUTRAL"""
        ...

    def compute_volatility_state(self, instrument_states: List[Dict],
                                  vix_level: float = None) -> str:
        """LOW / NORMAL / HIGH / EXTREME"""
        ...

    def compute_volume_state(self, instrument_states: List[Dict]) -> str:
        """BELOW_AVERAGE / AVERAGE / ABOVE_AVERAGE / SURGE"""
        ...

    def compute_rsi_state(self, instrument_states: List[Dict]) -> str:
        """OVERSOLD / NEUTRAL / OVERBOUGHT"""
        ...

    def compute_liquidity_state(self, instrument_states: List[Dict]) -> str:
        """TIGHT / NORMAL / LOOSE"""
        # Spread, depth, volume participation
        ...

    def compute_sentiment_state(self, news_sentiment: float = None,
                                 social_sentiment: float = None) -> str:
        """NEGATIVE / NEUTRAL / POSITIVE / EUPHORIA"""
        ...

    def compute_anomaly_state(self, instrument_states: List[Dict]) -> Dict:
        """Anomaly count, severity, sector clustering."""
        ...
```

#### 2.2 — Liquidity State (YENİ)
- [ ] Average spread (bid-ask)
- [ ] Volume participation (hacim / ortalama hacim)
- [ ] Market depth (derinlik)
- [ ] Liquidity regime: TIGHT / NORMAL / LOOSE

#### 2.3 — Sentiment State (YENİ)
- [ ] News sentiment score (mevcut news agent'dan)
- [ ] Social sentiment score (varsa)
- [ ] Fear/Greed composite
- [ ] Sentiment regime: NEGATIVE / NEUTRAL / POSITIVE / EUPHORIA

**Teslimat:** `pytest tests/test_market_state_faz2.py` — tüm component states

---

### FAZ 3: Ensemble Regime Detection (3-4 gün)

**Amaç:** 3 yöntemle ensemble rejim tespiti.

#### 3.1 — Ensemble Regime Detector
```python
# services/market_state/ensemble_regime.py

class EnsembleRegimeDetector:
    """3 yöntemle ensemble rejim tespiti.

    Yöntemler:
    1. HMM (hmm_regime.py) — %30 ağırlık
    2. Skor bazlı (regime.py) — %50 ağırlık
    3. GMM (yeni) — %20 ağırlık

    Karar mekanizması: Weighted voting
    """

    def __init__(self):
        self._hmm_detector = HMMRegimeDetector(n_regimes=4, rolling_window=63)
        self._score_detector = RegimeEngine()
        self._gmm_detector = None  # GMM opsiyonel

    def detect(self, features: Dict, returns: np.ndarray = None,
               volatility: np.ndarray = None) -> EnsembleResult:
        """Ensemble rejim tespiti."""
        results = {}

        # 1. Skor bazlı (mevcut)
        score_result = self._score_detector.detect_regime(features)
        results["score"] = {
            "regime": score_result.regime.value,
            "confidence": score_result.confidence,
            "weight": 0.50,
        }

        # 2. HMM (mevcut)
        if returns is not None and len(returns) >= 63:
            hmm_result = self._hmm_detector.predict_regime(returns, volatility)
            results["hmm"] = {
                "regime": hmm_result.regime,
                "confidence": hmm_result.confidence,
                "weight": 0.30,
                "probabilities": hmm_result.probabilities,
            }

        # 3. GMM (yeni, opsiyonel)
        if self._gmm_detector and returns is not None:
            gmm_result = self._gmm_detector.predict(returns, volatility)
            results["gmm"] = {
                "regime": gmm_result.regime,
                "confidence": gmm_result.confidence,
                "weight": 0.20,
            }

        # Weighted voting
        return self._weighted_vote(results)

    def _weighted_vote(self, results: Dict) -> EnsembleResult:
        """Ağırlıklı oylama ile final karar."""
        # Her rejim için ağırlıklı skor topla
        regime_scores = {}
        for method, result in results.items():
            regime = result["regime"]
            weight = result["weight"]
            confidence = result["confidence"]
            if regime not in regime_scores:
                regime_scores[regime] = 0.0
            regime_scores[regime] += weight * confidence

        # En yüksek skorlu rejim
        final_regime = max(regime_scores, key=regime_scores.get)
        final_confidence = regime_scores[final_regime]

        # Consensus kontrolü
        regimes = [r["regime"] for r in results.values()]
        consensus = len(set(regimes)) == 1

        return EnsembleResult(
            regime=final_regime,
            confidence=round(final_confidence, 4),
            consensus=consensus,
            methods=results,
            regime_scores=regime_scores,
        )
```

#### 3.2 — GMM Regime Detector (YENİ, Opsiyonel)
- [ ] Gaussian Mixture Model ile rejim tespiti
- [ ] HMM'den daha basit, daha hızlı
- [ ] Factor-level regime detection (Two Sigma yaklaşımı)

#### 3.3 — Ensemble Ağırlık Optimizasyonu
- [ ] Backtest ile ağırlık optimizasyonu
- [ ] Rejim bazlı ağırlık değişimi (crisis'te HMM ağırlığı artsın)
- [ ] Confidence-based dynamic weighting

**Teslimat:** `pytest tests/test_market_state_faz3.py` — ensemble voting, GMM, ağırlık optimizasyonu

---

### FAZ 4: Regime Transition Tracking (1-2 gün)

**Amaç:** Rejim değişimlerini takip et, kararlılık ölç.

#### 4.1 — Transition Tracker
```python
# services/market_state/transition_tracker.py

class RegimeTransitionTracker:
    """Rejim geçiş takibi ve istatistikleri."""

    def __init__(self, max_history: int = 1000):
        self._history = []  # [{timestamp, regime, confidence}]
        self._transitions = []  # [{from, to, timestamp, duration}]
        self._max_history = max_history

    def record(self, regime: str, confidence: float, timestamp: str = None):
        """Rejim kaydet, geçiş tespit et."""
        ...

    def get_stats(self) -> Dict:
        """Rejim istatistikleri:
        - Total observations
        - Total transitions
        - Regime distribution
        - Average duration (gün)
        - Stability score (0-1)
        - Current regime duration
        - Transition probability matrix
        """
        ...

    def get_stability_score(self, window: int = 20) -> float:
        """Son N gözlemde kaç geçiş oldu → kararlılık."""
        ...

    def get_transition_probability(self, from_regime: str, to_regime: str) -> float:
        """Belirli bir geçişin olasılığı."""
        ...
```

#### 4.2 — Alert System
- [ ] Rejim değişimi → `REGIME_TRANSITION` event
- [ ] Stability < 0.5 → kararsız piyasa uyarısı
- [ ] Beklenmedik geçiş (CRISIS → BULL) → dikkat uyarısı

**Teslimat:** `pytest tests/test_market_state_faz4.py` — transition tracking, stats, alerts

---

### FAZ 5: Risk Appetite ve Multi-Timeframe (2-3 gün)

**Amaç:** 6 faktörlü risk appetite ve çoklu zaman ufku.

#### 5.1 — Gelişmiş Risk Appetite
```python
# services/market_state/risk_appetite.py

class RiskAppetiteEngine:
    """6 faktörlü risk appetite hesaplama."""

    WEIGHTS = {
        "breadth": 0.30,
        "momentum": 0.20,
        "volatility": 0.20,
        "rsi": 0.10,
        "sentiment": 0.10,
        "macro": 0.10,
    }

    def compute(self, breadth_pct: float, momentum: float,
                volatility: float, rsi: float,
                sentiment_score: float = None,
                macro_score: float = None) -> float:
        """0-1 arası risk appetite skoru."""
        ...
```

#### 5.2 — Multi-Timeframe State
```python
# services/market_state/multi_timeframe.py

class MultiTimeframeEngine:
    """Çoklu zaman ufku market state."""

    TIMEFRAMES = ["intraday", "daily", "weekly", "monthly"]

    def compute_all_timeframes(self, data: Dict) -> Dict[str, MarketState]:
        """Her timeframe için ayrı market state."""
        ...

    def detect_divergence(self, states: Dict[str, MarketState]) -> List[str]:
        """Timeframe'ler arası uyumsuzluk tespit.

        Örneğin: Günlük BULL ama haftalık BEAR → dikkat
        """
        ...

    def get_alignment_score(self, states: Dict[str, MarketState]) -> float:
        """Timeframe uyumu skoru (0-1). 1 = tam uyum."""
        ...
```

#### 5.3 — Macro State Entegrasyonu
- [ ] `WorldStateManager`'dan macro state al
- [ ] `MacroRegimeDetector`'dan macro regime al
- [ ] Market state'e macro katkısı ekle

**Teslimat:** `pytest tests/test_market_state_faz5.py` — risk appetite, multi-TF, macro entegrasyon

---

### FAZ 6: Orchestrator Entegrasyonu ve API (2-3 gün)

**Amaç:** Tüm bileşenleri birleştir, mevcut pipeline'a entegre et.

#### 6.1 — MarketStateService Refactor
```python
# services/market_state/main.py (refactored)

class MarketStateService:
    """Market State Engine v2.0 — tüm bileşenleri orkestre eder."""

    def __init__(self):
        self._breadth_engine = MarketBreadthEngine()
        self._component_engine = ComponentStateEngine()
        self._ensemble_detector = EnsembleRegimeDetector()
        self._transition_tracker = RegimeTransitionTracker()
        self._risk_appetite = RiskAppetiteEngine()
        self._multi_tf = MultiTimeframeEngine()

    async def _compute_market_state(self):
        """Tüm bileşenleri hesapla, birleştir."""
        states = list(self._instrument_states.values())

        # 1. Breadth
        breadth = self._breadth_engine.compute(states, self._ad_history)

        # 2. Component states
        momentum_state = self._component_engine.compute_momentum_state(states)
        volatility_state = self._component_engine.compute_volatility_state(states, vix)
        volume_state = self._component_engine.compute_volume_state(states)
        rsi_state = self._component_engine.compute_rsi_state(states)
        liquidity_state = self._component_engine.compute_liquidity_state(states)
        sentiment_state = self._component_engine.compute_sentiment_state(news, social)

        # 3. Ensemble regime
        features = self._build_feature_dict(breadth, states)
        returns = self._get_returns_series()
        volatility = self._get_volatility_series()
        regime = self._ensemble_detector.detect(features, returns, volatility)

        # 4. Transition tracking
        self._transition_tracker.record(regime.regime, regime.confidence)

        # 5. Risk appetite
        risk_appetite = self._risk_appetite.compute(
            breadth.pct_advancing, avg_momentum, avg_volatility, avg_rsi,
            sentiment_score, macro_score
        )

        # 6. Multi-timeframe
        tf_states = self._multi_tf.compute_all_timeframes(data)

        # 7. Output
        market_state = self._format_output(...)
```

#### 6.2 — Event Bus Entegrasyonu
- [ ] `MARKET_STATE_CHANGED` event'ini zenginleştir
- [ ] Yeni event'ler: `BREADTH_ALERT`, `REGIME_TRANSITION`, `LIQUIDITY_ALERT`
- [ ] `signal_fusion` ve `decision_engine`'a yeni state'leri besle

#### 6.3 — API Endpoint'leri
- [ ] `GET /api/market/state` — tam market state (yeni format)
- [ ] `GET /api/market/breadth` — breadth detayları
- [ ] `GET /api/market/regime` — ensemble regime + probabilities
- [ ] `GET /api/market/transition` — transition history + stats
- [ ] `GET /api/market/multi-tf` — multi-timeframe states

**Teslimat:** `pytest tests/test_market_state_faz6.py` — end-to-end pipeline, API

---

### FAZ 7: Test, Backtest ve Production (3-4 gün)

**Amaç:** Sistemi production-ready yap.

#### 7.1 — Kapsamlı Test Suite
- [ ] Unit test'ler: her modül için
- [ ] Integration test'ler: pipeline akışı
- [ ] Ensemble test'leri: farklı senaryolarda consensus/no_consensus
- [ ] Breadth test'leri: aşırı seviye tespiti
- [ ] Edge case: tüm hisseler düştüyse, hiç veri yoksa

#### 7.2 — Backtest Entegrasyonu
- [ ] Ensemble regime vs tek yöntem performans karşılaştırması
- [ ] Breadth göstergelerinin tahmin gücü
- [ ] Regime-aware strateji backtest
- [ ] BIST-specific eşik optimizasyonu

#### 7.3 — Monitoring Dashboard
- [ ] Grafana: breadth grafikleri, regime timeline, risk appetite
- [ ] Prometheus: `market_state_duration_ms`, `regime_confidence`, `breadth_pct`
- [ ] Alert: regime değişimi, breadth aşırı, likidite krizi

#### 7.4 — Dokümantasyon
- [ ] Market State README güncelle
- [ ] Her modül için docstring
- [ ] Architecture diagram
- [ ] Runbook: troubleshooting

**Teslimat:** `pytest tests/test_market_state_faz7.py` — tüm testler yeşil, backtest raporu

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam pipeline)
         ├─────────────┤
         │ Integration  │  ← 15 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 60+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test | Kritik Test |
|-----|-------------|----------|-------------|
| 0 | test_market_state_faz0.py | 8 | Canonical regime, config |
| 1 | test_market_state_faz1.py | 12 | McClellan, TRIN, breadth alerts |
| 2 | test_market_state_faz2.py | 15 | Tüm component states |
| 3 | test_market_state_faz3.py | 12 | Ensemble voting, GMM |
| 4 | test_market_state_faz4.py | 8 | Transition tracking, stability |
| 5 | test_market_state_faz5.py | 10 | Risk appetite 6 faktör, multi-TF |
| 6 | test_market_state_faz6.py | 12 | End-to-end pipeline, API |
| 7 | test_market_state_faz7.py | 15 | Backtest, performans |
| **Toplam** | | **92+** | |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| HMM eğitimi başarısız | Orta | Yüksek | Rule-based fallback (mevcut) |
| Ensemble uyuşmazlığı | Yüksek | Orta | Confidence-based weighted voting |
| Breadth yanıltıcı (düşük likidite) | Yüksek | Yüksek | Volume eşiği, likidite filtresi |
| GMM kurulumu zor | Orta | Düşük | Opsiyonel, HMM + skor yeterli |
| Multi-TF çelişki | Yüksek | Orta | Alignment score, divergence alert |
| BIST-specific eşikler yanlış | Orta | Yüksek | Backtest ile optimize, adaptif eşik |
| Sentiment verisi eksik | Yüksek | Düşük | Fallback: sentiment katkısı 0 |
| Macro entegrasyonu karmaşık | Orta | Orta | Mevcut WorldStateManager'ı kullan |
| Performans (800+ hisse) | Orta | Orta | Incremental update, Redis cache |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 0** | 1-2 gün | Yok | Canonical regime, config, events |
| **Faz 1** | 2-3 gün | Faz 0 | Breadth engine (7 gösterge) |
| **Faz 2** | 2-3 gün | Faz 0 | Component states (8 state) |
| **Faz 3** | 3-4 gün | Faz 1+2 | Ensemble regime (3 yöntem) |
| **Faz 4** | 1-2 gün | Faz 3 | Transition tracking |
| **Faz 5** | 2-3 gün | Faz 2+3 | Risk appetite + multi-TF |
| **Faz 6** | 2-3 gün | Faz 5 | Orchestrator + API entegrasyon |
| **Faz 7** | 3-4 gün | Faz 6 | Test, backtest, production |
| **TOPLAM** | **16-24 gün** | | |

**Not:** Faz 1 ve Faz 2 paralel geliştirilebilir. Faz 3 ve Faz 4 paralel. Bu durumda toplam süre **12-18 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **Tek canonical regime kaynağı** — `RegimeEngine` tek kaynak, main.py'deki basit tespit kaldırılacak
2. **Ensemble voting** — HMM %30 + Skor %50 + GMM %20 (backtest ile optimize edilecek)
3. **NO_CONSENSUS → mevcut rejimi koru** — Belirsizlikte ani değişim yok
4. **BIST-specific normalize** — Döviz volatilitesi, düşük likidite, sektörel konsantrasyon
5. **Incremental update** — Her tick'te tüm state'i yeniden hesaplama, sadece değişeni güncelle
6. **Redis cache** — Market state'i Redis'te tut, API'den hızlı oku
7. **Event-driven** — Regime değişimi → event → tüm sistem güncellenir
8. **Backtest-first** — Her faz için backtest kanıtı gerekli

---

## 📚 Referanslar

1. Gupta et al. (2025) — "A forest of opinions: Multi-model ensemble-HMM voting framework" — https://doi.org/10.3934/DSFE.2025019
2. Two Sigma — "A Machine Learning Approach to Regime Modeling" — https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/
3. Springer (2026) — "Regime-Aware Adaptive Forecasting Framework"
4. arXiv RMATS (2026) — "Hierarchical HMM for regime boundary detection"
5. MDPI (2026) — "Regime-Aware LightGBM"
6. StockCharts — McClellan Oscillator, Summation Index, TRIN
7. Blueberry Markets — "Top Market Breadth Indicators for Traders"
