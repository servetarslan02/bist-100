# Macro Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** SBB Medium Term Program (2026-2028), ResearchGate Exchange Rate & Inflation Turkey (2026), J.P. Morgan QIS Conference (2026), ECB Financial Stability Review (2026), Federal Reserve Stress Test Scenarios (2026)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Makro Faktör Modeli (En İyi Uygulama)

**Temel prensip:** Makro veriler tek başına anlamlı değil, birlikte ve bağlam içinde anlamlı.

```
TCMB Faiz Kararı
    ↓
Sürpriz Hesapla (beklenti vs gerçek)
    ↓
Sektör Hassasiyeti (banka vs sanayi vs teknoloji)
    ↓
Şirket Hassasiyeti (döviz borcu, ithalat bağımlılığı)
    ↓
Fiyat Etkisi (CAR hesaplama)
    ↓
Decay (etki zamanla azalır)
```

### 1.2 Türkiye'ye Özgü Makro Dinamikler (Araştırma Bazlı)

| Makro Değişken | BIST Etkisi | Mekanizma | Kaynak |
|----------------|-------------|-----------|--------|
| **USDTRY** | Yüksek | İthalat maliyeti, döviz borcu, ihracat geliri | ResearchGate (2026) |
| **TCMB Faiz** | Yüksek | Kredi maliyeti, değerleme, sermaye akışı | SBB (2026) |
| **Enflasyon (CPI)** | Yüksek | Tüketici baskısı, maliyet artışı, değerleme | ResearchGate (2026) |
| **CDS Spread** | Orta-Yüksek | Ülke risk primi, yabancı yatırımcı algısı | ECB (2026) |
| **Cari Açık** | Orta | Döviz ihtiyacı, kur baskısı | SBB (2026) |
| **Kredi Büyümesi** | Orta | Ekonomik aktivite, balon riski | SBB (2026) |
| **VIX** | Orta | Global risk iştahı | J.P. Morgan (2026) |
| **Altın** | Düşük-Orta | Güvenli liman, enflasyon hedge | - |
| **Petrol** | Orta | Enerji maliyeti, enflasyon baskısı | - |
| **S&P500/Nasdaq** | Orta | Global piyasa sentiment | J.P. Morgan (2026) |

### 1.3 Makro Şok Analizi (En İyi Uygulama)

```
Şok Türleri:
1. Para Politikası Sürprizi (TCMB faiz değişimi)
2. Enflasyon Sürprizi (beklenti dışı CPI)
3. Kur Şoku (USDTRY ani hareket)
4. Global Risk-Off (VIX spike, S&P500 düşüş)
5. Emtia Şoku (petrol/altın ani hareket)
6. Jeopolitik Şok (savaş, yaptırım)

Her şok için:
- Magnitude (büyüklük)
- Surprise (beklenti dışı kısım)
- Decay (etki azalma hızı)
- Sector Impact (sektör bazlı etki)
- Company Impact (şirket bazlı etki)
```

---

## 2. Bizde Şu An Ne Var?

### 2.1 services/macro/ (7 modül, 116 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `tcmb.py` | 14 | policy_rate, real_rate, rate_surprise, policy_stance, rate_change | ⚠️ Çok basit |
| `inflation.py` | 14 | cpi_yoy, ppi_yoy, core_cpi, ppi_cpi_spread, inflation_trend | ⚠️ Çok basit |
| `fx.py` | 14 | usdtry, usdtry_change, usdtry_volatility, eurtry, eurusd | ⚠️ Çok basit |
| `cds.py` | 12 | cds_5y, cds_change, risk_level | ⚠️ Çok basit |
| `credit.py` | 12 | credit_growth_yoy, credit_gdp_ratio, credit_trend | ⚠️ Çok basit |
| `current_account.py` | 12 | ca_balance, ca_trend, ca_improving | ⚠️ Çok basit |
| `calendar.py` | 26 | MACRO_EVENTS dict, get_macro_events(), get_upcoming_events() | ⚠️ Basit |

