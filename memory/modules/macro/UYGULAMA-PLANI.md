# 🚀 Macro Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Araştırma + Kod Analizi)
**Kaynaklar:** SBB Medium Term Program (2026-2028), ResearchGate Exchange Rate & Inflation Turkey (2026), J.P. Morgan QIS Conference (2026), ECB Financial Stability Review (2026), AIMS Press Multi-Model HMM (2025), arXiv Agentic Trading (2026)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Entegrasyon Noktaları](#3-entegrasyon-noktaları)
4. [Genel Mimari Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 Makro Faktör Modeli — En İyi Uygulama

**Temel Prensip:** Makro veriler tek başına anlamlı değil, birlikte ve bağlam içinde anlamlı.

**Referans Mimariler:**

| Kaynak | Model | Kritik Bulgu |
|--------|-------|-------------|
| J.P. Morgan QIS (2026) | Multi-factor macro model | Surprise = actual - consensus, sector sensitivity dinamik olmalı |
| AIMS Press (2025) | Multi-model HMM voting | HMM + K-means ensemble → rejim tespitinde %15 daha iyi |
| SBB (2026-2028) | Medium Term Program | Türkiye'ye özgü: cari açık, döviz borcu, enflasyon beklentisi kritik |
| ECB (2026) | Financial Stability Review | Macro-financial linkages: faiz → kredi → büyüme → BIST zinciri |
| arXiv (2026) | Agentic Trading Meta-Analiz | Macro regime değişimi → strateji değişimi zorunlu |

### 1.2 Türkiye'ye Özgü Makro Dinamikler

| Makro Değişken | BIST Etkisi | Mekanizma | Türkiye Özgüllüğü |
|----------------|-------------|-----------|-------------------|
| **USDTRY** | 🔴 Yüksek | İthalat maliyeti, döviz borcu, ihracat geliri | Türkiye'de şirketlerin %60+'ı döviz borcu taşıyor |
| **TCMB Faiz** | 🔴 Yüksek | Kredi maliyeti, değerleme, sermaye akışı | Türkiye'de faiz enflasyonu geçişkenliği yüksek |
| **Enflasyon (CPI)** | 🔴 Yüksek | Tüketici baskısı, maliyet artışı, değerleme | Türkiye'de enflasyon beklentisi çıpalanamıyor |
| **CDS Spread** | 🟡 Orta-Yüksek | Ülke risk primi, yabancı yatırımcı algısı | Türkiye CDS'i gelişmekte olan piyasalarla korele |
| **Cari Açık** | 🟡 Orta | Döviz ihtiyacı, kur baskısı | Türkiye'de cari açık kronik yapısal sorun |
| **Kredi Büyümesi** | 🟡 Orta | Ekonomik aktivite, balon riski | Türkiye'de kredi büyümesi politik araç olarak kullanılıyor |
| **VIX** | 🟡 Orta | Global risk iştahı | Türkiye VIX'e diğer EM'lere göre daha hassas |
| **Altın** | 🟢 Düşük-Orta | Güvenli liman, enflasyon hedge | Türkiye'de altın kültürel yatırım aracı |
| **Petrol** | 🟡 Orta | Enerji maliyeti, enflasyon baskısı | Türkiye net petrol ithalatçısı |
| **S&P500/Nasdaq** | 🟡 Orta | Global piyasa sentiment | Türkiye correlations risk-on/risk-off'a bağlı |

### 1.3 Makro Şok Analizi — En İyi Uygulama

**Şok Türleri (Türkiye Odaklı):**

1. **Para Politikası Sürprizi** — TCMB faiz değişimi (beklenti vs gerçek)
2. **Enflasyon Sürprizi** — TÜİK CPI beklenti dışı
3. **Kur Şoku** — USDTRY ani hareket (> %3 günlük)
4. **Global Risk-Off** — VIX spike, S&P500 düşüş
5. **Emtia Şoku** — Petrol/altın ani hareket
6. **Jeopolitik Şok** — Savaş, yaptırım, siyasi kriz

**Her şok için hesaplanması gereken:**
- Magnitude (büyüklük)
- Surprise (beklenti dışı kısım)
- Decay (etki azalma hızı — half-life modeli)
- Sector Impact (sektör bazlı etki — 10 sektör)
- Company Impact (şirket bazlı etki — döviz borcu, ithalat bağımlılığı)

### 1.4 Macro Regime Detection — HMM Voting Framework

**Kaynak:** AIMS Press (2025) — Multi-Model Ensemble HMM Voting

**6 Makro Rejim:**

| Rejim | Tanım | Karakteristikler | BIST Etkisi |
|-------|-------|-----------------|-------------|
| **EXPANSION** | Genişleyici | Düşük faiz, düşük enflasyon, güçlü büyüme | Pozitif — büyüme hisseleri primli |
| **CONTRACTION** | Daraltıcı | Yüksek faiz, yüksek enflasyon, zayıf büyüme | Negatif — defansif hisseler tercih |
| **STAGFLATION** | Stagflasyon | Yüksek enflasyon, zayıf büyüme, yüksek faiz | Çok negatif — değer kaybı yaygın |
| **REFLATION** | Reflasyon | Düşük faiz, yükselen enflasyon, toparlanma | Karışık — emtia ve döviz odaklı |
| **RISK_ON** | Risk Açıklığı | Düşük VIX, yükselen S&P500, düşük CDS | Pozitif — büyüme ve teknoloji primli |
| **RISK_OFF** | Risk Kaçışı | Yüksek VIX, düşen S&P500, yükselen CDS | Negatif — defansif ve altın primli |

**Tespit Yöntemi:** Skor bazlı (ağırlıklı puanlama) — her rejim için 6 makro değişkenden skor hesapla, en yüksek skorlu rejim seç.

---

## 2. Mevcut Sistem Analizi

### 2.1 Dosya Yapısı (İlgili Dosyalar)

```
services/macro/
├── __init__.py                 # 1 satır
├── calendar.py                 # 26 satır — MACRO_EVENTS dict
├── cds.py                      # 12 satır — cds_5y, cds_change, risk_level
├── credit.py                   # 12 satır — credit_growth_yoy, credit_gdp_ratio
├── current_account.py          # 12 satır — ca_balance, ca_trend
├── fx.py                       # 14 satır — usdtry, usdtry_change, volatility
├── inflation.py                # 14 satır — cpi_yoy, ppi_yoy, core_cpi
└── tcmb.py                     # 14 satır — policy_rate, real_rate, rate_surprise

services/features/
└── macro.py                    # 281 satır — MacroFeatureEngine

services/intelligence/
└── macro_sensitivity.py        # 208 satır — MacroSensitivityEngine

services/ingestion/providers/
├── tcmb_provider.py            # 104 satır — TCMB EVDS API
└── macro_provider.py           # 139 satır — Yahoo + FRED + ECB
```

### 2.2 Mevcut Güçlü Yönler

| Bileşen | Durum | Detay |
|---------|-------|-------|
| MacroFeatureEngine | ✅ İyi | 30+ feature: USDTRY z-score/momentum/regime, VIX regime, commodity momentum |
| MacroSensitivityEngine | ✅ İyi | 10 sektör × 6 değişken hassasiyet matrisi, şirket override desteği |
| TCMB Provider | ✅ İyi | EVDS API entegrasyonu — USDTRY, faiz, CPI, PPI, cari açık |
| Macro Provider | ✅ İyi | Yahoo Finance + FRED + ECB — VIX, S&P500, altın, petrol |
| Calendar | ⚠️ Basit | MACRO_EVENTS dict var ama otomatik tetikleme yok |

### 2.3 Kritik Eksiklikler

| # | Eksik | Etki | Öncelik |
|---|-------|------|---------|
| 1 | **Macro Surprise Model** | Beklenti vs gerçek hesaplanamıyor | 🔴 Kritik |
| 2 | **Macro Regime Detection** | Makro bağlam olmadan karar veriliyor | 🔴 Kritik |
| 3 | **Dynamic Sector Sensitivity** | Sabit değerler — gerçek korelasyon yok | 🟡 Yüksek |
| 4 | **Macro Correlation Tracking** | Değişkenler arası ilişki bilinmiyor | 🟡 Yüksek |
| 5 | **Macro Stress Test** | "USDTRY +10% ise portföy ne olur?" cevaplanamıyor | 🟡 Yüksek |
| 6 | **Historical Macro Data** | Backtest'te makro feature kullanılamıyor | 🟡 Yüksek |
| 7 | **Factor Decomposition** | Hangi faktör ne kadar katkı bilinmiyor | 🟢 Orta |
| 8 | **Decay Model** | Şok etkisi zamanla nasıl azalır bilinmiyor | 🟢 Orta |

---

## 3. Entegrasyon Noktaları

### 3.1 Pipeline Entegrasyonu

```
MEVCUT:
  market_data → features → regime → signal_fusion → decision → risk → portfolio

HEDEF:
  market_data → features → [MACRO PIPELINE] → regime → signal_fusion → decision → risk → portfolio
                              ↑
                              Macro Features → Surprise Model →
                              Regime Detection → Sensitivity Engine →
                              Impact Analysis → Stress Test →
                              Correlation Tracking → Historical Store
```

### 3.2 Feature Pipeline Entegrasyonu

```python
# services/features/macro.py — compute_all_macro_features() genişletilecek

# MEVCUT: 30+ feature (USDTRY, VIX, commodity, global)
# HEDEF:  50+ feature (+ surprise, regime, correlation, stress, decomposition)

def compute_all_macro_features(macro_data, macro_history=None, expectations=None):
    features = {}

    # MEVCUT features
    features.update(macro_feature_engine.compute_currency_features(usdtry, eurtry))
    features.update(macro_feature_engine.compute_vix_features(vix))
    features.update(macro_feature_engine.compute_commodity_features(gold, oil))
    features.update(macro_feature_engine.compute_global_features(sp500, nasdaq))

    # YENİ: Macro surprise features
    features.update(macro_surprise_model.compute_surprise_features(expectations, actuals))

    # YENİ: Macro regime features
    features.update(macro_regime_detector.compute_regime_features(features))

    # YENİ: Correlation features
    features.update(macro_correlation_tracker.compute_correlation_features())

    return features
```

### 3.3 Regime Engine Entegrasyonu

```python
# services/intelligence/regime.py — mevcut regime engine'e macro regime ekle

# MEVCUT: Market regime (bull/bear/sideways)
# HEDEF:  Market regime + Macro regime (expansion/contraction/stagflation/risk-on/risk-off)

macro_regime = macro_regime_detector.detect_regime(macro_features)
# → regime_engine.combine(market_regime, macro_regime)
# → composite_regime (örn: "BULL_EXPANSION", "BEAR_RISK_OFF")
```

### 3.4 Decision Engine Entegrasyonu

```python
# services/core/decision_engine.py — macro etkiyi karara dahil et

# MEVCUT: Teknik + fundamental sinyaller → karar
# HEDEF:  Teknik + fundamental + macro sinyaller → karar

macro_impact = macro_sensitivity_engine.compute_macro_impact(ticker, sector, current_shocks)
# → decision_engine'a macro_stance ekle
# → macro_stance == -1.0 ise confidence azalt
# → macro_stance == 1.0 ise confidence artır
```

### 3.5 Risk Gate Entegrasyonu

```python
# services/core/risk_gate.py — macro stres testi risk gate'e eklenecek

# MEVCUT: Pozisyon boyutu, volatilite, likidite kontrolü
# HEDEF:  + Macro stres testi

stress_result = macro_stress_test.run_stress_test(portfolio, "USDTRY_10_PCT")
if stress_result["total_impact_pct"] < -15:  # %15+ kayıp riski
    risk_gate.veto("Macro stress test failed")
```

---

## 4. Genel Mimari Tasarım

### 4.1 Nihai Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ALPHA BIST — MACRO PIPELINE v2.0                │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: DATA COLLECTION                                    │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │
│  │  │ TCMB     │  │ Yahoo    │  │ TÜİK     │  │ FRED     │   │   │
│  │  │ EVDS API │  │ Finance  │  │ API      │  │ API      │   │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │   │
│  │       └─────────────┴────────────┴─────────────┘            │   │
│  │                          ↓                                    │   │
│  │  ┌──────────────────────────────────────────────────────┐    │   │
│  │  │  MacroDataStore — tarihsel + anlık veri              │    │   │
│  │  └──────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: FEATURE ENGINEERING                                │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │
│  │  │ Currency │  │  Rate    │  │Inflation │  │  VIX     │   │   │
│  │  │ Features │  │ Features │  │ Features │  │ Features │   │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │
│  │  │ Commodity│  │  Global  │  │   CDS    │  │  Credit  │   │   │
│  │  │ Features │  │ Features │  │ Features │  │ Features │   │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │   │
│  │  │ Surprise │  │  Regime  │  │Correlat. │                  │   │
│  │  │ Features │  │ Features │  │ Features │                  │   │
│  │  └──────────┘  └──────────┘  └──────────┘                  │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: MACRO SURPRISE MODEL                               │   │
│  │  - TCMB faiz beklenti vs gerçek                              │   │
│  │  - Enflasyon beklenti vs gerçek                              │   │
│  │  - Beklenti kaynağı: anket, swap pricing, consensus          │   │
│  │  - Surprise magnitude ve direction                           │   │
│  │  - Sector-specific surprise etkisi                           │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: MACRO REGIME DETECTION                             │   │
│  │  - 6 makro rejim (expansion/contraction/stagflation/...)     │   │
│  │  - Skor bazlı tespit (ağırlıklı puanlama)                    │   │
│  │  - Regime transition tracking                                │   │
│  │  - Regime-specific strateji önerisi                          │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 5: DYNAMIC SENSITIVITY ENGINE                         │   │
│  │  - Rolling sector-macro korelasyon (60 gün)                  │   │
│  │  - Sensitivity trend tracking                                │   │
│  │  - Company-specific override (döviz borcu, ithalat bağıml.)  │   │
│  │  - Factor decomposition (USDTRY/faiz/enflasyon/global katkısı)│  │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 6: MACRO IMPACT ANALYSIS                              │   │
│  │  - Şok etkisi (magnitude × sensitivity)                      │   │
│  │  - Decay modeli (half-life, etki zamanla azalır)             │   │
│  │  - Sector impact (sektör bazlı)                              │   │
│  │  - Company impact (şirket bazlı)                             │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 7: MACRO STRESS TEST                                  │   │
│  │  - Önceden tanımlı senaryolar (7 senaryo)                    │   │
│  │  - Portfolio bazlı stres testi                               │   │
│  │  - Sector impact hesaplama                                   │   │
│  │  - Breaking point analysis                                   │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 8: MACRO CALENDAR INTEGRATION                         │   │
│  │  - TCMB PPK tarihleri                                        │   │
│  │  - TÜİK veri açıklama tarihleri                             │   │
│  │  - Olay öncesi hazırlık (beklenti toplama)                   │   │
│  │  - Olay sonrası analiz tetikleme (surprise hesaplama)        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 9: MACRO CORRELATION TRACKING                         │   │
│  │  - USDTRY-altın korelasyonu                                  │   │
│  │  - Faiz-enflasyon korelasyonu                                │   │
│  │  - VIX-BIST korelasyonu                                      │   │
│  │  - Petrol-enerji sektörü korelasyonu                         │   │
│  │  - Rolling window (60 gün)                                   │   │
│  │  - Correlation breakdown alerts                              │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 10: HISTORICAL MACRO DATA STORE                       │   │
│  │  - Tarihsel makro veri deposu                                │   │
│  │  - Backtest'te makro feature kullanımı                       │   │
│  │  - Point-in-time makro veri                                  │   │
│  │  - Macro data versioning                                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Dosya Yapısı (Hedef)

```
services/macro/
├── __init__.py                    # MEVCUT
├── calendar.py                    # MEVCUT — refactor edilecek
├── cds.py                         # MEVCUT — refactor edilecek
├── credit.py                      # MEVCUT — refactor edilecek
├── current_account.py             # MEVCUT — refactor edilecek
├── fx.py                          # MEVCUT — refactor edilecek
├── inflation.py                   # MEVCUT — refactor edilecek
├── tcmb.py                        # MEVCUT — refactor edilecek
├── surprise_model.py              # YENİ — Phase 3: Macro surprise
├── regime_detector.py             # YENİ — Phase 4: Macro regime
├── sensitivity_engine.py          # YENİ — Phase 5: Dynamic sensitivity
├── impact_analyzer.py             # YENİ — Phase 6: Impact analysis + decay
├── stress_test.py                 # YENİ — Phase 7: Stress test
├── correlation_tracker.py         # YENİ — Phase 9: Correlation tracking
├── historical_store.py            # YENİ — Phase 10: Historical data
├── calendar_engine.py             # YENİ — Phase 8: Calendar integration
├── factor_decomposition.py        # YENİ — Phase 5: Factor decomposition
└── config/
    └── macro_config.py            # YENİ — Merkezi konfigürasyon

services/features/
└── macro.py                       # MEVCUT — genişletilecek (50+ feature)

services/intelligence/
└── macro_sensitivity.py           # MEVCUT — refactor edilecek (dynamic)
```

### 4.3 Hedef İstatistikler

| Metrik | Mevcut | Hedef |
|--------|--------|-------|
| Modül sayısı | 9 | 18 |
| Toplam satır | ~600 | ~2,500 |
| Macro features | 30+ | 50+ |
| Macro surprise | ❌ | ✅ |
| Macro regime | ❌ | ✅ 6 rejim |
| Sector sensitivity | Sabit | ✅ Dynamic rolling |
| Correlation tracking | ❌ | ✅ Rolling matrix |
| Stress test | ⚠️ Basit | ✅ 7 senaryo |
| Historical data | ❌ | ✅ PIT store |
| Calendar integration | ⚠️ Basit | ✅ Otomatik tetikleme |
| Factor decomposition | ❌ | ✅ |
| Decay model | ❌ | ✅ Half-life |

---

## 5. Faz Planı

### FAZ 0: Temel Altyapı (1 gün)

**Amaç:** Mevcut kodu refactor et, merkezi konfigürasyon oluştur.

#### 0.1 — Macro Config
```
Dosya: services/macro/config/macro_config.py
```
- [ ] `MacroConfig` Pydantic model — tüm eşikler merkezi
- [ ] Surprise eşikleri, regime parametreleri, stress test senaryoları
- [ ] Correlation window, decay half-life parametreleri
- [ ] Environment variable override desteği

#### 0.2 — Mevcut Macro Modülleri Refactor
```
Dosya: services/macro/tcmb.py, inflation.py, fx.py, cds.py, credit.py, current_account.py
```
- [ ] Her modül: config'den eşik okuma (hardcoded yok)
- [ ] Her modül: `compute_*_features()` standardizasyonu
- [ ] Her modül: error handling + logging geliştirme
- [ ] `__init__.py` güncelleme — tüm modülleri export et

#### 0.3 — Macro Data Store Interface
```
Dosya: services/macro/historical_store.py (interface)
```
- [ ] `MacroDataStore` abstract class — `save()`, `get()`, `get_range()`
- [ ] JSON-based implementasyon (başlangıç)
- [ ] Point-in-time veri erişimi

**Teslimat:** `pytest tests/test_macro_faz0.py` — refactor testleri yeşil

---

### FAZ 1: Macro Surprise Model (2 gün)

**Amaç:** Beklenti vs gerçek sürpriz hesapla.

#### 1.1 — Macro Surprise Model
```
Dosya: services/macro/surprise_model.py
```

```python
class MacroSurpriseModel:
    """Makro sürpriz hesaplama — beklenti vs gerçek."""

    EXPECTATION_SOURCES = {
        "TCMB_RATE": {"source": "TCMB Piyasa Katılımcıları Anketi", "fallback": "swap_pricing"},
        "CPI": {"source": "TÜİK Anket", "fallback": "consensus_forecast"},
        "GDP": {"source": "consensus_forecast", "fallback": "trend_extrapolation"},
    }

    def calculate_surprise(self, indicator: str, actual: float, expected: float = None) -> Dict:
        """Sürpriz hesapla."""
        # expected None ise → fallback kaynaklardan al
        # surprise = actual - expected
        # surprise_pct = surprise / |expected|
        # magnitude: SMALL (< %5), MEDIUM (%5-10), LARGE (> %10)
        # direction: HIGHER/LOWER/IN_LINE (TCMB için HAWKISH/DOVISH)
        pass

    def compute_surprise_features(self, expectations: Dict, actuals: Dict) -> Dict[str, float]:
        """Surprise feature'ları üret."""
        # tcmb_rate_surprise, cpi_surprise, gdp_surprise
        # surprise_magnitude, surprise_direction
        # surprise_cumulative_3m (son 3 ayın birikimli sürprizi)
        pass
```

#### 1.2 — Expectation Data Integration
- [ ] TCMB Piyasa Katılımcıları Anketi scraping (aylık)
- [ ] Consensus forecast toplama (Reuters, Bloomberg terminal fallback)
- [ ] Swap pricing'den beklenti çıkarma (TCMB faiz swapları)
- [ ] Beklenti verisi cache + TTL yönetimi

#### 1.3 — Surprise Impact Mapping
- [ ] Surprise → sector impact mapping
- [ ] Surprise → company impact mapping (döviz borcu, ithalat bağımlılığı)
- [ ] Surprise decay modeli (half-life: 5 gün)

**Teslimat:** `pytest tests/test_macro_faz1.py` — surprise hesaplama doğru

---

### FAZ 2: Macro Regime Detection (2 gün)

**Amaç:** Makro ortamı 6 rejimden birine sınıflandır.

#### 2.1 — Macro Regime Detector
```
Dosya: services/macro/regime_detector.py
```

```python
class MacroRegimeDetector:
    """Makro rejim tespiti — skor bazlı."""

    MACRO_REGIMES = {
        "EXPANSION": {"description": "Genişleyici"},
        "CONTRACTION": {"description": "Daraltıcı"},
        "STAGFLATION": {"description": "Stagflasyon"},
        "REFLATION": {"description": "Reflasyon"},
        "RISK_ON": {"description": "Risk Açıklığı"},
        "RISK_OFF": {"description": "Risk Kaçışı"},
    }

    def detect_regime(self, macro_features: Dict[str, float]) -> Dict:
        """Her rejim için skor hesapla, en yüksek skorlu rejimi seç."""
        scores = {}
        scores["EXPANSION"] = self._score_expansion(macro_features)
        scores["CONTRACTION"] = self._score_contraction(macro_features)
        scores["STAGFLATION"] = self._score_stagflation(macro_features)
        scores["REFLATION"] = self._score_reflation(macro_features)
        scores["RISK_ON"] = self._score_risk_on(macro_features)
        scores["RISK_OFF"] = self._score_risk_off(macro_features)
        best = max(scores, key=scores.get)
        return {"regime": best, "confidence": scores[best], "all_scores": scores}

    def compute_regime_features(self, macro_features: Dict) -> Dict[str, float]:
        """Rejim feature'ları üret."""
        # macro_regime_expansion_score, macro_regime_risk_on_score, ...
        # macro_regime_composite (0-5 arası skor)
        # macro_regime_transition_prob (rejim değişme olasılığı)
        pass
```

#### 2.2 — Rejim Skor Fonksiyonları
- [ ] `_score_expansion()`: faiz düşüyor, enflasyon düşüyor, S&P500 yükseliyor, VIX düşük
- [ ] `_score_contraction()`: faiz yükseliyor, enflasyon yükseliyor, büyüme zayıf
- [ ] `_score_stagflation()`: enflasyon yüksek, büyüme zayıf, faiz yüksek
- [ ] `_score_reflation()`: faiz düşük, enflasyon yükseliyor, toparlanma
- [ ] `_score_risk_on()`: VIX düşük, S&P500 yükseliyor, CDS düşük
- [ ] `_score_risk_off()`: VIX yüksek, S&P500 düşüyor, CDS yüksek

#### 2.3 — Regime Transition Tracking
- [ ] Son 30 günün rejim geçmişi
- [ ] Regime transition probability matrix
- [ ] Regime change alert (rejim değiştiğinde bildirim)

#### 2.4 — Regime-Strategy Mapping
- [ ] Her rejim için strateji önerisi
- [ ] EXPANSION → büyüme hisseleri, yüksek beta
- [ ] CONTRACTION → defansif, düşük beta, temettü
- [ ] RISK_OFF → altın, nakit, kısa vadeli tahvil

**Teslimat:** `pytest tests/test_macro_faz2.py` — 6 rejim doğru tespit

---

### FAZ 3: Dynamic Sector Sensitivity (2 gün)

**Amaç:** Sabit hassasiyet değerlerini dinamik rolling korelasyona çevir.

#### 3.1 — Dynamic Sensitivity Engine
```
Dosya: services/macro/sensitivity_engine.py
```

```python
class DynamicSensitivityEngine:
    """Dinamik sektör-macro hassasiyet — rolling korelasyon."""

    def __init__(self, window: int = 60):
        self._window = window
        self._sector_returns: Dict[str, List[float]] = {}  # sector → returns
        self._macro_values: Dict[str, List[float]] = {}    # macro_var → values

    def update(self, sector_returns: Dict[str, float], macro_values: Dict[str, float]):
        """Günlük güncelleme."""
        # Rolling window ile sector returns ve macro values sakla
        pass

    def compute_dynamic_sensitivity(self, sector: str) -> Dict[str, float]:
        """Sektör için dinamik hassasiyet hesapla."""
        # usdtry_sensitivity = rolling_corr(sector_returns, usdtry_changes)
        # interest_rate_sensitivity = rolling_corr(sector_returns, rate_changes)
        # ...
        pass

    def compute_factor_decomposition(self, ticker: str, sector: str) -> Dict[str, float]:
        """Factor decomposition — hangi faktör ne kadar katkı yaptı."""
        # usdtry_contribution, rate_contribution, inflation_contribution, ...
        # residual (açıklanamayan kısım)
        pass
```

#### 3.2 — Rolling Correlation Implementation
- [ ] 60 günlük rolling window
- [ ] 6 makro değişken × 10 sektör = 60 korelasyon
- [ ] Korelasyon trend tracking (artıyor/azalıyor/sabit)
- [ ] Anlamlılık testi (p < 0.05)

#### 3.3 — Company-Specific Sensitivity
- [ ] Döviz borcu yüksek şirketler → USDTRY hassasiyeti artır
- [ ] İthalat bağımlı şirketler → USDTRY hassasiyeti artır
- [ ] İhracatçı şirketler → USDTRY hassasiyeti ters çevir
- [ ] KAP'tan bilanço verisi çek → otomatik hassasiyet hesaplama

**Teslimat:** `pytest tests/test_macro_faz3.py` — dinamik korelasyon hesaplama doğru

---

### FAZ 4: Impact Analysis & Decay Model (1-2 gün)

**Amaç:** Şok etkisini hesapla, zamanla azalma modeli uygula.

#### 4.1 — Impact Analyzer
```
Dosya: services/macro/impact_analyzer.py
```

```python
class MacroImpactAnalyzer:
    """Makro şok etki analizi + decay modeli."""

    def compute_shock_impact(
        self,
        shock_type: str,
        magnitude: float,
        sector: str,
        ticker: str = None,
    ) -> Dict:
        """Şok etkisini hesapla."""
        # 1. Sensitivity al (dynamic veya static)
        # 2. Impact = magnitude × sensitivity
        # 3. Decay uygula
        pass

    def compute_decay(self, impact: float, days_elapsed: int, half_life: int = 5) -> float:
        """Half-life decay modeli."""
        # impact_t = impact_0 * (0.5)^(t / half_life)
        return impact * (0.5 ** (days_elapsed / half_life))

    def compute_cumulative_impact(self, shocks: List[Dict], ticker: str, sector: str) -> Dict:
        """Birden fazla şokun birikimli etkisi."""
        # Her şok için impact + decay hesapla
        # Toplam etki = Σ(impact_i × decay_i)
        pass
```

#### 4.2 — Decay Model Calibration
- [ ] Half-life parametresi config'den okunmalı
- [ ] Farklı şok türleri için farklı half-life
- [ ] Para politikası sürprizi: half-life = 10 gün
- [ ] Kur şoku: half-life = 5 gün
- [ ] Global risk-off: half-life = 3 gün

**Teslimat:** `pytest tests/test_macro_faz4.py` — decay modeli matematiksel doğru

---

### FAZ 5: Macro Stress Test (2 gün)

**Amaç:** "USDTRY +10% olursa portföy ne olur?" sorusunu cevapla.

#### 5.1 — Stress Test Engine
```
Dosya: services/macro/stress_test.py
```

```python
class MacroStressTest:
    """Makro stres testi — portfolio bazlı."""

    PREDEFINED_SCENARIOS = {
        "USDTRY_10_PCT": {"usdtry_change": 0.10},
        "TCMB_RATE_HIKE_500BP": {"interest_rate_change": 0.05},
        "VIX_SPIKE_50_PCT": {"vix_change": 0.50},
        "OIL_SHOCK_20_PCT": {"oil_change": 0.20},
        "GLOBAL_RISK_OFF": {"global_change": -0.10, "usdtry_change": 0.05},
        "INFLATION_HIGH": {"inflation_change": 0.05},
        "BIST_CRASH_10_PCT": {"bist_change": -0.10},
    }

    def run_stress_test(self, portfolio: Dict, scenario: str) -> Dict:
        """Stres testi çalıştır."""
        # 1. Senaryo şoklarını al
        # 2. Her pozisyon için etki hesapla (sensitivity × shock)
        # 3. Toplam portföy etkisi
        # 4. Breaking point analizi
        pass

    def run_custom_scenario(self, portfolio: Dict, shocks: Dict) -> Dict:
        """Özel senaryo stres testi."""
        pass

    def find_breaking_point(self, portfolio: Dict, shock_type: str) -> Dict:
        """Breaking point — kaç %'lik şok portföyü %10+ kayıp ettirir?"""
        # Binary search ile breaking point bul
        pass
```

#### 5.2 — Scenario Definitions
- [ ] 7 önceden tanımlı senaryo
- [ ] Özel senaryo desteği (custom shocks)
- [ ] Senaryo olasılık ataması (opsiyonel)

#### 5.3 — Portfolio Integration
- [ ] Mevcut portföy verisini al (portfolio_manager'dan)
- [ ] Her pozisyon için sector + ticker bilgisi
- [ ] Toplam etki + pozisyon bazlı detay

**Teslimat:** `pytest tests/test_macro_faz5.py` — stress test sonuçları tutarlı

---

### FAZ 6: Macro Calendar Integration (1-2 gün)

**Amaç:** Takvim olaylarını otomatik tetikle.

#### 6.1 — Calendar Engine
```
Dosya: services/macro/calendar_engine.py
```

```python
class MacroCalendarEngine:
    """Makro takvim entegrasyonu — otomatik tetikleme."""

    def __init__(self):
        self._events: List[Dict] = []
        self._expectations: Dict[str, float] = {}  # event_id → expected_value

    def get_upcoming_events(self, days: int = 7) -> List[Dict]:
        """Yaklaşan makro olayları getir."""
        # TCMB PPK tarihleri
        # TÜİK veri açıklama tarihleri (CPI, GDP, istihdam)
        # Global olaylar (FOMC, ECB)
        pass

    def register_expectation(self, event_id: str, expected: float):
        """Beklenti kaydet."""
        pass

    def trigger_post_event_analysis(self, event_id: str, actual: float) -> Dict:
        """Olay sonrası analiz tetikle."""
        # 1. Surprise hesapla
        # 2. Sector impact hesapla
        # 3. Company impact hesapla
        # 4. Event decay başlat
        pass

    def get_pre_event_alert(self, event_id: str) -> Dict:
        """Olay öncesi hazırlık uyarısı."""
        # Beklenti topla
        # Olası senaryoları hesapla
        # Risk seviyesini belirle
        pass
```

#### 6.2 — Event Database
- [ ] TCMB PPK toplantı tarihleri (2024-2027)
- [ ] TÜİK veri açıklama takvimi
- [ ] FOMC toplantı tarihleri
- [ ] ECB toplantı tarihleri

#### 6.3 — Auto-Trigger Integration
- [ ] Event bus'a macro event publish
- [ ] Olay öncesi: beklenti topla, senaryo hesapla
- [ ] Olay sonrası: surprise hesapla, impact analizi tetikle

**Teslimat:** `pytest tests/test_macro_faz6.py` — calendar tetikleme çalışıyor

---

### FAZ 7: Correlation Tracking (1-2 gün)

**Amaç:** Makro değişkenler arası korelasyonu takip et.

#### 7.1 — Correlation Tracker
```
Dosya: services/macro/correlation_tracker.py
```

```python
class MacroCorrelationTracker:
    """Makro değişkenler arası korelasyon takibi."""

    def __init__(self, window: int = 60):
        self._window = window
        self._history: Dict[str, List[float]] = {}

    def update(self, macro_data: Dict[str, float]):
        """Günlük veri güncelle."""
        # Rolling window ile sakla
        pass

    def get_correlation(self, var1: str, var2: str) -> Optional[float]:
        """İki değişken arası korelasyon."""
        # Son N gözlemi kullan
        # np.corrcoef ile hesapla
        pass

    def get_correlation_matrix(self) -> Dict[str, Dict[str, float]]:
        """Tüm değişkenler arası korelasyon matrisi."""
        pass

    def detect_correlation_breakdown(self) -> List[Dict]:
        """Korelasyon bozulması tespit et."""
        # Tarihsel korelasyon ile mevcut korelasyon karşılaştır
        # Anlamlı sapma varsa alert
        pass

    def compute_correlation_features(self) -> Dict[str, float]:
        """Korelasyon feature'ları üret."""
        # usdtry_gold_corr, vix_bist_corr, oil_energy_corr, rate_inflation_corr
        # correlation_stability (korelasyon stabilite skoru)
        pass
```

#### 7.2 — Key Correlation Pairs
- [ ] USDTRY ↔ Altın (döviz-altın ilişkisi)
- [ ] Faiz ↔ Enflasyon (para politikası geçişkenliği)
- [ ] VIX ↔ BIST-100 (global risk iştahı)
- [ ] Petrol ↔ Enerji sektörü
- [ ] S&P500 ↔ BIST-100 (global korelasyon)
- [ ] CDS ↔ USDTRY (risk-kur ilişkisi)

**Teslimat:** `pytest tests/test_macro_faz7.py` — korelasyon hesaplama doğru

---

### FAZ 8: Historical Data Store (1-2 gün)

**Amaç:** Tarihsel makro veriyi sakla, backtest'te kullan.

#### 8.1 — Historical Store Implementation
```
Dosya: services/macro/historical_store.py
```

```python
class MacroHistoricalStore:
    """Tarihsel makro veri deposu — point-in-time."""

    def save(self, date: str, indicator: str, value: float, source: str):
        """Makro veri kaydet."""
        pass

    def get(self, date: str, indicator: str) -> Optional[float]:
        """Belirli tarihteki veriyi getir (point-in-time)."""
        pass

    def get_range(self, indicator: str, start_date: str, end_date: str) -> List[Dict]:
        """Tarih aralığındaki veriyi getir."""
        pass

    def get_latest(self, indicator: str) -> Optional[Dict]:
        """Son veriyi getir."""
        pass

    def backfill(self, indicator: str, data: List[Dict]):
        """Toplu veri yükleme (backfill)."""
        pass
```

#### 8.2 — Backtest Integration
- [ ] Backtest engine'e macro feature erişimi
- [ ] Point-in-time macro veri (look-ahead bias yok)
- [ ] Macro feature'ları backtest'te kullan

#### 8.3 — Data Sources Backfill
- [ ] TCMB EVDS'ten tarihsel veri çek
- [ ] Yahoo Finance'ten tarihsel VIX, S&P500, altın, petrol
- [ ] TÜİK'ten tarihsel CPI, PPI, GSYH

**Teslimat:** `pytest tests/test_macro_faz8.py` — tarihsel veri kaydetme/okuma doğru

---

### FAZ 9: Feature Pipeline Genişletme (1 gün)

**Amaç:** Macro feature sayısını 30'dan 50+'ya çıkar.

#### 9.1 — MacroFeatureEngine Genişletme
```
Dosya: services/features/macro.py (değişiklik)
```
- [ ] Surprise feature'ları ekle (tcmb_surprise, cpi_surprise)
- [ ] Regime feature'ları ekle (macro_regime_*, regime_composite)
- [ ] Correlation feature'ları ekle (usdtry_gold_corr, vix_bist_corr)
- [ ] Factor decomposition feature'ları ekle
- [ ] Decay feature'ları ekle (recent_shock_impact, shock_age_days)

#### 9.2 — Feature Contract
- [ ] Yeni feature'lar için feature contract oluştur
- [ ] Feature isim standardizasyonu
- [ ] Feature dokümantasyonu

**Teslimat:** `pytest tests/test_macro_faz9.py` — 50+ feature hesaplanıyor

---

### FAZ 10: Orchestrator Entegrasyonu + Test (2 gün)

**Amaç:** Macro pipeline'ı mevcut sisteme tam entegre et.

#### 10.1 — Orchestrator Entegrasyonu
```
Dosya: services/core/orchestrator.py (değişiklik)
```
- [ ] `run_full_pipeline()`'a macro pipeline ekle
- [ ] Macro features → regime → impact → stress test akışı
- [ ] Macro regime'i composite regime'e dahil et

#### 10.2 — Decision Engine Entegrasyonu
- [ ] Macro stance'ı karara dahil et
- [ ] Macro stress test sonucunu risk gate'e besle

#### 10.3 — Event Bus Entegrasyonu
- [ ] Macro event publish (regime change, surprise, stress alert)
- [ ] Macro event subscribe (calendar trigger)

#### 10.4 — Kapsamlı Test Suite
- [ ] Unit test: her modül
- [ ] Integration test: pipeline akışı
- [ ] Edge case: veri eksik, API hatası, anlamlı korelasyon yok

**Teslimat:** `pytest tests/test_macro_faz10.py` — end-to-end pipeline

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam pipeline)
         ├─────────────┤
         │ Integration  │  ← 15 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 50+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 0 | test_macro_faz0.py | 8 | Config refactor |
| 1 | test_macro_faz1.py | 10 | Surprise hesaplama doğru |
| 2 | test_macro_faz2.py | 12 | 6 rejim tespit |
| 3 | test_macro_faz3.py | 10 | Dynamic korelasyon |
| 4 | test_macro_faz4.py | 8 | Decay modeli |
| 5 | test_macro_faz5.py | 10 | Stress test |
| 6 | test_macro_faz6.py | 8 | Calendar tetikleme |
| 7 | test_macro_faz7.py | 8 | Correlation tracking |
| 8 | test_macro_faz8.py | 8 | Historical store |
| 9 | test_macro_faz9.py | 10 | 50+ feature |
| 10 | test_macro_faz10.py | 15 | End-to-end pipeline |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| TCMB EVDS API erişilemez | Orta | Yüksek | Cache + fallback (Yahoo Finance) |
| Beklenti verisi yok | Yüksek | Yüksek | Fallback: trend extrapolation, swap pricing |
| Korelasyon anlamlı değil | Orta | Orta | Minimum sample kontrolü, p-value test |
| Regime tespit yanlış | Orta | Yüksek | Confidence threshold, birden fazla yöntem |
| Tarihsel veri eksik | Yüksek | Orta | Backfill + interpolation |
| Stress test overfitting | Düşük | Orta | Basit senaryolar, cross-validation |
| Macro regime çok sık değişiyor | Orta | Orta | Smoothing, minimum duration filter |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 0** | 1 gün | Yok | Config, refactor |
| **Faz 1** | 2 gün | Faz 0 | Surprise model |
| **Faz 2** | 2 gün | Faz 0 | Regime detection |
| **Faz 3** | 2 gün | Faz 0 | Dynamic sensitivity |
| **Faz 4** | 1-2 gün | Faz 1+3 | Impact + decay |
| **Faz 5** | 2 gün | Faz 3+4 | Stress test |
| **Faz 6** | 1-2 gün | Faz 1 | Calendar integration |
| **Faz 7** | 1-2 gün | Faz 0 | Correlation tracking |
| **Faz 8** | 1-2 gün | Faz 0 | Historical store |
| **Faz 9** | 1 gün | Faz 1-8 | Feature expansion |
| **Faz 10** | 2 gün | Faz 1-9 | Orchestrator + test |
| **TOPLAM** | **16-20 gün** | | |

**Paralel geliştirme:** Faz 1, 2, 3, 7, 8 birbirinden bağımsız → paralel geliştirilebilir.
Bu durumda toplam süre **10-12 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **Skor bazlı regime** — HMM yerine skor basit ve interpretable
2. **Dynamic sensitivity** — Sabit değerler yerine rolling korelasyon
3. **Half-life decay** — Şok etkisi zamanla azalır (matematiksel model)
4. **Point-in-time data** — Backtest'te look-ahead bias yok
5. **NO_TRADE on uncertainty** — Surprise verisi yoksa etki sıfır kabul et
6. **Config-driven** — Tüm eşikler merkezi config'den
7. **Graceful degradation** — API hatası → cache → fallback → sıfır
8. **Backtest-first** — Her faz için backtest kanıtı gerekli

---

## 📚 Referanslar

1. SBB Medium Term Program (2026-2028) — Türkiye makro çerçeve
2. ResearchGate — Exchange Rate & Inflation Turkey (2026)
3. J.P. Morgan QIS Conference (2026) — Multi-factor macro model
4. ECB Financial Stability Review (2026) — Macro-financial linkages
5. AIMS Press — Multi-Model Ensemble HMM Voting (2025)
6. arXiv — Agentic Trading Meta-Analiz (2026)
