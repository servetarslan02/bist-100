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

## 5. Korelasyon Analizi

Piyasa bileşenleri arasındaki ilişkileri ölçer.

### Örnek: Korelasyon

```python
# services/features/seven_motors.py → Motor 1
from services.features.seven_motors import RelativeStrengthMotor

motor = RelativeStrengthMotor()
features = motor.compute(
    "THYAO", stock_close, benchmark_close,
    sector_close=sector_close,
    peer_closes={"ASELS": asels_close, "PGSUS": pgsus_close},
)
# features["rs_vs_bist_20d"] = +5.2% (BIST'ten iyi)
# features["rs_vs_sector_20d"] = +2.1% (Sektörden iyi)
# features["rs_trend"] = +0.8 (güçleniyor)
```

---

## 6. Anomali Kontrolü

Olağandışı fiyat/hacim hareketlerini tespit eder.

### Örnek: Anomali tespiti

```python
# services/core/streaming_anomaly.py
from services.core.streaming_anomaly import streaming_anomaly_detector

result = streaming_anomaly_detector.check_price("THYAO", 350.0, 305.0, volatility=0.25)
# is_anomaly: True, severity: CRITICAL

result = streaming_anomaly_detector.check_volume("THYAO", 5000000)
# is_anomaly: True, zscore: 4.5
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
