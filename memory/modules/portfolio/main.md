# portfolio/main

**Dosya:** `services/portfolio/main.py`
**Satır:** 802

## Açıklama

ALPHA BIST - Portfolio Service v2.0

v2.0: PortfolioManager v2.0 muhasebe altyapısıyla uyumlu.
- Cash ledger, position history, equity snapshots DB'ye persist edilir.
- Realized P&L, commission, weighted average cost doğru hesaplanır.
- EQUITY = CASH + MARKET_VALUE invariant korunur.
- Tek gerçek muhasebe kaynağı: PortfolioManager v2.0 + DB.

## Sınıflar (1)

- `PortfolioService`

## Fonksiyonlar (6)

- `__init__()`
- `_on_config_change()`
- `_safe_parse_ts()`
- `_verify_invariant()`
- `get_lock_metrics()`
- `get_health_status()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/db_lock`
- `core/database_dev`
- `core/config_watcher`
- `portfolio/portfolio_manager`
- `core/config`

