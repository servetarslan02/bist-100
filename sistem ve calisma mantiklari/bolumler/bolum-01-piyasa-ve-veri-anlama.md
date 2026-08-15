# Bölüm 1 — Piyasa ve Veri Anlama

## Amaç

Sistemin analiz yapmadan önce piyasadaki gerçek durumu eksiksiz ve güncel şekilde toplaması.

## Çalışma Mantığı

```
Veri kaynakları → Veri toplama → Normalleştirme → Zaman/piyasa kontrolü → Veri birleştirme → Son güncel piyasa görünümü
```

## Temel Prensip

Bu bölüm **yorum yapmaz** ve **hisse önermez**.

Sadece şu sorunun cevabını oluşturur:

> "Şu anda piyasada ne oluyor ve elimizde hangi güvenilir bilgiler var?"

Bu çıktıyı sonraki Piyasa Analizi, Hisse Keşfi, Fundamental Analiz, Haber Analizi, Tahmin ve Risk bölümleri kullanır.

---

## 1. Market Data

**Amaç:** Hisse/fon fiyatı, OHLCV, hacim, endeks ve volatilite gibi piyasa verilerini toplar.

**Kaynak:** yfinance (15dk gecikmeli), gelecekte Matriks/İş Yatırım

**Veri:**
- OHLCV (Açılış, Yüksek, Düşük, Kapanış, Hacim)
- Endeks verileri (BIST100, BIST30, sektör endeksleri)
- Volatilite (VIX, ATR, realized vol)

**Durum:** ✅ Çalışıyor (472 hisse, batch download)

**Dosya:** `services/ingestion/providers/yfinance_provider.py`

---

## 2. Fundamental Data

**Amaç:** Şirketlerin bilanço, gelir tablosu, nakit akışı, borç, kârlılık ve büyüme verilerini toplar.

**Kaynak:** yfinance (company info), gelecekte KAP finansal raporlar

**Veri:**
- Bilanço (toplam varlık, borç, özkaynak)
- Gelir tablosu (ciro, FAVÖK, net kâr)
- Nakit akışı (faaliyat, yatırım, finansman)
- Oranlar (F/K, PD/DD, ROE, ROIC, borç/özkaynak)

**Durum:** ✅ Çalışıyor (20 şirket, yfinance)

**Dosya:** `services/ingestion/providers/fundamental_provider.py`

---

## 3. KAP

**Amaç:** Şirket açıklamalarını, finansal sonuçları, özel durumları ve yatırımcı açısından önemli duyuruları toplar.

**Kaynak:** kap.org.tr API (şu an 500 hatası — sunucu sorunu)

**Veri:**
- Bildirim başlığı ve özeti
- Bildirim türü (finansal sonuç, temettü, yatırım, sözleşme, dava)
- Önem skoru
- Duyarlılık analizi

**Durum:** ⚠️ KAP API 500 hatası, RSS fallback var

**Dosya:** `services/ingestion/providers/kap_provider.py`

---

## 4. News

**Amaç:** Şirket, sektör, ekonomi ve piyasayla ilgili haberleri toplar.

**Kaynak:** RSS feed'ler (Dünya, Borsa Gündem, Bloomberg HT, AA)

**Veri:**
- Haber başlığı ve özeti
- Kaynak ve güvenilirlik
- Duyarlılık analizi
- Ticker eşleştirme (haber başlığından şirket adı çıkarma)

**Durum:** ✅ Çalışıyor (80 haber, 4 kaynak, 9 ticker eşleştiriliyor)

**Dosya:** `services/ingestion/providers/news_provider.py`

---

## 5. Social Media

**Amaç:** Sosyal medyadaki yatırımcı ilgisini ve genel sentiment'i toplar. **Tek başına gerçek kabul edilmez.**

**Kaynak:** StockTwits (403 engelli), Reddit (403 engelli), X/Twitter (ücretli API)

**Veri:**
- Mesaj hacmi
- Duyarlılık analizi
- Manipülasyon tespiti (bot, spam, koordinasyon)

**Durum:** ❌ Tüm kaynaklar engelli

**Dosya:** `services/ingestion/providers/social_provider.py`

---

## 6. Macro Data

**Amaç:** Faiz, enflasyon, döviz, emtia, küresel endeksler gibi makroekonomik verileri toplar.

**Kaynak:** yfinance (USDTRY, VIX, Gold, Oil, S&P500, Nasdaq), TCMB EVDS

**Veri:**
- USD/TRY, EUR/TRY kurları
- TCMB politika faizi
- TÜFE, ÜFE
- VIX, S&P500, Nasdaq
- Altın, petrol fiyatları

**Durum:** ✅ Çalışıyor (yfinance ile)

**Dosya:** `services/ingestion/providers/yfinance_provider.py` (fetch_macro)

---

## 7. Sector Data

**Amaç:** Şirketin bulunduğu sektörün performansını ve sektör bazlı gelişmeleri toplar.

**Kaynak:** yfinance (sektör endeksleri), KAP (sektör bildirimleri)

**Veri:**
- Sektör endeks performansı
- Sektör relatif gücü
- Sektör rotasyonu
- Sektör bazlı gelişmeler

**Durum:** ⚠️ Kısmen (sektör mapping var, endeks verisi eksik)

**Dosya:** `services/features/cross_sectional.py`

---

## 8. Corporate Actions

**Amaç:** Temettü, bölünme, bedelsiz, sermaye artırımı gibi şirket olaylarını takip eder.

**Kaynak:** KAP bildirimleri

**Veri:**
- Temettü miktarı ve tarihi
- Bölünme/bedelsiz oranı
- Bedelli sermaye artırımı
- Fiyat düzeltme katsayıları

**Durum:** ✅ Çalışıyor (fiyat ve pozisyon düzeltmesi)

**Dosya:** `services/ingestion/corporate_actions.py`

---

## 9. Trading Calendar

**Amaç:** Piyasanın açık/kapalı olduğunu, seans saatlerini ve tatilleri kontrol eder.

**Kaynak:** BIST resmi takvimi

**Veri:**
- İşlem günü mü?
- Piyasa açık mı?
- Seans (açılış, öğle arası, kapanış)
- Resmi tatiller
- Devre kesici durumları

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/market_calendar.py`

---

## 10. FX

**Amaç:** Farklı para birimlerindeki verileri ortak para birimine çevirmek ve kur etkisini takip etmek için kullanılır.

**Kaynak:** yfinance (USDTRY, EURTRY)

**Veri:**
- Döviz kurları
- Kur değişim hızı
- Kur volatilitesi
- Parasal pozisyon düzeltmesi

**Durum:** ✅ Çalışıyor

**Dosya:** `services/ingestion/providers/yfinance_provider.py`, `services/portfolio/enhancements.py`
