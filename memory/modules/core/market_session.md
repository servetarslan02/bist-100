# core/market_session

**Dosya:** `services/core/market_session.py`
**Satır:** 150

## Açıklama

ALPHA BIST — Market Session Manager

BIST piyasa saatleri ve durum yönetimi.
Europe/Istanbul timezone. UTC/local karışımı yok.

## Sınıflar (2)

- `MarketPhase`
- `MarketSessionManager`

## Fonksiyonlar (11)

- `__init__()`
- `now_istanbul()`
- `current_phase()`
- `is_trading_hours()`
- `is_pre_market()`
- `is_post_market()`
- `is_closed()`
- `next_phase_change()`
- `seconds_until_next_phase()`
- `should_run_trading_job()`
- `get_status()`

