# core/price_limits

**Dosya:** `services/core/price_limits.py`
**Satır:** 109

## Açıklama

ALPHA BIST — Price Limits

BIST fiyat limitleri:
- Normal hisseler: ±%10
- Volatil hisseler: ±%5 veya ±%20
- İlk seansta limit yok
- Devre kesici: ±%5 (gün içi), ±%10 (açılış)

## Sınıflar (2)

- `PriceLimitResult`
- `PriceLimitMonitor`

## Fonksiyonlar (4)

- `to_dict()`
- `__init__()`
- `set_custom_limit()`
- `check_price_limit()`

