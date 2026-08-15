# Bölüm 11 — Portföy Etkisi ve Optimizasyon

## Amaç

Bir hissenin tek başına iyi görünmesinin yeterli olmadığını, mevcut portföye eklendiğinde toplam riski ve getiriyi nasıl değiştireceğini hesaplamak.

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
Mevcut Portföy + Yeni Hisse
    ↓
Correlation
    ↓
Sector Exposure
    ↓
Factor Exposure
    ↓
Concentration
    ↓
Risk / Return
    ↓
Portfolio Optimization
    ↓
Optimal Position Size
```

---

## Nasıl çalışacak?

Örneğin yeni hisse çok güçlü olabilir:

```
Hisse skoru:      90/100
Risk:             Orta
Beklenen getiri:  +35%
```

Ama portföyde zaten aynı sektörden yüksek miktarda varsa:

- Sektör yoğunluğu ↑
- Korelasyon ↑
- Toplam risk ↑

sistem pozisyonu küçültebilir veya tamamen reddedebilir.

Tersi durumda yeni hisse portföydeki mevcut hisselerle düşük korelasyonluysa çeşitlendirme avantajı sağlayabilir.

---

## Neler hesaplanacak?

- Portföy beklenen getirisi
- Portföy volatilitesi
- Korelasyon
- Sektör yoğunluğu
- Hisse yoğunluğu
- Factor exposure
- Likidite
- Maximum position size
- Portföye eklenen marjinal risk
- Risk-adjusted return

---

## Önemli prensip

Sistem:

> "Bu hisse iyi."

ile yetinmeyecek.

Şunu soracak:

> "Bu hisse mevcut portföye eklendiğinde toplam portföy daha iyi mi, daha kötü mü oluyor?"

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

Bu sonuç Bölüm 12 — Karar ve Sinyal Füzyonu motoruna gönderilir.

---


---

**Kaynak:** Portfolio optimization — not just individual stock quality, but how it affects the whole portfolio.


### Örnek: Concentration risk

```python
# services/risk/enhanced_risk.py
from services.risk.enhanced_risk import concentration_risk

hhi = concentration_risk.compute_hhi({"A": 0.5, "B": 0.3, "C": 0.2})
# hhi = 0.38 (HHI)

sector_conc = concentration_risk.compute_sector_concentration(
    {"THYAO": 0.3, "ASELS": 0.2, "GARAN": 0.3, "AKBNK": 0.2},
    {"THYAO": "AVIATION", "ASELS": "TECH", "GARAN": "BANK", "AKBNK": "BANK"},
)
# sector_conc = {"AVIATION": 0.3, "TECH": 0.2, "BANK": 0.5}
```

### Örnek: Rebalance

```python
from services.risk.enhanced_risk import rebalance_engine

orders = rebalance_engine.compute_rebalance(
    current_weights={"A": 0.5, "B": 0.3, "C": 0.2},
    target_weights={"A": 0.3, "B": 0.4, "C": 0.3},
    portfolio_value=100000,
)
# A: SELL 20000, B: BUY 10000, C: BUY 10000
```

## Temel prensip

Hisseyi değil, **hisse + mevcut portföyü tek bir sistem olarak** optimize eder.
