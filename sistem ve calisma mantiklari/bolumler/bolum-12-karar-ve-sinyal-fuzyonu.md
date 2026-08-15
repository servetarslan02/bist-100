# Bölüm 12 — Karar ve Sinyal Füzyonu

## Amaç

Şimdiye kadar gelen bütün analizleri tek bir karar mekanizmasında birleştirmek.

**Kaynak:** Regime-conditioned signal weighting, conflict detection.

## Çalışma mantığı

```
Technical + Fundamental + Valuation + News/KAP + Macro + Sector + Forecast +
Monte Carlo + Risk + Portfolio → SİNYAL FÜZYONU → Çelişki Analizi →
Ağırlıklandırma → Confidence → Karar
```

### Örnek: Signal fusion

```python
from services.intelligence.signal_fusion import signal_fusion_engine

signals = {
    "technical": {"direction": "LONG", "score": 70},
    "fundamental": {"direction": "LONG", "score": 65},
    "news": {"direction": "SHORT", "score": 30},  # Çelişki!
    "opportunity": {"score": 72},
}
result = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
# fused_direction: LONG, has_conflict: True
# conflict_details: ["technical LONG vs news SHORT"]
```

## Temel prensip

Farklı analizleri basitçe ortalamaz; hangi sinyalin hangi koşulda daha anlamlı olduğunu değerlendirir.
