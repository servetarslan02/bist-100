# Bölüm 2 — Piyasa Analizi

## Amaç

Toplanan verilerden piyasanın genel durumunu anlamak. "Şu anda piyasa ne durumda?" sorusunun cevabı.

## Çalışma Mantığı

```
Piyasa verileri → Breadth/Rotasyon → Volatilite → Likidite → Rejim tespiti → Piyasa durumu
```

## Temel Prensip

Bu bölüm **hisse seçmez**. Sadece piyasanın genel durumunu belirler.

---

## 1. Market Breadth

**Amaç:** Piyasanın genel yönünü ölçer.

**Metrikler:**
- Yükselen/Düşen hisse oranı
- Yeni yüksek/düşük yapan hisse sayısı
- Sektör rotasyonu (hangi sektör güçleniyor, hangi zayıflıyor)
- Advance/Decline çizgisi

**Durum:** ✅ Çalışıyor (472 hisse breadth hesaplanıyor)

**Dosya:** `services/features/cross_sectional.py`

---

## 2. Volatilite Analizi

**Amaç:** Piyasanın ne kadar hareketli olduğunu ölçer.

**Metrikler:**
- BIST100 realized volatilite (20 gün)
- VIX seviyesi ve trendi
- ATR (Average True Range)
- Volatilite rejimi (LOW/NORMAL/HIGH/EXTREME)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/calculator.py`

---

## 3. Likidite Analizi

**Amaç:** Piyasadaki likidite durumunu ölçer.

**Metrikler:**
- Toplam işlem hacmi
- Hacim trendi
- Bid-ask spread
- Likidite skoru

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/seven_motors.py` (Motor 3)

---

## 4. Regime Tespiti

**Amaç:** Piyasanın hangi rejimde olduğunu belirler.

**Rejimler:**
- BULL / BEAR / SIDEWAYS
- HIGH-VOLATILITY / LOW-VOLATILITY
- RISK-ON / RISK-OFF
- CRISIS / RECOVERY
- MOMENTUM-EXPANSION / MOMENTUM-CONTRACTION

**Yöntem:** Feature-based (threshold değil, çoklu feature'dan karar verir)

**Durum:** ✅ Çalışıyor (11 rejim, feature-based)

**Dosya:** `services/intelligence/regime.py`

---

## 5. World State

**Amaç:** Global makro durumu takip eder.

**Faktörler:**
- Global risk iştahı
- USD gücü
- ABD faiz baskısı
- Emtia baskısı
- Türkiye makro risk
- Jeopolitik risk

**Durum:** ✅ Çalışıyor (10+ latent factor)

**Dosya:** `services/intelligence/world_state.py`

---

## 6. Sektör Analizi

**Amaç:** Sektör bazlı durumu analiz eder.

**Metrikler:**
- Sektör momentum
- Sektör rotasyonu (hangi sektör lider, hangi geride)
- Sektör relatif gücü
- Sektör konsantrasyonu

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/cross_sectional.py`, `services/features/seven_motors.py`
