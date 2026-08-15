# Bölüm 3 — Hisse Keşfi

## Amaç

BIST evrenindeki tüm hisseleri tarayıp, en güçlü fırsatları bulmak. "Hangi hisseler dikkat çekiyor?" sorusunun cevabı.

## Çalışma Mantığı

```
BIST evreni → Filtreleme → 7 Motor → Skorlama → Sıralama → Fırsat listesi
```

## Temel Prensip

Bu bölüm **karar vermez**. Sadece fırsatları sıralar ve nedenlerini gösterir.

---

## 1. Filtreleme

**Amaç:** İşlem yapılamayan veya verisi olmayan hisseleri eler.

**Kriterler:**
- Likidite (minimum günlük hacim)
- Veri kalitesi (son 20 gün veri var mı?)
- Listing status (aktif mi, askıya alınmış mı?)
- Tradability mask (tavan/taban, devre kesici)

**Durum:** ✅ Çalışıyor (472 hisse filtreden geçiyor)

**Dosya:** `services/core/tradability_mask.py`, `services/ingestion/bist_universe.py`

---

## 2. Feature Hesaplama

**Amaç:** Her hisse için 100+ sayısal özellik hesaplar.

**Kategoriler:**
- Teknik (58 feature): RSI, MACD, ATR, Bollinger, momentum, trend
- Cross-sectional (15+ feature): rank, sektör relative, peer correlation
- Fundamental (29 feature): P/E, P/B, ROE, FCF, bilanço kalitesi
- Macro (12+ feature): USDTRY, VIX, altın, petrol
- Sentiment (10+ feature): haber, KAP, sosyal medya

**Durum:** ✅ Çalışıyor (100+ feature/hisse)

**Dosya:** `services/features/calculator.py`, `services/features/fundamental.py`, `services/features/macro.py`, `services/features/sentiment.py`, `services/features/cross_sectional.py`

---

## 3. 7 Motor

**Amaç:** Her hisseyi 7 ayrı perspektiften analiz eder.

| Motor | Amaç | Özellik |
|-------|------|---------|
| 1. Relatif Güç | Hisse vs BIST + sektör | 1d/5d/20d/60d/120d |
| 2. Momentum + Trend | İvme ve değişim yönü | Eğim, R², ivme, yeni yüksek/düşük |
| 3. Hacim + Mikroyapı | Fiyat-hacim ilişkisi | Tick rule, VWAP, hacim anomalisi |
| 4. Fundamental | Sektörel normalize | P/E, ROE, FCF, bilanço kalitesi |
| 5. KAP + Haber | Yapılandırılmış extraction | Olay türü, etki, beklenmediklik |
| 6. Katalizör | Yaklaşan olaylar | Bilanço, temettü, sözleşme |
| 7. Neden Düşüyor? | Düşüş sınıflandırması | Market/sector/company/liquidity/panic |

**Durum:** ✅ Çalışıyor (47+ feature, 35 test)

**Dosya:** `services/features/seven_motors.py`

---

## 4. Skorlama

**Amaç:** Her hisseyi tek bir sıralama skorunda birleştirir.

**Yöntem:** LightGBM Ranker (regression) + Rule-based fallback

**Girdi:** 7 motorun tüm feature'ları (~100+)

**Hedef:** Cross-sectional rank (gelecek 5 gün getiri percentile'ı)

**Durum:** ✅ Çalışıyor (LightGBM + rule-based)

**Dosya:** `services/ml/ranking_model.py`

---

## 5. Adaptif Eşik

**Amaç:** Piyasa koşullarına göre fırsat eşiğini belirler.

**Yöntem:** Eşik = medyan + 0.5 × std

- Piyasa zorsa eşik düşer (daha çok fırsat geçer)
- Piyasa iyiyse eşik yükselir (daha seçici)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/scanner/opportunity_engine.py`

---

## 6. Çıktı

```
#   Hisse    Skor   Sinyal         Yön     Fiyat
1   THYAO    77.5   MOMENTUM       LONG    305.25
2   ASELS    72.3   BREAKOUT       LONG     38.50
3   AKBNK    68.1   SPEC           SHORT    68.80
...
```

Her fırsat için: skor, sinyal türü, yön, fiyat, decomposition (hangi motor ne kadar katkı yaptı), evidence, risks.
