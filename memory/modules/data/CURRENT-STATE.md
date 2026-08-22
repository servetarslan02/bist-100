# Data Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 7 |
| Toplam satır | ~2,005 |
| Test sayısı | 12 |
| Veri kaynakları | yfinance, BIST, LocalParquet |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| data_source.py | ✅ TAM | Multi-source fallback, Parquet cache |
| historical_adapter.py | ✅ TAM | Motor4/5/6 feature üretimi |
| historical_contracts.py | ✅ TAM | PIT-safe sözleşmeler |
| persistent_repository.py | ✅ TAM | SQLite CRUD + ingestion state |
| historical_fundamental_provider.py | ✅ TAM | yfinance quarterly fundamental |
| ingestion_pipeline.py | ✅ TAM | Incremental ingestion |

---

## Çözülen Sorunlar (2026-08-20)

1. **`get_yfinance_ticker` tanımsız** — 4 farklı yerde çağrılıyordu ama hiçbir yerde tanımlı değildi; eklendi

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| yfinance sınırları | P1 | Türkçe şirket isimleri için `.IS` suffix gerekli |
| BIST web scraping | P1 | Regex tabanlı parse; site yapısı değişirse kırılır |
| SQLite | P2 | Production'da yüksek concurrent write için yetersiz |
| News ingestion | P2 | RSS sadece son günleri döndürür |
| Fundamental provider | P2 | `earnings_dates` her zaman mevcut değil |
| Catalyst türetme | P2 | Basit mapping; gerçek catalyst tarihleri daha karmaşık |
