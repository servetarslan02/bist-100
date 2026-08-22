# Data

**Modül sayısı:** 7 | **Toplam satır:** ~2,005 | **Sınıf:** 13 | **Fonksiyon:** 62 | **Test:** 195

## Modüller

| Modül | Dosya | Sınıf/Fonksiyon | Açıklama |
|-------|-------|-----------------|----------|
| Data Source | `data_source.py` | DataSourceManager, YahooFinanceSource, BISTSource, LocalParquetSource | Çok kaynaklı veri çekme, Parquet cache, BIST 100 universe |
| Historical Adapter | `historical_adapter.py` | HistoricalDataAdapter | Historical repository → canonical scoring köprüsü; Motor4/5/6 feature üretimi |
| Historical Contracts | `historical_contracts.py` | FundamentalSnapshot, EventSnapshot, CatalystSnapshot, HistoricalDataRepository | PIT-safe veri sözleşmeleri, repository interface |
| Persistent Repository | `persistent_repository.py` | PersistentHistoricalRepository | SQLite tabanlı historical repository implementasyonu; CRUD + ingestion state |
| Historical Fundamental Provider | `historical_fundamental_provider.py` | HistoricalFundamentalProvider | yfinance'dan PIT-safe quarterly fundamental veri çekme; metric mapping |
| Ingestion Pipeline | `ingestion_pipeline.py` | HistoricalIngestionPipeline | Incremental ingestion: fundamental, KAP event, news event, catalyst türetme |

## Spec Uyumu

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Multi-source fallback | ✅ TAM | Local → Yahoo → BIST zinciri |
| Parquet cache | ✅ TAM | 24 saat TTL, ~10x hız |
| PIT-safe snapshots | ✅ TAM | `available_at <= backtest_date` kuralı |
| Incremental ingestion | ✅ TAM | Son başarılı timestamp takibi |
| Deduplication | ✅ TAM | `event_id` bazlı unique constraint |
| SQLite repository | ✅ TAM | WAL modu ile concurrent okuma |
| yfinance fundamental | ✅ TAM | Quarterly financials + earnings_dates |

## Düzeltilen Sorunlar (2026-08-20)

1. **`get_yfinance_ticker` tanımsız** — 4 farklı yerde çağrılıyordu ama hiçbir yerde tanımlı değildi; eklendi
2. **PIT-safe fundamental mapping** — `earnings_dates` her zaman mevcut değil; tahmini publication date (period_end + 60 gün) fallback eklendi
