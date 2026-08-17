# Alternative Data Nihai Sistem Dokümanı — Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Papers With Backtest (2025), Grand View Research (2026), IMARC Group (2026), Precedence Research (2026), Bright Data (2026), ReadySignal (2026)

---

## 1. Pazar Büyüklüğü ve Önemi

- **2025 pazar büyüklüğü:** $8.2 milyar (Grand View Research)
- **2034 tahmin:** $854.34 milyar (Precedence Research)
- **Hedge fund kullanımı:** %85'i en az 2 alternatif veri seti kullanıyor
- **Quant fund katkısı:** %30'u performansın %20+'sının alternatif veriden geldiğini söylüyor
- **Yatırım profesyoneli kullanımı:** %67 (2022'de %31'di)

**En büyük segment:** Kredi/banka kartı işlemleri (%17.60 pazar payı, 2025)

---

## 2. Alternatif Veri Taksonomisi (Araştırma Bazlı)

### 2.1 Coğrafi Konum Verisi (Foot Traffic)

**Ne:** Smartphone tabanlı mağaza ziyaret sayıları
**Kullanım:** Perakende satış tahmini, bölgesel aktivite trendleri
**Alpha:** Mağaza trafiği artışı → satış artışı → hisse fiyatı artışı
**Türkiye:** Google Maps popülerlik, AVM ziyaretçi verisi

**Provider'lar (Global):**
- SafeGraph (ABD)
- Placer.ai (ABD)
- Advan (global)
- Unacast (ABD/AB)

**Türkiye Provider'ları:**
- Google Maps API (ücretsiz, popülerlik verisi)
- AVM yönetimleri (kapalı veri)
- GSM operatörleri (Turkcell, Vodafone — anonim konum verisi)

### 2.2 Tüketici İşlemleri (Credit Card)

**Ne:** Anonim kredi/banka kartı harcama verileri
**Kullanım:** Şirket gelir tahmini, pazar payı değişimi, tüketici trendi
**Alpha:** Gerçek harcama verisi → çeyreklik gelir tahmini → erken bilgi avantajı
**Türkiye:** BKM (Bankalararası Kart Merkezi) — aylık harcama verisi

**Provider'lar (Global):**
- 1010data (ABD)
- Earnest Analytics (ABD)
- Second Measure (ABD)
- Fable Data (AB)

**Türkiye Provider'ları:**
- **BKM** — Aylık toplam harcama, işlem sayısı, sektörel dağılım
- **TCMB** — Nakit kullanımı, elektronik ödeme istatistikleri
- **Bankalar** — Kapalı veri (garanti, İş Bankası vb.)

### 2.3 Uydu Görüntüsü ve Uzaktan Algılama

**Ne:** Uydu görüntüleriyle fiziksel varlık izleme
**Kullanım:** Otopark doluluk, petrol depolama, tarım ürünleri, inşaat ilerleme
**Alpha:** Fiziksel aktivite → şirket performansı → erken tahmin
**Türkiye:** Sanayi bölgeleri, limanlar, AVM otoparkları

**Provider'lar (Global):**
- Orbital Insight (ABD/global)
- RS Metrics (ABD)
- SpaceKnow (AB)
- Kayrros (AB)

**Türkiye Provider'ları:**
- **Sentinel-2** (Copernicus — ücretsiz)
- **Google Earth Engine** (ücretsiz)
- **Planet Labs** (ücretli, yüksek çözünürlük)

### 2.4 Web Verisi (Job Postings, Fiyatlar, Ürün Yorumları)

**Ne:** Web scraping ile şirket verisi toplama
**Kullanım:** İş ilanları → şirket büyümesi, fiyat takibi → rekabet analizi
**Alpha:** İş ilanı artışı → şirket büyüme sinyali → hisse artışı
**Türkiye:** Kariyer.net, LinkedIn, Trendyol, Hepsiburada

**Provider'lar (Global):**
- Thinknum (ABD/global)
- LinkUp (global)
- Revelio Labs (global)
- Diffbot (global)

**Türkiye Provider'ları:**
- **Kariyer.net** — İş ilanları (web scraping)
- **LinkedIn** — Hiring trends (API)
- **Trendyol** — Satış sıralaması (web scraping)
- **Hepsiburada** — Satış verisi (web scraping)
- **n11** — E-ticaret verisi (web scraping)

### 2.5 Sosyal Medya ve Sentiment (ESG dahil)

**Ne:** Sosyal medya, haber, forum sentiment analizi
**Kullanım:** Gerçek zamanlı piyasa duyarlılığı, ESG tartışmaları
**Alpha:** Sentiment değişimi → fiyat hareketi → erken sinyal
**Türkiye:** Ekşi Sözlük, X/Twitter, Reddit r/yatirim

**Provider'lar (Global):**
- RavenPack (global)
- RepRisk (global)
- FactSet Truvalue (ABD/global)
- Social Market Analytics (ABD)

**Türkiye Provider'ları:**
- **X/Twitter API** — Türkçe finansal tweet'ler
- **Ekşi Sözlük** — Web scraping (şirket başlıkları)
- **Investing.com TR** — Hisse yorumları (web scraping)
- **Borsa İstanbul Forum** — Web scraping

