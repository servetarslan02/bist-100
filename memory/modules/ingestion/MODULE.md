# 01 — Ingestion (Veri Toplama) Modülü

## Giriş

Ingestion modülü, ALPHA BIST sisteminin **veri toplama ve besleme katmanıdır**. Borsa İstanbul'daki tüm hisseler için çok kaynaklı (yfinance, KAP, TCMB, Matriks, haber RSS, sosyal medya) veriyi çeker, doğrular, düzeltir ve downstream servislere (Feature Engine, Scanner, Backtest) publish eder.

**Çözdüğü problem:** Ham piyasa verisinin dağınık, gecikmeli, hatalı ve tekrarlı olmasını tek bir resilient pipeline'da birleştirerek güvenilir, PIT-safe (point-in-time) bir veri akışı sağlamak.

---

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────────┐
│                     main.py (IngestionService)                      │
│  5 async loop: market_data, kap, macro, news, social               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │           orchestrator_integration.py                         │  │
│  │        (IngestionOrchestrator — tüm pipeline)                 │  │
│  └───────────┬───────────┬───────────┬───────────┬───────────────┘  │
│              │           │           │           │                   │
│  ┌───────────▼──┐ ┌──────▼──────┐ ┌──▼────────┐ ┌▼──────────────┐  │
│  │ data_pipeline │ │reconciliation│ │deduplication│ │point_in_time │  │
│  │ (Quality Gate)│ │(Cross-source)│ │(Event dedup)│ │(Look-ahead)  │  │
│  └──────────────┘ └─────────────┘ └───────────┘ └───────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              provider_manager.py (ProviderManager)            │  │
│  │   Failover + Priority + Circuit Breaker + Rate Limiter       │  │
│  └───────┬───────────┬───────────┬───────────┬──────────────────┘  │
│          │           │           │           │                       │
│  ┌───────▼──┐ ┌──────▼──────┐ ┌──▼────────┐ ┌▼──────────────┐      │
│  │yfinance  │ │ KAP         │ │ TCMB      │ │ News/Social   │      │
│  │provider  │ │ provider    │ │ provider  │ │ providers     │      │
│  └──────────┘ └─────────────┘ └───────────┘ └───────────────┘      │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Resilience Katmanları                                       │  │
│  │  circuit_breaker │ rate_limiter │ retry_policy │ incremental │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Destek Modülleri                                            │  │
│  │  bist_universe │ corporate_actions │ universe_enhancements   │  │
│  │  realtime │ ingestion_metrics │ data_validator               │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Neden Bu Tasarım Seçimi?

| Karar | Gerekçe |
|-------|---------|
| **Çoklu provider + failover** | Tek kaynak bağımlılığı risklidir; yfinance çökerse BIST veya Matriks devreye girer |
| **Circuit breaker** | Arızalı provider'ı hızlıca devre dışı bırakır, gereksiz retry'ları önler |
| **Rate limiter (sliding window)** | API limit aşımlarını önler; her provider için ayrı limit tanımlı |
| **Exponential backoff + jitter** | Thundering herd etkisini önler, provider'ı nazikçe zorlar |
| **Point-in-time validator** | Backtest'te look-ahead bias'ı kesin olarak engeller |
| **Event deduplication** | Aynı verinin iki kez işlenmesini önler (24 saatlik sliding window) |
| **Cross-source reconciliation** | Farklı kaynaklardan gelen fiyatları ağırlıklı ortalama ile birleştirir |
| **Incremental fetcher** | Sadece delta veriyi çeker, bandwidth ve API limit tasarrufu |
| **Auto-discovery (Universe)** | Yeni halka arzları, birleşmeleri otomatik takip eder |
| **Prometheus metrics** | Grafana dashboard'u ile gerçek zamanlı monitoring |

---

## Uçtan Uca Veri Akışı

Bir veri noktasının (ör: THYAO fiyatı) yolculuğu:

