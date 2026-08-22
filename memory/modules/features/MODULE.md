# 02 — Features (Feature Engine) Modülü

## Giriş

Features modülü, ALPHA BIST sisteminin **feature hesaplama ve yönetim katmanıdır**. Ham piyasa verisini (OHLCV, fundamental, KAP, haber, makro) makine öğrenmesi modelinin anlayabileceği sayısal feature'lara dönüştürür. 100+ feature, 9 bağımsız motor, cross-sectional analiz, drift detection ve PIT-aware feature store içerir.

**Çözdüğü problème:** Ham fiyat verisinden anlamlı sinyal çıkarmak; feature'ların point-in-time güvenliğini sağlamak; model performansını izlemek ve feature drift'ini tespit etmek.

---

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    main.py (FeatureEngineService)                       │
│         Event-driven: market.tick → feature computation → store         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              pipeline.py (FeaturePipelineOrchestrator)            │  │
│  │  Calculator → BIST Features → Contract → Store → Drift → Select  │  │
│  └───────┬───────────┬───────────┬───────────┬───────────┬──────────┘  │
│          │           │           │           │           │               │
│  ┌───────▼──┐ ┌──────▼──────┐ ┌──▼────────┐ ┌▼──────────┐ ┌▼────────┐  │
│  │calculator│ │seven_motors │ │cross_sect. │ │bist_feats │ │store    │  │
│  │(Mask-1st)│ │(9 Motor)    │ │(Rank/Zscr) │ │(BIST-özel)│ │(PIT+v2) │  │
│  └──────────┘ └─────────────┘ └───────────┘ └───────────┘ └─────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Analiz & İzleme Katmanı                                         │  │
│  │  drift_detector │ importance_tracker │ feature_selector │ discovery│  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Gerçek Zamanlı Katman                                           │  │
│  │  incremental_state │ bar_engine │ data_adapter │ feature_contract │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Ek Feature Modülleri                                            │  │
│  │  technical_features │ extended_indicators │ fundamental │ macro   │  │
│  │  sentiment │ bist_features                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Neden Bu Tasarım Seçimi?

| Karar | Gerekçe |
|-------|---------|
| **9 bağımsız motor** | Her motor farklı sinyal türüne odaklanır; paralel çalıştırılarak pipeline süresi kısaltılır |
| **Mask-first design** | İşlem yapılamayan günler (açığa satış yasağı, devre kesici) feature hesaplamasına dahil edilmez |
| **PIT-aware Feature Store** | Backtest'te gelecek feature kullanılmaz; `available_at` timestamp ile garanti edilir |
| **Feature versioning** | Model değişikliklerinde geriye dönük uyumluluk; v1, v2, v3 paralel çalışabilir |
| **Feature lineage** | Her feature'ın nasıl üretildiği izlenir; debug ve audit için kritik |
| **Cross-sectional engine** | Hisseyi tek başına değil, tüm BIST evreni içinde değerlendirir (rank, z-score, sector relative) |
| **Panel engine (vektörize)** | Backtest'te her (ticker, gün) için sıfırdan hesaplama yerine tek geçişli batch hesaplama |
| **Drift detection (KS, PSI)** | Feature dağılım değişikliğini erken tespit eder; model bozulmasını önler |
| **Feature contract** | Her feature için metadata (source, status, availability_ts) tutar; veri kalitesini garanti eder |
| **Feature discovery** | Otomatik interaction/lag feature üretimi; manuel feature engineering yükünü azaltır |

---

## Uçtan Uca Veri Akışı

Bir hisse için feature hesaplamanın yolculuğu (ör: THYAO):

1. **main.py** → `_on_tick(event)` → `market.tick` event'i gelir
2. **Price cache** → Son 200 tick saklanır; 20+ tick birikince feature hesaplama tetiklenir
3. **calculator.py** → `FeatureCalculator.compute_all_features(df, mask)`
   - Tradability mask uygulanır (invalid günler → NaN)
   - SMA, EMA, RSI, MACD, Bollinger, Stochastic, ATR, ADX, OBV hesaplanır
   - Volume profile, price action (higher highs, lower lows) hesaplanır
   - Scalar guard: dict/nested feature'lar filtrelenir
