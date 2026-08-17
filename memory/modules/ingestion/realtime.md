# ingestion/realtime

**Dosya:** `services/ingestion/realtime.py`
**Satır:** 142

## Açıklama

ALPHA BIST — Real-time Data Provider v1.0

Gerçek zamanlı veri akışı:
- BIST canlı fiyat (WebSocket/streaming)
- Fallback: yfinance polling (5 dakika)
- Event-driven updates

FAZ 1: Real-time data

## Sınıflar (1)

- `RealtimeDataProvider`

## Fonksiyonlar (5)

- `__init__()`
- `on_tick()`
- `get_last_price()`
- `get_all_prices()`
- `get_stats()`

