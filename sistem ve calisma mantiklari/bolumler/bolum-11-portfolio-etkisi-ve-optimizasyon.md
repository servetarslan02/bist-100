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

## Temel prensip

Hisseyi değil, **hisse + mevcut portföyü tek bir sistem olarak** optimize eder.
