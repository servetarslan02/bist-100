# Bölüm 9 — Karar ve Uygulama

## Amaç

Tüm analizleri birleştirip nihai karar vermek ve uygulamak. "Ne yapmalıyım?" sorusunun cevabı.

## Çalışma Mantığı

```
Tüm sinyaller → Fusion → Karar → Risk Gate → Sipariş → Execution → Portföy
```

## Temel Prensip

AI tek başına karar vermez. Veri + Evidence + Risk → Karar. AI sadece bir bileşendir.

---

## 1. Signal Fusion

**Amaç:** 7 motorun çıktısını tek bir sinyale birleştirir.

**Bileşenler:**
- Teknik sinyal
- Fundamental sinyal
- Momentum sinyal
- Sentiment sinyal
- Macro sinyal
- Valuation sinyal
- AI sinyal

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/signal_fusion.py`

---

## 2. Çelişki Tespiti

**Amaç:** Sinyaller çelişiyorsa bunu gizlemez, gösterir.

**Örnek:**
- Teknik: LONG (momentum güçlü)
- Fundamental: SHORT (bilanço kötü)
- → Çelişki! Hangi taraf neden ağır basıyor?

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/signal_fusion.py`

---

## 3. Karar Motoru

**Kararlar:**
- **LONG:** Fiyatın yükselme olasılığı yüksek
- **SHORT:** Fiyatın düşme olasılığı yüksek
- **HOLD:** Belirsiz, mevcut pozisyonu koru
- **NO_TRADE:** Yeterli veri yok veya risk çok yüksek

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/decision_engine.py`

---

## 4. Risk Gate

**Amaç:** Karar risk kontrollerinden geçemiyorsa engeller.

**Kontroller:**
- Pozisyon limiti
- Sektör konsantrasyonu
- Drawdown limiti
- Bilinmeyen veri

**Durum:** ✅ Çalışıyor (fail-closed)

**Dosya:** `services/risk/main.py`

---

## 5. Execution Simulator

**Amaç:** Gerçekçi sanal işlem yapar.

**Özellikler:**
- Spread uygulaması
- Slippage modeli (volatilite, hacim, emir büyüklüğü)
- Komisyon (broker + BIST + BSMV)
- Partial fill desteği

**Durum:** ✅ Çalışıyor

**Dosya:** `services/simulation/execution_simulator.py`

---

## 6. Explainability

**Amaç:** Her kararın nedenini açıklar.

**Sorular:**
- WHY? (Neden bu karar?)
- WHY NOT? (Neden diğer yön değil?)
- WHAT CHANGED? (Ne değişti?)
- WHAT COULD INVALIDATE? (Ne ters gidebilir?)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/intelligence/signal_fusion.py`

---

## 7. Çıktı

```
KARAR: BUY (MEDIUM)
──────────────────────────────
Fiyat:        ₺305.25
Hedef:        ₺340 (+11.4%)
Stop:         ₺284 (-6.9%)
Pozisyon:     150 hisse (₺45,788)
──────────────────────────────
Nedenler:
  ✓ Momentum güçlü (score: 77)
  ✓ Hacim anomalisi (3.2σ)
  ✓ Sektör rotasyonu pozitif
Riskler:
  ⚠ Yüksek volatilite (%25)
  ⚠ Aşırı alım bölgesi (RSI: 68)
──────────────────────────────
Risk Gate:    GEÇTİ
Execution:    150 @ ₺305.40 (slippage: 0.05%)
Komisyon:     ₺3.68
```