### 2.6 Mobil Uygulama Kullanımı

**Ne:** App indirme, kullanım, engagement verisi
**Kullanım:** Dijital şirket büyüme tahmini (fintech, streaming, e-ticaret)
**Alpha:** App engagement artışı → kullanıcı büyümesi → gelir artışı
**Türkiye:** Trendyol, Hepsiburada, Getir, Papara

**Provider'lar (Global):**
- Data.ai (AppAnnie) (global)
- Sensor Tower (global)
- Apptopia (global)

**Türkiye Provider'ları:**
- **Google Play API** — İndirme sayısı, rating
- **App Store API** — Sıralama, yorumlar

### 2.7 Web Trafiği ve Arama Trendleri

**Ne:** Website ziyaretçi verisi, Google arama trendleri
**Kullanım:** E-ticaret satış tahmini, marka ilgisi
**Alpha:** Web trafiği artışı → satış artışı → hisse artışı
**Türkiye:** SimilarWeb, Google Trends

**Provider'lar (Global):**
- SimilarWeb (global)
- SEMrush (global)
- Google Trends (ücretsiz)

**Türkiye Provider'ları:**
- **Google Trends** — Türkçe arama trendleri (ücretsiz API)
- **SimilarWeb** — Web trafiği (ücretli API)

### 2.8 Tedarik Zinciri ve Lojistik

**Ne:** Gemi trafiği, konteyner verisi, gümrük verisi
**Kullanım:** İthalat/ihracat tahmini, emtia akışı
**Alpha:** Liman aktivitesi → ticaret hacmi → ekonomik aktivite
**Türkiye:** Mersin, İzmir, İstanbul limanları

**Provider'lar (Global):**
- MarineTraffic (global)
- IHS Markit (global)
- Panjiva (ABD)

**Türkiye Provider'ları:**
- **MarineTraffic** — Gemi takibi (API)
- **TUIK** — İthalat/ihracat verisi (ücretsiz)

---

## 3. Feature Haritası (Araştırma Bazlı)

### 3.1 Tüketici İşlemleri Features (BKM)

```python
cc_total_spend_growth       # Toplam harcama büyüme oranı
cc_transaction_count_change  # İşlem sayısı değişimi
cc_avg_transaction_size      # Ortalama işlem tutarı
cc_sector_allocation         # Sektörel harcama dağılımı
cc_online_vs_offline         # Online/mağaza oranı
cc_foreign_card_ratio        # Yabancı kart harcaması
cc_seasonal_deviation        # Mevsimsel sapma
cc_momentum_3m               # 3 aylık harcama momentumu
```

### 3.2 Coğrafi Konum Features

```python
foot_traffic_change          # Mağaza ziyaret değişim oranı
foot_traffic_vs_sector       # Sektöre göre ziyaret
foot_traffic_seasonal        # Mevsimsel normalize ziyaret
foot_traffic_momentum        # Ziyaret momentumu
store_density_change         # Mağaza yoğunluğu değişimi
```

### 3.3 Uydu Features

```python
parking_occupancy            # Otopark doluluk oranı
factory_activity_index       # Fabrika aktivite indeksi
port_vessel_count            # Liman gemi sayısı
construction_progress        # İnşaat ilerleme
crop_health_index            # Tarım ürün sağlığı
oil_storage_level            # Petrol depolama seviyesi
```

### 3.4 Web/İş İlanı Features

```python
job_posting_count            # Açık iş ilanı sayısı
job_posting_growth_30d       # 30 günlük büyüme
tech_hiring_ratio            # Teknik iş ilanı oranı
management_hiring_ratio      # Yönetim iş ilanı oranı
layoff_signal                # İşten çıkarma sinyali
salary_range_change          # Maaş aralığı değişimi
remote_work_ratio            # Uzaktan çalışma oranı
web_traffic_monthly          # Aylık web trafiği
web_traffic_growth           # Trafik büyüme oranı
app_ranking_change           # App sıralama değişimi
```

### 3.5 Sosyal Medya Features

```python
social_sentiment_score       # Sentiment skoru (-1 ile +1)
social_volume_24h            # Son 24 saat hacim
social_volume_change         # Hacim değişimi
social_engagement_avg        # Ortalama engagement
social_manipulation_score    # Manipülasyon risk skoru
social_viral_score           # Viral olma skoru
social_platform_breakdown    # Platform bazlı dağılım
```

### 3.6 Arama Trendi Features

```python
google_trends_score          # Google arama trendi (0-100)
google_trends_momentum       # Trend momentumu
search_brand_interest        # Marka ilgi skoru
search_category_interest     # Kategori ilgi skoru
search_related_queries       # İlişkili aramalar
```

---