### 2.2 services/features/macro.py (281 satır) — MacroFeatureEngine

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `compute_currency_features()` | 38-88 | USDTRY z-score, momentum, percentile, regime, volatility | ✅ İyi |
| `compute_rate_features()` | 90-113 | Policy rate, rate differential, rate trend | ⚠️ Basit |
| `compute_inflation_features()` | 115-143 | CPI level, trend, surprise, CPI-PPI spread | ⚠️ Basit |
| `compute_vix_features()` | 145-178 | VIX level, z-score, percentile, regime, momentum | ✅ İyi |
| `compute_commodity_features()` | 180-200 | Gold/Oil price, momentum | ⚠️ Basit |
| `compute_global_features()` | 202-220 | S&P500/Nasdaq level, momentum | ⚠️ Basit |
| `compute_all_macro_features()` | 222-248 | Tümünü birleştir | ✅ İyi |

### 2.3 services/intelligence/macro_sensitivity.py (208 satır) — MacroSensitivityEngine

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `SECTOR_MACRO_SENSITIVITY` | 15-105 | 10 sektör × 6 makro değişken hassasiyet matrisi | ✅ İyi |
| `get_sector_sensitivity()` | 113-115 | Sektör hassasiyeti getir | ✅ |
| `set_company_sensitivity()` | 117-119 | Şirket bazlı hassasiyet kaydet | ✅ |
| `get_company_sensitivity()` | 121-129 | Şirket hassasiyeti (önce şirket, yoksa sektör) | ✅ |
| `compute_macro_impact()` | 131-175 | Makro şok etkisi hesapla | ✅ İyi |
| `compute_scenario_impact()` | 177-207 | Önceden tanımlı senaryo etkisi | ✅ İyi |

### 2.4 services/ingestion/providers/ (2 modül)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `tcmb_provider.py` | 104 | TCMB EVDS API — USDTRY, faiz, CPI, PPI, cari açık | ✅ İyi |
| `macro_provider.py` | 139 | Yahoo Finance + FRED + ECB — VIX, S&P500, altın, petrol | ✅ İyi |

---

## 3. Eksikler (Kritik)

### 3.1 Macro Surprise Modeli Yok

**Sorun:** TCMB faiz kararı sadece `actual - expected` ile hesaplanıyor ama gerçek beklenti verisi yok.
**Etki:** Surprise hesaplaması anlamsız
**Çözüm:** Anket verisi (TCMB Piyasa Katılımcıları Anketi) veya swap pricing'den beklenti çıkar

### 3.2 Macro Regime Detection Yok

**Sorun:** Makro ortam (genişleyici/daraltıcı, risk-on/risk-off) tespit edilmiyor
**Etki:** Makro bağlam olmadan karar veriliyor
**Çözüm:** Makro regime clustering (K-means veya HMM)

### 3.3 Sector-Macro Interaction Modeli Yok

**Sorun:** Sektör hassasiyeti sabit değerler — gerçek korelasyon yok
**Etki:** Dinamik sektör etkisi hesaplanamıyor
**Çözüm:** Rolling sector-macro korelasyon

### 3.4 Macro Factor Decomposition Yok

**Sorun:** Makro etki tek skor — hangi faktörün ne kadar katkı yaptığı bilinmiyor
**Etki:** Attribution eksik
**Çözüm:** Factor decomposition (USDTRY katkısı, faiz katkısı, enflasyon katkısı ayrı)

### 3.5 Macro Calendar Integration Yok

**Sorun:** Takvim var ama otomatik tetikleme yok
**Etki:** Makro olaylar öncesi hazırlık yapılamıyor
**Çözüm:** Calendar → event trigger → analysis pipeline

### 3.6 Historical Macro Data Yok

**Sorun:** Sadece anlık veri — tarihsel makro veri saklanmıyor
**Etki:** Backtest'te makro feature kullanılamıyor
**Çözüm:** Tarihsel makro veri deposu

### 3.7 Macro Correlation Tracking Yok

