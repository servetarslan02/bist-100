# ALPHA BIST — Teknik Mimarî Spesifikasyon v1.1

> **Proje:** BIST Market Intelligence & Quant Engine
> **Hedef:** 800+ BIST hissesini 7/24 tarayan, otonom piyasa zekâsı platformu
> **Donanım:** i7 13. nesil + RTX 4080 16GB VRAM + 16GB RAM
> **Tarih:** 14 Ağustos 2026
> **Durum:** Architecture v1.1 — Kilitli
> **v1.1 Değişiklikleri:** SPEC matematiksel tanım, Event→Asset Impact Graph, Canonical Event Schema, Asset State Schema, Feature Contract, ML Label Protocol, Dynamic Monte Carlo, Memory Limits, Fine-tuning düzeltmesi, Pandas kaldırıldı

---

## İçindekiler

1. [Proje Tanımı](#1-proje-tanımı)
2. [Sistem Mimarisi](#2-sistem-mimarisi)
3. [Canonical Event Schema](#3-canonical-event-schema)
4. [Asset State Schema](#4-asset-state-schema)
5. [Feature Contract](#5-feature-contract)
6. [SPEC / Opportunity Matematiği](#6-spec--opportunity-matematiği)
7. [Event → World → Asset Impact Engine](#7-event--world--asset-impact-engine)
8. [Veri Katmanı](#8-veri-katmanı)
9. [Event Streaming](#9-event-streaming)
10. [Real-Time Engine](#10-real-time-engine)
11. [ML Pipeline & Label Protocol](#11-ml-pipeline--label-protocol)
12. [AI/LLM Katmanı](#12-aillm-katmanı)
13. [Finansal Motorlar](#13-finansal-motorlar)
14. [Risk Yönetimi](#14-risk-yönetimi)
15. [Öğrenme Sistemi](#15-öğrenme-sistemi)
16. [Donanım Kaynak Dağılımı & Memory Limits](#16-donanım-kaynak-dağılımı--memory-limits)
17. [Dashboard & UI](#17-dashboard--ui)
18. [Teknoloji Stack](#18-teknoloji-stack)
19. [Geliştirme Aşamaları](#19-geliştirme-aşamaları)
20. [Referanslar](#20-referanslar)

---

## 1. Proje Tanımı

### 1.1 Ne Değil?

- ❌ 3-5 hisse analiz eden basit bir AI botu
- ❌ Teknik indikatör çizelgesi
- ❌ ChatGPT'ye "hangi hisseyi alayım?" diye soran uygulama
- ❌ Kripto dashboard klonu

### 1.2 Ne?

> **BIST'in tamamını sürekli sayısal olarak izleyen, olayları anlayan, ilişkileri çıkaran, fırsatları keşfeden, senaryo/backtest yapan, risk hesaplayan, sonuçlarını ölçen ve kontrollü biçimde kendini geliştiren otonom finansal zekâ platformu.**

### 1.3 Temel Prensip

**"Piyasayı oluşturan değişkenlerin tamamını önceden bildiğimizi varsaymamalıyız."**

Sistem sadece RSI, MACD, F/K gibi sabit metrikleri kullanmayacak. Feature interaction discovery, permutation importance, SHAP, mutual information ve regime-conditioned importance ile bilinmeyen ilişkileri keşfedecek.

### 1.4 Katman Ayrımı (Kesin)

| Katman | Görev | Teknoloji | NOT |
|--------|-------|-----------|-----|
| **Quant** | Deterministik hesaplama | Python / NumPy / **Polars** | ❌ Pandas ana pipeline'da yok |
| **ML** | Tahmin / pattern discovery | LightGBM / XGBoost / PyTorch | SHAP + permutation importance |
| **AI** | Reasoning / synthesis / yorumlama | Gemma 4 12B | Sadece filtrelenmiş adaylara |

**v1.1 Düzeltmesi:** Pandas ana pipeline'dan kaldırılmıştır. Quant katmanında Polars + PyArrow kullanılacaktır. Pandas yalnızca küçük ad-hoc araştırma/query'lerde kullanılabilir.

---

## 2. Sistem Mimarisi

### 2.1 Üst Düzey Akış

```
                        KAYNAKLAR
                           │
            ┌──────────────┼──────────────┐
            ↓              ↓              ↓
         PİYASA          HABER          MAKRO
            │              │              │
            └──────────────┼──────────────┘
                           ↓
                   PROVIDER ADAPTERS
                           ↓
                     SCHEMA REGISTRY
                           ↓
                      REDPANDA
                           │
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
       REALTIME STATE   CLICKHOUSE    RAW EVENTS
             │             │             │
             ↓             ↓             ↓
       FEATURE ENGINE   ANALYTİKS     PARQUET
             │                           │
             ↓                           ↓
        ML ENSEMBLE                  DUCKDB
             │                           │
             └─────────────┬─────────────┘
                           ↓
                   IMPACT PROPAGATION
                           ↓
                   WORLD STATE (dynamic)
                           ↓
                    GEMMA 4 12B
                           ↓
                   REGIME / STRATEGY
                           ↓
             OPPORTUNITY / SPEC ENGINE
                           ↓
                   SIMULATION LAB
                           ↓
                     RISK GATE
                           ↓
                  DECISION ENGINE
                           ↓
            PAPER / EXECUTION SIMULATOR
                           ↓
                      OUTCOME
                           ↓
                   ATTRIBUTION
                           ↓
                   LEARNING LAB
                           ↓
               MLflow / VALIDATION
                           ↓
                    CHAMPION MODEL
                           ↺
```

### 2.2 Filtreleme Hiyerarşisi

```
800+ hisse (tüm BIST)
    ↓ İlk filtre (anomali/momentum)
~150 aday
    ↓ İleri analiz (ML scoring)
~40 aday
    ↓ Yüksek potansiyel (multi-model consensus)
~10 aday
    ↓ Derin AI reasoning
3-5 güçlü aday / SPEC
```

---

## 3. Canonical Event Schema

Tüm olaylar aşağıdaki standart formatta olacaktır. Bu, sistemin her bileşinin aynı dili konuşmasını garanti eder.

### 3.1 Base Event

```json
{
  "event_id": "uuid-v4",
  "event_type": "market.tick | news.event | kap.event | macro.event | ...",
  "schema_version": "v1",
  "timestamp": "2026-08-14T10:32:01.123Z",
  "source": "yfinance | kap | tcmb | newsapi | ...",
  "source_timestamp": "2026-08-14T10:31:58.000Z",
  "ingest_timestamp": "2026-08-14T10:32:01.150Z",
  "quality": 0.99,
  "latency_ms": 27,
  "confidence": 1.0,
  "data": { ... },
  "metadata": {
    "provider": "yfinance",
    "instrument_ids": [42, 187],
    "tickers": ["THYAO", "ASELS"],
    "entities": ["Fed", "TCMB"]
  }
}
```

### 3.2 Market Tick Event

```json
{
  "event_type": "market.tick",
  "data": {
    "instrument_id": 42,
    "ticker": "THYAO",
    "price": 312.40,
    "volume": 182340,
    "bid": 312.30,
    "ask": 312.50,
    "trade_count": 847,
    "vwap": 311.85
  }
}
```

### 3.3 News Event

```json
{
  "event_type": "news.event",
  "data": {
    "news_id": "uuid",
    "title": "...",
    "body": "...",
    "url": "...",
    "language": "tr",
    "entities": ["Fed", "USD"],
    "instrument_ids": [42, 87],
    "event_class": "MACRO | COMPANY | SECTOR | GEOPOLITICAL",
    "sentiment": -0.34,
    "importance": 0.82,
    "novelty": 0.71,
    "credibility": 0.90
  }
}
```

### 3.4 KAP Event

```json
{
  "event_type": "kap.event",
  "data": {
    "kap_id": "KAP-2026-184291",
    "ticker": "THYAO",
    "company_id": 42,
    "announcement_type": "ÖZEL DURUM AÇIKLAMASI",
    "title": "...",
    "summary": "...",
    "is_price_sensitive": true,
    "sentiment": 0.64,
    "importance": 0.88,
    "event_class": "INVESTMENT | FINANCIAL_RESULT | DIVIDEND | CAPITAL_CHANGE | CONTRACT"
  }
}
```

### 3.5 Macro Event

```json
{
  "event_type": "macro.event",
  "data": {
    "macro_id": "uuid",
    "indicator": "CPI_YOY",
    "country": "TR",
    "actual": 58.2,
    "expected": 55.0,
    "previous": 56.1,
    "surprise": 3.2,
    "surprise_zscore": 2.1,
    "importance": 0.95,
    "source": "TCMB"
  }
}
```

### 3.6 Signal Event

```json
{
  "event_type": "signal.generated",
  "data": {
    "instrument_id": 42,
    "ticker": "THYAO",
    "signal_type": "SPEC | MOMENTUM | BREAKOUT | VALUE | EVENT_DRIVEN",
    "direction": "LONG | SHORT | NEUTRAL",
    "score": 91.0,
    "confidence": 0.84,
    "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
    "horizon": "1-5D | 1-4W | 1-6M | 6-24M",
    "expected_return_pct": 7.8,
    "expected_volatility_pct": 4.2,
    "edge_decomposition": {
      "flow_anomaly": 21,
      "relative_strength": 18,
      "regime_compatibility": 16,
      "historical_similarity": 14,
      "fundamental_state": 11,
      "event_state": 8,
      "volatility_risk": -5,
      "correlation_risk": -3,
      "total": 80
    },
    "reasoning": "...",
    "model_version": "opportunity_v27",
    "strategy_id": 5
  }
}
```

---

## 4. Asset State Schema

Her hissenin anlık durumu bu formatta tutulacaktır. State incremental güncellenir, her tick'te tüm geçmiş yeniden hesaplanmaz.

### 4.1 Full Asset State

```json
{
  "instrument_id": 42,
  "ticker": "THYAO",
  "timestamp": "2026-08-14T10:32:01.123Z",

  "price": {
    "current": 312.40,
    "previous": 311.80,
    "change_pct": 0.19,
    "change_1d_pct": 1.24,
    "change_5d_pct": 3.82,
    "change_20d_pct": 7.14
  },

  "volume": {
    "current": 182340,
    "avg_20d": 142000,
    "ratio_20d": 1.28,
    "zscore_20d": 1.84,
    "unusual": false,
    "trend": 0.12
  },

  "momentum": {
    "roc_5d": 3.82,
    "roc_20d": 7.14,
    "roc_60d": 12.40,
    "acceleration": 0.84
  },

  "volatility": {
    "atr_14": 4.82,
    "atr_14_pct": 1.54,
    "realized_5d": 18.4,
    "realized_20d": 22.1,
    "regime": "NORMAL | LOW | HIGH | EXTREME",
    "zscore": 0.34,
    "bb_position": 0.72
  },

  "technical": {
    "rsi_14": 64.2,
    "macd_histogram": 0.42,
    "stochastic_k": 68.1,
    "adx": 32.4,
    "cci": 112.0,
    "williams_r": -31.9,
    "mfi": 62.8
  },

  "relative": {
    "strength_vs_index": 1.84,
    "strength_vs_sector": 2.12,
    "sector_rank": 3,
    "cross_sectional_rank": 47
  },

  "liquidity": {
    "bid_ask_spread_pct": 0.06,
    "amihud_illiquidity": 0.0012,
    "turnover_rate": 0.84
  },

  "fundamental": {
    "pe_ratio": 8.2,
    "pb_ratio": 1.4,
    "ev_ebitda": 5.1,
    "dividend_yield": 0.032,
    "debt_equity": 0.42,
    "revenue_growth_pct": 18.4,
    "last_updated": "2026-07-15"
  },

  "event_sentiment": {
    "kap_sentiment": 0.64,
    "news_sentiment": 0.31,
    "social_sentiment": 0.18,
    "event_impact": 0.72,
    "days_since_last_event": 3
  },

  "ml_scores": {
    "anomaly_score": 0.42,
    "spec_score": 0.78,
    "momentum_5d_pred": 0.71,
    "momentum_20d_pred": 0.68,
    "breakout_prob": 0.64,
    "risk_score": 0.31
  },

  "regime": {
    "current": "MOMENTUM-EXPANSION",
    "confidence": 0.82,
    "duration_hours": 47.2
  },

  "edge_score": 84.0,
  "confidence": 0.79,
  "risk_level": "MEDIUM"
}
```

### 4.2 State Update Rules

```
Yeni tick geldiğinde:
  1. price.current güncelle
  2. price.change_pct = (new - previous) / previous * 100
  3. volume.current güncelle
  4. volume.zscore_20d = (current - avg_20d) / std_20d (rolling window)
  5. momentum.roc_5d = (current / price_5d_ago - 1) * 100
  6. volatility.atr_14 = incremental ATR update
  7. technical.rsi_14 = incremental RSI update
  8. relative.strength_vs_index = return / index_return
  9. ml_scores.* = inference (gerekirse)
  10. edge_score = weighted sum of all components
```

**Kritik:** Her adımda sadece ilgili değer güncellenir. 799 diğer hisse etkilenmez.

---

## 5. Feature Contract

### 5.1 Feature Kategorileri ve Hesaplama Formülleri

#### Category 1: Returns (Deterministic)

| Feature | Formül | Window |
|---------|--------|--------|
| `return_1d` | `(P_t / P_{t-1} - 1) * 100` | 1 gün |
| `return_5d` | `(P_t / P_{t-5} - 1) * 100` | 5 gün |
| `return_20d` | `(P_t / P_{t-20} - 1) * 100` | 20 gün |
| `return_60d` | `(P_t / P_{t-60} - 1) * 100` | 60 gün |
| `log_return_1d` | `ln(P_t / P_{t-1}) * 100` | 1 gün |

#### Category 2: Volume (Rolling Window)

| Feature | Formül | Window |
|---------|--------|--------|
| `volume_ratio_20d` | `V_t / mean(V_{t-20:t})` | 20 gün |
| `volume_zscore_20d` | `(V_t - mean(V_{t-20:t})) / std(V_{t-20:t})` | 20 gün |
| `volume_trend` | `slope(V_{t-10:t}) / mean(V_{t-10:t})` | 10 gün |
| `unusual_volume` | `1 if volume_zscore > 2.0 else 0` | 20 gün |

#### Category 3: Momentum

| Feature | Formül | Window |
|---------|--------|--------|
| `roc_5d` | `(P_t / P_{t-5} - 1) * 100` | 5 gün |
| `roc_20d` | `(P_t / P_{t-20} - 1) * 100` | 20 gün |
| `price_acceleration` | `roc_5d_t - roc_5d_{t-5}` | 10 gün |

#### Category 4: Volatility

| Feature | Formül | Window |
|---------|--------|--------|
| `atr_14_pct` | `ATR(14) / P_t * 100` | 14 gün |
| `realized_vol_20d` | `std(log_returns_{t-20:t}) * sqrt(252) * 100` | 20 gün |
| `bb_position` | `(P_t - BB_lower) / (BB_upper - BB_lower)` | 20 gün |
| `volatility_ratio` | `realized_vol_5d / realized_vol_20d` | 5/20 gün |
| `volatility_regime` | `LOW if ratio < 0.5, HIGH if ratio > 1.5, else NORMAL` | 5/20 gün |

#### Category 5: Technical Indicators

| Feature | Formül | Window |
|---------|--------|--------|
| `rsi_14` | `100 - 100/(1 + avg_gain/avg_loss)` | 14 gün |
| `macd_histogram` | `EMA(12) - EMA(26) - Signal(9)` | 12/26/9 |
| `adx` | `DX = |+DI - -DI| / (+DI + -DI) * 100` | 14 gün |
| `cci` | `(TP - SMA(TP)) / (0.015 * MAD(TP))` | 20 gün |
| `mfi` | `100 - 100/(1 + positive_mf/negative_mf)` | 14 gün |

#### Category 6: Relative Strength

| Feature | Formül | Window |
|---------|--------|--------|
| `strength_vs_index` | `return_stock / return_index` | 20 gün |
| `strength_vs_sector` | `return_stock / return_sector` | 20 gün |
| `cross_sectional_rank` | `rank(return_20d) / N * 100` | 20 gün |

#### Category 7: Trend

| Feature | Formül | Window |
|---------|--------|--------|
| `price_vs_sma20` | `(P_t / SMA(20) - 1) * 100` | 20 gün |
| `price_vs_sma50` | `(P_t / SMA(50) - 1) * 100` | 50 gün |
| `trend_slope_20d` | `slope(P_{t-20:t}) / P_t * 100` | 20 gün |
| `ma_cross_signal` | `1 if SMA(20) > SMA(50) else -1` | 20/50 gün |

#### Category 8: Patterns

| Feature | Formül | Window |
|---------|--------|--------|
| `gap_pct` | `(O_t / C_{t-1} - 1) * 100` | 1 gün |
| `daily_range_pct` | `(H_t - L_t) / C_t * 100` | 1 gün |
| `consecutive_up` | `count(C_t > C_{t-1} for last 5)` | 5 gün |
| `near_20d_high` | `1 if C_t >= max(H_{t-20:t}) * 0.98` | 20 gün |
| `near_20d_low` | `1 if C_t <= min(L_{t-20:t}) * 1.02` | 20 gün |

#### Category 9: Cross-Sectional (Tüm BIST)

| Feature | Formül | Window |
|---------|--------|--------|
| `sector_momentum` | `mean(return_20d) of sector peers` | 20 gün |
| `market_breadth_contribution` | `1 if stock > market_median else -1` | 1 gün |
| `correlation_to_index` | `corr(returns, index_returns)` | 60 gün |

#### Category 10: Event-Derived

| Feature | Formül | Window |
|---------|--------|--------|
| `kap_sentiment_ema` | `EMA(kap_sentiment, alpha=0.3)` | sürekli |
| `news_impact_score` | `importance * sentiment * novelty` | son 24 saat |
| `event_surprise_zscore` | `(actual - expected) / std(historical)` | olay bazlı |

### 5.2 Feature Discovery Pipeline (v1.1 Ek)

Sistem "binlerce değişkeni kendi keşfedecek" iddiasını desteklemek için bu pipeline gereklidir:

```
Raw Features (50+)
        ↓
Feature Interaction Generation
  - pairwise products
  - ratios
  - differences
  - lag features (1d, 2d, 5d)
        ↓
Candidate Features (500+)
        ↓
Filtering Pipeline:
  1. Mutual Information (target ile)
  2. Correlation filter (kendi aralarında yüksek korelasyonlu olanları ele)
  3. Permutation Importance (model bazlı)
  4. SHAP values (hangi feature gerçekten katkı sağlıyor)
  5. Feature Stability (farklı zaman dilimlerinde tutarlı mı)
  6. Leakage Detection (gelecek bilgisi sızıntısı var mı)
  7. Regime-Conditioned Importance (farklı rejimlerde farklı mı)
        ↓
Selected Features (100-200)
        ↓
ML Training
        ↓
Model Feature Importance (per model)
        ↓
Feedback → Feature Generation'a geri dön
```

**Kritik Not:** Bu pipeline batch olarak çalışır (gece/piyasa kapalıyken). Canlıda sadece seçilmiş features hesaplanır.

---

## 6. SPEC / Opportunity Matematiği

### 6.1 SPEC Tanımı (Kesin)

**SPEC ≠ Yüksek skor**

**SPEC = Anormal davranış + Kanıt birleşimi + Rejim uyumu + Beklenen değer + Risk/asimetri + İstatistiksel benzerlik**

### 6.2 SPEC Skor Formülü

```
SPEC_SCORE = w1 * AnomalyScore
           + w2 * EvidenceConsensus
           + w3 * RegimeCompatibility
           + w4 * ExpectedValue
           + w5 * RiskAsymmetry
           + w6 * HistoricalSimilarity
           - w7 * PenaltyFactors
```

#### Bileşen 1: AnomalyScore

```
AnomalyScore = f(volume_zscore, price_zscore, volatility_zscore, flow_zscore)

Hesaplama:
  raw_anomaly = (volume_zscore^2 + price_zscore^2 + volatility_zscore^2) / 3
  AnomalyScore = min(raw_anomaly / 4.0, 1.0)  # normalize to [0, 1]

Eşik: AnomalyScore > 0.5 → anormal kabul edilir
```

#### Bileşen 2: EvidenceConsensus (Kanıt Birliği)

```
EvidenceConsensus = count(evidence_i > threshold) / total_evidence_count

Kanıtlar:
  - volume_anomaly: volume_zscore > 2.0
  - price_breakout: price > bb_upper or near_20d_high
  - sector_strength: strength_vs_sector > 1.5
  - kap_positive: kap_sentiment > 0.3
  - momentum_build: roc_5d > 2.0 and acceleration > 0
  - low_volatility_expansion: volatility_regime == "LOW" and volume_zscore > 1.5
  - institutional_flow: (varsa order-flow verisi)

Eşik: EvidenceConsensus > 0.57 (4/7 kanıt) → SPEC adayı
```

#### Bileşen 3: RegimeCompatibility

```
RegimeCompatibility = regime_fit_score(current_regime, historical_regime_returns)

Hesaplama:
  - Mevcut rejimde benzer sinyallerin geçmiş performansı
  - Regime-Momentum uyumu: 1.0 if regime supports direction, 0.3 if neutral, 0.0 if contradicts

Eşik: RegimeCompatibility > 0.6
```

#### Bileşen 4: ExpectedValue

```
ExpectedValue = P(positive_return) * E[return | positive] - P(negative_return) * E[return | negative]

Hesaplama:
  - ML modelinden: P(positive), E[return | positive], E[return | negative]
  - Historical analogues'dan: benzer durumlardaki ortalama getiri

Normalize: EV = (raw_EV - min_EV) / (max_EV - min_EV)
```

#### Bileşen 5: RiskAsymmetry

```
RiskAsymmetry = ExpectedUpside / ExpectedDownside

Hesaplama:
  - Upside: %75 percentile of simulated returns
  - Downside: %25 percentile of simulated returns
  - Ratio = Upside / |Downside|

Normalize: RA = min(Ratio / 3.0, 1.0)
```

#### Bileşen 6: HistoricalSimilarity

```
HistoricalSimilarity = max(cosine_similarity(current_features, historical_features))

Hesaplama:
  - Mevcut feature vektörü ile geçmiş tüm durumlar arasındaki cosine similarity
  - En benzer N durumun sonraki getirileri
  - Positive rate among top-10 similar states

Normalize: HS = positive_rate
```

#### Bileşen 7: PenaltyFactors

```
PenaltyFactors = p1 * high_volatility_penalty
               + p2 * low_liquidity_penalty
               + p3 * correlation_risk_penalty
               + p4 * overcrowding_penalty

high_volatility_penalty: 1.0 if volatility_regime == "EXTREME", 0.5 if "HIGH"
low_liquidity_penalty: 1.0 if amihud > threshold
correlation_risk_penalty: 1.0 if correlation_to_index > 0.9
overcrowding_penalty: 1.0 if same_signal_count > 20 (çok fazla hisse aynı sinyali üretiyorsa)
```

### 6.3 Ağırlıklar (Başlangıç, ML ile optimize edilecek)

```python
SPEC_WEIGHTS = {
    "anomaly": 0.20,
    "evidence": 0.25,
    "regime": 0.15,
    "expected_value": 0.20,
    "risk_asymmetry": 0.10,
    "historical_similarity": 0.10,
}
```

### 6.4 SPEC Adaylık Kriterleri

```
SPEC Candidate IF:
  AnomalyScore > 0.5
  AND EvidenceConsensus >= 4/7
  AND RegimeCompatibility > 0.6
  AND ExpectedValue > 0
  AND RiskAsymmetry > 1.0
  AND PenaltyFactors < 0.5

SPEC Score = weighted_sum / (1 + PenaltyFactors)
```

### 6.5 Skor → Kategori

```
SPEC Score >= 0.85  →  🔴 HIGH CONVICTION SPEC
SPEC Score >= 0.70  →  🟠 SPEC CANDIDATE
SPEC Score >= 0.55  →  🟡 WATCH
SPEC Score < 0.55   →  ⚪ NORMAL
```

---

## 7. Event → World → Asset Impact Engine

### 7.1 Impact Propagation Model

Sistem "dünyayı anlayan" bir platform olmak için olayların nasıl yayıldığını modellemelidir.

```
EVENT
  ↓
ENTITY EXTRACTION
  ↓
IMPACT CLASSIFICATION
  ↓
PROPAGATION GRAPH
  ↓
AFFECTED ASSETS + IMPACT MAGNITUDE + TIME HORIZON
```

### 7.2 Propagation Graph (Etki Yayılım Grafiği)

```
FED faiz kararı (+25bp)
  │
  ├──→ USD Index (+0.8%)
  │      ├──→ USD/TRY (+1.2%)
  │      │      ├──→ BIST Import costs ↑
  │      │      │      └──→ TUPRS, PETKM (negative)
  │      │      └──→ BIST Export earnings ↑
  │      │             └──→ THYAO, ASELS (positive)
  │      └──→ EM Risk Appetite ↓
  │             └──→ BIST Overall ↓
  │                    └──→ BANK sector ↓
  │                           ├──→ AKBNK (-2.1%)
  │                           ├──→ GARAN (-1.8%)
  │                           └──→ YKBNK (-1.9%)
  │
  ├──→ US 10Y Yield (+12bp)
  │      └──→ Global Risk-Off
  │             └──→ VIX ↑
  │                    └──→ BIST Volatility ↑
  │
  └──→ Gold (+1.5%)
         └──→ ALTIN companies ↑
```

### 7.3 Impact Propagation Kuralları

```python
PROPAGATION_RULES = {
    "FED_RATE_HIKE": {
        "USD_INDEX": {"impact": +0.8, "lag_hours": 0, "confidence": 0.9},
        "EM_RISK": {"impact": -0.6, "lag_hours": 0, "confidence": 0.85},
        "BIST_BANK": {"impact": -0.7, "lag_hours": 1, "confidence": 0.8},
        "BIST_TECH": {"impact": -0.3, "lag_hours": 2, "confidence": 0.6},
        "GOLD": {"impact": +0.5, "lag_hours": 0, "confidence": 0.7},
    },
    "TCMB_RATE_CUT": {
        "USD_TRY": {"impact": +0.4, "lag_hours": 0, "confidence": 0.85},
        "BIST_BANK": {"impact": +0.6, "lag_hours": 1, "confidence": 0.8},
        "BIST_REAL_ESTATE": {"impact": +0.5, "lag_hours": 2, "confidence": 0.7},
    },
    "OIL_SHOCK_UP": {
        "TUPRS": {"impact": +0.8, "lag_hours": 0, "confidence": 0.9},
        "THYAO": {"impact": -0.6, "lag_hours": 0, "confidence": 0.85},
        "PETKM": {"impact": +0.4, "lag_hours": 0, "confidence": 0.7},
        "BIST_ENERGY": {"impact": +0.5, "lag_hours": 0, "confidence": 0.8},
    },
    # ... 50+ kural
}
```

### 7.4 Dynamic World State

World State statik değişkenler değil, **zaman içinde değişen latent state** olmalıdır.

```
World State t0
    ↓ EVENT (Fed kararı)
World State t1
    ↓ IMPACT PROPAGATION
BIST State t1
    ↓ SECTOR STATE UPDATE
Sector States t1
    ↓ ASSET STATE UPDATE
Asset States t1
```

### 7.5 World State Vector (Dynamic)

```python
class DynamicWorldState:
    timestamp: datetime

    # Latent factors (zaman içinde değişir)
    global_risk_appetite: float      # 0-1
    usd_strength: float              # 0-1
    us_rate_pressure: float          # 0-1
    commodity_pressure: float        # 0-1
    oil_pressure: float              # 0-1
    turkey_macro_risk: float         # 0-1
    geopolitical_risk: float         # 0-1
    em_risk_appetite: float          # 0-1

    # Transition model
    transition_matrix: np.ndarray    # 8x8 state transition
    event_impact_vector: np.ndarray  # 8x1 event impact

    # State update
    def update(self, event: AlphaEvent):
        impact = self.compute_impact(event)
        self.state_vector = self.transition_matrix @ self.state_vector + impact
        self.state_vector = np.clip(self.state_vector, 0, 1)
        self.timestamp = event.timestamp

    def compute_impact(self, event: AlphaEvent) -> np.ndarray:
        # Propagation rules'dan etki vektörü hesapla
        rule = PROPAGATION_RULES.get(event.event_type)
        if rule:
            return self.apply_propagation(rule, event.data)
        return np.zeros(8)
```

### 7.6 Haber Pipeline (Detaylı Sözleşme)

```
Haber kaynağı
    ↓
RAW EVENT (news.raw)
    ↓
ENTITY EXTRACTION
  - NER (Named Entity Recognition)
  - Şirket, kişi, kurum, ülke, emtia tanıma
  - Türkçe + İngilizce
    ↓
EVENT CLASSIFICATION
  - MACRO (Fed, TCMB, ECB, enflasyon, faiz)
  - COMPANY (şirket haberi, KAP)
  - SECTOR (sektör bazlı)
  - GEOPOLITICAL (savaş, ambargo, seçim)
  - MARKET (borsa hareketi, işlem)
    ↓
SENTIMENT ANALYSIS
  - Pozitif / Negatif / Nötr
  - Confidence skoru
  - Türkçe NLP modeli
    ↓
IMPORTANCE SCORING
  - novelty: bu bilgi yeni mi?
  - credibility: kaynak güvenilir mi?
  - market_relevance: piyasayı etkiler mi?
  - surprise: beklenti dışı mı?
    ↓
IMPACT ESTIMATION
  - Hangi varlıklar etkilenir?
  - Ne kadar etkilenir?
  - Ne zaman etkilenir?
  - Propagation graph üzerinden
    ↓
AFFECTED ASSETS
  - instrument_ids[]
  - impact_magnitude[]
  - time_horizon[]
  - confidence[]
    ↓
EVENT (news.event) → Redpanda
```

---

## 8. Veri Katmanı

### 8.1 Veri Kaynakları

| Veri | Kaynak | Erişim | Gecikme |
|------|--------|--------|---------|
| BIST fiyat/hacim | yfinance | Ücretsiz API | 15dk |
| KAP bildirimleri | kap.org.tr | Scrape + parse | Anlık |
| TCMB makro | TCMB EVDS | Ücretsiz API | Günlük |
| Global fiyat | Alpha Vantage / Twelve Data | Ücretsiz tier | 15dk |
| Haber | NewsAPI + RSS | Ücretsiz tier | Dakika |
| Sosyal medya | X API | Ücretli (V2'de) | Anlık |

### 8.2 Üç Katmanlı Depolama

```
PostgreSQL  → OLTP (operasyonel/ilişkisel)
ClickHouse  → OLAP (analitik/time-series)
Redis       → Hot state/cache
Parquet     → Data lake (uzun dönem)
DuckDB      → Historical research queries
```

---

## 9. Event Streaming

### 9.1 Redpanda Topic Yapısı (26 topic)

```
market.tick, market.trade, market.quote, market.orderbook
news.raw, news.event, kap.event, macro.event, social.event
feature.updated, state.updated, market_state.changed, world_state.changed
signal.generated, anomaly.detected, regime.changed
simulation.requested, simulation.completed
risk.changed, risk.alert, kill_switch.triggered
decision.created, order.placed, order.filled
prediction.created, outcome.created
```

### 9.2 Schema Registry

Her event tipi versiyonlanır: `market.tick.v1`, `market.tick.v2`

---

## 10. Real-Time Engine

### 10.1 Temel Prensip

**Her tick'te 800 hissenin geçmişini yeniden okumak yok.**

```
tick → state update → incremental features → anomaly check → candidate filter
```

### 10.2 Incremental Update Mekanizması

```python
def process_tick(tick: MarketTick):
    state = get_state(tick.instrument_id)

    # 1. Price update
    state.price.previous = state.price.current
    state.price.current = tick.price
    state.price.change_pct = (tick.price / state.price.previous - 1) * 100

    # 2. Volume update (rolling window)
    state.volume.history.append(tick.volume)
    state.volume.history = state.volume.history[-20:]  # keep last 20
    state.volume.current = tick.volume
    state.volume.avg_20d = mean(state.volume.history)
    state.volume.zscore_20d = (tick.volume - state.volume.avg_20d) / std(state.volume.history)

    # 3. Momentum (requires historical prices)
    if len(state.price.history) >= 5:
        state.momentum.roc_5d = (tick.price / state.price.history[-5] - 1) * 100

    # 4. Only recompute affected features
    if state.volume.zscore_20d > 2.0:
        recompute_anomaly_score(state)

    save_state(state)
```

---

## 11. ML Pipeline & Label Protocol

### 11.1 ML Label Tanımları (Kesin)

Her ML modeli için label (hedef değişken) kesin olarak tanımlanmıştır:

| Model | Label | Hesaplama |
|-------|-------|-----------|
| `momentum_5d` | `return_5d` | `(P_{t+5} / P_t - 1) * 100` |
| `momentum_20d` | `return_20d` | `(P_{t+20} / P_t - 1) * 100` |
| `breakout` | `breakout_success` | `1 if max(H_{t+5:t+10}) > P_t * 1.03 else 0` |
| `anomaly` | `unusual_return` | `1 if |return_5d| > 2 * realized_vol else 0` |
| `risk` | `max_drawdown_20d` | `min(P_{t:t+20}) / P_t - 1` |
| `spec` | `spec_outcome` | `1 if return_20d > 5% AND max_drawdown > -3% else 0` |

### 11.2 Training Protocol

```
1. DATA COLLECTION
   - ClickHouse'dan son 5 yıl features + outcomes
   - Survivorship bias: sadece listede kalan hisseler (delist edilenler de dahil)
   - Look-ahead bias: feature hesaplama sadece t anına kadar olan veriyle

2. LABEL GENERATION
   - Her label yukarıdaki formüllere göre hesaplanır
   - NaN labels filtrelenir
   - Label distribution kontrolü (class imbalance varsa SMOTE/weights)

3. TRAIN/VALIDATION/TEST SPLIT
   - Train: 2018-2024
   - Validation: 2024-2025
   - Test (walk-forward): 2025-2026
   - Zaman bazlı split (shuffle yok!)

4. FEATURE SELECTION
   - Mutual Information
   - Permutation Importance
   - SHAP
   - Feature stability check
   - Leakage detection

5. MODEL TRAINING
   - LightGBM (ana model)
   - XGBoost (ensemble alternatifi)
   - Hyperparameter: Optuna ile optimization
   - Cross-validation: Time-series split

6. EVALUATION
   - Sharpe Ratio
   - Max Drawdown
   - Win Rate
   - Profit Factor
   - Precision/Recall (sinyal doğruluğu)
   - Calibration (predicted probability vs actual frequency)

7. WALK-FORWARD VALIDATION
   - Rolling window: her ay yeni model eğit, sonraki ay test et
   - Out-of-sample performance ölçümü

8. CHAMPION/CHALLENGER
   - Yeni model eski modelden Sharpe'da %5+ daha iyi mi?
   - Evet → Challenger → Paper trading → Champion
   - Hayır → Eski model korunur
```

### 11.3 Bias Koruması

| Bias | Koruma Mekanizması |
|------|-------------------|
| Look-ahead | Feature hesaplama sadece t anına kadar olan veriyle |
| Survivorship | Delist edilen hisseler de training data'da |
| Selection | Sadece belirli hisseleri değil, tüm BIST'i kullan |
| Overfitting | Walk-forward validation, regularization |
| Data leakage | Feature leakage detection pipeline |

### 11.4 Ensemble Mimarisi

```
LightGBM (momentum_5d)  →  P1
LightGBM (momentum_20d) →  P2
XGBoost (breakout)       →  P3
LightGBM (anomaly)       →  P4
LightGBM (risk)          →  P5

Weighted Average:
  Final = w1*P1 + w2*P2 + w3*P3 + w4*P4 + w5*P5

  w_i = 1 / (validation_error_i) normalized
```

---

## 12. AI/LLM Katmanı

### 12.1 Model: Gemma 4 12B Unified Q4_0

- Quantization: Q4_0 (6.7 GB VRAM)
- Context: 8K-16K (256K kullanmayacağız)
- Runtime: Ollama
- Görev: Reasoning / synthesis / yorumlama

### 12.2 LLM Görev Tanımı

```
✅ Seçilmiş adayları derin reasoning
✅ KAP/haber yorumlama
✅ Olaylar arası bağlantı kurma
✅ Senaryo değerlendirme
✅ Bulguları doğal dile çevirme
✅ Karar zincirini açıklama

❌ 800 hisseyi sürekli okumayacak
❌ Tick hesaplamayacak
❌ Teknik indikatör hesaplamayacak
❌ Bütün database'i belleğine almayacak
```

### 12.3 Fine-tuning Stratejisi (v1.1 Düzeltme)

```
Aşama 1 (başlangıç): RAG / Memory — Gemma sabit, sadece context değişir
Aşama 2 (veri birikince): QLoRA — küçük adapter ağırlıkları (RTX 4080'de yapılabilir)
Aşama 3 (ileri): Cloud training — gerektiğinde GPU kiralanarak

❌ Full fine-tuning mimari hedef olarak yok
```

---

## 13. Finansal Motorlar

### 13.1 Regime Engine

Piyasa rejimi tespiti:

```
PANIC, RISK-OFF, HIGH-VOLATILITY, TRENDING-UP, TRENDING-DOWN,
RANGE, LOW-VOLATILITY, RECOVERY, MOMENTUM-EXPANSION, MOMENTUM-CONTRACTION
```

### 13.2 Strategy Engine

```
Momentum, Breakout, Mean Reversion, Event Driven, SPEC, Value, Defensive
```

Stratejiler piyasa rejimine göre otomatik aktif/pasif olur.

### 13.3 Simulation Engine

**v1.1 Düzeltme: Monte Carlo senaryo sayısı dinamik**

```python
def compute_scenario_count(volatility, model_uncertainty, portfolio_size, compute_budget):
    base_count = 1000

    # Yüksek volatilite → daha fazla senaryo
    vol_multiplier = max(1.0, volatility / 0.02)

    # Yüksek model belirsizliği → daha fazla senaryo
    uncertainty_multiplier = max(1.0, model_uncertainty / 0.3)

    # Büyük portföy → daha fazla senaryo
    size_multiplier = max(1.0, portfolio_size / 100000)

    # Hesaplama bütçesi (maksimum)
    max_count = compute_budget / 0.001  # her senaryo ~0.001 saniye

    count = int(base_count * vol_multiplier * uncertainty_multiplier * size_multiplier)
    return min(count, max_count, 50000)
```

### 13.4 Counterfactual Engine

```
Actual:    THYAO +6%
Expected:  +1.4% (model beklentisi, olay olmadan)
Event contribution: +4.6%
```

---

## 14. Risk Yönetimi

### 14.1 Risk Gate — AI'nın Üstünde

```
AI: "THYAO AL"
      ↓
Risk Gate:
  ├─ Pozisyon limiti (max %10)
  ├─ Sektör konsantrasyonu (max %30)
  ├─ Korelasyon riski (max 0.8)
  ├─ Drawdown limiti (max %15)
  ├─ Günlük zarar limiti (max %5)
  ├─ Likidite riski
  └─ Gap riski
      ↓
ONAY / RED / AZALT
```

### 14.2 Kill Switch

```
Otomatik tetikleme:
  - Tek günde portföy >%5 düşüş
  - Model drift tespiti
  - Veri kalitesi anomalisi
  - Beklenmeyen volatilite spike'ı
  - Manuel tetikleme
```

---

## 15. Öğrenme Sistemi

### 15.1 Üç Ayrı Hafıza

| Hafıza | İçerik | Teknoloji |
|--------|--------|-----------|
| Episodic | "13 Ağustos 2026'da ne oldu?" | ClickHouse |
| Semantic | "Bu şirket hangileriyle ilişkili?" | PostgreSQL + pgvector |
| Learned Model | "Bu özellikler hangi sonucu doğurur?" | LightGBM/XGBoost |

### 15.2 Öğrenme Döngüsü

```
LIVE MODEL → PREDICTION → OUTCOME → ERROR → DATASET
  → ML RETRAINING + LLM QLoRA (gelecek)
  → VALIDATION → BACKTEST → WALK-FORWARD
  → PAPER TRADING → CHAMPION / CHALLENGER
```

---

## 16. Donanım Kaynak Dağılımı & Memory Limits

### 16.1 i7 13. Nesil + RTX 4080 16GB + 16GB RAM

**v1.1 Düzeltme: 16GB RAM ciddi sınır. Aşağıdaki limitler zorunludur.**

#### RAM Dağılımı (Sıkı)

```
Windows OS              ~4-5 GB
Docker services         ~3-4 GB
PostgreSQL + Redis      ~1-2 GB
Python workers          ~1-2 GB
Buffer                   ~1 GB
────────────────────────────────
Toplam                  ~10-13 GB
LLM RAM                 GPU'da (RAM'de değil)
```

#### Container Memory Limits (Zorunlu)

```yaml
# docker-compose.yml
services:
  postgres:
    mem_limit: 1g
  clickhouse:
    mem_limit: 2g
  redis:
    mem_limit: 512m
  redpanda:
    mem_limit: 1g
  api:
    mem_limit: 512m
  ingestion:
    mem_limit: 256m
  feature-engine:
    mem_limit: 512m
  market-state:
    mem_limit: 256m
  intelligence:
    mem_limit: 512m
  simulation:
    mem_limit: 512m
  risk:
    mem_limit: 256m
  portfolio:
    mem_limit: 256m
  learning:
    mem_limit: 1g
```

#### ClickHouse Query Limits

```xml
<!-- ClickHouse config -->
<max_memory_usage>2000000000</max_memory_usage>  <!-- 2GB -->
<max_memory_usage_for_all_queries>4000000000</max_memory_usage_for_all_queries>  <!-- 4GB -->
```

#### Redpanda Memory Limits

```yaml
redpanda:
  command:
    - --memory 1G
    - --reserve-memory 0M
```

#### Worker Concurrency Limits

```python
# Feature engine
MAX_CONCURRENT_TICKS = 50  # aynı anda işlenecek maksimum tick

# ML inference
MAX_CONCURRENT_PREDICTIONS = 10

# LLM
MAX_CONCURRENT_LLM_REQUESTS = 1  # tek seferde 1 LLM isteği
```

#### Graceful Degradation

```python
# RAM kullanımı %85'i aşarsa:
if memory_usage > 0.85:
    # 1. ClickHouse cache küçült
    # 2. Redis TTL'leri kısalt
    # 3. ML inference sıklığı azalt
    # 4. LLM istekleri bekleme moduna al
    # 5. Dashboard güncelleme sıklığı azalt
    logger.warning("HIGH MEMORY: graceful degradation activated")
```

---

## 17. Dashboard & UI

### 17.1 Sayfa Yapısı (16 Sayfa)

```
CORE:     Overview, Market Radar, Market Map, Event Center
INTEL:    Opportunities, Asset Intelligence, World Intelligence, AI Research
PORTFOLIO: Portfolio, Scenario Lab, Strategy Center
MODELS:   Model Center, Learning Lab
SYSTEM:   Data Center, Alert Center, System Health
GLOBAL:   Ctrl+K AI Command Center
```

### 17.2 Tasarım Dili

- Siyah/graphite zemin, 1px separator, yüksek bilgi yoğunluğu
- Monospaced numerik alanlar, sparklines, heatmap
- Teal/amber/red sadece anlam taşıdığımızda
- ❌ Neon, gradient, dev kartlar, kripto estetiği

---

## 18. Teknoloji Stack

| Katman | Seçim | Not |
|--------|-------|-----|
| Frontend | Next.js + React + TypeScript | Tailwind + shadcn/ui |
| Backend | Python + FastAPI | Polars (❌ Pandas ana pipeline) |
| Event Bus | Redpanda | Tek node, Kafka uyumlu |
| OLTP | PostgreSQL | pgvector dahil |
| OLAP | ClickHouse | Finansal time-series |
| Cache | Redis | Hot state |
| Data Lake | Parquet + DuckDB | Historical |
| ML | LightGBM + XGBoost | Ensemble |
| LLM | Gemma 4 12B Q4_0 | Ollama |
| Embeddings | BGE-M3 multilingual | Türkçe+İngilizce |
| Model Registry | MLflow | Versioning |
| Workflow | Prefect | Batch jobs |
| Monitoring | Prometheus + Grafana | OpenTelemetry |
| Containers | Docker Compose | Tek laptopta |

---

## 19. Geliştirme Aşamaları

### MVP (~4-6 hafta)
- BIST delayed data + KAP + TCMB EVDS
- PostgreSQL + ClickHouse + Redis + Redpanda
- Feature engine (50+ feature, incremental)
- Basic ML (LightGBM baseline)
- Gemma 4 12B reasoning
- Backtest (replay-based)
- Dashboard skeleton

### V1 (~3-4 ay)
- 800+ asset coverage
- SPEC engine (matematiksel tanım)
- Impact Propagation Engine
- Dynamic World State
- Feature Discovery Pipeline
- Simulation Lab (dynamic Monte Carlo)
- Learning Engine
- Tüm 16 sayfa dashboard

### V2 (~6-12 ay)
- Lisanslı real-time feed
- Broker API entegrasyonu
- Kontrollü otomatik execution
- LLM QLoRA fine-tuning
- Sosyal medya streaming

---

## 20. Referanslar

- Borsa İstanbul: borsaistanbul.com/veriler/veri-yayini
- KAP: kap.org.tr
- TCMB EVDS: evds.tcmb.gov.tr
- ClickHouse StockHouse: clickhouse.com/blog/building-stockhouse
- Gemma 4: ai.google.dev/gemma/docs/core/model_card_4
- MLflow: mlflow.org/docs/latest/ml/model-registry
- Fin-Analyst (LLM + Rule-Based): arxiv.org/abs/2607.12233
- Time-Series DB Benchmark: arxiv.org/abs/2608.01459
- BlackRock Aladdin: blackrock.com/aladdin
- KX kdb+ tick: code.kx.com/q/wp/rt-tick

---

*v1.1 — 14 Ağustos 2026 — Servet'in geri bildirimleriyle teknik olarak sıkılaştırılmıştır.*
