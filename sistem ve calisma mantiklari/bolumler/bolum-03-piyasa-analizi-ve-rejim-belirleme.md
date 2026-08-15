# Bölüm 3 — Piyasa Analizi ve Rejim Belirleme

## Amaç

Temizlenmiş verilerden piyasada şu anda hangi ortamın yaşandığını belirlemek. Hisse seçmeden önce piyasanın yönü, gücü ve risk seviyesi anlaşılır.

**Kaynak:** Springer (2026) Regime-Aware Adaptive Forecasting, AIMS (2025) Multi-Model Ensemble-HMM, MDPI (2026) Regime-Aware LightGBM.

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
Temiz Veri
    ↓
Endeks Analizi
    ↓
Trend + Momentum
    ↓
Hacim
    ↓
Volatilite
    ↓
Makro Durum
    ↓
Sektör Dağılımı
    ↓
Korelasyonlar
    ↓
Anomali Kontrolü
    ↓
MARKET REGIME
```

---

## 1. Endeks Analizi

BIST100'ün genel yönünü ve gücünü ölçer.

**Hesaplanacaklar:**
- BIST100 trendi (yukarı/aşağı/yatay)
- Trend gücü (ADX, R²)
- Hacim artışı/azalışı
- Yeni yüksek/düşük yapan hisse sayısı

### Örnek: Breadth hesaplama

```python
# services/features/cross_sectional.py
from services.features.cross_sectional import CrossSectionalEngine

engine = CrossSectionalEngine()

# Tüm BIST için breadth
universe_features = {
    "THYAO": {"return_1d": 2.0},
    "ASELS": {"return_1d": -1.5},
    "GARAN": {"return_1d": 1.0},
    "AKBNK": {"return_1d": -0.5},
    "EREGL": {"return_1d": 3.0},
}

breadth = engine.compute_market_breadth_features(universe_features)
# breadth["market_breadth"] = 0.6 (3 yükselen / 5 toplam)
# breadth["market_advancing"] = 3
# breadth["market_declining"] = 2
```

---

## 2. Rejim Tespiti

Piyasanın hangi rejimde olduğunu belirler.

**Rejimler:**
- BULL / BEAR / SIDEWAYS
- HIGH-VOLATILITY / LOW-VOLATILITY
- RISK-ON / RISK-OFF
- CRISIS / RECOVERY
- MOMENTUM-EXPANSION / MOMENTUM-CONTRACTION

### Araştırma bulgusu

**Springer (2026):** Rejim tespitinde keyfi eşikler (">%5 düşüş = bear") yerine istatistiksel karakteristikler kullanılmalı. HMM (Hidden Markov Model) ve feature-based yaklaşımlar daha güvenilir.

**MDPI (2026):** Regime-aware LightGBM — farklı rejimlerde farklı modeller kullanmak tek modelden daha iyi performans veriyor.

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
    "usdtry_momentum": 1,     # USDTRY stabil
    "vix_level": 14,          # Düşük VIX
    "global_momentum": 2,     # Global piyasa pozitif
}

result = regime_engine.detect_regime(features)
# result.regime = BULL
# result.confidence = 0.85
# result.duration_hours = 48

# Rejime göre ağırlıklar
weights = regime_engine.get_regime_weights(result.regime)
# momentum: 0.25 (yüksek), defensive: 0.15 (düşük)
```

### Örnek: Rejim değişimi etkisi

```python
# RISK-OFF rejiminde:
weights = regime_engine.get_regime_weights("RISK-OFF")
# defensive: 0.40 (yüksek), momentum: 0.10 (düşük)

# Karşılaştırma: BULL rejiminde
weights = regime_engine.get_regime_weights("BULL")
# momentum: 0.25 (yüksek), defensive: 0.15 (düşük)
```

**Kaynak:** AIMS (2025) — Multi-Model Ensemble-HMM voting framework.

---

## 3. Sektör Dağılımı

