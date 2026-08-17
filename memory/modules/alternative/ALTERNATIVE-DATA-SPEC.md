# Alternative Data Sistem Dokümanı — Türkiye Kaynakları

**Tarih:** 2026-08-18
**Not:** Tek model LLM kullanıyoruz (Ollama, local sınırlı)

---

## 1. Mevcut Durum

### Mevcut Modüller (5)
```
services/alternative/
├── web_scraping.py    ← Web scraping features (5 feature)
├── social.py          ← Sosyal medya features (5 feature)
├── jobs.py            ← İş ilanı features (4 feature)
├── credit_card.py     ← Kredi kartı features (3 feature)
└── satellite.py       ← Uydu verisi features (3 feature)
```

### Mevcut Entegrasyon
- `services/features/sentiment.py` → social entegrasyonu var
- `services/ingestion/providers/social_provider.py` → X/Twitter provider var
- `services/ingestion/providers/news_provider.py` → RSS haber var

### Eksikler
- Gerçek veri kaynaklarına bağlantı yok (sadece data dictionary)
- Türkiye'ye özgü kaynaklar tanımlanmamış (Ekşi, Kariyer.net, BKM)
- Otomatik veri çekme yok
- Veri doğrulama/zenginleştirme yok
- Feature store entegrasyonu yok

---

## 2. Türkiye Alternatif Veri Kaynakları

### 2.1 Sosyal Medya ve Forum

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **X/Twitter** | Sentiment, volume | API v2 | Hisse bazlı hashtag, $ticker |
| **Ekşi Sözlük** | Sentiment, gündem | Web scraping | Şirket başlıkları, borsa entry'leri |
| **Reddit r/yatirim** | Sentiment | API | Türkçe yatırım tartışmaları |
| **Investing.com TR** | Sentiment, yorum | Web scraping | Hisse yorum sayfaları |
| **Borsa İstanbul Forum** | Sentiment | Web scraping | Hisse tartışmaları |
| **Telegram grupları** | Sentiment, sinyal | MTProto API | BIST trading grupları |

### 2.2 İş İlanları

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **Kariyer.net** | İş ilanı sayısı, departman | Web scraping / API | Şirket büyüme göstergesi |
| **LinkedIn** | Hiring trends, company growth | API | Şirket işe alım hızı |
| **Eleman.net** | İş ilanı | Web scraping | Sektör bazlı istihdam |
| **Secretcv** | İş ilanı | Web scraping | Şirket bazlı hiring |

### 2.3 E-Ticaret ve Tüketici

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **Trendyol** | Satış sıralaması, fiyat | Web scraping / API | Perakende şirketleri |
| **Hepsiburada** | Satış sıralaması | Web scraping | Perakende şirketleri |
| **n11** | Satış verisi | Web scraping | E-ticaret şirketleri |
| **Amazon TR** | Satış sıralaması | Web scraping |Uluslararası şirketler |
| **App Store / Google Play** | App sıralaması | API / scraping | Dijital şirketler |

### 2.4 Finansal Veri Sağlayıcıları

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **BKM (Bankalararası Kart Merkezi)** | Kredi kartı harcama | API / rapor | Tüketici harcama trendi |
| **TCMB** | Faiz, enflasyon, döviz | EVDS API | Makro etki |
| **TÜİK** | İstihdam, GSYH, ÜFE | API | Makro göstergeler |
| **SPK** | Yatırımcı sayısı, açığa satış | Web | Piyasa duyarlılığı |
| **BIST** | İşlem hacmi, yatırımcı | Web | Piyasa verisi |
| **KAP** | Şirket bildirimleri | API | Olay bazlı analiz |

### 2.5 Web ve Dijital

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **SimilarWeb** | Web trafiği | API | Dijital şirketler |
| **Google Trends** | Arama trendleri | API | Marka bilinirliği |
| **SEMrush** | SEO, anahtar kelime | API | Dijital performans |
| **Social Blade** | Sosyal medya istatistikleri | API | Influencer/marka takibi |

