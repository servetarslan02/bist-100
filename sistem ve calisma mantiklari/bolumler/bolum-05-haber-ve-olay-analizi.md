# Bölüm 5 — Haber ve Olay Analizi

## Amaç

Haberlerden, KAP açıklamalarından ve yaklaşan olaylardan bilgi çıkarmak. "Şu anda ne oluyor ve bunun etkisi ne?" sorusunun cevabı.

## Çalışma Mantığı

```
Haber/KAP/Sosyal → Sınıflandırma → Etki yönü → Beklenmediklik → Sektör zincirleme → Olay skoru
```

## Temel Prensip

Basit pozitif/negatif sınıflandırma yapmaz. Her olayın türünü, etkisini, süresini ve belirsizliğini ayrı ayrı ölçer.

---

## 1. Haber Analizi

**Kaynak:** RSS feed'ler (Dünya, Borsa Gündem, Bloomberg HT, AA)

**İşlem:**
- Haber başlığından ticker çıkarma
- Duyarlılık analizi (pozitif/negatif/nötr)
- Önem skoru (haber türüne göre)
- Kaynak güvenilirlik skoru
- Haber duplication engelleme (aynı haber farklı kaynaklardan)

**Durum:** ✅ Çalışıyor (80 haber, 4 kaynak)

**Dosya:** `services/ingestion/providers/news_provider.py`

---

## 2. KAP Analizi

**Kaynak:** kap.org.tr

**İşlem:**
- Olay türü sınıflandırması (18 tür: temettü, bedelsiz, yatırım, sözleşme, dava, vb.)
- Finansal etki yönü + büyüklüğü
- Beklenmediklik skoru (tarihsel ortalamaya göre)
- Belirsizlik skoru (bilgi eksikliği)
- Etkilenen sektörler

**Durum:** ⚠️ KAP API 500 hatası, RSS fallback var

**Dosya:** `services/intelligence/kap_extractor.py`

---

## 3. Sektör Zincirleme Etki

**Amaç:** Bir sektördeki olayın diğer sektörleri nasıl etkilediğini takip eder.

**Örnek:**
- Petrol ↑ → Enerji sektörü → Havacılık maliyeti ↑ (-0.60)
- Faiz ↑ → Bankacılık → İnşaat kredi maliyeti ↑ (-0.50)
- Metal ↓ → İnşaat hammadde maliyeti ↓ (+0.30)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/kap_extractor.py` (SectorChainImpact)

---

## 4. Katalizör Takibi

**Amaç:** Yaklaşan olayları takip eder ve bunların potansiyel etkisini ölçer.

**Olaylar:**
- Bilanço açıklama tarihi
- Temettü ödeme tarihi
- Bedelsiz/bedelli tarihi
- Genel kurul
- Sözleşme sonucu
- Regülasyon değişikliği

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/seven_motors.py` (Motor 6)

---

## 5. Sentiment Momentum

**Amaç:** Sadece sentiment seviyesini değil, değişim hızını da takip eder.

**Metrikler:**
- Son 3 gün vs önceki 3 gün sentiment farkı
- Hacim artışı + pozitif sentiment = güçlü sinyal
- Hacim artışı + negatif sentiment = zayıflık

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/sentiment.py`

---

## 6. Event Decay

**Amaç:** Bir olayın etkisinin zamanla azaldığını modeler.

**Model:**
- Gün 0: %100 etki
- Gün 1: %70 etki
- Gün 5: %15 etki
- Gün 10+: %0 etki

**Durum:** ⚠️ Model tanımlı, otomatik uygulama eksik

---

## 7. Çıktı

Her hisse için:
- KAP olay türü + etki skoru
- Haber sentiment + momentum
- Yaklaşan katalizörler
- Sektör zincirleme etkisi
- Beklenmediklik + belirsizlik skoru
