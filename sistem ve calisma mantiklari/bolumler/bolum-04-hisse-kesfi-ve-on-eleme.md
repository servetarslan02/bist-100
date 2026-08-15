# Bölüm 4 — Hisse Keşfi ve Ön Eleme

## Amaç

BIST'teki tüm hisseleri tek tek derin analiz etmek yerine, önce çok geniş havuzu sistematik biçimde daraltıp analiz edilmeye değer adayları bulmak.

---

## Kullanılacak sistemler

- Stock Discovery Engine
- Liquidity Filter
- Technical Screener
- Fundamental Screener
- Factor Engine
  - Value
  - Momentum
  - Quality
  - Growth
  - Size
  - Low Volatility
- Relative Strength
- Sector Strength
- Anomaly Detection
- Market Regime bilgisi

---

## Çalışma mantığı

```
Tüm BIST Hisseleri
    ↓
Veri / kalite filtresi
    ↓
Likidite filtresi
    ↓
Riskli / uygunsuz hisseleri ele
    ↓
Fundamental ön filtre
    ↓
Technical ön filtre
    ↓
Momentum / Relative Strength
    ↓
Value / Quality / Growth
    ↓
Sektör + Market Regime uyumu
    ↓
Skorlama
    ↓
ADAY HİSSE HAVUZU
```

---

## Nasıl kullanılacak?

Örneğin sistem 600+ hisseyi tarıyor.

Önce:

> "Bu hissede yeterli ve güvenilir veri var mı?"

Sonra:

> "Likiditesi yeterli mi?"

Sonra:

> "Finansal açıdan tamamen problemli mi?"

Sonra:

> "Teknik olarak ilgi çekici mi?"

Sonra:

> "Momentum, value, quality gibi faktörlerde nerede?"

Son olarak Bölüm 3'te belirlenen piyasa rejimi ve sektör koşullarıyla uyumu hesaplanır.

Her hisse için bir aday skoru oluşturulur.

Örneğin:

```
Hisse X
Quality:             82
Value:               76
Momentum:            91
Liquidity:           88
Sector Strength:     84
Market Regime Fit:   79
Discovery Score:     84/100
```

Bu BUY anlamına gelmez.

Sadece:

> "Bu hisseyi daha derin incelemeye değer."

anlamına gelir.

---

## Çıktı

Örneğin:

```
600+ hisse
    ↓
250 uygun
    ↓
100 kaliteli aday
    ↓
30 güçlü aday
    ↓
10-20 DERİN ANALİZ ADAYI
```

Bu 10–20 hisse sonraki **Bölüm 5 — Şirketi Derinlemesine Analiz Etme** bölümüne gönderilir.

---

## Temel prensip

Bu bölüm **hızlı ve geniş tarama** yapar; **nihai hisse önerisini vermez**.