### 2.6 Uydu ve Coğrafi

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **Sentinel-2** | Fabrika trafiği, depo | API (Copernicus) | Sanayi şirketleri |
| **Google Earth Engine** | Araç yoğunluğu | API | Otopark, liman trafiği |
| **Planet Labs** | Yüksek çözünürlük | API | Perakende mağaza trafiği |

### 2.7 Haber ve Medya

| Kaynak | Tür | Erişim | BIST İlişkisi |
|--------|-----|--------|----------------|
| **KAP** | Resmi bildirimler | API | En kritik kaynak |
| **Anadolu Ajansı** | Haber | RSS | Makro/şirket haberleri |
| **Bloomberg HT** | Finansal haber | RSS/Web | Piyasa yorumları |
| **Dünya Gazetesi** | Ekonomi haber | RSS | Sektör analizleri |
| **ParaAnaliz** | Analiz | Web | Hisse analizleri |
| **Finans Gündem** | Haber | RSS | BIST haberleri |

---

## 3. Feature Haritası

### 3.1 Sosyal Medya Features

```python
# Her ticker için:
social_sentiment          # -1 ile +1 arası sentiment skoru
social_volume_24h         # Son 24 saatteki mention sayısı
social_volume_change      # Hacim değişimi (%)
social_engagement_avg     # Ortalama engagement
social_viral_score        # Viral olma skoru
social_manipulation_score # Manipülasyon risk skoru
social_positive_ratio     # Pozitif/negatif oran
social_platform_breakdown # Platform bazlı dağılım
social_top_topics         # En çok konuşulan konular
social_influencer_sentiment # Etkileyici hesap sentimenti
```

### 3.2 İş İlanı Features

```python
# Her şirket için:
job_posting_count         # Açık iş ilanı sayısı
job_posting_change_30d    # 30 günlük değişim
job_posting_change_90d    # 90 günlük değişim
tech_hiring_ratio         # Teknik iş ilanı oranı
management_hiring_ratio   # Yönetim iş ilanı oranı
layoff_signal             # İşten çıkarma sinyali
avg_salary_range          # Ortalama maaş aralığı
department_growth         # Departman bazlı büyüme
remote_ratio              # Uzaktan çalışma oranı
```

### 3.3 Kredi Kartı Features (BKM)

```python
# Sektör/şirket bazlı:
cc_spend_growth           # Harcama büyüme oranı
cc_spend_vs_sector        # Sektöre göre harcama
cc_transaction_count      # İşlem sayısı
cc_avg_transaction        # Ortalama işlem tutarı
cc_seasonal_deviation     # Mevsimsel sapma
cc_online_ratio           # Online harcama oranı
cc_foreign_ratio          # Yabancı kart harcaması
```

### 3.4 Web Trafik Features

```python
# Her şirket için:
web_traffic_monthly       # Aylık ziyaretçi
web_traffic_change        # Trafik değişim oranı
web_bounce_rate           # Hemen çıkma oranı
web_avg_session_duration  # Ortalama oturum süresi
web_traffic_source        # Trafik kaynağı dağılımı
web_mobile_ratio          # Mobil trafik oranı
web_search_organic_ratio  # Organik arama oranı
app_ranking_change        # App store sıralama değişimi
```

### 3.5 Uydu Features

```python
# Her şirket/lokasyon için:
factory_activity_index    # Fabrika aktivite indeksi
parking_occupancy         # Otopark doluluk oranı
store_traffic             # Mağaza trafik indeksi
port_activity             # Liman aktivite indeksi
construction_progress     # İnşaat ilerleme
```

### 3.6 Arama Trendi Features

```python
# Her ticker/şirket için:
google_trends_score       # Google arama trendi (0-100)
google_trends_change      # Trend değişim oranı
search_volume_relative    # Göreceli arama hacmi
related_queries           # İlişkili aramalar
brand_interest_score      # Marka ilgi skoru
```

---

## 4. Veri Toplama Mimarisi

