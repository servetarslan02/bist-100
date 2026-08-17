# BIST Piyasa Kuralları Özeti

**Amaç:** Tüm modüllerin uyması gereken BIST'e özgü kurallar tek dosyada.
**Kullanım:** LLM bu dosyayı okuyarak BIST kurallarını anlayabilir.

---

## 1. İşlem Saatleri

**Kaynak:** Borsa İstanbul resmi, Garanti BBVA, ÜNLÜ Menkul
**Not:** 2015 BISTECH geçişinden sonra tek seans sistemi uygulanmaktadır.

| Aşama | Saat | Açıklama |
|-------|------|----------|
| Açılış Seansı Emir Toplama | 09:40-09:55 | Sadece emir girilir, işlem yok |
| Fiyat Belirleme ve İşlem | 09:55-10:00 | Açılış fiyatı belirlenir |
| Sürekli İşlem | 10:00-18:00 | Ana işlem seansı (tek seans, ara yok) |
| Kapanış Seansı | 18:00-18:10 | Kapanış fiyatları belirlenir |

**Önemli:**
- 2015 öncesi iki seans (10:00-12:30 + 14:00-17:40) vardı
- 2015 BISTECH geçişinden sonra tek seans (10:00-18:00)
- Öğle arası yok
- Scanner, scheduler, API bu saatlere göre çalışmalı

---

## 2. Fiyat Limitleri

**Kaynak:** Borsa İstanbul resmi, İş Yatırım, AA (2020)

| Pazar | Fiyat Marjı | Devre Kesici | Açığa Satış Yukarı Adım |
|-------|------------|--------------|------------------------|
| Yıldız Pazar | ±%20 | %10 | VAR |
| Ana Pazar | ±%15 | %7.5 | VAR |
| Alt Pazar | ±%10 | %5 | YOK |
| Tüm gruplar (kriz) | ±%10 | %5 | — |

**Devre Kesici:**
- Sadece aşağı yönlü tetiklenir
- Tetikleme sonrası 15 dakika emir toplama
- Açılış seansında devre kesici yok

**Önemli:** price_limits.py, risk_gate.py bu kuralları uygulamalı.

---

## 3. Açığa Satış

**Kaynak:** Borsa İstanbul resmi, Para Dergi (2025), Ata Yatırım

- **BIST-50** hisseleri açığa satılabilir (BIST-30 değil!)
- **Yukarı adım kuralı:** Açığa satış fiyatı son işlem fiyatından yüksek olmalı (BIST-50)
- **Brüt takaslı** hisselerde açığa satış yasak
- **SPK geçici yasak** kontrolü gerekli
- Alt Pazar'da açığa satış yok

**Önemli:** short_selling.py, risk_gate.py bu kuralları uygulamalı.

---

## 4. Brüt Takas

- SPK tarafından belirlenir
- Brüt takaslı hisselerde:
  - Açığa satış yasak
  - T+0 ödeme (nakit aynı gün)
  - Kredili işlem yasak

**Önemli:** gross_settlement.py, risk_gate.py bu kuralları uygulamalı.

---

## 5. Komisyon Yapısı

| Bileşen | Oran | Açıklama |
|---------|------|----------|
| Broker | %0.03-0.2 (değişken) | Aracı kuruma göre değişir, hacme bağlı |
| BIST | %0.0056 | Borsa payı (Borsa İstanbul tarifesi) |
| MKK | %0.00109 | Saklama payı (Kayıt sayısı üzerinden) |
| BSMV | %5 (komisyon üzerinden) | Banka ve Sigorta Muameleleri Vergisi |
| Minimum | ₺1 | Alt sınır |

**Kaynak:** Borsa İstanbul ücretlendirme tablosu, Ata Yatırım, TEB Yatırım
**Not:** Broker oranları aracı kuruma ve işlem hacmine göre büyük farklılık gösterir.

**Önemli:** fee_calculator.py, portfolio_manager.py, backtest/engine.py bu oranları kullanmalı.

---

## 6. Temettü

**Kaynak:** EY Türkiye (2025), Verginet.net