4. **seven_motors.py** → `NineMotorEngine.compute_all()` — 9 motor paralel çalıştırılır:
   - **Motor 1**: Relatif Güç (vs BIST, sektör, peer — çok ufuklu)
   - **Motor 2**: Momentum + Trend (ROC, trend eğimi, ivme, breakout)
   - **Motor 3**: Hacim + Mikroyapı (volume percentile, tick rule, VWAP, MFI, CMF)
   - **Motor 4**: Fundamental (sektör normalize, FCF, kalite skorları)
   - **Motor 5**: KAP + Haber (sentiment, surprise, zaman ağırlıklı)
   - **Motor 6**: Katalizör (zaman decay ile yaklaşan olaylar)
   - **Motor 7**: "Neden Düşüyor?" (çok faktörlü düşüş sınıflandırması)
   - **Motor 8**: Mean Reversion (Bollinger, RSI, Williams %R, CCI)
   - **Motor 9**: Seasonality (ay bazlı, gün bazlı, çeyrek bazlı getiri)
5. **cross_sectional.py** → Evren bazlı rank, z-score, sector relative, market breadth
6. **bist_features.py** → BIST'e özgü: kur hassasiyeti, enflasyon, faiz, yabancı yatırımcı, Piotroski F-Score
7. **feature_contract.py** → Her feature `FeatureDataPoint` ile sarılır (value, source, status, availability_ts)
8. **store.py** → `FeatureStore.set()` → snapshot, lineage, baseline güncelleme
9. **drift_detector.py** → KS test, PSI, z-score ile drift kontrolü
10. **pipeline.py** → Feature selection (importance-based veya variance+correlation)
11. **Redis** → Hot state (`features:{ticker}`) → anlık erişim
12. **ClickHouse** → Historical storage → backtest ve analiz

---

## Dosya Bazlı Sorumluluk Tablosu

### Ana Pipeline

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `main.py` | Servis giriş noktası; event-driven tick processing, Redis/CH storage | 228 | 🔴 Kritik |
| `pipeline.py` | Pipeline orchestrator; Calculator → BIST → Contract → Store → Drift → Select | 475 | 🔴 Kritik |
| `calculator.py` | Mask-aware teknik feature hesaplama; SMA, RSI, MACD, Bollinger, ATR, ADX, OBV | 598 | 🔴 Kritik |
| `__init__.py` | Public API; tüm modülleri export eder | 93 | 🟡 Orta |

### 9 Motor Feature Engine

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `seven_motors.py` | 9 motor feature engine; RS, Momentum, Volume, Fundamental, KAP, Catalyst, WhyFalling, MeanReversion, Seasonality | 1381 | 🔴 Kritik |

### Cross-Sectional & Panel

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `cross_sectional.py` | Evren bazlı rank, z-score, sector relative, market breadth, peer correlation | 331 | 🔴 Kritik |
| `panel_engine.py` | Vektörize batch feature motoru; backtest için tek geçişli RSI, momentum, roc, volume_zscore | 375 | 🟡 Orta |

### Feature Store & Contract

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `store.py` | Feature Store v2.0; PIT correctness, versioning, lineage, snapshots, baselines | 667 | 🔴 Kritik |
| `feature_contract.py` | Feature data contract; FeatureDataPoint (value, source, status, availability_ts) | 162 | 🟡 Orta |

### Analiz & İzleme

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `drift_detector.py` | Feature drift detection; KS test, PSI, z-score, rolling window, alert sistemi | 652 | 🟡 Orta |
| `importance_tracker.py` | Feature importance tracking; SHAP, native importance, RFE, importance drift | 617 | 🟡 Orta |
| `feature_selector.py` | Feature selection; correlation, variance, VIF, importance-based, auto pipeline | 408 | 🟡 Orta |
| `discovery.py` | Feature discovery; interaction generation, lag features, MI, leakage detection | 381 | 🟢 Düşük |

### Gerçek Zamanlı Katman

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `incremental_state.py` | Incremental feature state; tick bazlı RSI, EMA, ATR, MACD güncellemesi | 275 | 🟡 Orta |
| `bar_engine.py` | Canonical bar engine; tick → 1m → 5m → 15m → 1h → 1d bar üretimi | 213 | 🟡 Orta |
| `data_adapter.py` | Veri adaptörü; fundamental, KAP, haber verisini motor formatına çevirme | 635 | 🟡 Orta |

