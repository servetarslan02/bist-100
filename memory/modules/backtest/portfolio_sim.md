# backtest/portfolio_sim

**Dosya:** `services/backtest/portfolio_sim.py`
**Satır:** 565

## Açıklama

ALPHA BIST — Portfolio Simulator v3.0 (Institutional Grade)

Finansal doğruluk:
- Position lifecycle (open → partial close → full close)
- Oversell prevention
- Cash accounting invariant: cash + cost_basis + realized_pnl = initial (approximately)
- Commission: BIST yapısı (broker + exchange + BSMV)
- Slippage: volume-aware
- Realized / unrealized P&L
- Daily equity snapshot
- Audit trail (her işlem loglanır)
- Deterministic sonuç garantisi

Mevcut v2.0 ile aynı finansal sonuçları üretir.

## Sınıflar (6)

- `Trade`
- `Position`
- `EquitySnapshot`
- `AuditEntry`
- `BISTCommissionModel`
- `PortfolioSimulatorV3`

## Fonksiyonlar (25)

- `to_dict()`
- `market_value()`
- `unrealized_pnl()`
- `unrealized_pnl_pct()`
- `to_dict()`
- `to_dict()`
- `compute()`
- `__init__()`
- `execute_buy()`
- `execute_sell()`
- `update_equity()`
- `get_total_value()`
- `get_realized_pnl()`
- `get_unrealized_pnl()`
- `can_buy()`
- `get_position_count()`
- `has_position()`
- `get_trades()`
- `get_equity_curve()`
- `get_audit_log()`
- `compute_metrics()`
- `check_invariants()`
- `_compute_holding_days()`
- `_audit()`
- `reset()`

