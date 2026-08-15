# Bölüm 8 — Risk Yönetimi

## Amaç

Riski ölçmek, sınırlamak ve kontrol etmek. "Ne kadar kaybedebilirim?" sorusunun cevabı.

## Çalışma Mantığı

```
Pozisyon → Risk hesaplama → Limit kontrolü → Konsantrasyon → Korelasyon → Karar
```

## Temel Prensip

Risk motoru her zaman **fail-closed** çalışır. Risk hesaplanamıyorsa işlem yapılmaz.

---

## 1. Pozisyon Riski

**Metrikler:**
- Pozisyon büyüklüğü (portföyün yüzdesi)
- Volatilite katkısı
- VaR katkısı
- Stop-loss mesafesi

**Durum:** ✅ Çalışıyor

**Dosya:** `services/risk/enhanced_risk.py`

---

## 2. Konsantrasyon Riski

**Metrikler:**
- HHI (Herfindahl-Hirschman Index)
- Sektör konsantrasyonu
- En büyük pozisyon ağırlığı

**Limitler:**
- Tek hisse: maksimum %10
- Tek sektör: maksimum %30

**Durum:** ✅ Çalışıyor

**Dosya:** `services/risk/enhanced_risk.py`

---

## 3. Korelasyon Riski

**Amaç:** Pozisyonlar arası korelasyonu ölçer.

**Metrikler:**
- Pozisyonlar arası korelasyon
- Portföy beta'sı
- Korelasyon riski skoru

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/seven_motors.py`, `services/risk/enhanced_risk.py`

---

## 4. Drawdown Riski

**Metrikler:**
- Mevcut drawdown
- Maksimum drawdown
- Drawdown süresi
- Toparlanma süresi

**Limit:** Maksimum drawdown %15

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/decision_engine.py`, `services/risk/main.py`

---

## 5. Likidite Riski

**Amaç:** Pozisyonun kolayca kapatılıp kapatılamayacağını ölçer.

**Metrikler:**
- Günlük ortalama hacim
- Hacim/kapasite oranı
- Spread

**Durum:** ✅ Çalışıyor

**Dosya:** `services/features/seven_motors.py`

---

## 6. Volatilite Targeting

**Amaç:** Portföy volatilitesini hedef seviyede tutar.

**Yöntem:**
- Düşük volatilite → kaldıraç artır
- Yüksek volatilite → pozisyon küçült

**Durum:** ✅ Çalışıyor

**Dosya:** `services/risk/enhanced_risk.py`

---

## 7. Position Sizing

**Amaç:** Her pozisyonun büyüklüğünü hesaplar.

**Yöntem:** Kelly Criterion (yarım Kelly daha güvenli)

**Formül:**
```
f* = (p × b - q) / b
p = kazanma oranı
b = ortalama kazanç / ortalama kayıp
q = 1 - p
```

**Durum:** ✅ Çalışıyor

**Dosya:** `services/risk/position_sizing.py`, `services/risk/enhanced_risk.py`

---

## 8. Risk Gate

**Amaç:** Tüm risk kontrollerinden geçemeyen kararları engeller.

**Kontroller:**
- Pozisyon limiti
- Sektör konsantrasyonu
- Günlük zarar limiti
- Drawdown limiti
- Bilinmeyen veri → BLOCK

**Durum:** ✅ Çalışıyor (fail-closed)

**Dosya:** `services/risk/main.py`

---

## 9. Çıktı

```
RİSK DURUMU
──────────────────────────────
Risk Seviyesi:        ORTA
Drawdown:             %3.2
Sektör Konsantrasyonu: %22
En Büyük Pozisyon:    %8.5 (THYAO)
Günlük P&L:          +₺1,250
──────────────────────────────
Risk Gate:            GEÇTİ
```
