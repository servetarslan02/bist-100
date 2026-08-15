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

## Temel prensip

Sistem geçmiş kararlarını unutmaz; **tahmin → gerçek sonuç → hata → öğrenme → doğrulama → yeni model** döngüsüyle zaman içinde kendini **ölçülebilir şekilde** geliştirir.
