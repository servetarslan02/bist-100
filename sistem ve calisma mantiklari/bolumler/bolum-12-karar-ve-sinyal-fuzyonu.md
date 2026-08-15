# Bölüm 12 — Karar ve Sinyal Füzyonu

## Amaç

Şimdiye kadar gelen bütün analizleri tek bir karar mekanizmasında birleştirmek. Burada sistem ilk kez nihai yatırım kararına yaklaşır.

**Kaynak:** arXiv RMATS (2026) Recursive Multi-Agent Trading System — integrates four specialist agents (Sentiment, Report, Analysis, Risk).

---

## Kullanılacak sistemler

- Signal Fusion Engine
- Technical Score
- Fundamental Score
- Valuation Score
- News/KAP Score
- Macro Score
- Sector Score
- Forecast Probability
- Monte Carlo
- Risk Score
- Portfolio Score
- Confidence Engine
- Evidence / Source Verification

---

## Çalışma mantığı

```
Technical + Fundamental + Valuation + News/KAP + Macro + Sector + Forecast +
Monte Carlo + Risk + Portfolio → SİNYAL FÜZYONU → Çelişki Analizi →
Ağırlıklandırma → Confidence → Karar
```

---

## 1. Sabit Ağırlık Yok

**Kritik:** Piyasa rejimine ve zaman ufkuna göre ağırlıklar değişir.

- Kısa vadeli: teknik/momentum daha önemli
- Uzun vadeli: fundamental/değerleme daha önemli

---

## 2. Çelişen Sinyaller

### Örnek: Çelişki tespiti

```python
# services/intelligence/signal_fusion.py
from services.intelligence.signal_fusion import signal_fusion_engine

signals = {
    "technical": {"direction": "LONG", "score": 70},
    "fundamental": {"direction": "LONG", "score": 65},
    "news": {"direction": "SHORT", "score": 30},  # Çelişki!
    "opportunity": {"score": 72},
}

result = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
# fused_direction: LONG
# has_conflict: True
# conflict_details: ["technical LONG vs news SHORT"]
# reasons: ["Momentum güçlü: 70", "Fundamental pozitif: 65"]
# risks: ["Sinyal çakışması var"]
```

---

## 3. Confidence

Sonuç sadece skor olmayacak:

```
Opportunity Score: 86/100
Confidence:        %79
Risk:              Orta
Expected Return:   +31%
Downside:          -14%
```

---

## 4. Karar Seviyeleri

```
STRONG BUY / BUY / WATCH / HOLD / REDUCE / AVOID / NO_TRADE
```

**NO_TRADE**, sistemin yeterli kanıt veya güven görmediği durumlarda özellikle önemli.

---

## 5. Kararın Gerekçesi

```
Karar: BUY
Pozitif: + Güçlü fundamental + Ucuz valuation + Pozitif catalyst
Negatif: - Teknik momentum zayıf - Volatilite yüksek
Ana risk: ...
```

---

## Temel prensip

> "RMATS integrates four specialist agents and outputs structured ensemble decisions." — arXiv (2026)

Farklı analizleri basitçe ortalamaz; **hangi sinyalin hangi koşulda daha anlamlı olduğunu** değerlendirir.
