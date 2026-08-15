# Bölüm 12 — Karar ve Sinyal Füzyonu

## Amaç

Şimdiye kadar gelen bütün analizleri tek bir karar mekanizmasında birleştirmek. Burada sistem ilk kez nihai yatırım kararına yaklaşır.

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
Technical
Fundamental
Valuation
News/KAP
Macro
Sector
Forecast
Monte Carlo
Risk
Portfolio
    ↓
SİNYAL FÜZYONU
    ↓
Çelişki Analizi
    ↓
Ağırlıklandırma
    ↓
Confidence
    ↓
Karar
```

---

## En önemli nokta: Sabit ağırlık yok

Her durumda:

> Technical %20 + Fundamental %20...

gibi kör bir formül kullanılmayacak.

Piyasa rejimine ve zaman ufkuna göre ağırlıklar değişebilecek.

Örneğin kısa vadeli işlemde teknik/momentum daha önemli olabilirken, uzun vadeli yatırımda fundamental/değerleme daha fazla ağırlık kazanabilir.

---

## Çelişen sinyaller

Örneğin:

- Fundamental → Çok güçlü
- Valuation → Ucuz
- News → Pozitif
- Technical → Çok zayıf
- Risk → Yüksek

Sistem bunları gizleyip tek bir yüksek skor üretmeyecek.

**Neden çeliştiklerini analiz edecek.**

---

## Confidence

Sonuç sadece skor olmayacak:

```
Opportunity Score: 86/100
Confidence:        %79
Risk:              Orta
Expected Return:   +31%
Downside:          -14%
```

Confidence düşükse sistem bunu açıkça belirtecek.

---

## Karar seviyeleri

```
STRONG BUY
BUY
WATCH
HOLD
REDUCE
AVOID
NO_TRADE
```

**NO_TRADE**, sistemin yeterli kanıt veya güven görmediği durumlarda özellikle önemli.

---

## Kararın gerekçesi

Sonuç mutlaka açıklanabilir olmalı:

```
Karar: BUY
Pozitif:
  + Güçlü fundamental
  + Ucuz valuation
  + Pozitif catalyst
  + İyi sektör
Negatif:
  - Teknik momentum zayıf
  - Volatilite yüksek
Ana risk:           ...
Kararı destekleyen kanıtlar: ...
```

---

## Sonraki bölümlerle bağlantı

Karar doğrudan Backtest / Paper Trading / Execution Simulation sistemlerine gönderilebilir.

Gerçek emir söz konusuysa ayrıca **Risk Gate** kararın önüne geçer.

---


---

**Kaynak:** Signal fusion — not simple average. Weight changes with regime. Conflict detection between signals.


### Örnek: Signal fusion

```python
# services/intelligence/signal_fusion.py
from services.intelligence.signal_fusion import signal_fusion_engine

signals = {
    "technical": {"direction": "LONG", "score": 70},
    "fundamental": {"direction": "LONG", "score": 65},
    "momentum": {"direction": "LONG", "score": 80},
    "news": {"direction": "SHORT", "score": 30},  # Çelişki!
    "macro": {"direction": "NEUTRAL", "score": 50},
    "valuation": {"direction": "LONG", "score": 75},
    "ai": {"direction": "LONG", "score": 68},
    "opportunity": {"score": 72},
}

result = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
# result.fused_direction = "LONG"
# result.fused_confidence = 0.65
# result.has_conflict = True
# result.conflict_details = ["technical LONG vs news SHORT"]
# result.reasons = ["Momentum güçlü: 80", "Değerleme cazip: 75"]
# result.risks = ["Sinyal çakışması var"]
```

## Temel prensip

Bu bölüm farklı analizleri basitçe ortalamaz; **hangi sinyalin hangi koşulda daha anlamlı olduğunu** değerlendirip, **çelişkileri ve belirsizliği** de hesaba katarak **açıklanabilir bir karar** üretir.