Sektör bazlı performans ve rotasyon analizi.

**Hesaplanacaklar:**
- Sektör momentum
- Sektör rotasyonu (hangi sektör lider, hangi geride)
- Sektör relatif gücü
- Sektör konsantrasyonu

### Örnek: Sektör momentum

```python
# services/features/cross_sectional.py
engine = CrossSectionalEngine()

universe_features = {
    "THYAO": {"momentum_20d": 10},
    "ASELS": {"momentum_20d": 8},
    "GARAN": {"momentum_20d": -3},
    "AKBNK": {"momentum_20d": -2},
}
sectors = {
    "THYAO": "AVIATION", "ASELS": "TECH",
    "GARAN": "BANK", "AKBNK": "BANK",
}

sector_mom = engine.compute_sector_momentum(universe_features, sectors)
# sector_momentum_AVIATION: 10.0
# sector_momentum_TECH: 8.0
# sector_momentum_BANK: -2.5
```

---

## 4. Volatilite Analizi

Piyasanın ne kadar hareketli olduğunu ölçer.

**Metrikler:**
- BIST100 realized volatilite (20 gün)
- VIX seviyesi ve trendi
- ATR (Average True Range)
- Volatilite rejimi (LOW/NORMAL/HIGH/EXTREME)

### Örnek: Volatilite rejimi

```python
# services/features/seven_motors.py → Motor 2
from services.features.seven_motors import MomentumTrendMotor

motor = MomentumTrendMotor()
features = motor.compute("THYAO", close, high, low, volume)

# features["realized_vol_20d"] = 25.3
# features["atr_14"] = 8.5
# features["atr_14_pct"] = 2.8
```

---

## 5. Korelasyon Analizi

Piyasa bileşenleri arasındaki ilişkileri ölçer.

**Metrikler:**
- Hisse-BIST korelasyonu
- Hisse-Sektör korelasyonu
- Sektör-BIST korelasyonu
- Makro korelasyonlar (USDTRY, VIX, petrol)

### Örnek: Korelasyon hesaplama

```python
# services/features/seven_motors.py → Motor 1
from services.features.seven_motors import RelativeStrengthMotor

motor = RelativeStrengthMotor()
features = motor.compute(
    "THYAO", stock_close, benchmark_close,
    sector_close=sector_close,
    peer_closes={"ASELS": asels_close, "PGSUS": pgsus_close},
)

# features["rs_vs_bist_20d"] = +5.2%  (BIST'ten iyi)
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

# Fiyat anomalisi
result = streaming_anomaly_detector.check_price("THYAO", 350.0, 305.0, volatility=0.25)
# is_anomaly: True, severity: CRITICAL

# Hacim anomalisi
result = streaming_anomaly_detector.check_volume("THYAO", 5000000)
# is_anomaly: True, zscore: 4.5
```

---

## Çıktı

```
MARKET REGIME
──────────────────────────────
Piyasa rejimi:     BULL
Confidence:        %85
Süre:              48 saat
──────────────────────────────
BIST100 trendi:    Yukarı
Momentum:          Güçlü (+5.0)
Volatilite:        Düşük (18%)
Breadth:           %72 yükselen
──────────────────────────────
Güçlü sektörler:   Teknoloji (+8%), Enerji (+6%)
Zayıf sektörler:   Bankacılık (-3%)
──────────────────────────────
Risk seviyesi:     Düşük
VIX:               14.25
USDTRY:            Stabil
```

Bu bölüm hisse önermez. Hisse bulma motoruna, "şu an nasıl bir piyasada seçim yapıyoruz?" bilgisini verir.

---

## Temel prensip

Rejim tespitinde **keyfi eşikler** kullanılmayacak.

Araştırma bulgusu:

> "Feature-based approaches outperform threshold-based methods in regime detection." — Springer (2026)

Sistem, birden fazla feature'ın birlikte değerlendirmesiyle rejim belirler.