### Ek Feature Modülleri

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `bist_features.py` | BIST'e özgü feature'lar; kur, enflasyon, faiz, sektör, KAP, yabancı yatırımcı, kalite skorları | 615 | 🟡 Orta |
| `technical_features.py` | Teknik feature modülü; trend, momentum, volatility, volume | 213 | 🟢 Düşük |
| `extended_indicators.py` | Genişletilmiş göstergeler; Ichimoku, Fibonacci, pivot points | 275 | 🟢 Düşük |
| `fundamental.py` | Fundamental feature engine; değerleme, kârlılık, büyüme, bilanço | 378 | 🟢 Düşük |
| `macro.py` | Makro feature engine; USDTRY, enflasyon, faiz, VIX, risk appetite | 394 | 🟢 Düşük |
| `sentiment.py` | Sentiment feature engine; haber, sosyal medya, KAP sentiment | 322 | 🟢 Düşük |

---

## 9 Motor Detayları

### Motor 1: Relatif Güç (`RelativeStrengthMotor`)
- Hisse vs BIST endeksi, sektör, peer karşılaştırması
- Çok ufuklu: 1, 5, 10, 20, 60, 120, 252 gün
- Beta, alpha, RS momentum, peer rank/z-score

### Motor 2: Momentum + Trend (`MomentumTrendMotor`)
- ROC (çok ufuklu), trend eğimi (lineer regresyon slope + R²)
- Momentum ivmesi (2. türev), yeni yüksek/düşük tespiti
- Breakout başarısızlığı, drawdown, toparlanma gücü
- Golden/Death cross, price channel, volatility-adjusted momentum

### Motor 3: Hacim + Mikroyapı (`VolumeMicrostructureMotor`)
- Volume percentile, up/down volume ratio, tick rule (alış/satış baskısı)
- VWAP sapması, volume z-score, OBV, MFI, CMF
- Volume trend, para akışı indeksi

### Motor 4: Fundamental (`FundamentalMotor`)
- Sektörel normalize (PE, PB, EV/EBITDA sektör medyanına göre)
- FCF merkezli (margin, yield, ROA)
- Büyüme kalitesi, bilanço kalitesi skoru (0-100)
- Value, Growth, Quality skorları

### Motor 5: KAP + Haber (`KAPNewsMotor`)
- KAP olay türü sayıları, sentiment, surprise, zaman ağırlıklı sentiment
- Haber sentiment momentum, kaynak çeşitliliği
- LLM analiz entegrasyonu (opsiyonel)
- Kombine sentiment (KAP %60 + Haber %40)

### Motor 6: Katalizör (`CatalystMotor`)
- Yaklaşan olaylar (kazanç, temettü, toplantı)
- Zaman decay (30 gün half-life) ile ağırlıklandırılmış önem
- Katalizör kümülasyonu tespiti

### Motor 7: "Neden Düşüyor?" (`WhyFallingMotor`)
- Market selloff, sector selloff, company-specific ayrıştırması
- Liquidity event, temporary panic, oversold bounce tespiti
- Falling knife risk skoru (0-100)
- Geçici vs kalıcı düşüş sınıflandırması

### Motor 8: Mean Reversion (`MeanReversionMotor`)
- Bollinger Bands (20, 50 gün), RSI (5, 14, 21 gün)
- Williams %R, Stochastic RSI, CCI
- Mean reversion sinyali ve gücü

### Motor 9: Seasonality (`SeasonalityMotor`)
- Ay bazlı getiri istatistikleri (en iyi/en kötü ay)
- Haftanın günü etkisi
- Çeyrek bazlı momentum

---

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Mask-first**: İşlem yapılamayan günler feature hesaplamasına dahil edilmez; `TradabilityMask` tüm calculator ve motorlarda kullanılır
2. **PIT correctness**: Feature Store'da `available_at` timestamp; backtest'te gelecek feature kullanılamaz
3. **Motor bağımsızlığı**: 9 motor birbirinin sonucunu etkilemez; paralel çalıştırılabilir
4. **Scalar guard**: Feature output'ları sadece scalar (int/float) olabilir; dict, list, array filtrelenir
5. **Feature versioning**: v1, v2, v3 paralel çalışabilir; geriye dönük uyumluluk
6. **Graceful degradation**: Bir motor çökse diğerleri devam eder; eksik feature → default 0

### Kırmızı Çizgiler

- ❌ **Look-ahead bias**: Feature Store `available_at` bypass edilemez
- ❌ **Mask bypass**: `mask=0` olan günler feature hesaplamasında kullanılamaz
- ❌ **Non-scalar feature**: Model input'ları sadece scalar olabilir; nested yapı kabul edilmez
- ❌ **NaN/Inf propagation**: Feature output'ları NaN/Inf içeremez; `_enforce_scalar_features` filtreler
- ❌ **Feature contract ihlali**: Her feature source, status, availability_ts bilgisi taşımak zorunda