## 4. Veri Toplama Mimarisi (Araştırma Bazlı)

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                              │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Consumer │ Geoloc.  │ Satellite│ Web/Job  │ Social/Search   │
│ BKM      │ Google   │ Sentinel │ Kariyer  │ X/Twitter       │
│ TCMB     │ Maps     │ Planet   │ LinkedIn │ Ekşi            │
│ Bankalar │ AVM      │ GEE      │ Trendyol │ Google Trends   │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴─────┬───────────┘
     │          │          │          │           │
     └──────────┴──────────┴──────────┴───────────┘
                         │
                    ┌────┴────┐
                    │COLLECTOR│  Her kaynak için adapter
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │VALIDATOR│  Veri doğrulama
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ENRICHER │  Zenginleştirme
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │  STORE  │  Feature store
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │FEATURES │  Feature hesaplama
                    └─────────┘
```

---

## 5. Türkiye'ye Özgü Kaynaklar

### 5.1 Ücretsiz Kaynaklar

| Kaynak | Veri | API | Güvenilirlik |
|--------|------|-----|-------------|
| **BKM** | Kredi kartı harcama | Rapor | Yüksek |
| **TCMB** | Faiz, enflasyon, döviz | EVDS API | Yüksek |
| **TÜİK** | İstihdam, GSYH, ÜFE | API | Yüksek |
| **Google Trends** | Arama trendleri | API | Yüksek |
| **KAP** | Şirket bildirimleri | API | En yüksek |
| **BIST** | İşlem verisi | Web | Yüksek |
| **SPK** | Yatırımcı verisi | Web | Yüksek |

### 5.2 Ücretli/Kapalı Kaynaklar

| Kaynak | Veri | Erişim | Maliyet |
|--------|------|--------|---------|
| **SimilarWeb** | Web trafiği | API | $$$ |
| **LinkedIn** | Hiring trends | API | $$ |
| **Planet Labs** | Uydu görüntüleri | API | $$$$ |
| **Matriks** | Gerçek zamanlı piyasa | API | $$ |

### 5.3 Web Scraping Kaynakları

| Kaynak | Veri | Zorluk | Yasal Risk |
|--------|------|--------|-----------|
| **Kariyer.net** | İş ilanları | Orta | Düşük |
| **Ekşi Sözlük** | Sentiment | Orta | Düşük |
| **Trendyol** | Satış sıralaması | Yüksek | Orta |
| **Hepsiburada** | Satış verisi | Yüksek | Orta |
| **Investing.com TR** | Hisse yorumları | Orta | Düşük |

---

## 6. LLM Entegrasyonu (Tek Model — Ollama)

### Neden Tek Model?

Local sınırlı olduğu için tek model kullanıyoruz. Bu aslında avantaj:
- **Tutarlı çıktılar** — farklı modellerin çelişkisi yok
- **Düşük maliyet** — tek inference maliyeti
- **Basit altyapı** — tek model yönetimi

### LLM Kullanım Alanları

| Görev | Prompt Örneği | Çıktı |
|-------|---------------|-------|
| **Türkçe sentiment** | "Bu tweet'in sentimentini analiz et: {text}" | sentiment_score, confidence |
| **KAP analizi** | "Bu KAP açıklamasını analiz et: {disclosure}" | event_type, impact, direction |
| **Haber etki** | "Bu haberin BIST'e etkisi: {headline}" | impact_score, affected_sectors |
| **İş ilanı analizi** | "Bu iş ilanı şirket için ne anlama geliyor: {posting}" | growth_signal, department |
| **Manipülasyon tespiti** | "Bu sosyal medya aktivitesi manipülasyon mu: {activity}" | manipulation_score |

### Hallucination Koruması

```
LLM çıktısı → JSON parse → Range validation → Source check → Accept/Reject

Örnek:
- confidence = 4.8 → REJECT (0-1 arası olmalı)
- price = -500 → REJECT (negatif olamaz)
- source = "uydurulan haber" → REJECT (kaynak doğrulanamadı)
```

---

## 7. Entegrasyon Planı

### Faz 1: Ücretsiz Kaynaklar (Hemen)
1. BKM API — kredi kartı harcama
2. Google Trends API — arama trendleri
3. KAP API — şirket bildirimleri
4. TCMB EVDS API — makro veriler

### Faz 2: Web Scraping (1-2 hafta)
1. Kariyer.net scraper — iş ilanları
2. Ekşi Sözlük scraper — sentiment
3. X/Twitter API — sosyal medya

### Faz 3: Ücretli Kaynaklar (Ay)
1. SimilarWeb — web trafiği
2. LinkedIn API — hiring trends

### Faz 4: Uydu (Opsiyonel)
1. Sentinel-2 — fabrika aktivite
2. Google Earth Engine — otopark doluluk

---

## 8. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Veri kaynakları | 5 (data dictionary) | 27+ (gerçek bağlantı) |
| Feature sayısı | 20 (basit) | 60+ (araştırma bazlı) |
| BKM entegrasyonu | ❌ | ✅ |
| Google Trends | ❌ | ✅ |
| Kariyer.net scraper | ❌ | ✅ |
| Ekşi Sözlük scraper | ❌ | ✅ |
| Uydu verisi | ❌ | ✅ |
| LLM sentiment | ❌ | ✅ (Ollama) |
| Manipülasyon tespiti | ⚠️ Basit | ✅ LLM destekli |
| Feature store entegrasyonu | ❌ | ✅ |
| Cross-source reconciliation | ❌ | ✅ |
