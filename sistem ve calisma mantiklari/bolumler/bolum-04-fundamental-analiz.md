# Bölüm 4 — Fundamental Analiz

## Amaç

Şirketlerin finansal sağlığını analiz etmek. "Bu şirket değerinde mi, altında mı, üstünde mi?" sorusunun cevabı.

## Çalışma Mantığı

```
Finansal veri → Bilanço analizi → Kârlılık → Büyüme → Değerleme → Karşılaştırma → Fundamental skor
```

## Temel Prensip

Tek bir çarpana (F/K gibi) bakarak değerlendirme yapmaz. Çok boyutlu analiz yapar.

---

## 1. Finansal Tablo Analizi

**Bilanço:**
- Toplam varlık, toplam borç, özkaynak
- Net borç, net borç/FAVÖK
- Cari oran, likidite

**Gelir Tablosu:**
- Ciro, FAVÖK, net kâr
- Brüt/FAVÖK/Net marj
- Büyüme hızı (yıllık, çeyreklik)

**Nakit Akışı:**
- Faaliyet nakit akışı
- Serbest nakit akışı (FCF)
- FCF marjı, FCF getirisi

**Durum:** ✅ Çalışıyor (yfinance ile)

**Dosya:** `services/ingestion/providers/fundamental_provider.py`

---

## 2. Kârlılık Analizi

**Metrikler:**
- ROE (Özkaynak Kârlılığı)
- ROA (Varlık Kârlılığı)
- ROIC (Yatırım Sermayesi Kârlılığı)
- Marj trendi (genişliyor/daralıyor)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/fundamental.py`

---

## 3. Büyüme Analizi

**Metrikler:**
- Ciro büyümesi (yıllık, CAGR)
- Kâr büyümesi
- FCF büyümesi
- Büyüme kalitesi (yüksek büyüme + düşen marj + artan borç = düşük kalite)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/fundamental.py`

---

## 4. Bilanço Kalitesi

**Metrikler:**
- Borç/Özkaynak oranı
- Cari oran
- Nakit/Borç oranı
- FCF tutarlılığı

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/fundamental.py`

---

## 5. Sektörel Normalize

**Amaç:** Aynı sektördeki şirketleri karşılaştırılabilir hale getirir.

**Yöntem:** Şirket çarpanı / Sektör medyanı

Örnek: F/K 8.5 / Sektör medyanı 11.0 = 0.77 (ucuz)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/fundamental.py`, `services/features/seven_motors.py` (Motor 4)

---

## 6. Enflasyon Muhasebesi (TMS 29)

**Problem:** Türkiye'de enflasyon muhasebesi F/K, PD/DD gibi metrikleri bozar.

**Çözüm:**
- FCF'yi merkeze al (nakit akışı enflasyondan daha az etkilenir)
- Parasal pozisyon kâr/zararını arındır
- Marj trendini takip et (enflasyon etkisinden arındırılmış)

**Durum:** ⚠️ Kısmen (FCF merkezli, tam TMS29 düzeltmesi eksik)

**Dosya:** `services/features/seven_motors.py` (Motor 4)

---

## 7. Earnings Quality

**Amaç:** Kârın kalitesini ölçer (sadece miktarı değil).

**Metrikler:**
- Net kâr vs Faaliyet nakit akışı (kâr nakit ile destekleniyor mu?)
- Alacak büyümesi vs Ciro büyümesi
- Tek seferlik kalemler
- Accruals oranı

**Durum:** ⚠️ Kısmen

**Dosya:** `services/features/fundamental.py`

---

## 8. Çıktı

Her şirket için:
- 29+ fundamental feature
- Sektörel normalize edilmiş çarpanlar
- Bilanço kalitesi skoru
- Büyüme kalitesi skoru
- Kârlılık trendi
