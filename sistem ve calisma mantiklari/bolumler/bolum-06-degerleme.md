# Bölüm 6 — Değerleme

## Amaç

Şirketin gerçeğe uygun değerini hesaplamak. "Bu şirket pahalı mı, ucuz mu?" sorusunun cevabı.

## Çalışma Mantığı

```
Finansal veri → Multiples → Peer Comparison → DCF → Senaryolar → Değerleme sonucu
```

## Temel Prensip

Tek bir yöntemle değerleme yapmaz. Çoklu yöntem kullanır ve sonuçları karşılaştırır.

---

## 1. Multiples Değerleme

**Çarpanlar:**
- F/K (Price/Earnings)
- PD/DD (Price/Book)
- FD/FAVÖK (EV/EBITDA)
- F/Satış (EV/Sales)
- FCF Getirisi
- Temettü Getirisi

**Karşılaştırma:**
- Sektör medyanına göre
- Sektör ortalamasına göre
- Şirketin kendi tarihsel ortalamasına göre

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/valuation/engine.py`

---

## 2. Peer Comparison

**Amaç:** Aynı sektördeki şirketlerle karşılaştırır.

**Yöntem:** Şirket çarpanı / Peer grubu medyanı

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/valuation/engine.py`

---

## 3. DCF (Discounted Cash Flow)

**Amaç:** Gelecek nakit akışlarının bugünkü değerini hesaplar.

**Girdi:**
- 5 yıllık gelir tahmini
- Marj tahmini
- CAPEX tahmini
- Working capital değişimi
- WACC (Ağırlıklı Ortalama Sermaye Maliyeti)
- Terminal büyüme oranı

**Çıktı:**
- İçsel değer (intrinsic value)
- Mevcut fiyata göre upside/downside
- Sensitivity table (WACC × terminal growth → fiyat)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/valuation/engine.py`

---

## 4. Değerleme Senaryoları

**Senaryolar:**
- **Bear:** Muhtemel kötü durum (düşük büyüme, düşük marj, yüksek WACC)
- **Base:** En olası durum
- **Bull:** Muhtemel iyi durum (yüksek büyüme, yüksek marj, düşük WACC)

**Beklenen Değer:**
```
Expected Value = P(bear) × V_bear + P(base) × V_base + P(bull) × V_bull
```

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/valuation/engine.py`

---

## 5. Çıktı

```
THYAO — DEĞERLEME
──────────────────────────────
F/K:          8.2x  (Sektör: 11x)
PD/DD:        1.4x  (Sektör: 1.8x)
FD/FAVÖK:     5.1x  (Sektör: 7x)
FCF Getirisi: %6.8  (Sektör: %4.2)
──────────────────────────────
DCF Bear:     ₺280  (%10.4 downside)
DCF Base:     ₺340  (%8.7 upside)
DCF Bull:     ₺420  (%34.2 upside)
──────────────────────────────
Beklenen Değer: ₺347
Mevcut Fiyat:   ₺312
Upside:         %11.2
Görüş:          UNDERVALUED
```
