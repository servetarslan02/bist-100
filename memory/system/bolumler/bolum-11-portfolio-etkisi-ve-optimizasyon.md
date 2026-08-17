# Bölüm 11 — Portföy Etkisi ve Optimizasyon

## Amaç

Bir hissenin tek başına iyi görünmesinin yeterli olmadığını, mevcut portföye eklendiğinde toplam riski ve getiriyi nasıl değiştireceğini hesaplamak.

**Kaynak:** ScienceDirect (2026) Integrated Financial Risk Management, arXiv AlphaCrafter (2026) Concentration Risk, Resonanz Capital Position Sizing Framework (2025), Springer (2026) Risk Management for Interdependent Assets.

---

## Kullanılacak sistemler

- Portfolio Optimization
- Position Sizing
- Correlation Engine
- Factor Exposure
- Concentration Risk
- Liquidity / Capacity
- Portfolio Accounting

---

## Çalışma mantığı

```
Mevcut Portföy + Yeni Hisse → Correlation → Sector Exposure →
Factor Exposure → Concentration → Risk/Return → Portfolio Optimization →
Optimal Position Size
```

---

## 1. Korelasyon Riski

**Araştırma bulgusu:** Springer (2026) — "Analysis of fourteen assets reveals extreme risk concentration with 67.89% of portfolio variance from correlated positions."

### Örnek: Korelasyon hesaplama

```python
# services/risk/enhanced_risk.py
from services.risk.enhanced_risk import ledoit_wolf
import numpy as np

returns = np.random.randn(100, 5) * 0.02
cov = ledoit_wolf.estimate(returns)
# 5x5 kovaryans matrisi (shrinkage uygulanmış)
# Yüksek korelasyon → risk konsantrasyonu uyarısı
```

---

## 2. Konsantrasyon Riski

**Araştırma bulgusu:** arXiv AlphaCrafter (2026) — "Concentration risk by considering factor correlations, and outputs a structured ensemble."

### Örnek: HHI hesaplama

```python
from services.risk.enhanced_risk import concentration_risk

# Equal weight → düşük HHI
hhi = concentration_risk.compute_hhi({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
# hhi = 0.25

# Concentrated → yüksek HHI
hhi_conc = concentration_risk.compute_hhi({"A": 0.9, "B": 0.1})
# hhi_conc = 0.82
```

### Örnek: Sektör konsantrasyonu

```python
sector_conc = concentration_risk.compute_sector_concentration(
    {"THYAO": 0.3, "ASELS": 0.2, "GARAN": 0.3, "AKBNK": 0.2},
    {"THYAO": "AVIATION", "ASELS": "TECH", "GARAN": "BANK", "AKBNK": "BANK"},
)
# sector_conc = {"AVIATION": 0.3, "TECH": 0.2, "BANK": 0.5}
```

---

## 3. Pozisyon Büyüklüğü

**Araştırma bulgusu:** Resonanz Capital (2025) — "Disciplined sizing and sell rules tie conviction to risk, limit hidden exposures, and enforce exits."

### Örnek: Kelly criterion

```python
from services.risk.enhanced_risk import position_sizer

# Yarım Kelly (daha güvenli)
kelly = position_sizer.kelly_criterion(
    win_rate=0.6, avg_win=2.0, avg_loss=1.0, fraction=0.5)
# kelly = 0.20

size = position_sizer.compute_position_size(
    capital=100000, kelly_fraction=kelly,
    price=305.25, stop_distance=15.26, max_position_pct=10)
# size = 131 lot
```

---

## 4. Rebalance

### Örnek: Eşik bazlı rebalance

```python
from services.risk.enhanced_risk import rebalance_engine

orders = rebalance_engine.compute_rebalance(
    current_weights={"A": 0.5, "B": 0.3, "C": 0.2},
    target_weights={"A": 0.3, "B": 0.4, "C": 0.3},
    portfolio_value=100000,
)
# A: SELL 20000, B: BUY 10000, C: BUY 10000
# Turnover limit: %30 (aşılırsa ölçeklenir)
```

---

## 5. Volatility Targeting

### Örnek: Kaldıraç hesaplama

```python
from services.risk.enhanced_risk import volatility_targeter

# Düşük volatilite → kaldıraç artır
leverage = volatility_targeter.compute_leverage(0.10, 0.20)
# leverage = 2.0

# Yüksek volatilite → pozisyon küçült
leverage = volatility_targeter.compute_leverage(0.40, 0.20)
# leverage = 0.5
```

---

## Çıktı

```
Current Portfolio Risk:   42
After Adding Stock:       39
Optimal Position:         %4.2
Expected Portfolio Return: +18%
Diversification Benefit:  +7
Sector Concentration:     Kabul edilebilir
Decision:                 ADD
```

---

## Temel prensip

> "Disciplined sizing ties conviction to risk, limits hidden exposures, and enforces exits." — Resonanz Capital (2025)

Hisseyi değil, **hisse + mevcut portföyü tek bir sistem olarak** optimize eder.
