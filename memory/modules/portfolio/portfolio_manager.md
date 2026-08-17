# portfolio/portfolio_manager

**Dosya:** `services/portfolio/portfolio_manager.py`
**Satır:** 1009

## Açıklama

ALPHA BIST — Portfolio Manager v2.0

Kurumsal seviye portföy muhasebesi:
- Weighted average cost basis
- Realized / Unrealized P&L ayrı takip
- Komisyon + BSMV muhasebesi
- Günlük equity curve snapshots (high-water mark)
- Pozisyon geçmişi (açılış/kapanış/kısmi kapatma audit trail)
- Nakit hareketleri ledger (cash ledger)
- Drawdown tracking

v1.0 API'leri 100% geriye uyumlu.

## Sınıflar (7)

- `Position`
- `Trade`
- `CashLedgerEntry`
- `EquitySnapshot`
- `PositionHistoryEntry`
- `CommissionModel`
- `PortfolioManager`

## Fonksiyonlar (42)

- `market_value()`
- `cost_basis()`
- `unrealized_pnl()`
- `unrealized_pnl_pct()`
- `to_dict()`
- `pnl()`
- `pnl_pct()`
- `holding_days()`
- `to_dict()`
- `to_dict()`
- `to_dict()`
- `to_dict()`
- `__init__()`
- `calculate()`
- `breakdown()`
- `_trim_list()`
- `__init__()`
- `calculate_commission()`
- `get_commission_breakdown()`
- `_record_cash()`
- `get_cash_ledger()`
- `_record_position_change()`
- `get_position_history()`
- `_record_equity()`
- `get_equity_snapshots()`
- `get_high_water_mark()`
- `get_drawdown()`
- `open_position()`
- `close_position()`
- `_reduce_position()`
- ... ve 12 daha

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/fee_calculator`