**Sorun:** Makro değişkenler arası korelasyon takip edilmiyor
**Etki:** USDTRY-altın, faiz-enflasyon ilişkisi bilinmiyor
**Çözüm:** Rolling correlation matrix

### 3.8 Macro Stress Test Yok

**Sorun:** Makro senaryo stres testi yok
**Etki:** "USDTRY %10 artarsa portföy ne olur?" sorusu cevaplanamıyor
**Çözüm:** Macro stress test engine

---

## 4. Nihai Macro Mimarisi

### 4.1 Macro Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    MACRO PIPELINE                            │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DATA SOURCES                            │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ TCMB     │  │ Yahoo    │  │ TÜİK     │          │   │
│  │  │ EVDS API │  │ Finance  │  │ API      │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ FRED     │  │ ECB      │  │ BKM      │          │   │
│  │  │ API      │  │ API      │  │ API      │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RAW MACRO DATA                          │   │
│  │  - TCMB: faiz, enflasyon, döviz, cari açık         │   │
│  │  - Yahoo: VIX, S&P500, altın, petrol               │   │
│  │  - TÜİK: GSYH, istihdam, sanayi üretimi            │   │
│  │  - FRED: ABD verileri                               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO FEATURE ENGINE                    │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Currency │  │  Rate    │  │Inflation │          │   │
│  │  │ Features │  │ Features │  │ Features │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  VIX     │  │ Commodity│  │  Global  │          │   │
│  │  │ Features │  │ Features │  │ Features │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │  CDS     │  │  Credit  │  │ Current  │          │   │
│  │  │ Features │  │ Features │  │ Account  │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO SURPRISE MODEL                    │   │
│  │  - TCMB faiz beklenti vs gerçek                     │   │
│  │  - Enflasyon beklenti vs gerçek                     │   │
│  │  - Beklenti kaynağı: anket, swap pricing, consensus │   │
│  │  - Surprise magnitude ve direction                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO REGIME DETECTION                  │   │
│  │  - Genişleyici / Daraltıcı                          │   │
│  │  - Risk-On / Risk-Off                               │   │
│  │  - Enflasyonist / Deflasyonist                      │   │
│  │  - Kur baskısı / Kur stabil                         │   │
│  │  - K-means veya HMM ile tespit                      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO SENSITIVITY ENGINE                │   │
│  │  - Sektör bazlı hassasiyet (10 sektör × 6 değişken) │   │
│  │  - Şirket bazlı hassasiyet (override)               │   │
│  │  - Rolling correlation (gerçek korelasyon)           │   │
│  │  - Factor decomposition (hangi faktör ne kadar)      │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO IMPACT ANALYSIS                   │   │
│  │  - Şok etkisi (magnitude × sensitivity)             │   │
│  │  - Decay modeli (etki zamanla azalır)               │   │
│  │  - Sector impact (sektör bazlı)                     │   │
│  │  - Company impact (şirket bazlı)                    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO STRESS TEST                       │   │
│  │  - USDTRY +10%                                      │   │
│  │  - TCMB +500bp                                      │   │
│  │  - VIX +50%                                         │   │
│  │  - Petrol +20%                                      │   │
│  │  - Global risk-off                                  │   │
│  │  - Portfolio impact hesaplama                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO CALENDAR INTEGRATION              │   │
│  │  - TCMB PPK tarihleri                               │   │
│  │  - TÜİK veri açıklama tarihleri                    │   │
│  │  - Olay öncesi hazırlık                             │   │
│  │  - Olay sonrası analiz tetikleme                    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MACRO CORRELATION TRACKING              │   │
│  │  - USDTRY-altın korelasyonu                         │   │
│  │  - Faiz-enflasyon korelasyonu                       │   │
│  │  - VIX-BIST korelasyonu                             │   │
│  │  - Petrol-enerji sektörü korelasyonu                │   │
│  │  - Rolling window (60 gün)                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              HISTORICAL MACRO DATA STORE             │   │
│  │  - Tarihsel makro veri deposu                       │   │
│  │  - Backtest'te makro feature kullanımı              │   │
│  │  - Point-in-time makro veri                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Macro Surprise Model (Nihai)

