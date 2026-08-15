# Bölüm 14 — Paper Trading ve Execution Simulation

## Amaç

Backtest'ten geçen sistemi gerçek para kullanmadan, gerçek piyasa akışına yakın koşullarda çalıştırmak.

---

## Kullanılacak sistemler

- Paper Trading Engine
- Execution Simulator
- Order Management
- Liquidity Engine
- Spread Model
- Slippage Model
- Partial Fill
- Transaction Cost
- Portfolio Ledger
- P&L Tracking

---

## Çalışma mantığı

```
Gerçek Piyasa Verisi
    ↓
Karar / Sinyal
    ↓
Risk Gate
    ↓
Emir Simülasyonu
    ↓
Spread + Slippage + Likidite
    ↓
Fill / Partial Fill
    ↓
Sanal Portföy
    ↓
P&L + Risk
    ↓
Gerçek Sonuçla Karşılaştırma
```

---

## Nasıl kullanılacak?

Örneğin sistem:

> BUY — Hisse X — %4 pozisyon

dedi.

Paper Trading sistemi gerçek emir göndermez.

Piyasa koşullarına bakarak:

```
Emir:       1.000 lot
Spread:     ...
Slippage:   ...
Likidite:   ...
Fill:       850 lot
Bekleyen:   150 lot
```

gibi gerçekçi bir işlem sonucu üretir.

---

## Neden gerekli?

Backtest'te iyi görünen sistem gerçek piyasada:

- slippage
- spread
- düşük likidite
- emir gerçekleşmemesi
- ani fiyat hareketleri

nedeniyle kötü çalışabilir.

Paper trading bunu production öncesinde ortaya çıkarır.

---

## Ölçülecekler

- Signal Accuracy
- Execution Quality
- Slippage
- Fill Rate
- Realized P&L
- Drawdown Risk
- Portfolio Impact

---

## Kritik bağlantı

```
Backtest → Paper Trading → Gerçek piyasa sonuçları → Prediction / Execution karşılaştırması → Model iyileştirme
```

Sistem yeterli süre paper trading'de başarılı olmadan gerçek para ile işlem katmanına geçmemeli.

---


---

**Kaynak:** Execution simulation — slippage model, partial fills, realistic transaction costs.


### Örnek: Execution simulation

```python
# services/simulation/execution_simulator.py
from services.simulation.execution_simulator import (
    execution_simulator, Order, OrderSide, OrderType,
)

order = Order(
    order_id="ORD-001", portfolio_id=1, instrument_id=1,
    ticker="THYAO", side=OrderSide.BUY, order_type=OrderType.MARKET,
    quantity=1000,
)

result = execution_simulator.execute_order(
    order, market_price=305.25,
    avg_volume=500000, volatility=0.25, spread_pct=0.1,
)
# result.status = FILLED
# result.filled_quantity = 1000
# result.avg_fill_price = 305.40 (slippage: 0.05%)
# result.commission = 3.68
# result.slippage = 0.05
```

## Temel prensip

Backtest **"geçmişte çalıştı mı?"**, paper trading ise **"bugünün gerçek piyasa koşullarında gerçekten çalışıyor mu?"** sorusunu cevaplar.
