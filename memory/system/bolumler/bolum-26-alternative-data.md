# Bölüm 26 — Alternative Data

## Amaç

Geleneksel finansal verilerin ötesinde, piyasayı daha erken ve daha doğru tahmin etmek için alternatif veri kaynaklarını kullanmak.

**Kaynak:** ReadySignal (2026) Alt Data Market $30B, Grand View Research (2026) Alternative Data Market, Mordor Intelligence (2026) $17.78B Market.

---

## Kullanılacak sistemler

- Alternative Data Collector
- Web Scraper
- Satellite Data Processor
- Credit Card Data Processor
- Social Media Analyzer
- App Usage Tracker
- Job Posting Analyzer
- Patent/Innovation Tracker

---

## Çalışma mantığı

```
Alternative Data Sources → Veri Toplama → Temizleme → Feature Extraction →
Geleneksel verilerle birleştirme → Model input → Tahmin
```

---

## 1. Alternative Data Türleri

**Araştırma bulgusu:** Mordor Intelligence (2026) — "The Alternative Data Market worth $17.78 billion in 2026, growing at a CAGR of 51.91%."

### Kategoriler:
```
1. Credit/Debit Card Transactions → %17.6 pazar payı (en büyük)
2. Web Scraping → Fiyat, ürün, stok verileri
3. Satellite Imagery → Fabrika trafiği, tarım, enerji
4. Social Media → Sentiment, trend, viral konular
5. App Usage → Şirket popülerliği, kullanıcı trendi
6. Job Postings → Büyüme sinyali, işe alım trendi
7. Patent Filings → İnovasyon, gelecek büyüme
8. Shipping/Logistics → Ticaret akışı
9. Sensor Data → IoT, enerji tüketimi
```

---

## 2. Credit Card Data

**Araştırma bulgusu:** Grand View Research (2026) — "Credit & debit card transactions segment led the market with largest revenue share of 17.60% in 2025."

### Ne sağlar?
```
- Gerçek zamanlı satış verileri (çeyreklik raporlardan önce)
- Tüketici trendleri
- Şirket performansı tahmini
- Sektör karşılaştırması
```

### BIST için uygulanabilirlik:
```
- Türk bankalarının kredi kartı verileri (anonymized)
- E-ticaret platformlarının satış verileri
- Market/mağaza trafiği
```

### Örnek: Credit card feature

```python
# services/alternative/credit_card.py
def compute_cc_features(cc_data, ticker):
    features = {}

    # Aylık harcama trendi
    features["cc_spend_growth"] = cc_data[ticker]["spend_growth_mom"]
    features["cc_spend_growth_yoy"] = cc_data[ticker]["spend_growth_yoy"]

    # Sektör karşılaştırması
    features["cc_vs_sector"] = cc_data[ticker]["spend_growth"] - cc_data[cc_data[ticker]["sector"]]["avg_spend_growth"]

    # Mevsimsellik
    features["cc_seasonal_deviation"] = (
        cc_data[ticker]["spend"] - cc_data[ticker]["spend_3y_avg_same_month"]
    ) / cc_data[ticker]["spend_3y_avg_same_month"]

    return features
```

---

## 3. Web Scraping

### Ne sağlar?
```
- Fiyat takibi (e-ticaret, emlak)
- Ürün bulunabilirliği
- İnceleme/rating trendleri
- İş ilanı sayıları
```

### BIST şirketleri için:
```
- Trendyol: Satış verileri, ürün sayısı
- Hepsiburada: GMV, satıcı sayısı
- Getir/Yemeksepi: Sipariş hacmi
- Sahibinden: Emlak fiyatları, ilan sayısı
- Kariyer.net: İş ilanı trendleri
```

### Örnek: Web scraping feature

```python
# services/alternative/web_scraping.py
def compute_web_features(scraped_data, ticker):
    features = {}
    
    # İş ilanı trendi (büyüme sinyali)
    features["job_posting_growth"] = scraped_data[ticker]["job_growth_30d"]
    features["job_posting_count"] = scraped_data[ticker]["job_count"]
    
    # Ürün/rating trendi
    features["review_count_growth"] = scraped_data[ticker]["review_growth_30d"]
    features["avg_rating_change"] = scraped_data[ticker]["rating_change_30d"]
    
    # Fiyat trendi
    features["price_vs_competitors"] = scraped_data[ticker]["price_index"]
    
    return features
```

---

## 4. Satellite Imagery

### Ne sağlar?
```
- Fabrika trafiği (araç sayısı → üretim hacmi)
- Tarım verimi (mahsul tahmini)
- Enerji tüketimi (endüstriyel aktivite)
- Liman trafiği (ticaret hacmi)
- Perakende mağaza trafiği
```

