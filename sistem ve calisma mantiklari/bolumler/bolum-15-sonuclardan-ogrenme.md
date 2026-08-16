# Bölüm 15 — Sonuçlardan Öğrenme ve Model Geri Besleme

## Amaç

Sistem verdiği tahminlerin ve kararların sonuçlarını takip edip nerede doğru, nerede yanlış olduğunu öğrenmek.

**Kaynak:** Aerospike (2025) Model Drift Detection, arXiv TimeSeek (2026) Temporal Reliability, FSB (2026) AI Risk Management.

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
Tahmin/Karar → Gerçekleşen Sonuç → Karşılaştırma → Hata Analizi →
Neden Yanıldı? → Model Performansı → Calibration → Memory → Gelecek Kararlar
```

---

## 1. Prediction → Outcome Döngüsü

### Örnek: Prediction recording

```python
# services/learning/integrated_learning.py
from services.learning.integrated_learning import integrated_learning

integrated_learning.record_decision("THYAO",
    {"direction": "LONG", "action": "BUY", "composite_score": 70},
    {"momentum_20d": 5, "rsi_14": 60, "price": 305.25}, "BULL")
# prediction_id: "THYAO-20260816120000"
# feature_snapshot: {"price": 305.25, "momentum_20d": 5, ...}
```

### Örnek: Outcome recording

```python
# 5 gün sonra
integrated_learning.record_outcome("THYAO", 320.0, 305.25, 5, "auto")
# predicted: LONG, actual: LONG → DOĞRU
# accuracy güncellendi
```

---

## 2. Confidence Calibration

**Araştırma bulgusu:** arXiv TimeSeek (2026) — "Temporal drift in large language models. Calibration drift detection."

Model %80 confidence verdiği tahminlerin gerçekten %80'i doğru mu?

### Örnek: Calibration kontrolü

```python
# services/learning/integrated_learning.py
insights = integrated_learning.get_insights()
# overall_accuracy: 0.67
# recent_accuracy: 0.72
# best_regime: BULL (%75 doğruluk)
# worst_regime: HIGH-VOLATILITY (%45 doğruluk)
```

---

## 3. Drift Detection

**Araştırma bulgusu:** Aerospike (2025) — "What model drift is, how data and concept drift arise, how to detect drift."

### Drift türleri:
- **Feature drift:** Feature dağılımı değişti
- **Prediction drift:** Tahmin dağılımı değişti
- **Outcome drift:** Gerçek sonuç dağılımı değişti
- **Regime drift:** Piyasa rejimi değişti

---

## 4. Hata Kalıpları

Sistem hangi koşullarda hata yapıyor?

```
HIGH-VOLATILITY rejimde → %35 doğruluk (düşük)
BULL rejimde → %75 doğruluk (yüksek)
Yüksek skorlu tahminlerde → bile hata yapılıyor
```

---

## 5. Kritik Prensip

**Model kendi kendine sessizce değişmez.**

```
Observed Problem → Analysis → Proposed Change →
Backtest → Validation → Shadow Test → Production
```

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

## Temel prensip

> "Monitoring and retraining keep production models healthy." — Aerospike (2025)

Sistem geçmiş kararlarını unutmaz; **tahmin → sonuç → hata → öğrenme** döngüsüyle kendini geliştirir.
