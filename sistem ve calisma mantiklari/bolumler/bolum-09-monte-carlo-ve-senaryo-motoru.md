# Bölüm 9 — Monte Carlo ve Senaryo Motoru

## Amaç

Tek bir tahmin yerine, binlerce farklı olası piyasa geleceğini simüle ederek getiri ve kayıp dağılımını görmek.

---

## Kullanılacak sistemler

- Monte Carlo Engine
- Scenario Engine
- Volatility Model
- Correlation Model
- Return Distribution
- Tail Risk
- Stress Testing

---

## Çalışma mantığı

```
Bölüm 8 Tahminleri + Getiri Geçmişi + Volatilite + Korelasyon + Makro / Rejim
    ↓
Monte Carlo
    ↓
Binlerce Olası Gelecek
    ↓
Fiyat Dağılımı
    ↓
Getiri Dağılımı
    ↓
Risk / Olasılık
```

---

## Nasıl kullanılacak?

Örneğin sistem 10.000 senaryo çalıştırabilir:

- %5 → çok kötü sonuç
- %25 → negatif
- %50 → baz sonuç çevresi
- %75 → iyi
- %95 → çok iyi

Böylece yalnızca:

> "Beklenen getiri %30."

değil;

> "Beklenen getiri %30 fakat %20 ihtimalle %15'ten fazla kayıp oluşabilir."

gibi daha gerçekçi sonuç üretir.

---

## Önceki bölümler nasıl etkiler?

- **Bölüm 3 — Market Regime:** Risk-on/risk-off durumuna göre senaryolar değişir.
- **Bölüm 5 — Fundamental:** Büyüme, kârlılık ve nakit akışı varsayımları dağılımı etkiler.
- **Bölüm 6 — Haber/KAP:** Önemli olaylar belirli senaryoların olasılığını değiştirir.
- **Bölüm 7 — Valuation:** Fair value senaryolar için referans oluşturur.
- **Bölüm 8 — Forecast:** Monte Carlo'nun başlangıç beklentilerini sağlar.

---

## Stress Test

Normal senaryoların yanında:

- BIST -%10
- Kur +%10
- Faiz +%5
- Sektör -%15
- Volatilite 2x

gibi kötü koşullar da test edilir.

---

## Çıktı

```
Expected Return:     +28%
Median Return:       +24%
Downside Probability: %18
5% Worst Case:       -22%
95% Best Case:       +67%
Tail Risk:           Orta
Stress Result:       -31%
```

Bu sonuç Bölüm 10 — Risk Motoruna aktarılır.

---

## Temel prensip

Monte Carlo geleceği tahmin ettiğini iddia etmez; **mevcut varsayımlar altında mümkün geleceklerin dağılımını ve kuyruk risklerini** ölçer.
