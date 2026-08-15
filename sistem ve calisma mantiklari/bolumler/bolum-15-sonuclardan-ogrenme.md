# Bölüm 15 — Sonuçlardan Öğrenme ve Model Geri Besleme

## Amaç

Sistem verdiği tahminlerin ve kararların sonuçlarını takip edip nerede doğru, nerede yanlış olduğunu öğrenmek.

**Kaynak:** Confidence calibration, prediction→outcome feedback loop.

## Çalışma mantığı

```
Tahmin/Karar → Gerçekleşen Sonuç → Karşılaştırma → Hata Analizi →
Neden Yanıldı? → Model Performansı → Calibration → Memory → Gelecek Kararlar
```

### Örnek: Prediction recording

```python
from services.learning.integrated_learning import integrated_learning

integrated_learning.record_decision("THYAO",
    {"direction": "LONG", "action": "BUY", "composite_score": 70},
    {"momentum_20d": 5, "rsi_14": 60, "price": 305.25}, "BULL")
```

### Örnek: Outcome recording

```python
integrated_learning.record_outcome("THYAO", 320.0, 305.25, 5, "auto")
# predicted: LONG, actual: LONG → DOĞRU
```

## Temel prensip

Sistem geçmiş kararlarını unutmaz; tahmin → sonuç → hata → öğrenme döngüsüyle kendini geliştirir.
