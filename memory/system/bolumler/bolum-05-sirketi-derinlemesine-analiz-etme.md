# Bölüm 5 — Şirketi Derinlemesine Analiz Etme

## Amaç

Bölüm 4'te seçilen adayların gerçekten finansal ve operasyonel olarak kaliteli şirketler olup olmadığını anlamak.

**Kaynak:** TMS 29 Enflasyon Muhasebesi, FCF-centered analysis for inflation-distorted markets.

---

## Kullanılacak sistemler

- Fundamental Analysis
  - Bilanço Analizi
  - Gelir Tablosu Analizi
  - Nakit Akışı Analizi
  - Borç / Likidite Analizi
  - Kârlılık Analizi
  - Büyüme Analizi
- Earnings Quality
- Sektör Karşılaştırması
- Şirket/rekabet analizi

---

## Çalışma mantığı

```
Aday Hisse → Finansal tablolar → Gelir ve büyüme → Kârlılık →
Nakit üretimi → Borç ve bilanço sağlamlığı → Kazancın kalitesi →
Sektör karşılaştırması → Şirket kalitesi
```

---

## 1. Enflasyon Muhasebesi (TMS 29)

**Kritik:** Türkiye'de enflasyon muhasebesi F/K, PD/DD gibi metrikleri bozar.

**Çözüm:**
- FCF'yi merkeze al (nakit akışı enflasyondan daha az etkilenir)
- Parasal pozisyon kâr/zararını arındır
- Marj trendini takip et

### Örnek: FCF-centered analiz

```python
# services/features/fundamental.py
from services.features.fundamental import fundamental_feature_engine

fund = {
    "price": 305.25,
    "pe_ratio": 8.5,
    "free_cash_flow": 6800000,
    "revenue": 100000000,
    "market_cap": 100000000,
    "profit_margin": 0.10,
    "debt_to_equity": 0.45,
}

features = fundamental_feature_engine.compute_all_fundamental_features(fund)
# fcf_yield_pct: 6.8% (FCF merkezli)
# balance_sheet_quality: 75
# growth_quality_score: 85
```

---

## 2. Kârlılık Analizi

**Metrikler:** ROE, ROA, ROIC, Marj trendi (genişliyor/daralıyor)

### Örnek: Kârlılık feature'ları

```python
features = fundamental_feature_engine.compute_profitability_features(fund)
# roe: 15.0%, roa: 8.0%, profit_margin: 10.0%
```

---

## 3. Büyüme Analizi

**Metrikler:** Ciro büyümesi, Kâr büyümesi, FCF büyümesi, Büyüme kalitesi

### Örnek: Büyüme kalitesi

```python
features = fundamental_feature_engine.compute_quality_features(fund)
# growth_quality_score: 85 (yüksek büyüme + iyi marj + düşük borç)
# growth_quality_warning: 0 (uyarı yok)
```

---

## 4. Bilanço Analizi

### Örnek: Bilanço feature'ları

```python
features = fundamental_feature_engine.compute_balance_sheet_features(fund)
# debt_to_equity: 0.45
# current_ratio: 1.8
# net_debt_ebitda: 2.1
# cash_debt_ratio: 0.40
```

---

## 5. Earnings Quality

Kârın kalitesini ölçer (sadece miktarı değil).

### Örnek: Nakit dönüşümü

```python
features = fundamental_feature_engine.compute_cash_flow_features(fund)
# fcf_margin: 6.8%
# fcf_yield_pct: 6.8%
# cash_conversion: 1.2 (faaliyet kârı nakit ile destekleniyor)
```

Yüksek kâr + düşük nakit dönüşümü = şüpheli kalite.

---

## 6. Sektör Karşılaştırması

### Örnek: Sektörel normalize

```python
# F/K 8.5 / Sektör medyanı 11.0 = 0.77 (ucuz)
features = fundamental_feature_engine.compute_all_fundamental_features(fund)
# sector_norm_pe_ratio: 0.77
```

---

## Çıktı

```
Company Quality:       87/100
Growth:                Güçlü
Profitability:         Güçlü
Cash Flow:             Orta/Güçlü
Debt:                  Düşük risk
Earnings Quality:      Yüksek
Fundamental Conclusion: Güçlü
```

---

## Temel prensip

İyi şirket ≠ iyi yatırım. Şirket mükemmel olabilir ama fiyatı aşırı pahalıysa sistem bunu fırsat olarak değerlendirmemeli.
