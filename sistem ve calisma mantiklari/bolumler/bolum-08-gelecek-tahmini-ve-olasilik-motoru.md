# Bölüm 8 — Gelecek Tahmini ve Olasılık Motoru

## Amaç

Hissenin geleceğini tek bir fiyatla tahmin etmek yerine, olası sonuçları ve bunların gerçekleşme ihtimallerini hesaplamak.

---

## Kullanılacak sistemler

- Forecasting Engine
  - Time-Series Models
  - Fundamental Forecast
  - Technical Forecast
  - Macro Forecast
  - AI Forecast
- Probability Engine
  - Confidence Calibration
  - Uncertainty Analysis

---

## Çalışma mantığı

```
Geçmiş Fiyat/Hacim + Fundamental + Technical + Makro + Sektör + Haber/KAP + Değerleme
    ↓
Forecasting Engine
    ↓
Bull / Base / Bear
    ↓
Olasılık Dağılımı
    ↓
Beklenen Getiri
    ↓
Confidence + Uncertainty
```

---

## Nasıl kullanılacak?

Sistem örneğin:

- Bull → 170 TL → %25 olasılık
- Base → 145 TL → %50 olasılık
- Bear → 105 TL → %25 olasılık

gibi senaryolar oluşturabilir.

Ama bunları rastgele belirlemeyecek.

Her senaryonun arkasında:

- finansal beklentiler
- teknik yapı
- piyasa rejimi
- sektör
- makro
- haber/KAP
- değerleme

olacak.

---

## Modeller birbirini nasıl etkiler?

Örneğin:

- **Fundamental** → Uzun vadeli beklenti
- **Technical** → Kısa/orta vadeli momentum
- **Macro** → Piyasa koşulları
- **News/KAP** → Ani olay etkisi
- **Valuation** → Fiyat hedefinin mantıklı sınırı

Bunlar birleştirilerek tek bir modelin kör noktası azaltılır.

---

## Confidence

Model:

> "145 TL olacak."

demek yerine:

> "145 TL civarı için %X güvenim var; belirsizliğin ana kaynağı Y."

diyebilmeli.

Tahminler gerçekleşen sonuçlarla sürekli karşılaştırılarak confidence calibration yapılacak.

---

## Çıktı

```
Expected Price:    145 TL
Expected Return:   +31%
Bull Probability:  %25
Base Probability:  %50
Bear Probability:  %25
Confidence:        %82
Uncertainty:       Orta
```

Bu çıktı Bölüm 9 — Monte Carlo ve Senaryo Motoru tarafından daha geniş olasılık simülasyonuna dönüştürülür.

---

## Temel prensip

Sistem geleceği "bilmiş gibi" davranmaz; **olasılık dağılımı + belirsizlik + güven seviyesi** üretir.
