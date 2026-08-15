# Bölüm 5 — Şirketi Derinlemesine Analiz Etme

## Amaç

Bölüm 4'te seçilen adayların gerçekten finansal ve operasyonel olarak kaliteli şirketler olup olmadığını anlamak.

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
Aday Hisse
    ↓
Finansal tablolar
    ↓
Gelir ve büyüme
    ↓
Kârlılık
    ↓
Nakit üretimi
    ↓
Boranç ve bilanço sağlamlığı
    ↓
Kazancın kalitesi
    ↓
Sektör karşılaştırması
    ↓
Şirket kalitesi
```

---

## Neler incelenecek?

Örneğin:

- Ciro büyüyor mu?
- Kâr sürdürülebilir mi?
- FCF üretiyor mu?
- Borç taşıyabilir mi?
- Marjlar iyileşiyor mu?
- ROE / ROIC nasıl?
- Kârın ne kadarı gerçek operasyonlardan geliyor?
- Bilanço güçleniyor mu, bozuluyor mu?
- Şirket sektöründeki rakiplerine göre nasıl?

---

## Diğer bölümlerle etkileşim

**Bölüm 3 — Piyasa Analizi:**
Piyasa riskliyse güçlü şirketlerde bile risk katsayısı değişebilir.

**Bölüm 4 — Hisse Keşfi:**
Discovery skorunu oluşturan fundamental faktörlerin gerçek derinlik analizini burada yapar.

**Bölüm 6 — Haber/KAP:**
Örneğin bilanço iyi görünürken önemli bir KAP açıklaması geldiyse bu analiz güncellenir.

**Bölüm 7 — Değerleme:**
Şirketin gelecekteki büyüme ve kârlılık varsayımlarını valuation motoruna gönderir.

---


---

**Kaynak:** Fundamental analysis — FCF-centered approach for inflation-distorted markets (TMS29). Sector-normalized multiples. Earnings quality: net income vs cash flow comparison.


### Örnek: Fundamental feature hesaplama

```python
# services/features/fundamental.py
from services.features.fundamental import fundamental_feature_engine

fund = {
    "price": 305.25, "pe_ratio": 8.5, "pb_ratio": 1.4,
    "roe": 0.15, "profit_margin": 0.10, "debt_to_equity": 0.45,
    "free_cash_flow": 6800000, "revenue": 100000000, "market_cap": 100000000,
}

features = fundamental_feature_engine.compute_all_fundamental_features(fund)
# features["raw_pe_ratio"] = 8.5
# features["roe"] = 15.0
# features["fcf_yield_pct"] = 6.8
# features["balance_sheet_quality"] = 75.0
# features["growth_quality_score"] = 85.0
```

### Örnek: Sektörel normalize

```python
# Aynı P/E farklı sektörlerde farklı anlama gelir
# Banka P/E 8 = ucuz, Teknoloji P/E 8 = aşırı ucuz
sector_medians = {"pe_ratio": 11.0, "pb_ratio": 1.8, "ev_ebitda": 7.0}
features = fundamental_feature_engine.compute_all_fundamental_features(fund)
# features["sector_norm_pe_ratio"] = 0.77 (8.5 / 11.0 = sektör medyanının altında)
```

## Çıktı

```
Company Quality:       87/100
Growth:                Güçlü
Profitability:         Güçlü
Cash Flow:             Orta/Güçlü
Debt:                  Düşük risk
Earnings Quality:      Yüksek
Sector Position:       Güçlü
Fundamental Conclusion: Güçlü / Orta / Zayıf
```

Buradaki sonuç henüz BUY değildir.

Sistem artık şu soruya cevap verebiliyor:

> "Bu şirket gerçekten kaliteli mi ve finansal olarak gelecekte değer üretme potansiyeli var mı?"

Sonraki bölümde bunun üzerine haber + KAP + sosyal medya + olay etkisi eklenir.