---

## Bilinen Sınırlamalar

1. **SHAP bağımlılığı**: `importance_tracker` SHAP kurulu değilse native importance'a düşer; daha az hassas
2. **Panel engine sadece 4 feature**: `rsi_14`, `momentum_20d`, `roc_5d`, `volume_zscore` — diğerleri scalar yoldan hesaplanır
3. **Seasonality motoru 252 gün gerektirir**: Yeni listelenen hisselerde çalışmaz
4. **Cross-sectional engine tüm evreni gerektirir**: Tek hisse için çalıştırılamaz; batch pipeline gerekli
5. **Discovery engine O(K²) maliyet**: Top-K feature sayısı arttıkça interaction generation yavaşlar
6. **Fundamental data_adapter yfinance bağımlılığı**: yfinance kurulu değilse fundamental feature'lar MISSING olur
7. **Sentiment basit keyword-based**: LLM entegrasyonu henüz yok; Motor 5'te opsiyonel
8. **`seven_motors.py` Motor 7 sıralı**: Motor 1-6'nın çıktılarına bağlı olduğu için paralel çalıştırılamaz
9. **Feature Store in-memory**: Restart sonrası snapshot'lar kaybolur; persistence henüz implemente edilmemiş
10. **`panel_engine.py` sadece skor feature'ları**: Tüm 100+ feature için değil, sadece skor hesaplamasında kullanılan 4 feature için vektörize

---

## Cross-Reference: Diğer Modüllerle Bağlantılar

| Hedef Modül | Bağlantı | Açıklama |
|-------------|----------|----------|
| **Ingestion** (`services/ingestion/`) | `CanonicalEvent` ← `market.tick` | Ingestion'dan gelen fiyat verisi feature hesaplaması için tüketilir |
| **Ingestion** → `tradability_mask` | `FeatureCalculator` → `TradabilityMask.compute_mask()` | İşlem yapılamayan günlerin maskelenmesi |
| **Ingestion** → `data_quality` | `DataPipeline` → `DataQualityChecker` | Veri kalite kontrolü (ingestion tarafında) |
| **Core** → `event_bus` | `main.py` → `publish_event(EventType.FEATURE_UPDATED)` | Feature güncellemeleri downstream'e publish edilir |
| **Core** → `database` | `main.py` → Redis hot state, ClickHouse historical | Feature persistansı |
| **Scanner** | Event bus → `FEATURE_UPDATED` | Scanner feature'ları tüketerek tarama yapar |
| **Backtest** | `FeatureStore.get_all(as_of=...)` | PIT-aware feature okuma |
| **Backtest** → `panel_engine` | `PanelFeatureEngine.compute()` → `features_at()` | Vektörize batch feature hesaplama |
| **Backtest** → `store` | `FeatureStore.get_snapshot(timestamp)` | Zaman noktasına geri dönme |
| **Model Training** → `importance_tracker` | `compute_shap()`, `recursive_feature_elimination()` | Feature importance ve seçimi |
| **Model Training** → `feature_selector` | `auto_select()` | Varyans + korelasyon + importance filtreleme |
| **Monitoring** → `drift_detector` | `detect_all()` | Feature drift tespiti ve alert |

---

## Singleton Haritası

| Singleton | Dosya | Açıklama |
|-----------|-------|----------|
| `feature_calculator` | `calculator.py` | Mask-aware teknik feature calculator |
| `seven_motor_engine` | `seven_motors.py` | 9 motor feature engine (alias: `NineMotorEngine`) |
| `cross_sectional_engine` | `cross_sectional.py` | Cross-sectional feature motoru |
| `feature_store` | `store.py` | Feature Store v2.0 (PIT-aware, versioned) |
| `feature_pipeline` | `pipeline.py` | Pipeline orchestrator |
| `drift_detector` | `drift_detector.py` | Feature drift detection |
| `importance_tracker` | `importance_tracker.py` | Feature importance tracking |
| `feature_selector` | `feature_selector.py` | Feature selection |
| `bist_feature_engine` | `bist_features.py` | BIST'e özgü feature engine |
| `data_adapter` | `data_adapter.py` | Veri adaptörü |
| `feature_discovery_engine` | `discovery.py` | Feature discovery pipeline |
| `state_manager` | `incremental_state.py` | Incremental feature state manager |
| `bar_engine_manager` | `bar_engine.py` | Canonical bar engine manager |
