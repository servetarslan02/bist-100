# BIST Piyasa Kuralları Özeti

**Amaç:** Tüm modüllerin uyması gereken BIST'e özgü kurallar tek dosyada.
**Kullanım:** LLM bu dosyayı okuyarak BIST kurallarını anlayabilir.

---

## 1. İşlem Saatleri

| Seans | Saat | Açıklama |
|-------|------|----------|
| Emir Toplama | 09:40-09:55 | Sadece emir girilir, işlem yok |
| Seans 1 | 09:55-12:30 | Tek fiyat yöntemi |
| Ara | 12:30-14:00 | İşlem yok |
| Seans 2 | 14:00-17:40 | Sürekli müzayede |
| Kapanış | 17:40-18:00 | Kapanış fiyatları |
| After-hours | 18:00+ | Piyasa kapalı |

**Önemli:** Scanner, scheduler, API bu saatlere göre çalışmalı.

---

## 2. Fiyat Limitleri

| Hisse Türü | Limit | Açıklama |
|------------|-------|----------|
| Normal | ±%10 | Önceki kapanışa göre |
| Volatil | ±%5 veya ±%20 | SPK belirler |
| İlk seansta | Limit yok | Açılış fiyatına kadar |
| Devre kesici | ±%5 (gün içi), ±%10 (açılış) | Otomatik durdurma |

**Önemli:** price_limits.py, risk_gate.py bu kuralları uygulamalı.

---

## 3. Açığa satış

- Sadece **BIST-30** hisseleri açığa satılabilir
- **Uptick rule:** Son işlem fiyatından yüksek fiyatla açığa satış
- **Brüt takaslı** hisselerde açığa satış yasak
- **SPK geçici yasak** kontrolü gerekli

**Önemli:** short_selling.py bu kuralları uygulamalı.

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
| Broker | %0.03 (değişken) | Aracı kurum |
| BIST | %0.0056 | Borsa payı |
| MKK | %0.00109 | Saklama payı |
| BSMV | %5 (komisyon üzerinden) | Vergi |
| Minimum | ₺1 | Alt sınır |

**Önemli:** fee_calculator.py, portfolio_manager.py, backtest/engine.py bu oranları kullanmalı.

---

## 6. Temettü

- KAP üzerinden açıklanır
- Temettü tarihi öncesi hisse fiyatı düşer (ex-date)
- Stopaj: %10 (gerçek kişiler)
- Temettü verimi = Hisse fiyatı / Yıllık temettü

**Önemli:** portfolio/enhancements.py, features/fundamental.py bu kuralları uygulamalı.

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
