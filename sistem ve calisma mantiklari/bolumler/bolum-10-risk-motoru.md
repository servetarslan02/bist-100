# Bölüm 10 — Risk Motoru

## Amaç

Bir hissenin sadece ne kadar kazandırabileceğini değil, ne kadar ve hangi koşullarda kaybettirebileceğini belirlemek.

**Kaynak:** Du (2026) Ledoit-Wolf covariance, Oxford (2023) volatility targeting, Kelly criterion.

---

## Çalışma mantığı

```
Hisse + Monte Carlo + Volatilite + Market Regime + Fundamental Risk + Liquidity + Portfolio →
RISK ENGINE → Risk Score + Maximum Loss + Drawdown + Position Limit + Risk/Reward
```

---

## 1. Ledoit-Wolf Kovaryans

### Örnek: Regularized kovaryans

```python
# services/risk/enhanced_risk.py
from services.risk.enhanced_risk import ledoit_wolf
import numpy as np

returns = np.random.randn(100, 5) * 0.02
cov = ledoit_wolf.estimate(returns)
# 5x5 kovaryans matrisi (shrinkage uygulanmış)
```

---

## 2. Kelly Criterion

### Örnek: Pozisyon boyutu

```python
from services.risk.enhanced_risk import position_sizer

kelly = position_sizer.kelly_criterion(0.6, 2.0, 1.0, fraction=0.5)
# kelly = 0.20 (yarım Kelly)

size = position_sizer.compute_position_size(100000, kelly, 305.25, 15.26)
# size = 131 lot
```

---

## 3. Volatility Targeting

### Örnek: Kaldıraç hesaplama

```python
from services.risk.enhanced_risk import volatility_targeter

leverage = volatility_targeter.compute_leverage(0.10, 0.20)
# leverage = 2.0 (düşük vol → yüksek kaldıraç)

leverage = volatility_targeter.compute_leverage(0.40, 0.20)
# leverage = 0.5 (yüksek vol → düşük kaldıraç)
```

---

## Çıktı

```
Risk Score:     34/100
Risk Level:     Orta
VaR:            -8.2%
Max Drawdown:   -12%
Position Limit: %5
Risk/Reward:    2.8
```

---

## Temel prensip

"Bu hisse iyi mi?" sorusundan önce "bu fırsatı hangi riskle ve portföyün ne kadarını kullanarak değerlendirmeliyiz?" sorusunu cevaplar.
