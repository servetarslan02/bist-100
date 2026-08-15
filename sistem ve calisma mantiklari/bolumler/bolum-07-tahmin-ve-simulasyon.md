# Bölüm 7 — Tahmin ve Simülasyon

## Amaç

Gelecek olasılıklarını tahmin etmek. "Bu hisse için ne olabilir?" sorusunun cevabı.

## Çalışma Mantığı

```
Feature'lar → Monte Carlo → Olasılık dağılımı → Forecasting → Ensemble → Tahmin
```

## Temel Prensip

"Bu hisse yükselecek" demez. "Bu hissenin %60 olasılıkla 20 günde sektörden iyi performans gösterme olasılığı var" der.

---

## 1. Monte Carlo Simülasyonu

**Amaç:** Binlerce olası fiyat yolu simüle eder.

**Yöntem:** Geometric Brownian Motion (GBM)

**Parametreler:**
- Mevcut fiyat
- Beklenen getiri (yıllık)
- Volatilite (yıllık)
- Simülasyon süresi (gün)
- Simülasyon sayısı (10,000+)

**Çıktı:**
- P10, P25, P50 (medyan), P75, P90 fiyat seviyeleri
- P(getiri > 0), P(getiri > %5), P(getiri > %10)
- VaR %95, CVaR %95

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/monte_carlo.py`

---

## 2. Portfolio Monte Carlo

**Amaç:** Portföy seviyesinde risk hesaplar.

**Yöntem:** Korelasyon matrisi ile birlikte simülasyon

**Çıktı:**
- Portföy VaR
- Portföy CVaR
- Beklenen drawdown
- Kaybetme olasılığı

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/monte_carlo.py`

---

## 3. Olasılık Dağılımı

**Amaç:** Farklı senaryoların gerçekleşme olasılığını hesaplar.

**Metrikler:**
- P(5 günlük relatif pozitif getiri)
- P(20 günlük > sektör)
- P(20 günlük > +5%)
- P(max drawdown > X)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/probability.py`

---

## 4. Forecasting

**Amaç:** Farklı zaman ufukları için tahmin üretir.

**Ufuklar:** 1 gün, 5 gün, 20 gün, 60 gün, 120 gün

**Yöntem:** Ensemble (teknik + istatistiksel + ML + LLM + Monte Carlo)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/forecasting.py`

---

## 5. Adjusted-MSE Loss

**Amaç:** Yanlış yönlü tahminleri ağır cezalandırır.

**Model:** +5% tahmin ama gerçek -5% → 11× ceza

**Kaynak:** Du (2026) — Chinese A-share çalışması

**Durum:** ✅ Çalışıyor

**Dosya:** `services/ml/ranking_model.py`

---

## 6. Çıktı

```
THYAO — 20 GÜNLÜK TAHMİN
──────────────────────────────
P10:    ₺280  (%10 olasılıkla bu fiyatın altında)
P25:    ₺295
P50:    ₺315  (medyan)
P75:    ₺340
P90:    ₺370  (%10 olasılıkla bu fiyatın üstünde)
──────────────────────────────
P(pozitif getiri):  %62
P(+5% üzeri):       %41
P(-5% altı):        %18
──────────────────────────────
VaR %95:    -%8.2
CVaR %95:   -%11.5
```
