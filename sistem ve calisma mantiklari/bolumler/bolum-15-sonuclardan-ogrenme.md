# Bölüm 15 — Sonuçlardan Öğrenme ve Model Geri Besleme

## Amaç

Sistem verdiği tahminlerin ve kararların sonuçlarını takip edip nerede doğru, nerede yanlış olduğunu öğrenmek.

---

## Kullanılacak sistemler

- Outcome Tracking
- Prediction Evaluation
- Model Performance
- Confidence Calibration
- Error Analysis
- Performance Attribution
- Research Memory
- Model Feedback Loop

---

## Çalışma mantığı

```
Tahmin / Karar
    ↓
Gerçekleşen Sonuç
    ↓
Karşılaştırma
    ↓
Hata Analizi
    ↓
Neden Yanıldı?
    ↓
Model / Faktör Performansı
    ↓
Calibration
    ↓
Memory
    ↓
Gelecek Kararlar
```

---

## Neler takip edilecek?

Örneğin sistem:

> Hisse X için %80 yükseliş confidence'ı verdi.

Sonuç:

> Hisse %3 düştü.

Sistem sadece "yanlış tahmin" demeyecek.

Şunları araştıracak:

- Teknik sinyal mi yanıldı?
- Fundamental varsayım mı yanlıştı?
- Haber etkisi yanlış mı ölçüldü?
- Market regime değişti mi?
- Monte Carlo dağılımı hatalı mıydı?
- Confidence fazla mı yüksekti?
- Veri kalitesinde sorun var mıydı?

---

## Confidence Calibration

Örneğin:

> Model %80 confidence verdiği tahminler
> Gerçekte %58 başarılı

ise sistem modelin aşırı güvenli olduğunu tespit eder.

Böylece confidence kalibrasyonu zaman içinde düzeltilir.

---

## Faktörlerin gerçek performansı

Sistem ayrıca:

- Momentum → başarılı
- Value → orta
- News sentiment → zayıf
- KAP signals → güçlü

gibi hangi sinyallerin gerçekten işe yaradığını takip eder.

---

## Çok önemli prensip

**Model kendi kendine sessizce değişmez.**

Öğrenme sonucunda:

```
Observed Problem
    ↓
Analysis
    ↓
Proposed Change
    ↓
Backtest
    ↓
Validation
    ↓
Shadow Test
    ↓
Production
```

süreci uygulanır.

---

## Çıktı

```
Prediction Accuracy:    %67
Calibration Error:      %4.2
Best Signal:            KAP/Event
Weakest Signal:         Social Sentiment
Detected Issues:        3
Improvement Candidates: 2
```

---


---

**Kaynak:** Learning — prediction→outcome→feedback loop. Confidence calibration. Drift detection.


### Örnek: Prediction recording

```python
# services/learning/integrated_learning.py
from services.learning.integrated_learning import integrated_learning

# Her karar anında
integrated_learning.record_decision(
    ticker="THYAO",
    decision={"direction": "LONG", "action": "BUY", "composite_score": 70},
    features={"momentum_20d": 5, "rsi_14": 60, "price": 305.25},
    regime="BULL",
)
# prediction_id = "THYAO-20260816120000"
# feature_snapshot = {"price": 305.25, "momentum_20d": 5, ...}
```

### Örnek: Outcome recording

```python
# 5 gün sonra
integrated_learning.record_outcome(
    ticker="THYAO", actual_price=320.0, entry_price=305.25,
    holding_days=5, outcome_type="auto",
)
# predicted: LONG, actual: LONG → DOĞRU
# accuracy güncellendi
```

## Temel prensip

Sistem geçmiş kararlarını unutmaz; **tahmin → gerçek sonuç → hata → öğrenme → doğrulama → yeni model** döngüsüyle zaman içinde kendini **ölçülebilir şekilde** geliştirir.