```
┌─────────────────────────────────────────────────────────┐
│                    DATA SOURCES                          │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Social   │ Jobs     │ Finance  │ Web      │ Satellite   │
│ X,Ekşi   │ Kariyer  │ BKM,TCMB│ Similar  │ Sentinel    │
│ Reddit   │ LinkedIn │ TÜİK    │ Google   │ Planet      │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴─────┬───────┘
     │          │          │          │           │
     └──────────┴──────────┴──────────┴───────────┘
                         │
                    ┌────┴────┐
                    │ COLLECTOR│  ← Her kaynak için adapter
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ VALIDATOR│  ← Veri doğrulama
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ ENRICHER │  ← Zenginleştirme
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │  STORE   │  ← Feature store
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ FEATURES │  ← Feature hesaplama
                    └─────────┘
```

---

## 5. Uygulama Planı

### Faz 1: Gerçek Veri Bağlantıları
1. `BKMProvider` — BKM kredi kartı harcama verisi
2. `EkshiProvider` — Ekşi Sözlük sentiment
3. `KariyerProvider` — Kariyer.net iş ilanları
4. `GoogleTrendsProvider` — Google Trends verisi
5. `SimilarWebProvider` — Web trafik verisi

### Faz 2: Feature Hesaplama
1. Her kaynak için feature extraction pipeline
2. Feature store entegrasyonu
3. Cross-source reconciliation

### Faz 3: Entegrasyon
1. `features/sentiment.py` → sosyal medya features
2. `features/calculator.py` → alternatif veri features
3. `intelligence/main.py` → alternatif veri analizi

### Faz 4: LLM Entegrasyonu (Tek Model)
1. Ollama ile Türkçe sentiment analizi
2. KAP açıklaması yorumlama
3. Haber etki analizi
4. Sosyal medya manipülasyon tespiti

---

## 6. LLM Kullanımı (Tek Model — Ollama)

Local sınırlı olduğu için tek model kullanıyoruz:

```python
class AlternativeDataAnalyzer:
    """Tek LLM model ile alternatif veri analizi."""
    
    def __init__(self, llm_client):
        self.llm = llm_client  # Ollama
    
    async def analyze_social_sentiment(self, text: str) -> Dict:
        """Sosyal medya sentiment analizi."""
        prompt = f"Bu Türkçe finansal metni analiz et: {text}"
        # LLM → sentiment skoru
    
    async def analyze_job_posting(self, posting: str) -> Dict:
        """İş ilanı analizi."""
        prompt = f"Bu iş ilanını analiz et: {posting}"
        # LLM → şirket büyüme sinyali
    
    async def analyze_kap_disclosure(self, disclosure: str) -> Dict:
        """KAP açıklaması analizi."""
        prompt = f"Bu KAP açıklamasını analiz et: {disclosure}"
        # LLM → etki skoru
    
    async def analyze_news_impact(self, headline: str) -> Dict:
        """Haber etki analizi."""
        prompt = f"Bu haberin BIST'e etkisini analiz et: {headline}"
        # LLM → etki yönü ve büyüklüğü
```

### Tek Model Avantajları
- Düşük maliyet
- Tutarlı çıktılar
- Basit altyapı
- Hızlı inference

### Tek Model Dezavantajları
- Uzmanlaşma eksik
- Context window sınırlı
- Türkçe performansı değişken

---

## 7. Veri Kaynakları Öncelik Sırası

| Öncelik | Kaynak | Neden |
|---------|--------|-------|
| 🔴 Kritik | KAP | En güvenilir, resmi kaynak |
| 🔴 Kritik | BKM | Gerçek tüketici verisi |
| 🔴 Kritik | Google Trends | Ücretsiz, güvenilir |
| 🟡 Önemli | X/Twitter | Gerçek zamanlı sentiment |
| 🟡 Önemli | Kariyer.net | Şirket büyüme göstergesi |
| 🟡 Önemli | Ekşi Sözlük | Türk kamuoyu |
| 🟢 İsteğe bağlı | SimilarWeb | Ücretli, dijital şirketler |
| 🟢 İsteğe bağlı | Uydu verisi | Ücretli, sanayi şirketleri |
| 🟢 İsteğe bağlı | E-ticaret sıralaması | Perakende şirketleri |
