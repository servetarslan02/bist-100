# Bölüm 28 — Turkish Macro Indicators

## Amaç

Türkiye'ye özgü makroekonomik göstergelerin BIST üzerindeki etkisini anlamak ve bu göstergeleri sisteme dahil etmek.

**Kaynak:** SBB Medium Term Program (2026-2028), ResearchGate (2023) Exchange Rate and Inflation under Weak Monetary Policy.

---

## Kullanılacak sistemler

- TCMB Data Collector
- Inflation Tracker
- FX Rate Monitor
- CDS Spread Monitor
- Credit Growth Tracker
- Current Account Monitor
- Political Risk Assessor

---

## Çalışma mantığı

```
TCMB Kararları + Enflasyon + USDTRY + CDS + Kredi Büyümesi + Cari Açık →
Macro Engine → BIST Etki Analizi → Portfolio Kararı
```

---

## 1. TCMB Faiz Kararları

### BIST üzerindeki etki:
```
Faiz artışı → Kısa vadede BIST düşüş (borç maliyeti artar)
             → Uzun vadede BIST yükseliş (TL güçlenir, enflasyon düşer)
Faiz düşüşü → Kısa vadede BIST yükseliş (likidite artar)
             → Uzun vadede risk (enflasyon, kur baskısı)
```

### Örnek: TCMB faiz feature'ları

```python
# services/macro/tcmb.py
def compute_tcmb_features(tcmb_data):
    features = {}

    # Faiz seviyesi
    features["tcmb_rate"] = tcmb_data["policy_rate"]
    features["tcmb_rate_change"] = tcmb_data["policy_rate"].diff()
    features["tcmb_rate_change_3m"] = tcmb_data["policy_rate"].diff(3)

    # Reel faiz
    features["real_rate"] = tcmb_data["policy_rate"] - tcmb_data["inflation"]
    features["real_rate_change"] = features["real_rate"].diff()

    # Faiz beklentisi
    features["rate_expectation"] = tcmb_data["rate_expectation_survey"]
    features["rate_surprise"] = tcmb_data["policy_rate"] - tcmb_data["rate_expectation"]

    # Para politikası sinyali
    features["policy_stance"] = (
        1 if features["tcmb_rate_change"] > 0 else (-1 if features["tcmb_rate_change"] < 0 else 0)
    )

    return features
```

---

## 2. Enflasyon

### BIST üzerindeki etki:
```
Yüksek enflasyon → Nominal kârlar şişer → BIST yükselebilir
                 → Ama reel getiri düşer
                 → TMS 29 muhasebe zorunluluğu
Düşük enflasyon → Reel getiri artar → BIST uzun vadede yükselir
```

### Türkiye'ye özgü:
```
- TÜFE: Tüketici fiyat endeksi
- ÜFE: Üretici fiyat endeksi (öncü gösterge)
- Çekirdek enflasyon: Gıda ve enerji hariç
- Enflasyon beklentisi: TCMB anketi
```

### Örnek: Enflasyon feature'ları

```python
# services/macro/inflation.py
def compute_inflation_features(inflation_data):
    features = {}
    
    # Enflasyon seviyesi
    features["cpi_yoy"] = inflation_data["cpi_yoy"]
    features["ppi_yoy"] = inflation_data["ppi_yoy"]
    features["core_cpi"] = inflation_data["core_cpi"]
    
    # Enflasyon trendi
    features["cpi_trend"] = inflation_data["cpi_yoy"].rolling(3).mean()
    features["cpi_momentum"] = inflation_data["cpi_yoy"].diff(3)
    
    # PPI-CPI farkı (maliyet baskısı)
    features["ppi_cpi_spread"] = inflation_data["ppi_yoy"] - inflation_data["cpi_yoy"]
    
    # Enflasyon beklentisi
    features["inflation_expectation"] = inflation_data["expectation_survey"]
    features["inflation_surprise"] = inflation_data["cpi_yoy"] - inflation_data["expectation_survey"]
    
    # BIST reel getiri
    features["bist_real_return"] = inflation_data["bist_return"] - inflation_data["cpi_yoy"]
    
    return features
```

---

## 3. USDTRY Döviz Kuru

### BIST üzerindeki etki:
```
USDTRY artışı (TL zayıflama) → İhracatçılar kazanır (THY, TUPRS)
                              → İthalatçılar kaybeder
                              → Genel BIST baskısı (kur riski)
USDTRY düşüşü (TL güçlenme) → İthalatçılar kazanır
                              → İhracatçılar kaybeder
                              → BIST genel yükseliş
```

### Sektör bazlı etki:
```
Pozitif korelasyon: Bankacılık (döviz pozisyonu)
Negatif korelasyon: İhracatçı (THY, TUPRS, EREGL)
Nötr: İçe dönük şirketler (perakende, gıda)
```

### Örnek: USDTRY feature'ları

```python
# services/macro/fx.py
def compute_fx_features(fx_data, stock_data):
    features = {}

    # Kur seviyesi
    features["usdtry"] = fx_data["usdtry"]
    features["usdtry_change_1d"] = fx_data["usdtry"].pct_change(1)
    features["usdtry_change_5d"] = fx_data["usdtry"].pct_change(5)
    features["usdtry_change_20d"] = fx_data["usdtry"].pct_change(20)

    # Kur volatilitesi
    features["usdtry_volatility"] = fx_data["usdtry"].pct_change().rolling(20).std() * (252**0.5)

    # BIST ile korelasyon
    features["usdtry_bist_corr"] = fx_data["usdtry"].pct_change().rolling(60).corr(stock_data["bist100"].pct_change())

    # Sepet kur (EURTRY + USDTRY)
    features["basket_rate"] = (fx_data["eurtry"] + fx_data["usdtry"]) / 2

    return features
```

