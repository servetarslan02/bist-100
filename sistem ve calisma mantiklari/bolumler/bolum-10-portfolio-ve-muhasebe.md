# Bölüm 10 — Portföy ve Muhasebe

## Amaç

Portföyü takip etmek, muhasebe yapmak ve performansı ölçmek. "Ne kadar kazandım/kaybettim?" sorusunun cevabı.

## Çalışma Mantığı

```
İşlem → Pozisyon güncelleme → Nakit güncelleme → P&L hesaplama → Performans ölçümü
```

## Temel Prensip

Her işlem immutable olarak kaydedilir. Portföy durumu her zaman yeniden hesaplanabilir.

---

## 1. Pozisyon Takibi

**Veri:**
- Hisse kodu
- Lot sayısı
- Ortalama maliyet
- Güncel fiyat
- Piyasa değeri
- Gerçekleşmemiş kâr/zarar

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/main.py`

---

## 2. Ortalama Maliyet

**Yöntem:** Weighted Average Cost

```
Yeni ort. maliyet = (eski lot × eski fiyat + yeni lot × yeni fiyat) / toplam lot
```

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/main.py`

---

## 3. Komisyon Modeli

**Bileşenler:**
- Broker komisyonu: %0.03
- BIST ücreti: %0.0056
- BSMV: Komisyon üzerinden %5
- Minimum: ₺1

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/enhancements.py`

---

## 4. Vergi Modeli

**Tür:**
- Temettü stopajı: %10
- Sermaye kazancı: %0 (şu an)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/enhancements.py`

---

## 5. Temettü İşleme

**İşlem:**
- Temettü miktarı hesapla
- Stopaj kes
- Nakit ekle
- Pozisyon maliyetini güncelle

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/enhancements.py`

---

## 6. Performans Metrikleri

**Metrikler:**
- Toplam getiri
- Yıllıklandırılmış getiri (CAGR)
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maksimum drawdown
- Kazanma oranı
- Profit factor
- Ortalama kazanç / Ortalama kayıp
- Expectancy
- Devir hızı

**Durum:** ✅ Çalışıyor

**Dosya:** `services/backtest/engine.py`, `services/portfolio/enhancements.py`

---

## 7. Benchmark Karşılaştırma

**Benchmark:** BIST100

**Metrikler:**
- Alpha (fazla getiri)
- Beta
- Information ratio
- Tracking error
- Up/Down capture

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/enhancements.py`

---

## 8. Performans Ayrıştırması

**Amaç:** Toplam getiriyi bileşenlerine ayırır.

**Bileşenler:**
- Hisse seçimi etkisi
- Sektör seçimi etkisi
- Faktör maruziyeti (momentum, value)
- FX etkisi

**Durum:** ✅ Çalışıyor

**Dosya:** `services/portfolio/enhancements.py`

---

## 9. Uzlaştırma

**Amaç:** Portföy tutarlılığını kontrol eder.

**Kontrol:** Nakit + Pozisyon Değerleri = Özkaynak

**Durum:** ✅ Çalışıyor

**Dosya:** `services/risk/reconciliation.py`

---

## 10. Çıktı

```
PORTFÖY DURUMU
──────────────────────────────
Toplam Değer:    ₺112,450
Nakit:           ₺45,200
Yatırım:         ₺67,250
──────────────────────────────
Günlük P&L:      +₺1,250 (+1.1%)
Toplam P&L:      +₺12,450 (+12.4%)
Sharpe:          1.85
Max Drawdown:    -%5.2
──────────────────────────────
Pozisyonlar:
  THYAO:  150 lot  ₺45,750  (+8.2%)
  ASELS:  200 lot  ₺7,600   (+3.1%)
  AKBNK:  100 lot  ₺6,880   (-2.4%)
```
