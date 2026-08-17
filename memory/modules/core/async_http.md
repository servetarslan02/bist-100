# core/async_http

**Dosya:** `services/core/async_http.py`
**Satır:** 144

## Açıklama

ALPHA BIST — Async HTTP Client Utility

Tüm provider'lar için ortak async HTTP altyapısı.

Özellikler:
- aiohttp tabanlı async HTTP client
- Timeout, retry, hata yönetimi
- Connection pooling
- Rate limiting
- Response caching (opsiyonel)

Kullanım:
    client = AsyncHTTPClient(timeout=10, max_retries=3)
    data = await client.get_json("https://api.example.com/data")

## Sınıflar (1)

- `AsyncHTTPClient`

## Fonksiyonlar (1)

- `__init__()`