---

## 4. CDS Spread (Ülke Risk Primi)

### BIST üzerindeki etki:
```
CDS artışı → Ülke riski artar → Yabancı yatırımcı çıkış → BIST düşüş
CDS düşüşü → Ülke riski azalır → Yabancı giriş → BIST yükseliş
```

### Örnek: CDS feature'ları

```python
# services/macro/cds.py
def compute_cds_features(cds_data):
    features = {}
    
    # CDS seviyesi
    features["cds_5y"] = cds_data["cds_5y"]
    features["cds_change_5d"] = cds_data["cds_5y"].pct_change(5)
    features["cds_change_20d"] = cds_data["cds_5y"].pct_change(20)
    
    # CDS volatilitesi
    features["cds_volatility"] = cds_data["cds_5y"].pct_change().rolling(20).std()
    
    # Risk seviyesi
    if cds_data["cds_5y"] > 400:
        features["risk_level"] = 3  # Yüksek risk
    elif cds_data["cds_5y"] > 250:
        features["risk_level"] = 2  # Orta risk
    else:
        features["risk_level"] = 1  # Düşük risk
    
    return features
```

---

## 5. Kredi Büyümesi

### BIST üzerindeki etki:
```
Kredi artışı → Ekonomik büyüme → BIST yükseliş
Kredi daralması → Ekonomik yavaşlama → BIST düşüş
Aşırı kredi büyümesi → Balon riski → Gelecek düzeltme
```

### Örnek: Kredi feature'ları

```python
# services/macro/credit.py
def compute_credit_features(credit_data):
    features = {}
    
    # Kredi büyüme hızı
    features["credit_growth_yoy"] = credit_data["credit_growth_yoy"]
    features["credit_growth_mom"] = credit_data["credit_growth_mom"]
    
    # Kredi/GSYH oranı
    features["credit_gdp_ratio"] = credit_data["total_credit"] / credit_data["gdp"]
    features["credit_gdp_change"] = features["credit_gdp_ratio"].diff()
    
    # Tüketici kredisi trendi
    features["consumer_credit_growth"] = credit_data["consumer_credit_growth"]
    
    # Ticari kredi trendi
    features["commercial_credit_growth"] = credit_data["commercial_credit_growth"]
    
    return features
```

---

## 6. Cari Açık

### BIST üzerindeki etki:
```
Cari açık artışı → Döviz ihtiyacı → USDTRY baskısı → BIST baskısı
Cari açık azalması → Döviz dengesi → TL desteği → BIST desteği
```

### Örnek: Cari açık feature'ları

```python
# services/macro/current_account.py
def compute_ca_features(ca_data):
    features = {}
    
    # Cari denge
    features["current_account_balance"] = ca_data["balance"]
    features["current_account_gdp"] = ca_data["balance"] / ca_data["gdp"] * 100
    
    # Trend
    features["ca_trend"] = ca_data["balance"].rolling(12).mean()
    features["ca_improving"] = 1 if ca_data["balance"].diff(3) > 0 else 0
    
    return features
```

---

## 7. BIST-Specific Makro Etki Matrisi

| Makro Gösterge | BIST Genel | Bankacılık | İhracatçı | İthalatçı |
|----------------|------------|------------|-----------|-----------|
| Faiz artışı | Kısa: -, Uzun: + | - | + | - |
| Enflasyon artışı | + (nominal) | + | + | - |
| USDTRY artışı | - | - | + | - |
| CDS artışı | - | - | 0 | - |
| Kredi büyümesi | + | + | + | + |
| Cari açık azalması | + | + | - | + |

---

## 8. Makro Takvim

### Kritik tarihler:
```
TCMB PPK toplantısı: Ayda bir (faiz kararı)
TÜFE açıklaması: Her ayın 3. günü
Cari açık: Her ayın 12. günü
İşsizlik: Her ayın 15. günü
GSYH: Çeyreklik
```

### Örnek: Makro takvim kontrolü

```python
# services/macro/calendar.py
def get_macro_events(date):
    events = []

    # TCMB PPK
    if is_ppk_meeting_day(date):
        events.append({"type": "TCMB_PPK", "importance": "HIGH", "expected_impact": "FX + BIST", "time": "14:00"})

    # TÜFE
    if is_cpi_release_day(date):
        events.append(
            {"type": "CPI_RELEASE", "importance": "HIGH", "expected_impact": "BIST + FX + Bonds", "time": "10:00"}
        )

    return events
```

---

## Çıktı

```
TCMB Rate:            42.5%
Real Rate:            +8.5%
CPI YoY:              34.0%
USDTRY:               47.88
CDS 5Y:               285
Credit Growth:        +15.2%
Current Account:      -$3.2B
Macro Risk Level:     MEDIUM
```

---

## Temel prensip

Türkiye'nin makro dinamikleri gelişmiş piyasalardan farklıdır. **Yüksek enflasyon, kur volatilitesi, CDS spread ve TCMB kararları BIST'i doğrudan etkiler.** Bu göstergeleri takip etmeyen sistem eksik kalır.

> Kaynak: SBB Medium Term Program (2026-2028), ResearchGate (2023) Exchange Rate and Inflation
