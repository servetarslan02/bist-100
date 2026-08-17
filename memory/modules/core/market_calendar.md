# core/market_calendar

**Dosya:** `services/core/market_calendar.py`
**Satır:** 236

## Açıklama

ALPHA BIST — Market Calendar v1.0

BIST işlem saatleri, tatiller, devre kesici durumları.
Market kapalıyken veri veya işlem üretmemeli.

FAZ 1.7: Trading Calendar

## Sınıflar (3)

- `MarketSession`
- `MarketStatus`
- `MarketCalendar`

## Fonksiyonlar (11)

- `__init__()`
- `is_trading_day()`
- `is_market_open()`
- `get_session()`
- `get_status()`
- `next_open()`
- `next_close()`
- `trading_days_between()`
- `add_halt()`
- `_is_halt()`
- `get_info()`

