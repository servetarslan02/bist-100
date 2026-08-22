# ALT — Alternative Data

## Giriş

Alternative Data modülü, geleneksel piyasa verilerinin (fiyat, hacim) dışında kalan veri kaynaklarını toplar, işler ve feature'lara dönüştürür. Google Trends, kredi kartı harcamaları, iş ilanları, Ekşi Sözlük sentiment, Investing.com yorumları, uydu görüntüleri ve LLM tabanlı sentiment analizi gibi 8+ kaynaktan 60+ feature üretir. Bu feature'lar agent sistemi ve ML modelleri tarafından kullanılır.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────┐
│              AlternativeFeatureEngine                        │
│              (feature_engine.py)                              │
│  Tüm kaynakları orkestre eder, 60+ feature üretir           │
├─────────────────────────────────────────────────────────────┤
│                    Adapter Registry                           │
│                    (base.py — AdapterRegistry)                │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────────┤
│Google│ BKM  │Kariyer│ Ekşi │Invest│Satel-│ LLM  │  Social   │
│Trends│Credit│ .net │Sözlük│.com  │lite  │Senti-│  Media    │
│      │Card  │      │      │      │      │ment  │           │
├──────┴──────┴──────┴──────┴──────┴──────┴──────┴────────────┤
│                    BaseAdapter (base.py)                      │
│  collect() → validate() → compute_features() → cache         │
├─────────────────────────────────────────────────────────────┤
│  RateLimiter │ CircuitBreaker │ DataQualityValidator         │
│  (token      │ (3 state FSM)  │ (7 katmanlı kalite kontrol) │
│   bucket)    │                │                              │
├─────────────────────────────────────────────────────────────┤
│  Cross-Source Reconciliation (reconciliation.py)              │
│  Feature Store (feature_store.py)                             │
└─────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| Adapter pattern (BaseAdapter) | Her veri kaynağı kendi collect/compute mantığına sahip; ortak arayüz ile genişletilebilirlik sağlanır |
| Circuit breaker | Harici API'ler (Google Trends, Ekşi, Investing.com) sık çökebilir; 5 ardışık hata → OPEN, 5 dk sonra HALF_OPEN |
| Token bucket rate limiter | Her kaynak için ayrı limit (Google Trends 10/dk, Ekşi 5/dk); API ban'ı önlenir |
| 7 katmanlı veri kalitesi | Null check → type → empty → zero-value → range → staleness → completeness — kötü veri feature'a dönüşmez |
| Cross-source reconciliation | Aynı hisse için farklı kaynaklar çelişkili sinyal verebilir; güvenilirlik skoru hesaplanır |
| Feature store (point-in-time) | Backtest'te gelecek veri sızıntısını önler; `get_latest(ticker, before_date)` |
| LLM sentiment fallback | LLM yoksa keyword-based sentiment (Türkçe negation handling ile) çalışır |
| Uydu verisi (Sentinel-2) | Fabrika/liman/otopark aktivitesi — alternatif veri olarak benzersiz sinyal |

## Uçtan Uca Veri Akışı

