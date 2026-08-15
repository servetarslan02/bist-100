# Bölüm 7 — Değerleme

## Amaç

Şirket kaliteli ve geleceği olumlu görünse bile, mevcut fiyatının bu beklentilere göre ucuz mu pahalı mı olduğunu belirlemek.

---

## Kullanılacak sistemler

- DCF
- Relative Valuation
  - P/E, P/B, EV/EBITDA vb. çarpanlar
- Fair Value Engine
- Growth Assumptions
- Margin of Safety
- Sector Valuation Comparison

---

## Çalışma mantığı

```
Şirket Analizi + Haber / KAP / Olaylar + Sektör + Makro
    ↓
Gelecek finansal varsayımlar
    ↓
DCF + Çarpan Analizi
    ↓
Fair Value
    ↓
Mevcut Fiyat
    ↓
Upside / Downside
    ↓
Margin of Safety
```

---

## Nasıl kullanılacak?

Örneğin sistem şirket için:

- Büyüme: %25
- Marj: iyileşiyor
- FCF: güçlü
- Risk: orta

gibi Bölüm 5 ve 6'dan gelen bilgileri kullanarak geleceğe yönelik finansal varsayımlar oluşturur.

Sonra tek bir yönteme güvenmez.

Örneğin:

- DCF Fair Value → 150 TL
- P/E Fair Value → 142 TL
- EV/EBITDA Value → 155 TL
- Sector Comparison → 148 TL

Bunları karşılaştırarak daha sağlam bir fair value aralığı oluşturur.

Örneğin:

```
Current Price:    110 TL
Fair Value Range: 142–155 TL
Expected Upside:  +29–41%
```

---

## Çok önemli prensip

**İyi şirket ≠ iyi yatırım.**

Şirket mükemmel olabilir ama fiyatı aşırı pahalıysa sistem bunu fırsat olarak değerlendirmemeli.

Aynı şekilde ucuz görünen bir hisse de sadece ucuz olduğu için önerilmemeli.

---

## Diğer bölümlerle etkileşim

- **Fundamental** → DCF varsayımlarını besler.
- **Haber/KAP** → Gelecek gelir, büyüme veya risk varsayımlarını değiştirebilir.
- **Makro** → İskonto oranı ve büyüme varsayımlarını etkiler.
- **Sektör** → Çarpanların karşılaştırılacağı referansı sağlar.
- **Risk** → Fair value'nun güven aralığını etkiler.

---

## Çıktı

```
Fair Value:           142–155 TL
Current Price:        110 TL
Upside:               +29–41%
Valuation:            Ucuz
Margin of Safety:     Orta/Yüksek
Valuation Confidence: %84
```

Bu da Bölüm 8 — Gelecek Tahmini için başlangıç girdilerinden biri olur.

---


---

**Kaynak:** Multiples vs DCF comparison. Bear/Base/Bull scenarios with probability weighting. Margin of Safety concept.


### Örnek: Multiples değerleme

```python
# services/intelligence/valuation/engine.py
from services.intelligence.valuation.engine import valuation_engine

multiples = valuation_engine.compute_multiples_valuation(
    ticker="THYAO", current_price=305.25,
    company_multiples={"pe": 8.5, "pb": 1.4, "ev_ebitda": 5.1},
    sector_multiples={"pe": {"median": 11.0, "avg": 12.5}},
)
# multiples[0].upside_pct = +29.4% (P/E 8.5 vs sektör 11.0)
```

### Örnek: DCF

```python
dcf = valuation_engine.compute_dcf(
    ticker="THYAO", current_price=305.25,
    revenue_forecast=[60e9, 70e9, 80e9, 90e9, 100e9],
    margin_forecast=[0.10, 0.11, 0.12, 0.12, 0.13],
    shares_outstanding=1_373_278_203,
    total_debt=5e9, total_cash=10e9,
)
# dcf.implied_price = 340.50
# dcf.upside_pct = +11.6%
# dcf.sensitivity_table = {"17.0%": {"2.0%": 320, "3.0%": 340, "4.0%": 365}}
```

## Temel prensip

Sistem sadece "hisse ucuz" demeyecek; "hangi varsayımlarla, hangi yöntemlerle, ne kadar ucuz ve bu hesabın güveni ne?" sorularını cevaplayacak.