1. **main.py** → `_market_data_loop()` her 5 dakikada bir tetiklenir
2. **bist_universe** → `BIST_100_TICKERS` listesinden aktif hisseleri alır
3. **incremental_fetcher** → `should_fetch("THYAO", min_interval=60)` kontrolü; son çekmeden bu yana yeterli süre geçtiyse devam
4. **provider_manager** → `fetch("market_price", ticker="THYAO")` çağrısı
   - Priority 0: yfinance → circuit breaker kapalıysa dene
   - Rate limiter → `acquire("yfinance")` → gerekirse bekle
   - Retry policy → exponential backoff ile 3 deneme
   - Başarılı → `ProviderResult` döner
   - Başarısız → Priority 1: BIST provider'a düş
5. **reconciliation** → Çoklu kaynak varsa ağırlıklı canonical price hesapla
6. **data_pipeline** → `DataQualityChecker` ile kalite skoru (≥70 geçer)
   - Kalite düşükse → reddet + audit log
   - Kalite yeterli → `FeatureCalculator` ile feature hesapla
7. **deduplication** → `check_and_mark(event)` → aynı event daha önce işlendiyse atla
8. **point_in_time** → `is_available_at("market_price", data_ts, query_ts)` → 15dk gecikme kontrolü
9. **corporate_actions** → Temettü/bölünme düzeltmeleri uygulanır
10. **Event bus** → `CanonicalEvent` olarak `market.tick` topic'ine publish edilir
11. **Feature Engine** → Event'i tüketir, feature'ları hesaplar ve store'a kaydeder

---

## Dosya Bazlı Sorumluluk Tablosu

### Ana Modüller

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `main.py` | Servis giriş noktası; 5 async loop (market, KAP, macro, news, social) | 441 | 🔴 Kritik |
| `orchestrator_integration.py` | Tüm pipeline'ı birleştiren orchestrator; provider registration, full ingestion | 317 | 🔴 Kritik |
| `data_pipeline.py` | Data Quality Gate; kalite skoru, reddetme, audit trail | 206 | 🔴 Kritik |
| `provider_manager.py` | Provider yönetimi; failover, priority, health tracking | 366 | 🔴 Kritik |
| `bist_universe.py` | Hisse evreni; BIST 100/30/50/ALL listeleri, sektör haritası, auto-discovery | 309 | 🔴 Kritik |
| `__init__.py` | Public API; tüm singleton'ları export eder | 70 | 🟡 Orta |

### Resilience Katmanları

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `circuit_breaker.py` | Circuit breaker pattern; CLOSED→OPEN→HALF_OPEN state machine | 288 | 🔴 Kritik |
| `rate_limiter.py` | Sliding window rate limiter; provider bazlı limit | 220 | 🔴 Kritik |
| `retry_policy.py` | Exponential backoff + jitter; retryable/non-retryable ayrımı | 313 | 🔴 Kritik |
| `incremental.py` | Sadece delta veri çekme; ticker bazlı son çekme zamanı takibi | 196 | 🟡 Orta |
| `deduplication.py` | Event deduplication; MD5 hash, 24 saatlik sliding window | 162 | 🟡 Orta |

### Veri Kalite & Doğrulama

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `point_in_time.py` | Look-ahead bias önleme; veri tipi bazlı gecikme süreleri | 238 | 🔴 Kritik |
| `reconciliation.py` | Kaynaklar arası fiyat uzlaştırma; ağırlıklı canonical price | 243 | 🟡 Orta |
| `corporate_actions.py` | Temettü, bölünme, bedelsiz düzeltmeleri; fiyat ve pozisyon ayarı | 350 | 🟡 Orta |
| `universe_enhancements.py` | Likidite skoru, survivorship bias koruması, outlier detection | 205 | 🟢 Düşük |

### Monitoring & Destek

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `ingestion_metrics.py` | Prometheus metrics; provider, circuit breaker, rate limiter, pipeline | 246 | 🟡 Orta |
| `realtime.py` | Gerçek zamanlı veri akışı; yfinance polling, WebSocket fallback | 157 | 🟢 Düşük |

### Provider'lar (`providers/`)

