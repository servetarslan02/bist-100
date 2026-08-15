# Bölüm 3 — Piyasa Analizi ve Rejim Belirleme

## Amaç

Temizlenmiş verilerden piyasada şu anda hangi ortamın yaşandığını belirlemek. Hisse seçmeden önce piyasanın yönü, gücü ve risk seviyesi anlaşılır.

**Kaynak:** Springer (2026) Regime-Aware Adaptive Forecasting, AIMS (2025) Multi-Model Ensemble-HMM, MDPI (2026) Regime-Aware LightGBM, Nature (2026) Regime-Aware GNN.

---

## Kullanılacak sistemler

- Technical Analysis
- Price Action
- Volume Analysis
- Volatility Engine
- Market Regime Detection
- Correlation Engine
- Macro Analysis
- Sector Analysis
- Relative Strength
- Anomaly Detection

---

## Çalışma mantığı

```
Temiz Veri → Endeks Analizi → Trend + Momentum → Hacim →
Volatilite → Makro Durum → Sektör Dağılımı → Korelasyonlar →
Anomali Kontrolü → MARKET REGIME
```

---

## 1. Rejim Tespiti

**Araştırma bulguları:**

**Springer (2026):** "Market regimes (bull, bear, sideways) should be based on statistical characteristics rather than arbitrary thresholds."

**MDPI (2026):** "A three-state Gaussian HMM identifies bull, bear, and sideways regimes based on risk-adjusted returns."

**Nature (2026):** "HMM assisted regime-aware learnable graph neural networks explicitly model market regime transitions."

**Kritik bulgu:** Keyfi eşikler ("%5 düşüş = bear") yerine feature-based yaklaşımlar daha güvenilir.

### Örnek: Feature-based rejim tespiti

```python
# services/intelligence/regime.py
from services.intelligence.regime import regime_engine

features = {
    "breadth_pct": 72,        # %72 hisse yükseliyor
    "momentum_avg": 5.0,      # Ortalama momentum pozitif
    "volatility_avg": 18,     # Düşük volatilite
    "rsi_avg": 62,            # RSI ortalaması
    "risk_appetite": 0.7,     # Yüksek risk iştahı
    "vix_level": 14,          # Düşük VIX
}

result = regime_engine.detect_regime(features)
# result.regime = BULL
# result.confidence = 0.85
# result.duration_hours = 48

weights = regime_engine.get_regime_weights(result.regime)
# momentum: 0.25 (yüksek), defensive: 0.15 (düşük)
```

---

## 2. Breadth Analizi

Yükselen/düşen hisse oranı.

### Örnek: Breadth hesaplama

```python
# services/features/cross_sectional.py
from services.features.cross_sectional import CrossSectionalEngine

engine = CrossSectionalEngine()
universe = {
    "THYAO": {"return_1d": 2.0}, "ASELS": {"return_1d": -1.5},
    "GARAN": {"return_1d": 1.0}, "AKBNK": {"return_1d": -0.5},
}
breadth = engine.compute_market_breadth_features(universe)
# market_breadth: 0.6 (3 yükselen / 5 toplam)
```

---

## 3. Sektör Analizi

### Örnek: Sektör momentum

```python
engine = CrossSectionalEngine()
sector_mom = engine.compute_sector_momentum(
    {"THYAO": {"momentum_20d": 10}, "GARAN": {"momentum_20d": -3}},
    {"THYAO": "AVIATION", "GARAN": "BANK"},
)
# sector_momentum_AVIATION: 10.0
# sector_momentum_BANK: -3.0
```

---

## 4. Volatilite Analizi

### Örnek: Volatilite rejimi

```python
# services/features/seven_motors.py → Motor 2
features = motor.compute("THYAO", close, high, low, volume)
# features["realized_vol_20d"] = 25.3
# features["atr_14_pct"] = 2.8
```

---

## Çıktı

```
Piyasa rejimi:     BULL
Confidence:        %85
BIST100 trendi:    Yukarı
Momentum:          Güçlü (+5.0)
Volatilite:        Düşük (18%)
Breadth:           %72 yükselen
Güçlü sektörler:   Teknoloji (+8%), Enerji (+6%)
Risk seviyesi:     Düşük
```

---

## Temel prensip

> "Feature-based approaches outperform threshold-based methods in regime detection." — Springer (2026)