### BIST için uygulanabilirlik:
```
- Tüpraş: Rafineri trafiği
- Ereğli Demir: Fabrika aktivitesi
- THY: Havalimanı trafiği
- Migros/BIM: Mağaza otopark doluluğu
- Tofaş/Ford Otosan: Fabrika trafiği
```

### Örnek: Satellite feature

```python
# services/alternative/satellite.py
def compute_satellite_features(sat_data, ticker):
    features = {}

    # Fabrika trafiği
    features["factory_traffic_change"] = sat_data[ticker]["vehicle_count_change"]
    features["factory_traffic_vs_baseline"] = (
        sat_data[ticker]["vehicle_count"] / sat_data[ticker]["vehicle_count_1y_avg"]
    )

    # Mağaza trafiği (perakende)
    if sat_data[ticker].get("store_parking"):
        features["store_traffic_change"] = sat_data[ticker]["parking_fill_change"]

    return features
```

---

## 5. Social Media Sentiment

### Ne sağlar?
```
- Halk sentiment'i
- Viral trendler
- Erken uyarı sinyalleri
- Manipülasyon tespiti
```

### BIST için kaynaklar:
```
- Twitter/X: $THYAO, $ASELS hashtag'leri
- Ekşi Sözlük: Şirket entry'leri
- Reddit: r/Yatirim
- Telegram: Yatırım grupları
```

### Örnek: Social sentiment feature

```python
# services/alternative/social.py
def compute_social_features(social_data, ticker):
    features = {}
    
    # Sentiment skoru
    features["social_sentiment"] = social_data[ticker]["sentiment_score"]
    features["social_sentiment_change"] = social_data[ticker]["sentiment_change_7d"]
    
    # Mention hacmi
    features["social_volume"] = social_data[ticker]["mention_count"]
    features["social_volume_zscore"] = social_data[ticker]["volume_zscore"]
    
    # Viral sinyal
    features["social_viral"] = 1 if social_data[ticker]["volume_zscore"] > 3 else 0
    
    return features
```

---

## 6. App Usage Data

### Ne sağlar?
```
- Kullanıcı büyüme trendi
- Engagement metrikleri
- Churn rate tahmini
- Yeni kullanıcı akışı
```

### BIST şirketleri için:
```
- Trendyol: İndirme, aktif kullanıcı
- Getir: Sipariş hacmi
- Hepsiburada: GMV trendi
- Papara/İninal: Kullanıcı sayısı
```

---

## 7. Job Posting Data

### Ne sağlar?
```
- Büyüme sinyali (işe alım = büyüme planı)
- Azaltma sinyali (işten çıkarma = küçülme)
- Teknoloji yatırımı (yeni pozisyonlar)
- Bölgesel genişleme
```

### Örnek: Job posting feature

```python
# services/alternative/jobs.py
def compute_job_features(job_data, ticker):
    features = {}
    
    # İş ilanı trendi
    features["job_posting_growth"] = job_data[ticker]["growth_30d"]
    features["job_posting_growth_90d"] = job_data[ticker]["growth_90d"]
    
    # Pozisyon türü dağılımı
    features["tech_hiring_pct"] = job_data[ticker]["tech_positions_pct"]
    features["sales_hiring_pct"] = job_data[ticker]["sales_positions_pct"]
    
    # İşten çıkarma sinyali
    features["layoff_signal"] = 1 if job_data[ticker].get("layoff_news") else 0
    
    return features
```

---

## 8. BIST için Erişilebilir Alternative Data

| Veri Türü | Kaynak | Erişim | Maliyet |
|-----------|--------|--------|---------|
| Credit Card | Türk bankaları | API | Yüksek |
| Web Scraping | Kendi scraper | Scrape | Düşük |
| Satellite | Planet, Maxar | API | Çok yüksek |
| Social | Twitter API | API | Orta |
| App Data | SimilarWeb | API | Orta |
| Job Postings | Kariyer.net | Scrape | Düşük |
| Shipping | AIS data | API | Yüksek |

### BIST için önerilen:
```
1. Web Scraping (düşük maliyet, yüksek değer)
2. Social Media Sentiment (orta maliyet, orta değer)
3. Job Postings (düşük maliyet, yüksek değer)
4. Credit Card (yüksek maliyet, yüksek değer — eğer erişilebilirse)
```

---

## Çıktı

```
Alternative Data Sources:  7
BIST-applicable:           5
Recommended for MVP:       3 (Web, Social, Jobs)
Estimated Alpha:           +2-5% annual
Data Latency:              1-7 days
Cost:                      Low-Medium
```

---

## Temel prensip

> "Alternative data used to mean niche datasets used by hedge funds. Now it's mainstream." — ReadySignal (2026)

BIST'te alternative data henüz yaygın değil. **Bu, erken kullananlar için avantaj sağlar.** En düşük maliyetle en yüksek değer: web scraping + job postings + social sentiment.

> Kaynak: ReadySignal (2026), Grand View Research (2026), Mordor Intelligence (2026)
