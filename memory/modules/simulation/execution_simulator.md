# simulation/execution_simulator

**Dosya:** `services/simulation/execution_simulator.py`
**Satır:** 258

## Açıklama

ALPHA BIST — Execution Simulator v1.0

Gercekci sanal islem:
- Order lifecycle (CREATED → FILLED)
- Slippage model (volatility, spread, liquidity, order size)
- Transaction cost model (commission, BSMV)
- Partial fill destegi

FAZ 10: Order & Execution Simulator

## Sınıflar (6)

- `OrderStatus`
- `OrderSide`
- `OrderType`
- `Order`
- `Fill`
- `ExecutionSimulator`

## Fonksiyonlar (5)

- `execute_order()`
- `_execute_order_internal()`
- `_compute_slippage()`
- `_compute_commission()`
- `create_fill()`

