# Bölüm 11 — Portföy Etkisi ve Optimizasyon

## Amaç

Bir hissenin tek başına iyi görünmesinin yeterli olmadığını, mevcut portföye eklendiğinde toplam riski ve getiriyi nasıl değiştireceğini hesaplamak.

**Kaynak:** Portfolio optimization — correlation-based diversification, factor exposure tracking.

## Çalışma mantığı

```
Mevcut Portföy + Yeni Hisse → Correlation → Sector Exposure →
Factor Exposure → Concentration → Risk/Return → Portfolio Optimization →
Optimal Position Size
```

### Örnek: Concentration risk

```python
from services.risk.enhanced_risk import concentration_risk
hhi = concentration_risk.compute_hhi({"A": 0.5, "B": 0.3, "C": 0.2})
# hhi = 0.38
```

### Örnek: Rebalance

```python
from services.risk.enhanced_risk import rebalance_engine
orders = rebalance_engine.compute_rebalance(
    {"A": 0.5, "B": 0.3, "C": 0.2}, {"A": 0.3, "B": 0.4, "C": 0.3}, 100000)
# A: SELL 20000, B: BUY 10000, C: BUY 10000
```

## Temel prensip

Hisseyi değil, **hisse + mevcut portföyü tek bir sistem olarak** optimize eder.
