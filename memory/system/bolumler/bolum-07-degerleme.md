# Bölüm 7 — Değerleme

## Amaç

Şirket kaliteli ve geleceği olumlu görünse bile, mevcut fiyatının bu beklentilere göre ucuz mu pahalı mı olduğunu belirlemek.

**Kaynak:** Oaktree Capital "The Calculus of Value" (2025), Margin of Safety concept, Bear/Base/Bull scenario analysis.

---

## Kullanılacak sistemler

- DCF
- Relative Valuation (P/E, P/B, EV/EBITDA)
- Fair Value Engine
- Growth Assumptions
- Margin of Safety
- Sector Valuation Comparison

---

## Çalışma mantığı

```
Şirket Analizi + Haber/KAP + Sektör + Makro → Gelecek finansal varsayımlar →
DCF + Çarpan Analizi → Fair Value → Mevcut Fiyat → Upside/Downside → Margin of Safety
```

---

## 1. Multiples Değerleme

### Örnek: Multiples karşılaştırma

```python
# services/intelligence/valuation/engine.py
from services.intelligence.valuation.engine import valuation_engine

multiples = valuation_engine.compute_multiples_valuation(
    ticker="THYAO",
    current_price=305.25,
    company_multiples={"pe": 8.5, "pb": 1.4, "ev_ebitda": 5.1},
    sector_multiples={"pe": {"median": 11.0, "avg": 12.5}},
)
# P/E upside: +29.4% (8.5 vs sektör 11.0)
```

---

## 2. DCF

### Örnek: DCF hesaplama

```python
dcf = valuation_engine.compute_dcf(
    ticker="THYAO",
    current_price=305.25,
    revenue_forecast=[60e9, 70e9, 80e9, 90e9, 100e9],
    margin_forecast=[0.10, 0.11, 0.12, 0.12, 0.13],
    shares_outstanding=1_373_278_203,
    total_debt=5e9,
    total_cash=10e9,
)
# implied_price: 340.50, upside: +11.6%
# sensitivity_table: WACC × terminal_growth → fiyat
```

---

## 3. Peer Comparison

Aynı sektördeki şirketlerle karşılaştırır.

### Örnek: Peer karşılaştırma

```python
# services/intelligence/valuation/engine.py
company = {"pe": 8.5, "pb": 1.4, "ev_ebitda": 5.1}
sector = {
    "pe": {"median": 11.0, "avg": 12.5},
    "pb": {"median": 1.8, "avg": 2.0},
    "ev_ebitda": {"median": 7.0, "avg": 7.5},
}
multiples = valuation_engine.compute_multiples_valuation("THYAO", 305.25, company, sector)
# P/E upside: +29.4%, P/B upside: +28.6%, EV/EBITDA upside: +37.3%
```

---

## 4. Bear/Base/Bull Senaryoları

**Araştırma bulgusu:** Oaktree Capital — "Investment assets have intrinsic value. The key is estimating it under different assumptions."

### Örnek: Senaryo değerleme

```python
scenarios = valuation_engine.compute_valuation_scenarios(
    ticker="THYAO",
    current_price=305.25,
    base_assumptions={"revenue_growth": 0.10, "margin": 0.12, "wacc": 0.20},
    bear_adjustments={"revenue_growth": -0.05, "margin": -0.03, "wacc": 0.03},
    bull_adjustments={"revenue_growth": 0.05, "margin": 0.03, "wacc": -0.02},
    shares_outstanding=1_373_278_203,
)
# Bear: 280 TL, Base: 340 TL, Bull: 420 TL
# Expected Value = P(bear)×280 + P(base)×340 + P(bull)×420 = 347 TL
```

---

## 4. Çok Önemli Prensip

**İyi şirket ≠ iyi yatırım.** Şirket mükemmel olabilir ama fiyatı aşırı pahalıysa sistem bunu fırsat olarak değerlendirmemeli.

---

## Çıktı

```
Fair Value Range: 142–155 TL
Current Price:    110 TL
Upside:           +29–41%
Valuation:        Ucuz
Margin of Safety: Orta/Yüksek
```

---

## Temel prensip

Sistem sadece "hisse ucuz" demeyecek; "hangi varsayımlarla, hangi yöntemlerle, ne kadar ucuz ve bu hesabın güveni ne?" sorularını cevaplayacak.

## 5. Enflasyon Muhasebesi ile DCF (TMS 29)

Yüksek enflasyonda DCF hesaplaması farklılaşır:

### Nominal vs Reel DCF:
```python
def inflation_adjusted_dcf(nominal_fcf, inflation_rate, discount_rate, years):
    # Reel faiz oranı
    real_rate = (1 + discount_rate) / (1 + inflation_rate) - 1
    
    # Reel FCF'ler
    real_fcfs = []
    for i in range(years):
        real_fcf = nominal_fcf / ((1 + inflation_rate) ** (i + 1))
        real_fcfs.append(real_fcf)
    
    # Reel DCF
    dcf = sum(fcf / ((1 + real_rate) ** (i + 1)) for i, fcf in enumerate(real_fcfs))
    
    return dcf
```

### TMS 29 düzeltmesi:
```python
def tms29_adjustment(financials, cpi_index_current, cpi_index_base):
    adjustment_factor = cpi_index_current / cpi_index_base
    
    adjusted = {
        "revenue": financials["revenue"] * adjustment_factor,
        "cost": financials["cost"] * adjustment_factor,
        "depreciation": financials["ppe"] / financials["useful_life"] * adjustment_factor,
        "monetary_gain_loss": calculate_monetary_items(financials, adjustment_factor),
    }
    
    return adjusted
```
