# Bölüm 14 — Paper Trading ve Execution Simulation

## Amaç

Backtest'ten geçen sistemi gerçek para kullanmadan, gerçek piyasa akışına yakın koşullarda çalıştırmak.

**Kaynak:** Slippage modeling, partial fills, realistic transaction costs.

## Çalışma mantığı

```
Gerçek Piyasa Verisi → Karar → Risk Gate → Emir Simülasyonu →
Spread + Slippage + Likidite → Fill → Sanal Portföy → P&L
```

### Örnek: Execution simulation

```python
from services.simulation.execution_simulator import execution_simulator, Order, OrderSide, OrderType

order = Order(order_id="O1", portfolio_id=1, instrument_id=1,
    ticker="THYAO", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000)
result = execution_simulator.execute_order(order, market_price=305.25,
    avg_volume=500000, volatility=0.25, spread_pct=0.1)
# filled: 1000, price: 305.40 (slippage: 0.05%), commission: 3.68
```

## Temel prensip

Backtest "geçmişte çalıştı mı?", paper trading "bugünün gerçek piyasa koşullarında çalışıyor mu?" sorusunu cevaplar.
