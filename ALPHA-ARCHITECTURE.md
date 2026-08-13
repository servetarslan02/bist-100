# ALPHA BIST — Nihai Teknik Mimarî Spesifikasyon v1.0

> **Proje:** BIST Market Intelligence & Quant Engine
> **Hedef:** 800+ BIST hissesini 7/24 tarayan, otonom piyasa zekâsı platformu
> **Donanım:** i7 13. nesil + RTX 4080 16GB VRAM + 16GB RAM
> **Tarih:** 14 Ağustos 2026
> **Durum:** Architecture v1.0 — Kilitli

---

## İçindekiler

1. [Proje Tanımı](#1-proje-tanımı)
2. [Sistem Mimarisi](#2-sistem-mimarisi)
3. [Veri Katmanı](#3-veri-katmanı)
4. [Event Streaming](#4-event-streaming)
5. [Real-Time Engine](#5-real-time-engine)
6. [Feature Engine](#6-feature-engine)
7. [ML Pipeline](#7-ml-pipeline)
8. [AI/LLM Katmanı](#8-aillm-katmanı)
9. [Knowledge Graph & World Intelligence](#9-knowledge-graph--world-intelligence)
10. [Finansal Motorlar](#10-finansal-motorlar)
11. [Risk Yönetimi](#11-risk-yönetimi)
12. [Öğrenme Sistemi](#12-öğrenme-sistemi)
13. [Dashboard & UI](#13-dashboard--ui)
14. [Teknoloji Stack](#14-teknoloji-stack)
15. [Donanım Kaynak Dağılımı](#15-donanım-kaynak-dağılımı)
16. [Geliştirme Aşamaları (MVP → V1 → V2)](#16-geliştirme-aşamaları)
17. [Eksikler & Düzeltmeler](#17-eksikler--düzeltmeler)
18. [Referanslar](#18-referanslar)

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

Sistem sadece RSI, MACD, F/K gibi sabit metrikleri kullanmayacak. Binlerce ham değişken arasındaki korelasyonları, gecikmeli ilişkileri, rejim değişimlerini ve beklenmeyen kombinasyonları kendi keşfedecek.

### 1.4 LLM'nin Rolü (Kritik Ayrım)

| Katman | Görev | Teknoloji |
|--------|-------|-----------|
| **Quant** | Deterministik hesaplama | Python/NumPy/Pandas |
| **ML** | Tahmin / pattern discovery | LightGBM, XGBoost, PyTorch |
| **AI** | Reasoning / synthesis / yorumlama | Gemma 4 12B |

**LLM 800 hisseyi sürekli okumayacak.** Sadece filtrelenmiş adaylara (5-20) derin reasoning uygulayacak.

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
                   KNOWLEDGE LAYER
                           │
                    ┌──────┴──────┐
                    ↓             ↓
                pgvector        State
                    │             │
                    └──────┬──────┘
                           ↓
                    GEMMA 4 12B
                           ↓
                 REASONING / SYNTHESIS
                           ↓
                   REGIME ENGINE
                           ↓
                  STRATEGY ENGINE
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

## 3. Veri Katmanı

### 3.1 Veri Kaynakları

#### Piyasa Verisi

| Veri | İlk Geliştirme (MVP) | Canlı Sistem | Not |
|------|----------------------|--------------|-----|
| BIST fiyat/hacim | yfinance (15dk gecikmeli) | Lisanslı BIST feed | yfinance `.IS` suffix ile BIST verisi verir |
| Order-flow | Yok (MVP'de) | BIST Equity Market Data Analytics | 1sn periyotla order arrival/cancellation |
| Endeksler | yfinance | Lisanslı feed | BIST100, BIST30, sektörel endeksler |
| Global fiyat | Alpha Vantage / Twelve Data (ücretsiz tier) | Lisanslı API | S&P500, Nasdaq, DAX, Asya |

**Not:** yfinance, BIST hisseleri için `.IS` suffix'i kullanır (örn: `THYAO.IS`). Ücretsiz ama 15dk gecikmeli. İlk MVP için yeterli.

#### Şirket Verisi

| Veri | Kaynak | Erişim |
|------|--------|--------|
| KAP bildirimleri | kap.org.tr | Scrape + parse (resmi API sınırlı) |
| Finansal tablolar | KAP | Parse (bilanço, gelir tablosu, nakit akışı) |
| Temettü/bedelli | KAP + BIST | Structured data |
| Sermaye hareketleri | KAP | Event extraction |

**KAP Parse Notu:** KAP'tan gelen bildirimlerin NLP ile işlenmesi kritik. Her bildirim tipi (Özel Durum Açıklaması, Finansal Rapor, Hak Kullanımı vb.) farklı formatta. Ayrı bir **KAP Parser servisi** gerekiyor. GitHub'da `kap` Python SDK'sı mevcut (github.com/topics/bist100).

#### Makro Veri

| Veri | Kaynak | API |
|------|--------|-----|
| USD/TRY, EUR/TRY | TCMB EVDS | Ücretsiz API key |
| Faiz (politika, tahvil) | TCMB EVDS | Ücretsiz |
| Enflasyon (TÜFE, ÜFE) | TÜİK | Ücretsiz |
| CDS | Investing.com | Scrape |
| VIX | Yahoo Finance | yfinance |
| Petrol, Altın | Alpha Vantage | Ücretsiz tier |
| Fed/ECB kararları | Haber akışı | NLP extraction |

**TCMB EVDS:** 145 kategori, on binlerce makro seri. Ücretsiz API key ile erişilebilir. Python'da `evds` kütüphanesi mevcut.

#### Haber & Sosyal

| Veri | Kaynak | Not |
|------|--------|-----|
| Finans haberleri | NewsAPI, Finnhub, RSS | Ücretsiz tier mevcut |
| Şirket haberleri | KAP + şirket IR sayfaları | Scrape |
| Sosyal medya | X API | Ücretli; ilk MVP'de opsiyonel |
| Analist raporları | Lisanslı kaynaklar | V2'de |

### 3.2 Veri Mimarisi — Üç Katmanlı Depolama

```
                   ALPHA DATA PLATFORM
                          │
           ┌──────────────┼──────────────┐
           ↓              ↓              ↓
       PostgreSQL      ClickHouse      Parquet
        OLTP            OLAP           DATA LAKE
           │              │              │
           └──────────────┼──────────────┘
                          ↓
                   ML / RESEARCH
```

#### PostgreSQL — Operasyonel Beyin

**Görev:** ACID, ilişkisel bütünlük, transactional işlemler

**Tablolar:**
- `companies` — şirket referans bilgileri
- `instruments` — hisse senedi bilgileri
- `sectors` — sektör tanımları
- `portfolios` — portföy bilgileri
- `positions` — pozisyonlar
- `orders` — emirler
- `fills` — gerçekleşen işlemler
- `strategies` — strateji tanımları
- `signals` — üretilen sinyaller
- `models` — model metadata
- `model_versions` — model versiyonları
- `alerts` — uyarılar
- `audit_logs` — denetim kayıtları
- `system_events` — sistem olayları
- `knowledge_entities` — bilgi grafiği varlıkları
- `knowledge_relations` — bilgi grafiği ilişkileri
- `users` — kullanıcı bilgileri (gelecek)

#### ClickHouse — Analitik Beyin

**Görev:** Milyarlarca satırda hızlı aggregation, time-series analytics

**Tablolar:**
- `market_ticks` — fiyat/hacim tick verileri
- `market_trades` — işlem verileri
- `quotes` — alış/satış teklifleri
- `orderbook_snapshots` — emir defteri anlık görüntüleri
- `features` — hesaplanmış feature'lar
- `asset_states` — hisse durumları
- `market_states` — piyasa durumları
- `world_states` — dünya durumları
- `news_events` — haber olayları
- `social_events` — sosyal medya olayları
- `kap_events` — KAP bildirimleri
- `macro_events` — makro olaylar
- `historical_signals` — geçmiş sinyaller
- `model_predictions` — model tahminleri
- `model_outcomes` — model sonuçları

**ClickHouse Avantajları (Araştırma Sonucu):**
- Kolon bazlı çalıştığı için yalnızca gereken kolonları okur
- Sıkıştırma ve vectorized execution ile büyük taramalarda çok güçlü
- Finansal tick data doğrudan hedeflenen kullanım alanlarından biri
- Longbridge Technology gibi fintech şirketleri production'da kullanıyor

#### Redis — Kısa Süreli Hafıza

**Görev:** Hot state, cache, canlı dashboard state

**Kullanım:**
- Her hissenin mevcut state'i (anlık fiyat, momentum, anomaly score vb.)
- Dashboard live state cache
- Rate limiting
- Pub/Sub (WebSocket broadcast)

#### Parquet + DuckDB — Uzun Süreli Arşiv

**Görev:** Historical data lake, research queries, ML dataset

**Kullanım:**
- 5+ yıllık tick/event verileri
- Backtest dataset'leri
- ML training data
- Araştırma sorguları

**DuckDB Avantajları:**
- Parquet üzerinde doğrudan projection/filter pushdown
- Dosyaları paralel tarama
- SQL interface ile kolay sorgu

### 3.3 Veri Saklama Stratejisi

```
HOT (son saatler/günler)  →  Redis + RAM + ClickHouse
WARM (son aylar)          →  ClickHouse + PostgreSQL
COLD (yıllar)             →  Parquet + DuckDB
```

---

## 4. Event Streaming

### 4.1 Redpanda

**Neden Redpanda (Kafka değil)?**
- Tek node'da çalışabilir (Kafka Zookeeper gerektirir)
- Kafka uyumlu API
- Düşük latency
- Daha az kaynak tüketimi
- Tek laptopta yeterli

### 4.2 Topic Yapısı

```
market.tick          # Fiyat tick'leri (partition: instrument_id)
market.trade         # İşlemler
market.quote         # Alış/satış teklifleri
market.orderbook     # Emir defteri

news.raw             # Ham haber akışı
news.event           # İşlenmiş haber olayları
kap.event            # KAP bildirimleri
macro.event          # Makro veri olayları
social.event         # Sosyal medya olayları

feature.updated      # Feature güncellemeleri
state.updated        # State değişiklikleri

signal.generated     # Üretilen sinyaller
simulation.requested # Simülasyon istekleri
simulation.completed # Tamamlanan simülasyonlar

risk.changed         # Risk değişiklikleri
decision.created     # Karar oluşturuldu

prediction.created   # Tahmin oluşturuldu
outcome.created      # Sonuç kaydedildi
```

### 4.3 Schema Registry

Event formatları versiyonlandırılacak:

```
market.tick.v1
market.tick.v2
news.event.v1
signal.generated.v1
```

**Amaç:** Bir servis veri formatını değiştirdiğinde bütün sistem kırılmasın.

---

## 5. Real-Time Engine

### 5.1 Temel Prensip

**Her tick'te 800 hissenin geçmişini yeniden okumak yok.**

```
tick
  ↓
state update (sadece değişen hisse)
  ↓
incremental feature hesaplama
  ↓
anomaly check
  ↓
candidate filter
```

### 5.2 State Store (RAM + Redis)

Her hissenin persistent state'i:

```python
class AssetState:
    ticker: str
    price: float
    volume: float
    returns_1m: float
    returns_5m: float
    returns_1h: float
    returns_1d: float
    volatility: float
    momentum_5d: float
    momentum_20d: float
    relative_strength: float
    sector_strength: float
    volume_zscore: float
    liquidity_score: float
    anomaly_score: float
    event_score: float
    social_score: float
    risk_score: float
    regime: str
    spec_score: float
    last_update: datetime
```

### 5.3 Incremental Update

Yeni tick geldiğinde:
1. İlgili hissenin state'ini güncelle
2. Rolling window hesaplamalarını增量 yap
3. Anomali kontrolü
4. Gerekli feature'ları yeniden hesapla
5. State'i Redis'e yaz
6. Event Bus'a_publish et

**Diğer 799 hisse etkilenmez.**

---

## 6. Feature Engine

### 6.1 Feature Kategorileri

#### Fiyat & Momentum
- `price_return_1m/5m/15m/1h/1d/5d/20d`
- `momentum_5d/20d/60d`
- `rate_of_change`
- `price_acceleration`
- `trend_strength` (ADX tabanlı)

#### Hacim
- `volume_zscore` (son 20 gün ortalamasına göre)
- `volume_ratio` (günlük ortalamaya göre)
- `buy_volume_ratio`
- `volume_trend`
- `unusual_volume_flag`

#### Volatilite
- `atr_14`
- `realized_volatility_5d/20d`
- `volatility_regime` (düşük/normal/yüksek/aşırı)
- `bollinger_width`
- `volatility_zscore`

#### Teknik
- `rsi_14`
- `macd_signal`
- `stochastic_k/d`
- `adx`
- `cci`
- `williams_r`
- `mfi` (Money Flow Index)

#### Göreceli Güç
- `relative_strength_vs_index`
- `relative_strength_vs_sector`
- `sector_momentum`
- `cross_sectional_rank`

#### Likidite
- `bid_ask_spread`
- `amihud_illiquidity`
- `turnover_rate`
- `free_float_adjusted_volume`

#### Fundamental (çeyreklik güncellenir)
- `pe_ratio`
- `pb_ratio`
- `ev_ebitda`
- `debt_equity`
- `roe`
- `revenue_growth`
- `earnings_growth`
- `dividend_yield`
- `free_float_ratio`

#### Event/Sentiment
- `kap_sentiment_score`
- `news_sentiment_score`
- `social_sentiment_score`
- `event_impact_score`
- `days_since_last_event`

### 6.2 Feature Store

İlk sürümde ayrı Feast altyapısı yok:

```
ClickHouse  → historical features
Redis       → hot/current features
Parquet     → training dataset features
```

---

## 7. ML Pipeline

### 7.1 Model Mimarisi — Ensemble

Tek model değil, uzman modeller:

```
Model 1 → Momentum (kısa vadeli hareket)
Model 2 → Breakout (kırılım başarısı)
Model 3 → Anomaly (anomali tespiti)
Model 4 → SPEC (olağandışı hareket davranışı)
Model 5 → Return Predictor (5D/20D/60D getiri olasılığı)
Model 6 → Risk (volatilite/drawdown tahmini)
Model 7 → Regime (piyasa rejimi sınıflandırma)
```

### 7.2 Model Teknolojileri

| Model | Kullanım | Neden |
|-------|----------|-------|
| **LightGBM** | Ana tabular ML | Hızlı, düşük bellek, finansal veride güçlü |
| **XGBoost** | Alternatif ensemble | Farklı boosting stratejisi |
| **PyTorch** | Deep learning (gelecek) | Sequence models, transformer time-series |

**Araştırma Notu:** LightGBM ve XGBoost, finansal zaman serisi tahmininde hâlâ en güçlü tabular ML modelleri. 2025-2026 araştırmaları, EMD + RFE ile birlikte kullanıldığında doğruluğun önemli ölçüde arttığını gösteriyor.

### 7.3 Eğitim Stratejisi

```
CANLI PİYASA
    ↓
Tahminler üretiliyor
    ↓
Gerçek sonuçlarla eşleştiriliyor
    ↓
Öğrenme örnekleri (prediction → outcome)
    ↓
Training dataset'e ekleniyor
    ↓
Periyodik yeniden eğitim (haftalık/gecelik)
    ↓
Walk-forward validation
    ↓
Champion/Challenger karşılaştırması
    ↓
Yeni model gerçekten daha iyi mi?
    ↓
Evet → Challenger → Champion
Hayır → Eski model korunur
```

### 7.4 Feature Engineering — Önemli Not

**Araştırma Sonucu:** 2025-2026 çalışmaları, ham fiyat verisinden üretilen geleneksel teknik indikatörlerin (RSI, MACD vb.) tek başına yetersiz olduğunu gösteriyor. Triple Barrier Labeling ve cross-sectional features çok daha güçlü.

**Önerilen feature stratejisi:**
1. Ham sayısal features (fiyat, hacim, volatilite)
2. Cross-sectional features (hisseler arası göreceli güç)
3. Regime-conditional features (piyasa rejimine göre farklı ağırlıklar)
4. Event-derived features (KAP/haber embedding'leri)
5. Temporal features (zaman desenleri, seans içi pattern'lar)

### 7.5 Backtest Mimarisi

**Replay-based backtest** — en güvenilir yöntem:

```
Historical Event Log
       ↓
Replay (zaman sırasıyla)
       ↓
Real System (geleceği bilmiyor)
       ↓
Decision üretimi
       ↓
Virtual Execution (spread, slippage dahil)
       ↓
Outcome ölçümü
```

**Backtest metrikleri:**
- Sharpe Ratio
- Sortino Ratio
- Maximum Drawdown
- Win Rate
- Profit Factor
- Calmar Ratio
- Information Ratio
- Hit Rate (5D/20D/60D)
- Precision / Recall (sinyal doğruluğu)

**Bias koruması:**
- Look-ahead bias engeli
- Survivorship bias engeli
- Transaction cost dahil
- Slippage modellemesi

---

## 8. AI/LLM Katmanı

### 8.1 Model Seçimi: Gemma 4 12B Q4_0

**Neden Gemma 4 12B?**
- Apache 2.0 lisansı (ücretsiz, ticari kullanım serbest)
- 256K context desteği
- RTX 4080 16GB'da Q4_0 ile ~6.7 GB VRAM kullanımı
- Multimodal (gelecekte grafik analizi için)
- Google DeepMind kalitesi

**Araştırma Notu:** Gemma 4 26B MoE (sadece 3.8B aktif) alternatif olarak düşünülebilir. Ancak 12B model daha stabil ve predictable.

**Quantization:** Q4_0 (6.7 GB VRAM)
**Context:** 8K-16K (256K kullanmayacağız — gereksiz VRAM tüketimi)
**Runtime:** Ollama

### 8.2 LLM'nin Görev Tanımı

```
❌ 800 hisseyi sürekli okumayacak
❌ Tick hesaplamayacak
❌ Teknik indikatör hesaplamayacak
❌ Bütün database'i belleğine almayacak

✅ Seçilmiş adayları derin reasoning
✅ KAP/haber yorumlama
✅ Olaylar arası bağlantı kurma
✅ Senaryo değerlendirme
✅ Bulguları doğal dile çevirme
✅ Karar zincirini açıklama
```

### 8.3 Context Builder

LLM'ye veri göndermeden önce sistem toplayacak:

```
Market State (piyasa durumu)
+ Company State (şirket durumu)
+ Sector State (sektör durumu)
+ Recent Events (son olaylar)
+ Historical Analogues (benzer geçmiş durumlar)
+ Signals (üretilen sinyaller)
+ Risk (risk durumu)
+ Scenario (senaryo sonuçları)
= 8-16K kaliteli context
```

### 8.4 Kalıcı AI Hafızası

Bilgisayar kapanınca AI unutmaz:

```
PostgreSQL     → ilişkisel bilgi
ClickHouse     → olay geçmişi
Parquet        → uzun dönem veri
pgvector       → embedding'ler
Knowledge Graph → entity ilişkileri
MLflow         → model geçmişi
```

---

## 9. Knowledge Graph & World Intelligence

### 9.1 World State

Sistem haberleri tek tek okumak yerine dünyanın mevcut durumunu oluşturacak:

```python
class WorldState:
    geopolitical_risk: float      # 0-1
    global_risk_appetite: float   # 0-1
    usd_strength: float           # 0-1
    us_rate_pressure: float       # 0-1
    commodity_pressure: float     # 0-1
    oil_pressure: float           # 0-1
    turkey_macro_risk: float      # 0-1
    emerging_market_risk: float   # 0-1
    vix_level: float
    social_attention: float       # 0-1
    news_shock: float             # 0-1
```

### 9.2 Knowledge Graph

İlk aşamada PostgreSQL + pgvector:

```
FED → USD → EMERGING MARKETS → BIST
PETROL → TUPRS → ENERGY SECTOR → BIST
TCMB → FAİZ → BANKACILIK → AKBNK/GARAN
```

İhtiyaç büyürse Neo4j'ye geçilebilir.

### 9.3 Entity Resolution

Aynı varlığın farklı kaynaklardaki ifadelerini birleştirme:

```
"Trump" = "ABD Başkanı" = "Washington yönetimi" = "White House"
"Fed" = "Federal Reserve" = "FOMC"
```

---

## 10. Finansal Motorlar

### 10.1 Regime Engine

Piyasanın mevcut durumunu tespit eder:

```
RISK-ON / RISK-OFF
TRENDING / RANGE
HIGH VOLATILITY / LOW VOLATILITY
PANIC / RECOVERY
MOMENTUM EXPANSION / CONTRACTION
```

### 10.2 Opportunity / SPEC Engine

**SPEC tespit kriterleri (çoklu kanıt birleştirme):**
- Normalden anormal hacim
- Fiyat sıkışması
- Takas değişimi
- Olumlu KAP
- Sektör güçlenmesi
- Teknik kırılım
- Düşük volatilite sonrası momentum

**Tek indikatör "AL" demek yerine kanıtların birbirini destekleyip desteklemediğine bakılır.**

### 10.3 Zaman Ufku Ayrımı

Her hisse için ayrı skor:

```
⚡ Kısa vade:  1-5 gün
📈 Orta vade:  1-4 hafta
🚀 Uzun vade:  1-6 ay
🏦 Çok uzun:   6-24 ay
```

### 10.4 Strategy Engine

```
Momentum          ACTIVE / PAUSED
Breakout          ACTIVE / PAUSED
Mean Reversion    ACTIVE / PAUSED
Event Driven      ACTIVE / PAUSED
Defensive         ACTIVE / PAUSED
SPEC              WATCH / ACTIVE
```

Stratejiler piyasa rejimine göre otomatik değişir.

### 10.5 Simulation Lab

```
Monte Carlo       → 10,000 senaryo
Historical Analog → Benzer geçmiş olaylar
Stress Test       → %10 düşüş, volatilite spike
Black Swan        → Ekstrem senaryolar
```

### 10.6 Counterfactual Engine

```
Actual:    THYAO +6%
Expected:  +1.4% (model beklentisi)
Event contribution: +4.6%
```

Hangi sinyalin gerçekten değer yarattığını öğrenmek için.

---

## 11. Risk Yönetimi

### 11.1 Risk Gate — AI'nın Üstünde

```
AI: "THYAO AL"
      ↓
Risk Gate:
  ├─ Pozisyon limiti aşıldı mı?
  ├─ Sektör konsantrasyonu?
  ├─ Korelasyon riski?
  ├─ Drawdown limiti?
  ├─ Likidite yeterli mi?
  ├─ Gap riski?
  └─ Tail risk?
      ↓
ONAY / RED / AZALT
```

### 11.2 Risk Metrikleri

- Value at Risk (VaR) — %95, %99
- Conditional VaR (CVaR)
- Maximum Drawdown
- Sector Concentration
- Correlation Matrix
- Beta
- Liquidity Risk
- Gap Risk

### 11.3 Kill Switch

Otomatik tetikleme koşulları:
- Tek günde portföy >%5 düşüş
- Model drift tespiti
- Veri kalitesi anomalisi
- Beklenmeyen volatilite spike'ı
- Manuel tetikleme

### 11.4 Otonomi Seviyeleri

```
LEVEL 1: AI önerir → insan onaylar
LEVEL 2: AI paper trade yapar
LEVEL 3: AI otomatik execution (sadece uzun doğrulama sonrası)
```

---

## 12. Öğrenme Sistemi

### 12.1 Üç Ayrı Hafıza

| Hafıza | İçerik | Teknoloji |
|--------|--------|-----------|
| **Episodic** | "13 Ağustos 2026'da ne oldu?" | ClickHouse / event store |
| **Semantic** | "Bu şirket hangileriyle ilişkili?" | PostgreSQL + pgvector + KG |
| **Learned Model** | "Bu özellikler hangi sonucu doğurur?" | LightGBM/XGBoost/PyTorch |

### 12.2 Öğrenme Döngüsü

```
LIVE MODEL
    ↓
PREDICTION
    ↓
OUTCOME (gerçek sonuç)
    ↓
ERROR (tahmin hatası)
    ↓
FEATURE ATTRIBUTION (hangi feature hatalı?)
    ↓
LEARNING DATASET
    ↓
ML RETRAINING + LLM LoRA (gelecek)
    ↓
VALIDATION
    ↓
BACKTEST
    ↓
WALK-FORWARD
    ↓
PAPER TRADING
    ↓
CHAMPION / CHALLENGER
```

### 12.3 LLM Fine-tuning Aşamaları

```
Aşama 1 (başlangıç): RAG / Memory — Gemma sabit, sadece context değişir
Aşama 2 (veri birikince): LoRA / QLoRA — küçük adapter ağırlıkları
Aşama 3 (ileri): Full fine-tuning — sadece gerektiğinde
```

---

## 13. Dashboard & UI

### 13.1 Sayfa Yapısı (16 Sayfa)

```
ALPHA

CORE
├── 01 Overview              Ana operasyon merkezi
├── 02 Market Radar          Tüm BIST'in canlı taraması
├── 03 Market Map            Piyasanın görsel haritası (treemap)
└── 04 Event Center          Canlı olay akışı & Event Response

INTELLIGENCE
├── 05 Opportunities         Fırsat / SPEC keşfi
├── 06 Asset Intelligence    Tek hisse derin analizi
├── 07 World Intelligence    Dünya → Türkiye → sektör → şirket
└── 08 AI Research           AI'nın araştırma günlüğü

PORTFOLIO
├── 09 Portfolio             Portföy ve pozisyon yönetimi
├── 10 Scenario Lab          Senaryo / simülasyon
└── 11 Strategy Center       Strateji yönetimi

MODELS
├── 12 Model Center          ML/AI model merkezi
└── 13 Learning Lab          Öğrenme ve performans

SYSTEM
├── 14 Data Center           Veri kalitesi ve kaynaklar
├── 15 Alert Center          Uyarılar
└── 16 System Health         Sistem sağlığı

GLOBAL
└── Ctrl+K AI Command Center Her yerden erişilebilir
```

### 13.2 Tasarım Dili

**Kullanılacak:**
- Siyah/graphite ana zemin
- Çok ince grid, 1px separator
- Yüksek bilgi yoğunluğu
- Küçük ama okunabilir fontlar
- Monospaced numerik alanlar
- Mikro grafikler, sparklines, heatmap
- Kontrollü animasyon
- Teal/amber/red sadece anlam taşıdığında

**Kullanılmayacak:**
- ❌ Büyük yuvarlak kartlar
- ❌ Neon yeşil finans teması
- ❌ Kripto borsası görünümü
- ❌ Gereksiz gradient
- ❌ Dev "AI" yazıları
- ❌ 5 tane büyük KPI kartı
- ❌ Boş alanla premium görünmeye çalışma

### 13.3 Önemli Ekranlar

#### Asset Intelligence — "WHY?" Paneli

```
EDGE = 94

+21  Flow anomaly
+18  Relative strength
+16  Regime compatibility
+14  Historical similarity
+11  Fundamental state
 +8  Event state
 -5  Volatility risk
 -3  Correlation risk
────────────────────
 94  FINAL EDGE
```

#### Event Response Center

```
14:32:17  🔴 HIGH IMPACT EVENT

FED HAWKISH SURPRISE

Confidence       96%
Market Impact    91%

STRATEGY IMPACT
Momentum         DEACTIVATE
Breakout         REDUCE
Defensive        INCREASE

PORTFOLIO ACTION
Risk target      14.2% → 10.1%
Cash target      20% → 34%

[SIMULATE] [APPROVE] [REJECT]
```

### 13.4 Teknoloji

```
Frontend:  Next.js + TypeScript + React
UI:        Tailwind + shadcn/ui
Charts:    TradingView Lightweight Charts veya custom Canvas/WebGL
Realtime:  WebSocket / SSE
State:     Zustand veya Jotai
```

---

## 14. Teknoloji Stack

### 14.1 Nihai Teknoloji Tablosu

| Katman | Seçim | Not |
|--------|-------|-----|
| **OS** | Windows 11 | Mevcut donanım |
| **Frontend** | Next.js + React + TypeScript | App Router |
| **UI** | Tailwind + shadcn/ui | Profesyonel terminal hissi |
| **Backend** | Python + FastAPI | ML ekosistemi güçlü |
| **Realtime** | WebSocket / SSE | Canlı dashboard |
| **Event Bus** | **Redpanda** | Tek node, Kafka uyumlu |
| **Schema** | Protobuf / Schema Registry | Event versiyonlama |
| **OLTP** | **PostgreSQL** | Operasyonel/ilişkisel |
| **OLAP** | **ClickHouse** | Analitik/time-series |
| **Cache** | **Redis** | Hot state/cache |
| **Data Lake** | **Parquet** | Uzun dönem arşiv |
| **Historical Query** | **DuckDB** | Araştırma/backtest |
| **Data Processing** | **Polars + PyArrow** | Pandas yerine (hızlı) |
| **Vector DB** | **pgvector** | PostgreSQL içinde |
| **ML** | LightGBM + XGBoost | Tabular prediction |
| **Deep Learning** | PyTorch | Gelecek: sequence models |
| **LLM** | **Gemma 4 12B Unified Q4_0** | Tek sürekli model |
| **LLM Runtime** | **Ollama** | Yerel inference |
| **Embeddings** | BGE-M3 sınıfı multilingual | Türkçe+İngilizce |
| **Model Registry** | **MLflow** | Versioning, lineage |
| **Workflow** | **Prefect** | Batch jobs |
| **Monitoring** | **Prometheus** | System metrics |
| **Visualization** | **Grafana** | Dashboard + alerts |
| **Telemetry** | **OpenTelemetry** | Traces, metrics, logs |
| **Containers** | **Docker Compose** | Tek laptopta |
| **Version Control** | **Git** | GitHub |
| **Replay** | Custom Event Replay Engine | Backtest temeli |
| **Security** | Secrets + RBAC + Risk Gate | API key encryption |

### 14.2 Kullanılmayanlar (Bilerek)

| Teknoloji | Neden Kullanılmıyor |
|-----------|---------------------|
| ❌ TimescaleDB | ClickHouse varken gereksiz |
| ❌ Neo4j | İlk aşamada PostgreSQL KG yeterli |
| ❌ Qdrant/Weaviate | pgvector yeterli |
| ❌ Feast | Feature store operasyonel karmaşıklığı henüz gerekli değil |
| ❌ Kubernetes | Tek laptopta gereksiz |
| ❌ Kafka cluster | Redpanda tek node yeterli |
| ❌ Birden fazla sürekli LLM | 16GB RAM/VRAM için model swapping kötü |
| ❌ Pandas | Polars daha hızlı |
| ❌ Devasa Transformer ensemble | LightGBM/XGBoost daha mantıklı |

---

## 15. Donanım Kaynak Dağılımı

### 15.1 i7 13. Nesil + RTX 4080 16GB + 16GB RAM

#### RAM Dağılımı

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

#### VRAM Dağılımı

```
Gemma 4 12B Q4_0        ~6.7 GB
KV cache (8K context)   ~0.5-1 GB
Embedding model         ~0.5 GB (gerektiğinde)
GPU ML training         gerektiğinde (LLM unload edilir)
────────────────────────────────
Toplam                  ~8-9 GB (16GB'dan az)
```

#### CPU Dağılımı

```
Data ingestion          sürekli
Event processing        sürekli
Feature calculation     sürekli
PostgreSQL              sürekli
Redis                   sürekli
Risk Engine             sürekli
Backtest orchestration  gerektiğinde
```

#### Disk Dağılımı

```
PostgreSQL data         ~10-50 GB
ClickHouse data         ~50-200 GB
Parquet archives        ~100+ GB
MLflow artifacts        ~5-10 GB
Models                  ~2-5 GB
Logs                    ~5-10 GB
```

### 15.2 Kritik Optimizasyon

**16 GB RAM en büyük kısıt.** Bu nedenle:
- "Her şeyi RAM'e al" mantığı değil → `stream → state → storage → retrieve → compute`
- ClickHouse query memory limitleri konulacak
- Gemma ile diğer ağır GPU işleri aynı anda çalışmayacak
- Model eğitimi piyasa kapalıyken yapılacak

---

## 16. Geliştirme Aşamaları

### 16.1 MVP (Minimum Viable Product)

**Hedef:** Uçtan uca çalışan sistemin ispatı

```
✅ BIST delayed data (yfinance)
✅ KAP scraper/parser
✅ TCMB EVDS API
✅ PostgreSQL + ClickHouse + Redis + Redpanda (Docker Compose)
✅ Temel feature engine (20-30 feature)
✅ Basic ML (LightGBM baseline)
✅ Gemma 4 12B (Ollama)
✅ Backtest framework (replay-based)
✅ Paper trading
✅ Dashboard skeleton (Market Radar + Overview)
✅ WebSocket canlı güncelleme
```

**Süre:** ~4-6 hafta

### 16.2 V1 (İlk Tam Versiyon)

**Hedef:** Tüm finansal motorlar çalışır

```
✅ 800+ asset coverage
✅ Event-driven architecture (tam)
✅ World Intelligence
✅ Knowledge Graph
✅ SPEC Engine
✅ Regime Engine
✅ Scenario Lab (Monte Carlo)
✅ Walk-forward validation
✅ Model Registry (MLflow)
✅ Learning Engine (otomatik öğrenme döngüsü)
✅ Tüm 16 sayfa dashboard
✅ Counterfactual Engine
✅ Alert Center
```

**Süre:** ~3-4 ay

### 16.3 V2 (Profesyonel Versiyon)

**Hedef:** Gerçek execution ve profesyonel veri

```
✅ Lisanslı real-time BIST feed
✅ Advanced order-flow analytics
✅ Profesyonel haber akışı
✅ Sosyal medya streaming
✅ Execution simulator (spread, slippage)
✅ Broker API entegrasyonu
✅ Kontrollü otomatik execution
✅ Gelişmiş portföy optimizasyonu
✅ LLM LoRA fine-tuning
✅ Multi-monitor destek
```

**Süre:** ~6-12 ay

---

## 17. Eksikler & Düzeltmeler

### 17.1 Konuşmada Tespit Edilen Eksikler

| # | Eksik/Sorun | Durum | Çözüm |
|---|-------------|-------|-------|
| 1 | Veri kaynağı belirsiz | Düzeltildi | yfinance (MVP) → lisanslı feed (V2) |
| 2 | KAP parse mekanizması tanımsız | Düzeltildi | Ayrı KAP Parser servisi + GitHub SDK |
| 3 | Feature listesi tanımsız | Düzeltildi | 50+ feature kategorize edildi |
| 4 | Backtest metrikleri eksik | Düzeltildi | Sharpe, Sortino, Max DD, Win Rate vb. |
| 5 | Model drift detection mekanizması tanımsız | Düzeltildi | MLflow monitoring + statistical tests |
| 6 | Data quality monitoring eksik | Düzeltildi | Her event'te quality/latency/confidence |
| 7 | Feature engineering detayları eksik | Düzeltildi | Cross-sectional, regime-conditional |
| 8 | İlk MVP scope'u net değil | Düzeltildi | 10 maddelik MVP tanımı |
| 9 | Gemma alternatifleri araştırılmamış | Düzeltildi | Gemma 4 26B MoE alternatif |
| 10 | ClickHouse ile TimescaleDB karşılaştırması yüzeysel | Düzeltildi | Araştırma ile ClickHouse lehine karar |
| 11 | Polars vs Pandas kararı gerekçelendirilmemiş | Düzeltildi | Performans farkı büyük |
| 12 | Replay engine detaylandırılmamış | Düzeltildi | Event-based backtest mimarisi |
| 13 | Risk Gate mekanizması tanımsız | Düzeltildi | Bağımsız risk motoru |
| 14 | Kill switch tetikleme koşulları eksik | Düzeltildi | 5 otomatik tetikleme koşulu |
| 15 | Counterfactual engine implementasyonu zor | Belirtildi | Monte Carlo ile yaklaşım |
| 16 | Haber geldiğinde strateji değişimi mekanizması eksik | Düzeltildi | Event Response Center |
| 17 | Embedding modeli seçimi belirsiz | Düzeltildi | BGE-M3 multilingual |
| 18 | LLM fine-tuning stratejisi yüzeysel | Düzeltildi | 3 aşamalı plan |
| 19 | Bias koruması (look-ahead, survivorship) detaysız | Düzeltildi | Replay engine ile doğal koruma |
| 20 | Docker Compose service tanımları eksik | Düzeltildi | Teknoloji tablosu + kaynak dağılımı |

### 17.2 Düzeltmeler (Araştırma Sonucu)

| # | Konu | Eski | Yeni | Gerekçe |
|---|------|------|------|---------|
| 1 | DB | PostgreSQL + TimescaleDB | PostgreSQL + ClickHouse | OLTP/OLAP ayrımı daha doğru |
| 2 | Data processing | Pandas | Polars + PyArrow | 10-100x performans farkı |
| 3 | Vector DB | Ayrı Qdrant/Weaviate | pgvector | 16GB RAM'de gereksiz ek servis |
| 4 | Feature Store | Feast | ClickHouse + Redis + Parquet | Tek laptopta Feast karmaşık |
| 5 | Model training | "Her saniye online learning" | Periyodik batch + champion/challenger | Overfitting riski |
| 6 | LLM context | 256K | 8-16K | VRAM tasarrufu |
| 7 | Gemma modeli | 12B (belirsiz) | 12B Unified Q4_0 | Resmi VRAM tablosu: 6.7GB |
| 8 | Workflow | Airflow | Prefect | Daha hafif, Python-native |

---

## 18. Referanslar

### Veri Kaynakları
- Borsa İstanbul Veri Yayını: borsaistanbul.com/veriler/veri-yayini
- KAP (Kamuyu Aydınlatma Platformu): kap.org.tr
- TCMB EVDS: evds.tcmb.gov.tr
- yfinance (BIST): `yfinance.download("THYAO.IS")`
- Alpha Vantage: alphavantage.co
- Twelve Data: twelvedata.com
- Finnhub: finnhub.io

### Teknoloji
- ClickHouse finans mimarisi: clickhouse.com/blog/building-stockhouse
- Longbridge + ClickHouse: clickhouse.com/blog/longbridge-technology
- Redpanda: redpanda.com
- Gemma 4 model kartı: ai.google.dev/gemma/docs/core/model_card_4
- Gemma 4 donanım rehberi: compute-market.com/blog/gemma-4-local-hardware-guide-2026
- MLflow Model Registry: mlflow.org/docs/latest/ml/model-registry
- Next.js App Router: nextjs.org/docs/app
- Prometheus: prometheus.io/docs
- PyTorch dağıtık eğitim: pytorch.org/docs/main/accelerator/distributed.html

### Akademik
- Fin-Analyst (LLM + Rule-Based Hybrid Trading): arxiv.org/abs/2607.12233
- Time-Series DB Benchmark (2026): arxiv.org/abs/2608.01459
- EMD + RFE ile finansal tahmin: sciencedirect.com/science/article/pii/S2199853125000666
- Triple Barrier Labeling: arxiv.org/html/2504.02249v2

### Referans Sistemler
- BlackRock Aladdin: blackrock.com/aladdin
- KX kdb+ tick mimarisi: code.kx.com/q/wp/rt-tick
- Google Cloud finansal streaming: cloud.google.com/blog/topics/financial-services/building-real-time-streaming-pipelines-for-market-data

---

## Son Not

Bu doküman **ALPHA BIST'in teknik mimarî spesifikasyonu v1.0** olarak kilitlidir.

Bundan sonra:
1. "Acaba başka DB/başka framework daha iyi mi?" diye sürekli teknoloji değiştirmek **yok**
2. **Benchmark → implementasyon → ölçüm** döngüsüne geçilecek
3. Gerçek performans ölçülecek, sonra optimize edilecek

**"Mükemmel mimari" aramak yerine, çalışan sistem inşa edip ölçmek daha profesyoneldir.**

---

*Oluşturulma: 14 Ağustos 2026*
*Mimari Versiyon: 1.0*
*Durum: Kilitli — Implementasyona geçilebilir*