```python
class MacroSurpriseModel:
    """Makro sürpriz hesaplama."""
    
    # Beklenti kaynakları
    EXPECTATION_SOURCES = {
        "TCMB_RATE": {
            "source": "TCMB Piyasa Katılımcıları Anketi",
            "fallback": "swap_pricing",
            "update_frequency": "monthly",
        },
        "CPI": {
            "source": "TÜİK Anket",
            "fallback": "consensus_forecast",
            "update_frequency": "monthly",
        },
        "GDP": {
            "source": "consensus_forecast",
            "fallback": "trend_extrapolation",
            "update_frequency": "quarterly",
        },
    }
    
    def calculate_surprise(self, indicator: str, actual: float, expected: float = None) -> Dict:
        """Sürpriz hesapla."""
        if expected is None:
            expected = self._get_expected(indicator)
        
        if expected is None:
            return {"surprise": 0, "confidence": 0, "source": "no_expectation"}
        
        surprise = actual - expected
        surprise_pct = surprise / abs(expected) if expected != 0 else 0
        
        # Sürpriz büyüklüğü
        if abs(surprise_pct) > 0.10:
            magnitude = "LARGE"
        elif abs(surprise_pct) > 0.05:
            magnitude = "MEDIUM"
        else:
            magnitude = "SMALL"
        
        # Yön
        if surprise > 0:
            direction = "HAWKISH" if indicator == "TCMB_RATE" else "HIGHER"
        elif surprise < 0:
            direction = "DOVISH" if indicator == "TCMB_RATE" else "LOWER"
        else:
            direction = "IN_LINE"
        
        return {
            "surprise": round(surprise, 4),
            "surprise_pct": round(surprise_pct, 4),
            "magnitude": magnitude,
            "direction": direction,
            "actual": actual,
            "expected": expected,
            "indicator": indicator,
        }
    
    def _get_expected(self, indicator: str) -> Optional[float]:
        """Beklenti değerini getir."""
        # TODO: Gerçek beklenti verisi (anket, swap pricing)
        return None
```

### 4.3 Macro Regime Detection (Nihai)

```python
class MacroRegimeDetector:
    """Makro rejim tespiti."""
    
    # Makro rejimler
    MACRO_REGIMES = {
        "EXPANSION": {"description": "Genişleyici", "characteristics": ["düşük faiz", "düşük enflasyon", "güçlü büyüme"]},
        "CONTRACTION": {"description": "Daraltıcı", "characteristics": ["yüksek faiz", "yüksek enflasyon", "zayıf büyüme"]},
        "STAGFLATION": {"description": "Stagflasyon", "characteristics": ["yüksek enflasyon", "zayıf büyüme", "yüksek faiz"]},
        "REFLATION": {"description": "Reflasyon", "characteristics": ["düşük faiz", "yükselen enflasyon", "toparlanma"]},
        "RISK_ON": {"description": "Risk Açıklığı", "characteristics": ["düşük VIX", "yükselen S&P500", "düşük CDS"]},
        "RISK_OFF": {"description": "Risk Kaçışı", "characteristics": ["yüksek VIX", "düşen S&P500", "yükselen CDS"]},
    }
    
    def detect_regime(self, macro_features: Dict[str, float]) -> Dict:
        """Makro rejim tespit et."""
        scores = {}
        
        # Her rejim için skor hesapla
        scores["EXPANSION"] = self._score_expansion(macro_features)
        scores["CONTRACTION"] = self._score_contraction(macro_features)
        scores["STAGFLATION"] = self._score_stagflation(macro_features)
        scores["REFLATION"] = self._score_reflation(macro_features)
        scores["RISK_ON"] = self._score_risk_on(macro_features)
        scores["RISK_OFF"] = self._score_risk_off(macro_features)
        
        # En yüksek skorlu rejim
        best_regime = max(scores, key=scores.get)
        
        return {
            "regime": best_regime,
            "confidence": round(scores[best_regime], 4),
            "all_scores": {k: round(v, 4) for k, v in scores.items()},
            "description": self.MACRO_REGIMES[best_regime]["description"],
        }
    
    def _score_expansion(self, f: Dict) -> float:
        """Genişleyici rejim skoru."""
        score = 0
        if f.get("rate_trend", 0) < 0:  # Faiz düşüyor
            score += 0.3
        if f.get("inflation_trend", 0) < 0:  # Enflasyon düşüyor
            score += 0.2
        if f.get("sp500_momentum_20d", 0) > 0:  # S&P500 yükseliyor
            score += 0.2
        if f.get("vix_regime", 0) < 1.5:  # VIX düşük
            score += 0.2
        if f.get("credit_growth_yoy", 0) > 0:  # Kredi büyüyor
            score += 0.1
        return min(score, 1.0)
    
    def _score_risk_off(self, f: Dict) -> float:
        """Risk-off rejim skoru."""
        score = 0
        if f.get("vix_regime", 0) > 2.5:  # VIX yüksek
            score += 0.3
        if f.get("sp500_momentum_20d", 0) < -5:  # S&P500 düşüyor
            score += 0.3
        if f.get("cds_5y", 0) > 300:  # CDS yüksek
            score += 0.2
        if f.get("usdtry_momentum_20d", 0) > 5:  # USDTRY yükseliyor
            score += 0.2
        return min(score, 1.0)
```

