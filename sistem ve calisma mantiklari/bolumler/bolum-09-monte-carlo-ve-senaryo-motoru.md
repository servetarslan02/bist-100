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


---

**Kaynak:** Monte Carlo — GBM simulation. VaR/CVaR for tail risk. Dynamic scenario count based on volatility.


### Örnek: Monte Carlo simülasyon

```python
# services/intelligence/monte_carlo.py
from services.intelligence.monte_carlo import monte_carlo_engine

result = monte_carlo_engine.simulate_price_paths(
    ticker="THYAO", current_price=305.25,
    expected_return_annual=0.15, volatility_annual=0.25,
    horizon_days=20, num_simulations=10000,
)
# result.p10 = 280.50 (%10 olasılıkla bu fiyatın altında)
# result.p50 = 315.20 (medyan)
# result.p90 = 355.80 (%10 olasılıkla bu fiyatın üstünde)
# result.prob_positive = 0.62
# result.var_95 = -8.2
# result.cvar_95 = -11.5
```

## Temel prensip

Monte Carlo geleceği tahmin ettiğini iddia etmez; **mevcut varsayımlar altında mümkün geleceklerin dağılımını ve kuyruk risklerini** ölçer.
