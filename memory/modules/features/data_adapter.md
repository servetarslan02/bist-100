# features/data_adapter

**Dosya:** `services/features/data_adapter.py`
**Satır:** 633

## Açıklama

ALPHA BIST — Data Adapter v1.0

Feature pipeline ile veri kaynakları arasında bağlantı katmanı.

Sorumluluk:
- Fundamental veriyi Motor 4 formatına çevir
- KAP/haber veriyi Motor 5 formatına çevir
- Katalizör veriyi Motor 6 formatına çevir
- Eksik veri durumunda MISSING/UNKNOWN döndür
- Point-in-time güvenliğini koru

Provider bağımlılıkları (yfinance, aiohttp) kurulu değilse
graceful degradation — MISSING status döner, pipeline durmaz.

## Sınıflar (1)

- `DataAdapter`

## Fonksiyonlar (15)

- `__init__()`
- `_load_providers()`
- `reset_duplicates()`
- `_run_async()`
- `fetch_fundamentals()`
- `_check_fundamental_freshness()`
- `_empty_fundamental()`
- `fetch_kap_events()`
- `fetch_news_events()`
- `derive_catalysts()`
- `_parse_news_date()`
- `_classify_kap_category()`
- `_estimate_sentiment()`
- `_estimate_importance()`
- `_kap_category_to_catalyst_type()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/production_metrics`
- `core/circuit_breaker`