### 4.4 Macro Correlation Tracking (Nihai)

```python
class MacroCorrelationTracker:
    """Makro değişkenler arası korelasyon takibi."""
    
    def __init__(self, window: int = 60):
        self._window = window
        self._history: Dict[str, List[float]] = {}
    
    def update(self, macro_data: Dict[str, float]):
        """Veri güncelle."""
        for key, value in macro_data.items():
            if key not in self._history:
                self._history[key] = []
            self._history[key].append(value)
            self._history[key] = self._history[key][-self._window:]
    
    def get_correlation(self, var1: str, var2: str) -> Optional[float]:
        """İki değişken arası korelasyon."""
        h1 = self._history.get(var1, [])
        h2 = self._history.get(var2, [])
        
        if len(h1) < 20 or len(h2) < 20:
            return None
        
        # Son N gözlemi kullan
        n = min(len(h1), len(h2), self._window)
        arr1 = np.array(h1[-n:])
        arr2 = np.array(h2[-n:])
        
        corr = np.corrcoef(arr1, arr2)[0, 1]
        return round(float(corr), 4)
    
    def get_correlation_matrix(self) -> Dict[str, Dict[str, float]]:
        """Tüm değişkenler arası korelasyon matrisi."""
        variables = list(self._history.keys())
        matrix = {}
        
        for v1 in variables:
            matrix[v1] = {}
            for v2 in variables:
                if v1 == v2:
                    matrix[v1][v2] = 1.0
                else:
                    matrix[v1][v2] = self.get_correlation(v1, v2)
        
        return matrix
```

### 4.5 Macro Stress Test (Nihai)

```python
class MacroStressTest:
    """Makro stres testi."""
    
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
        shocks = self.PREDEFINED_SCENARIOS.get(scenario)
        if not shocks:
            return {"error": f"Unknown scenario: {scenario}"}
        
        # Her pozisyon için etki hesapla
        impacts = []
        total_impact = 0
        
        for position in portfolio.get("positions", []):
            ticker = position.get("ticker", "")
            sector = position.get("sector", "OTHER")
            value = position.get("value", 0)
            
            # Sektör hassasiyeti
            sensitivity = macro_sensitivity_engine.get_sector_sensitivity(sector)
            
            # Etki hesapla
            impact = 0
            for shock_key, shock_value in shocks.items():
                sens_key = shock_key.replace("_change", "").replace("_pct", "")
                sens = sensitivity.get(sens_key, 0)
                impact += shock_value * sens
            
            position_impact = value * impact
            total_impact += position_impact
            
            impacts.append({
                "ticker": ticker,
                "sector": sector,
                "value": value,
                "impact_pct": round(impact * 100, 2),
                "impact_value": round(position_impact, 2),
            })
        
        return {
            "scenario": scenario,
            "shocks": shocks,
            "total_impact": round(total_impact, 2),
            "total_impact_pct": round(total_impact / portfolio.get("total_value", 1) * 100, 2),
            "position_impacts": impacts,
        }
```

