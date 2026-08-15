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


---

**Kaynak:** Ensemble approach — technical + statistical + ML + LLM + Monte Carlo. Each model has different blind spots.


### Örnek: Forecasting

```python
# services/intelligence/forecasting.py
from services.intelligence.forecasting import forecasting_engine

features = {"momentum_20d": 5, "realized_vol_20d": 20, "rsi_14": 60}
forecasts = forecasting_engine.compute_forecasts("THYAO", features, [1, 2, -1])
# forecasts[0]: horizon=1d, predicted_return=0.5%, confidence=0.8
# forecasts[1]: horizon=5d, predicted_return=1.2%, confidence=0.7
# forecasts[2]: horizon=20d, predicted_return=3.5%, confidence=0.6
```

### Örnek: Probability from features

```python
from services.intelligence.probability import probability_engine

features = {"roc_5d": 5, "momentum_20d": 10, "rsi_14": 60}
prob = probability_engine.compute_probability_from_features(features)
# prob["probability_positive"] = 0.68
# prob["confidence"] = 0.36
```

## Temel prensip

Sistem geleceği "bilmiş gibi" davranmaz; **olasılık dağılımı + belirsizlik + güven seviyesi** üretir.
