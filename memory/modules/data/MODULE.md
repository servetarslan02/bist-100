# DATA — Veri Katmanı

> Bu belge hedef mimariyi tanımlar, bugün kodda gerçekte var olan/olmayan kısımlar için `CURRENT-STATE.md`'ye bakın.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                       DATA SERVICES                             │
├─────────────────────┬───────────────────────────────────────────┤
│  Veri Kaynakları    │  Historical Repository                    │
├─────────────────────┼───────────────────────────────────────────┤
│ data_source.py      │ historical_contracts.py                   │
│  ├─ YahooFinance    │  ├─ FundamentalSnapshot                   │
│  ├─ BISTSource      │  ├─ EventSnapshot                         │
│  └─ LocalParquet    │  ├─ CatalystSnapshot                      │
│                     │  └─ HistoricalDataRepository (interface)  │
│ historical_adapter.py│ persistent_repository.py                 │
│  └─ Motor4/5/6      │  └─ SQLite tabanlı implementasyon         │
│    feature üretimi  │                                           │
│                     │ historical_fundamental_provider.py         │
│ ingestion_pipeline.py│  └─ yfinance PIT-safe fundamental veri   │
│  └─ Incremental     │                                           │
│    ingestion        │                                           │
└─────────────────────┴───────────────────────────────────────────┘
```

## Neden Bu Teknoloji / Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Multi-source fallback** (local → Yahoo → BIST) | Tek kaynak bağımlılığı yok; cache varsa hızlı, yoksa dış kaynaklardan çek |
| **Parquet cache** | CSV'den ~10x hızlı okuma; Apache Arrow formatı, columnar storage |
| **SQLite historical repository** | Hafif, dosya tabanlı, WAL modu ile concurrent okuma; PostgreSQL gerektirmez |
| **PIT-safe snapshot'lar** | `available_at <= backtest_date` kuralı ile look-ahead bias önlenir |
| **Incremental ingestion** | Son başarılı timestamp takibi; sadece yeni/değişmiş veriler çekilir |
| **Deduplication** | `event_id` bazlı unique constraint; aynı event tekrar kaydedilmez |
| **yfinance** | Ücretsiz, Python native, quarterly financials + earnings_dates desteği |
| **BIST web scraping** | Resmi BIST API + web scraping fallback; regex ile fiyat parse |

## Uçtan Uca Veri Akışı

```
1. DataSourceManager.get_stock_data(ticker) çağrılır
2. Cache kontrolü (Parquet dosyası, TTL 24 saat)
3. Cache hit → DataFrame döndür
4. Cache miss → kaynaklardan sırayla dene:
   4a. LocalParquetSource → yerel dosya
   4b. YahooFinanceSource → yfinance API
   4c. BISTSource → BIST API + web scraping
5. Başarılı kaynak → cache'e kaydet (Parquet) → DataFrame döndür
6. Tüm kaynaklar başarısız → boş DataFrame

Historical Ingestion Pipeline:
1. HistoricalIngestionPipeline.ingest_fundamentals(tickers) çağrılır
2. Son ingestion timestamp kontrolü (1 saat TTL)
3. HistoricalFundamentalProvider.fetch_historical_fundamentals(ticker)
   3a. yfinance quarterly_financials + earnings_dates çekilir
   3b. PIT-safe: period_end + available_at eşleştirilir
   3c. Ham metrikler standart isimlere maplenir
4. PersistentHistoricalRepository.add_fundamental_snapshot() → SQLite'a yaz
5. Aynı akış KAP event'leri ve news event'leri için de geçerli

Historical Adapter (Backtest için):
1. HistoricalDataAdapter.get_fundamental_features(ticker, current_date)
2. Repository'den PIT-safe snapshot'lar okunur
3. Motor4 feature'ları üretilir (fcf_yield, balance_sheet_quality, value_score, quality_score)
4. get_kap_events() → Motor5 formatında event listesi
5. get_catalyst_events() → Motor6 formatında catalyst listesi
6. compute_sentiment() → KAP + News ağırlıklı sentiment
7. compute_catalyst_features() → time decay score
```

## Servis Sınırları ve Sorumlulukları

| Dosya | Sorumluluk | Katman |
|-------|-----------|--------|
| `services/data/data_source.py` | Multi-source veri çekme (Yahoo, BIST, local), Parquet cache, BIST 100 universe | Veri Kaynağı |
| `services/data/historical_adapter.py` | Historical repository → canonical scoring köprüsü; Motor4/5/6 feature üretimi | Adaptör |
| `services/data/historical_contracts.py` | PIT-safe veri sözleşmeleri: `FundamentalSnapshot`, `EventSnapshot`, `CatalystSnapshot`, repository interface | Sözleşme |
| `services/data/persistent_repository.py` | SQLite tabanlı historical repository implementasyonu; CRUD + ingestion state | Depo |
| `services/data/historical_fundamental_provider.py` | yfinance'dan PIT-safe quarterly fundamental veri çekme; metric mapping | Sağlayıcı |
| `services/data/ingestion_pipeline.py` | Incremental ingestion: fundamental, KAP event, news event, catalyst türetme | Pipeline |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **PIT-Safe**: `available_at <= current_date` — gelecek veri kullanılmaz
2. **Incremental**: Son ingestion timestamp'i tutulur; sadece yeni veri çekilir
3. **Deduplication**: `event_id` bazlı unique constraint; aynı event tekrar kaydedilmez
4. **Multi-source fallback**: Tek kaynak başarısız olursa diğer kaynaklardan dene
5. **Cache-aware**: Parquet cache ile tekrar API çağrısı önlenir
6. **Graceful failure**: Kaynak başarısız olursa mevcut dataset bozulmaz

### Kırmızı Çizgiler

- ❌ `available_at > backtest_date` olan veri kullanılamaz (look-ahead bias)
- ❌ Sıfır veya negatif fiyatlı satırlar feature hesaplamasına giremez
- ❌ Duplicate event_id ile kayıt yapılamaz (SQLite UNIQUE constraint)
- ❌ Cache TTL dolmadan taze veri çekilemez (force=True hariç)

## Bilinen Sınırlamalar

1. **yfinance sınırları**: Türkçe şirket isimleri için `.IS` suffix gerekli; bazı hisselerde eksik veri
2. **BIST web scraping**: Regex tabanlı parse; site yapısı değişirse kırılır
3. **SQLite**: Production'da yüksek concurrent write için yetersiz olabilir
4. **News ingestion**: RSS sadece son günleri döndürür; historical news verisi ayrı kaynak gerektirir
5. **Fundamental provider**: `earnings_dates` her zaman mevcut değil; tahmini publication date (period_end + 60 gün) kullanılır
6. **Catalyst türetme**: KAP event'lerinden catalyst üretimi basit mapping; gerçek catalyst tarihleri daha karmaşık

## Cross-Reference

| Modül | Bağlantı |
|-------|----------|
| **core** | `orchestrator.py` → `data_source.get_stock_data()` çağırır; `canonical_scoring.py` → `historical_adapter` feature'larını kullanır |
| **features** | `calculator.py` → `DataSourceManager`'dan gelen DataFrame üzerinde feature hesaplar |
| **labels** | `generator.py` → `DataSourceManager`'dan gelen close fiyatları ile forward return label'ları üretir |
| **intelligence** | `news_pipeline.py` → `ingestion_pipeline`'dan gelen event'leri işler |