| Dosya | Sorumluluk | Satır | Kritiklik |
|-------|-----------|-------|-----------|
| `yfinance_provider.py` | Yahoo Finance; OHLCV, fiyat, endeks, makro (15dk gecikmeli) | 264 | 🔴 Kritik |
| `kap_provider.py` | KAP açıklamaları; async, şirket olayları, sentiment, önem skoru | 320 | 🔴 Kritik |
| `tcmb_provider.py` | TCMB EVDS; USD/TRY, enflasyon, faiz, cari açık (baseline fallback) | 170 | 🟡 Orta |
| `macro_provider.py` | Çoklu makro kaynak; Yahoo, TCMB, FRED, ECB paralel çekim | 326 | 🟡 Orta |
| `news_provider.py` | RSS haberleri; BloombergHT, Hürriyet Bigpara, TRT Haber | 255 | 🟡 Orta |
| `social_provider.py` | Sosyal medya; X/Twitter, StockTwits, Ekşi Sözlük, Reddit | 485 | 🟡 Orta |
| `fundamental_provider.py` | Finansal veri; yfinance + KAP fallback, çeyreklik bilanço | 299 | 🟡 Orta |
| `bist_provider.py` | Borsa İstanbul resmi; endeks, sektör (kurumsal API gerekli) | 121 | 🟢 Düşük |
| `matriks_provider.py` | Matriks; cross-validation kaynağı (kurumsal API gerekli) | 81 | 🟢 Düşük |
| `universe_provider.py` | Auto-discovery; KAP + yfinance + BIST web'den hisse listesi çekme | 811 | 🟡 Orta |
| `data_validator.py` | Kaynaklar arası cross-validation; fiyat doğrulama | 183 | 🟡 Orta |
| `news_credibility.py` | Haber güvenilirlik ağırlıkları; KAP 1.0, sosyal 0.2-0.5 | 124 | 🟢 Düşük |
| `provider_manager.py` | Provider manager (providers alt paketi) | 131 | 🟢 Düşük |
| `realtime_provider.py` | Gerçek zamanlı provider; WebSocket streaming | 317 | 🟢 Düşük |
| `bist_stream.py` | BIST WebSocket stream | 264 | 🟢 Düşük |

---

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Resilience-first**: Her provider çağrısı circuit breaker + rate limiter + retry ile korunur
2. **PIT correctness**: Backtest'te asla gelecek veri kullanılmaz; `PointInTimeValidator` bunu garanti eder
3. **Graceful degradation**: Bir provider çökse bile diğerleri devam eder; baseline değerlerle fallback
4. **Audit trail**: Her veri işleme adımında timestamp, ticker, action, reason kaydedilir
5. **Singleton pattern**: Tüm manager'lar ve provider'lar singleton; tek noktadan erişim
6. **Lazy import**: `orchestrator_integration` ve provider'lar lazy import ile yüklenir (circular dependency önleme)

### Kırmızı Çizgiler

- ❌ **Look-ahead bias**: PIT validator bypass edilemez; backtest'te gelecek veri kullanılamaz
- ❌ **Rate limit aşımı**: Rate limiter kaldırılamaz; API key ban riski var
- ❌ **Dedup bypass**: Aynı event iki kez işlenemez
- ❌ **Kalite gate bypass**: `min_quality_score` altındaki veri kabul edilemez
- ❌ **Provider hardcode**: Yeni provider eklemek için `ProviderManager.register()` kullanılmalı

---

## Bilinen Sınırlamalar

1. **BIST ve Matriks provider'ları devre dışı**: Kurumsal VERDA API credentials gerektirir; şu an sadece yfinance aktif
2. **yfinance 15 dakika gecikmeli**: Gerçek zamanlı trading için yeterli değil; sadece backtest ve günlük analiz için uygun
3. **TCMB baseline fallback**: API key yoksa hardcoded baseline değerler kullanılır; güncel değil
4. **Ekşi Sözlük scraping kırılgan**: HTML yapısı değişirse parse bozulur
5. **News sentiment basit**: Keyword-based; LLM entegrasyonu henüz yok
6. **Social provider rate limits**: X/Twitter API ücretsiz tier'ı çok kısıtlı
7. **`main.py` içinde `_refresh_universe` döngü sorunu**: `_refresh_universe` içinde `asyncio.gather` ile loop'lar çağrılıyor ama `_market_data_loop` zaten `while self._running` döngüsünde — potansiyel blokaj
8. **`realtime.py` Matriks streaming implemente edilmemiş**: Fallback olarak yfinance polling kullanıyor
9. **Corporate actions KAP parsing basit**: Regex ile temettü/bölünme çıkarma; edge case'lerde hatalı olabilir