---

## 5. Rakip Karşılaştırması

### 5.1 J.P. Morgan QIS (2026)

| Özellik | J.P. Morgan | Bizim Sistem | Fark |
|---------|-------------|-------------|------|
| Macro surprise model | ✅ Consensus + swap | ⚠️ Basit | ⚠️ |
| Regime detection | ✅ Multi-factor | ❌ | ❌ |
| Sector sensitivity | ✅ Dynamic | ⚠️ Sabit | ⚠️ |
| Stress test | ✅ Comprehensive | ⚠️ Basit | ⚠️ |
| Correlation tracking | ✅ Rolling | ❌ | ❌ |

### 5.2 ECB Financial Stability Review (2026)

| Özellik | ECB | Bizim Sistem | Fark |
|---------|-----|-------------|------|
| Macro risk assessment | ✅ Multi-country | ⚠️ Turkey only | ⚠️ |
| Stress scenarios | ✅ Severe | ⚠️ Basit | ⚠️ |
| Macro-financial linkages | ✅ | ❌ | ❌ |

### 5.3 SBB Medium Term Program (2026-2028)

| Özellik | SBB | Bizim Sistem | Fark |
|---------|-----|-------------|------|
| GDP forecast | ✅ | ❌ | ❌ |
| Inflation forecast | ✅ | ❌ | ❌ |
| Current account forecast | ✅ | ❌ | ❌ |
| Policy direction | ✅ | ❌ | ❌ |

---

## 6. Uygulama Planı

### Faz 1: Macro Surprise Model (Hemen)
1. TCMB beklenti verisi (anket veya swap pricing)
2. Enflasyon beklenti verisi
3. Surprise magnitude ve direction
4. Sektör bazlı surprise etkisi

### Faz 2: Macro Regime Detection (1 hafta)
1. 6 makro rejim tanımla
2. K-means veya skor bazlı tespit
3. Regime transition tracking
4. Regime-specific strateji

### Faz 3: Dynamic Sector Sensitivity (1 hafta)
1. Rolling sector-macro korelasyon
2. Sensitivity trend tracking
3. Company-specific override
4. Factor decomposition

### Faz 4: Macro Correlation Tracking (1 hafta)
1. Rolling correlation matrix
2. USDTRY-altın, faiz-enflasyon, VIX-BIST
3. Correlation regime detection
4. Correlation breakdown alerts

### Faz 5: Macro Stress Test (1 hafta)
1. Önceden tanımlı senaryolar
2. Portfolio bazlı stres testi
3. Sector impact hesaplama
4. Breaking point analysis

### Faz 6: Historical Macro Data (1 hafta)
1. Tarihsel makro veri deposu
2. Backtest'te makro feature kullanımı
3. Point-in-time makro veri
4. Macro data versioning

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 9 (7 macro + 2 feature) | 15 |
| Toplam satır | ~600 | ~1,500 |
| Macro features | ✅ 30+ | ✅ 50+ |
| Macro surprise | ⚠️ Basit | ✅ Anket + swap |
| Macro regime | ❌ | ✅ 6 rejim |
| Sector sensitivity | ⚠️ Sabit | ✅ Dynamic rolling |
| Correlation tracking | ❌ | ✅ Rolling matrix |
| Stress test | ⚠️ Basit | ✅ Comprehensive |
| Historical data | ❌ | ✅ PIT store |
| Calendar integration | ⚠️ Basit | ✅ Otomatik tetikleme |
| Factor decomposition | ❌ | ✅ |
| Decay model | ❌ | ✅ |
