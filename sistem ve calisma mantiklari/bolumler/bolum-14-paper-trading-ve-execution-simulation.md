# Bölüm 14 — Paper Trading ve Execution Simulation

## Amaç

Backtest'ten geçen sistemi gerçek para kullanmadan, gerçek piyasa akışına yakın koşullarda çalıştırmak.

**Kaynak:** arXiv AlphaCrafter (2026) — "Live-trading phase using paper-trading API from a real brokerage, operating under actual market order execution." MDPI (2026) — "Transaction costs, execution slippage, and permanent market impact."

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
Gerçek Piyasa Verisi → Karar → Risk Gate → Emir Simülasyonu →
Spread + Slippage + Likidite → Fill → Sanal Portföy → P&L → Gerçek Sonuçla Karşılaştırma
```

---

## 1. Execution Simulator

**Araştırma bulgusu:** MDPI (2026) — "Transaction costs, execution slippage, and permanent market impact when trading."

### Örnek: Gerçekçi işlem simülasyonu

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
# status: FILLED
# filled_quantity: 1000
# avg_fill_price: 305.40 (slippage: 0.05%)
# commission: 3.68
# slippage: 0.05
```

---

## 2. Slippage Model

```
Slippage = base_slippage + volume_impact
base_slippage = spread / 2
volume_impact = (order_size / avg_daily_volume) × volatility × k
```

100 lot emir ile 10,000 lot emir aynı slippage'a sahip olmamalı.

---

## 3. Komisyon Modeli

```
Broker komisyonu: %0.03
BIST ücreti: %0.0056
BSMV: Komisyon üzerinden %5
Minimum: ₺1
```

---

## 4. Partial Fill

Büyük emirler tamamen dolmayabilir:

```
Emir: 10,000 lot
Fill 1: 6,000 lot @ 305.25
Fill 2: 3,000 lot @ 305.40
Fill 3: 1,000 lot @ 305.60
```

---

## 5. Neden Gerekli?

Backtest'te iyi görünen sistem gerçek piyasada:
- Slippage
- Spread
- Düşük likidite
- Emir gerçekleşmemesi
- Ani fiyat hareketleri

nedeniyle kötü çalışabilir.

---

## Çıktı

```
Emir: BUY 1000 lot THYAO
Fill: 850 lot @ 305.40
Bekleyen: 150 lot
Slippage: 0.05%
Komisyon: ₺3.68
```

---

## Temel prensip

> "Live-trading phase using paper-trading API from a real brokerage, operating under actual market order execution." — arXiv AlphaCrafter (2026)

Backtest **"geçmişte çalıştı mı?"**, paper trading **"bugünün gerçek piyasa koşullarında çalışıyor mu?"** sorusunu cevaplar.