```
1. AlternativeFeatureEngine.compute_all_features(ticker, sources, sector)
2. AdapterRegistry.collect_all(ticker) → paralel veri toplama
   a. GoogleTrendsAdapter → pytrends → interest_over_time
   b. BKMAdapter → bkm.com.tr scraping → kart verileri
   c. KariyerNetAdapter → kariyer.net scraping → iş ilanları
   d. EksiSozlukAdapter → eksisozluk.com scraping → entry'ler
   e. InvestingAdapter → tr.investing.com scraping → yorumlar
   f. SatelliteAdapter → Copernicus API → NDVI/NDBI
3. Her adapter: collect() → DataQualityValidator.validate() → compute_features()
4. LLM sentiment (opsiyonel): KAP açıklamaları + haberler → LLMSentimentAnalyzer
5. CrossSourceReconciler.reconcile() → reliability_score, consensus_score
6. Composite features: alt_sentiment_avg, alt_growth_avg, alt_data_coverage
7. FeatureStore.put(ticker, date, features) → point-in-time kayıt
8. 60+ feature dict döndürülür
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `base.py` | BaseAdapter (abstract: collect, compute_features, fetch pipeline), RateLimiter (token bucket), CircuitBreaker (CLOSED/OPEN/HALF_OPEN FSM), DataQualityValidator (7 katmanlı kalite kontrol), QualityReport, AdapterRegistry (adapter kayıt/yönetim, paralel collect_all) |
| `feature_engine.py` | AlternativeFeatureEngine — tüm adapter'ları orkestre eder, 60+ feature üretir, LLM sentiment entegrasyonu, cross-source composite features (alt_sentiment_avg, alt_growth_avg, alt_data_coverage), feature name manifest |
| `google_trends.py` | GoogleTrendsAdapter — pytrends ile arama trendleri, BIST ticker → arama terimi mapping (20+ şirket), 9 feature (score, avg_30d, momentum_7d/30d, volatility, percentile, relative, trend, zscore) |
| `bkm_adapter.py` | BKMAdapter — BKM kredi kartı harcama verisi web scraping, Türk sayı formatı parse (1.234,56), 8 feature (spend_growth, transaction_count, avg_transaction, online_ratio, contactless_ratio, vs_sector, seasonal_deviation, foreign_ratio) |
| `kariyer_net.py` | KariyerNetAdapter — Kariyer.net iş ilanı scraping, 30+ şirket mapping, tech/management/remote role sınıflandırma, 6 feature (posting_count, posting_growth, tech_ratio, management_ratio, remote_ratio, diversity) |
| `eksi_sozluk.py` | EksiSozlukAdapter — Ekşi Sözlük entry scraping, keyword-based sentiment (Türkçe negation handling), 8 feature (sentiment, volume, positive_ratio, negative_ratio, avg_favorites, max_favorites, sentiment_std, controversial) |
| `investing_adapter.py` | InvestingAdapter — tr.investing.com yorum scraping, keyword-based sentiment, teknik rating çıkarma, 6 feature (sentiment, volume, positive_ratio, negative_ratio, sentiment_std, technical_rating) |
| `satellite_adapter.py` | SatelliteAdapter — Copernicus Sentinel-2 API, NDVI/NDBI hesaplama, 12+ şirket için fabrika/liman/otopark/lokasyon mapping, 9 feature (factory_activity, warehouse_activity, airport_activity, office_activity, ndvi_avg, ndbi_avg, activity_index, location_count) |
| `llm_sentiment.py` | LLMSentimentAnalyzer — Ollama ile Türkçe finansal metin sentiment, KAP/haber analizi, keyword-based fallback (negation handling), batch analiz, cache (TTL-based) |
| `social.py` | compute_social_features() — sosyal medya feature'ları (sentiment, volume, viral, positive_ratio, mention_count, engagement, sentiment_momentum, manipulation_score, platform breakdown) |
| `credit_card.py` | compute_cc_features() — kredi kartı harcama feature mapping |
| `satellite.py` | compute_satellite_features() — uydu verisi feature mapping |
| `web_scraping.py` | compute_web_features() — web scraping feature mapping (traffic, app ranking, review, price comparison) |
| `jobs.py` | compute_job_features() — iş ilanı feature mapping (posting_growth, tech_hiring_pct, layoff_signal, salary_change, remote_ratio) |
| `reconciliation.py` | CrossSourceReconciler — kaynaklar arası veri uzlaştırma, sentiment/growth consensus, tutarsızlık tespiti (eşik 0.5), güvenilirlik skoru, ReconciliationReport |
| `feature_store.py` | FeatureStore — feature versioning, point-in-time correctness (backtest güvenli), FeatureManifest (metadata), auto-register, persistence (JSON) |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Veri kalitesi < %50 → reddet** — DataQualityValidator skoru 0.5'in altındaysa veri kullanılmaz, circuit breaker failure sayılır.
2. **Circuit breaker OPEN → istek yok** — 5 ardışık hata sonrası 5 dakika boyunca o kaynaktan veri çekilmez.
3. **Rate limit aşılmaz** — Her kaynak için ayrı token bucket; Google Trends 10/dk, scraping kaynakları 5/dk.
4. **Point-in-time correctness** — Feature store'dan okuma yaparken `before_date` parametresi zorunlu; backtest'te gelecek veri sızıntısı yok.
5. **Negation handling** — Türkçe "değil", "yok", "olmayan" gibi negation kelimeleri keyword-based sentiment'te doğru işlenir.
6. **Cache TTL** — Feature cache 1 saat, LLM sentiment cache 1 saat; eski veri tekrar kullanılmaz.
7. **Fallback zinciri** — LLM sentiment → keyword-based → neutral. Hiçbir zaman None döndürmez.

## Bilinen Sınırlamalar

- **Scraping kararsızlığı** — Ekşi Sözlük, Investing.com, Kariyer.net HTML yapısı değişirse scraper bozulur.
- **Uydu verisi gecikme** — Sentinel-2 revizyon süresi 5 gün; gerçek zamanlı veri yok.
- **BKM verisi aylık** — Kredi kartı harcamaları aylık yayınlanır; günlük analiz için uygun değil.
- **Google Trends rate limit** — pytrends 10 istek/dk; çoklu ticker taraması yavaş olabilir.
- **LLM sentiment maliyeti** — Her metin için LLM çağrısı token tüketir; batch processing ile sınırlı.
- **Şirket mapping sabit** — 20-30 şirket için hardcoded mapping; yeni şirket eklenmesi manuel iş.

## Cross-Reference

- **Agent System** → `feature_engine.py` → üretilen feature'lar agent context'ine beslenir (`task.context["features"]`)
- **API** → `v1/alternative.py` → feature engine durumu ve feature listesi endpoint'leri
- **Scheduler** → `feature_calculation` job'u → periyodik feature hesaplama
- **ML Models** → Feature store'dan okunan feature'lar ranking model'e input olarak gider
- **Scanner** → Opportunity engine, alternative feature'ları skorlamada kullanır