- KAP üzerinden açıklanır
- Temettü tarihi öncesi hisse fiyatı düşer (ex-date)
- **Stopaj: %15** (gerçek kişiler, 2025 itibariyle — daha önce %10'du)
- Temettü verimi = Yıllık temettü / Hisse fiyatı

**Önemli:** portfolio/enhancements.py, features/fundamental.py bu oranı kullanmalı.

---

## 7. Bedelsiz Sermaye Artırımı

- KAP üzerinden açıklanır
- Hisse fiyatı düşer (oran kadar)
- Pozisyon miktarı artar (oran kadar)
- Fiyat düzeltmesi gerekli

**Önemli:** ingestion/corporate_actions.py bu düzeltmeleri yapmalı.

---

## 8. Şirket Olayları (KAP)

| Olay | Etki | Öncelik |
|------|------|---------|
| Finansal Sonuçlar | Yüksek | 🔴 |
| Temettü | Orta | 🟡 |
| Geri Alım | Pozitif | 🟡 |
| Sermaye Artırımı | Karma | 🟡 |
| Birleşme/Devralma | Yüksek | 🔴 |
| Yönetim Değişikliği | Düşük | 🟢 |
| Yasal/Düzenleyici | Karma | 🟡 |
| Sözleşme/Yatırım | Pozitif | 🟡 |

**Önemli:** intelligence/kap_extractor.py, intelligence/kap_llm_extractor.py bu olayları sınıflandırmalı.

---

## 9. Sektörler (BIST)

| Sektör | Örnek Hisseler | Özellik |
|--------|---------------|---------|
| Bankacılık | GARAN, AKBNK, ISCTR | Faiz hassas |
| Sanayi | EREGL, KRDMD, SAHOL | Döviz hassas |
| Teknoloji | ASELS, NETAS, INDES | Büyüme odaklı |
| Perakende | BIMAS, MGROS, TUKAS | Tüketici hassas |
| Enerji | TUPRS, TRKOM, AYGAZ | Emtia hassas |
| Ulaştırma | THYAO, PGSUS | Döviz geliri |
| İnşaat | TOASO, KONTR | Faiz hassas |
| Gıda | TATGD, BANVT | Enflasyon hassas |

**Önemli:** features/cross_sectional.py, intelligence/macro_sensitivity.py sektör hassasiyetlerini kullanmalı.

---

## 10. SPK Regülasyonları

| Kural | Eşik | Aksiyon |
|-------|------|---------|
| Bildirim yükümlülüğü | %5 | SPK'ya bildirim |
| Zorunlu teklif | %10 | Tüm hissedarlara teklif |
| Engelleme azınlığı | %20 | Veto hakkı |
| İçerden bilgi ticareti | Yasak | Ceza |
| Manipülasyon | Yasak | Ceza |
| Algoritmik trading | Bildirim zorunlu | SPK'ya bildirim |

**Önemli:** core/compliance.py, core/manipulation_detector.py bu kuralları uygulamalı.

---

## 11. VIOP (Vadeli İşlem ve Opsiyon)

| Sözleşme | Dayanık | Sözleşme Büyüklüğü |
|----------|---------|-------------------|
| BIST 30 Endeks | BIST 30 | Endeks × 10 TL |
| Dolar/TL | USD/TRY | 1.000 USD |
| Euro/TL | EUR/TRY | 1.000 EUR |
| Gram Altın | Altın | 1 gram |

**Önemli:** services/viop/ modülleri bu sözleşme özelliklerini kullanmalı.

---

## 12. Makro Göstergeler (Türkiye)

| Gösterge | Kaynak | Frekans | BIST Etki |
|----------|--------|---------|-----------|
| TCMB Politika Faizi | TCMB | Aylık | Yüksek |
| TÜFE (CPI) | TÜİK | Aylık | Yüksek |
| ÜFE (PPI) | TÜİK | Aylık | Orta |
| GSYH | TÜİK | Çeyreklik | Orta |
| Cari Açık | TCMB | Aylık | Orta |
| USDTRY | TCMB | Günlük | Yüksek |
| CDS Spread | Piyasa | Günlük | Orta |
| VIX | CBOE | Günlük | Orta |

**Önemli:** services/macro/, features/macro.py, intelligence/macro_sensitivity.py bu göstergeleri kullanmalı.

---

## 13. Veri Kaynakları (Türkiye)

| Kaynak | Veri | API | Güvenilirlik |
|--------|------|-----|-------------|
| KAP | Şirket bildirimleri | API | En yüksek |
| TCMB EVDS | Faiz, enflasyon, döviz | API | Yüksek |
| TÜİK | İstihdam, GSYH | API | Yüksek |
| BIST | İşlem verisi | Web | Yüksek |
| BKM | Kredi kartı harcama | Rapor | Yüksek |
| Google Trends | Arama trendleri | API (ücretsiz) | Yüksek |
| yfinance | OHLCV | API | Orta (15dk gecikmeli) |
| X/Twitter | Sosyal medya | API | Orta |
| Ekşi Sözlük | Sentiment | Web scraping | Orta |
| Kariyer.net | İş ilanları | Web scraping | Orta |

**Önemli:** services/ingestion/providers/ modülleri bu kaynakları kullanmalı.