---

## Cross-Reference: Diğer Modüllerle Bağlantılar

| Hedef Modül | Bağlantı | Açıklama |
|-------------|----------|----------|
| **Feature Engine** (`services/features/`) | `CanonicalEvent` → `market.tick` topic | Ingestion'dan gelen fiyat verisi feature hesaplaması için tüketilir |
| **Feature Engine** → `calculator.py` | `DataPipeline._process_single()` → `FeatureCalculator.compute_all_features()` | Data pipeline içinde feature hesaplama |
| **Feature Engine** → `tradability_mask` | `DataPipeline` → `TradabilityMask.compute_mask()` | İşlem yapılamayan günlerin maskelenmesi |
| **Core** → `data_quality` | `DataPipeline` → `DataQualityChecker.full_quality_check()` | Veri kalite kontrolü |
| **Core** → `event_bus` | `main.py` → `publish_event()` | Tüm veri event'leri Kafka topic'lerine publish edilir |
| **Core** → `event_schema` | `CanonicalEvent` | Standart event formatı |
| **Core** → `database` | `main.py` → PostgreSQL instrument map, ClickHouse storage | Veri persistansı |
| **Core** → `async_http` | Provider'lar → `get_client()` | Async HTTP client (aiohttp wrapper) |
| **Scanner / Backtest** | Event bus üzerinden | Ingestion'dan gelen veriler scanner ve backtest engine tarafından tüketilir |

---

## Singleton Haritası

| Singleton | Dosya | Açıklama |
|-----------|-------|----------|
| `bist_universe` | `bist_universe.py` | Hisse evreni (auto-discovery aktif) |
| `provider_manager` | `provider_manager.py` | Provider yönetimi |
| `circuit_breaker_manager` | `circuit_breaker.py` | Tüm circuit breaker'lar |
| `rate_limiter` | `rate_limiter.py` | Varsayılan BIST limitleri ile rate limiter |
| `pit_validator` | `point_in_time.py` | Point-in-time validator |
| `event_deduplicator` | `deduplication.py` | Event deduplication |
| `incremental_fetcher` | `incremental.py` | Incremental fetch takibi |
| `source_reconciler` | `reconciliation.py` | Kaynaklar arası uzlaştırma |
| `corporate_actions` | `corporate_actions.py` | Şirket olayları yönetimi |
| `ingestion_metrics` | `ingestion_metrics.py` | Prometheus metrics |
| `ingestion_orchestrator` | `orchestrator_integration.py` | Ana orchestrator (lazy) |
| `yfinance_provider` | `providers/yfinance_provider.py` | Yahoo Finance provider |
| `kap_provider` | `providers/kap_provider.py` | KAP provider |
| `tcmb_provider` | `providers/tcmb_provider.py` | TCMB EVDS provider |
| `news_provider` | `providers/news_provider.py` | Haber provider |
| `social_provider` | `providers/social_provider.py` | Sosyal medya provider |
| `fundamental_provider` | `providers/fundamental_provider.py` | Fundamental veri provider |
| `macro_provider` | `providers/macro_provider.py` | Makro veri provider |
| `bist_provider` | `providers/bist_provider.py` | BIST resmi provider |
| `matriks_provider` | `providers/matriks_provider.py` | Matriks provider |
| `universe_updater` | `providers/universe_provider.py` | Auto-discovery motoru |
| `news_credibility` | `providers/news_credibility.py` | Haber güvenilirlik sistemi |
| `data_validator` | `providers/data_validator.py` | Cross-validation |
| `realtime_provider` | `realtime.py` | Gerçek zamanlı veri |
