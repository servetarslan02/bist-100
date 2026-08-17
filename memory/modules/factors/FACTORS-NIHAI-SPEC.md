# Factors Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Fama-French Five-Factor (Borsa Istanbul, ResearchGate 2023), Piotroski F-Score (BIST, İşler Dergisi 2025), Beneish M-Score (BIST, SAGE 2025), Robeco Next-Gen Quant (2024), CFA Institute Factor Investing (2025), iShares Dynamic Factor Rotation (2025)

---

## 1. Mevcut Durum (Kod Analizi)

### Modüller (7 dosya, toplam 135 satır)

| Modül | Satır | Fonksiyon | Durum |
|-------|-------|-----------|-------|
| `piotroski.py` | 27 | `calculate_f_score()` | ⚠️ Basit, 9 kriter |
| `beneish.py` | 18 | `calculate_m_score()` | ⚠️ Basit, 8 değişken |
| `altman.py` | 14 | `calculate_z_score()` | ⚠️ Basit, 5 değişken |
| `fama_french.py` | 25 | `calculate_factor_scores()` | ⚠️ Basit, 5 faktör |
| `bist_anomalies.py` | 17 | `calculate_bist_anomalies()` | ⚠️ Çok basit |
| `ranking.py` | 14 | `rank_stocks()` | ⚠️ Basit ağırlıklı sıralama |
| `performance.py` | 20 | `track_factor_performance()` | ⚠️ Basit metrikler |

### Sorunlar

1. **piotroski.py**: 9 kriter var ama ağırlık yok — hepsi eşit ağırlıklı
2. **beneish.py**: 8 değişken var ama hepsi default=1 — gerçek veri gelmezse sonuç anlamsız
3. **altman.py**: Orijinal Altman formülü ama Türkiye'ye özgü düzeltme yok
4. **fama_french.py**: Sadece skor hesaplama — gerçek factor return yok
5. **bist_anomalies.py**: 4 anomalisi var ama çok yüzeysel
6. **ranking.py**: Basit ağırlıklı toplama — risk-adjusted ranking yok
7. **performance.py**: Sadece alpha, sharpe, max_drawdown — factor exposure yok
8. **Time-series analysis** yok — faktör performansı zaman içinde analiz edilmiyor
9. **Factor correlation** yok — faktörler arası korelasyon hesaplanmıyor
10. **Factor rotation** yok — rejime göre faktör ağırlığı değişmiyor

---

## 2. Factor Investing Nedir? (Araştırma Bazlı)

### Tanım

Factor investing, hisse seçiminde belirli "faktörler" (özellikler) kullanan stratejidir. Amaç, uzun vadede bu faktörlerin getiri premium'larından yararlanmaktır.

### Temel Faktörler (Fama-French)

| Faktör | Tanım | BIST Kanıt |
|--------|-------|-----------|
| **Value** | Düşük P/B, P/E → yüksek getiri | ✅ BIST'te çalışıyor |
| **Momentum** | Son 6-12 ay yüksek getiri → devam | ✅ BIST'te çalışıyor |
| **Size** | Küçük şirketler → yüksek getiri | ⚠️ BIST'te tartışmalı |
| **Quality** | Yüksek ROE, düşük borç → yüksek getiri | ✅ BIST'te çalışıyor |
| **Low Volatility** | Düşük volatilite → yüksek risk-adjusted getiri | ✅ BIST'te çalışıyor |

### Ek Faktörler (Araştırma Bazlı)

| Faktör | Tanım | BIST Kanıt |
|--------|-------|-----------|
| **Profitability** | Yüksek kârlılık → yüksek getiri | ✅ Fama-French 5-factor |
| **Investment** | Düşük yatırım → yüksek getiri | ⚠️ BIST'te tartışmalı |
| **Dividend** | Yüksek temettü → yüksek getiri | ✅ BIST'te çalışıyor |
| **Low Leverage** | Düşük borç → yüksek getiri | ✅ BIST'te çalışıyor |
| **Earnings Quality** | Yüksek kazanç kalitesi → yüksek getiri | ✅ Piotroski F-Score |

---

## 3. Nihai Factor Mimarisi

### 3.1 Factor Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    FACTOR PIPELINE                           │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Financial │  │ Market    │  │ Macro     │              │
│  │ Data      │  │ Data      │  │ Data      │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FACTOR CALCULATION                      │   │
│  │                                                      │   │
│  │  Value Factors:     P/B, P/E, EV/EBITDA, FCF Yield  │   │
│  │  Momentum Factors:  1M, 3M, 6M, 12M momentum        │   │
│  │  Quality Factors:   ROE, ROIC, F-Score, Earnings Q.  │   │
│  │  Size Factors:      Market Cap, Enterprise Value     │   │
│  │  Volatility Factors: Realized Vol, Beta, ATR         │   │
│  │  Leverage Factors:  D/E, Net Debt/EBITDA, Interest  │   │
│  │  Dividend Factors:  Yield, Payout Ratio, Growth     │   │
│  │  BIST-Specific:     FX Sensitivity, Sector Momentum  │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FACTOR SCORING                          │   │
│  │                                                      │   │
│  │  1. Cross-sectional ranking (her faktör için)        │   │
│  │  2. Z-score normalization                            │   │
│  │  3. Percentile scoring                               │   │
│  │  4. Composite score (ağırlıklı toplam)               │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FACTOR COMBINATION                      │   │
│  │                                                      │   │
│  │  1. Equal weight (eşit ağırlık)                      │   │
│  │  2. Risk parity (risk paritesi)                      │   │
│  │  3. Regime-based (rejime göre)                       │   │
│  │  4. ML-optimized (makine öğrenmesi)                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FACTOR RANKING                          │   │
│  │                                                      │   │
│  │  1. Cross-sectional rank                             │   │
│  │  2. Sector-neutral rank                              │   │
│  │  3. Risk-adjusted rank                               │   │
│  │  4. Final ranking                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Piotroski F-Score (Detaylı)

```python
class PiotroskiFScore:
    """Piotroski F-Score — 9 kriter, ağırlıklı."""
    
    # Kriter ağırlıkları (araştırma bazlı)
    WEIGHTS = {
        "net_income_positive": 1.0,      # Kârlılık
        "operating_cf_positive": 1.0,    # Nakit akışı
        "roa_increasing": 1.0,           # Kârlılık trendi
        "cf_gt_ni": 1.0,                 # Kazanç kalitesi
        "leverage_decreasing": 1.0,      # Borç azalması
        "current_ratio_increasing": 1.0, # Likidite artışı
        "no_dilution": 1.0,              # Seyreltme yok
        "gross_margin_increasing": 1.0,  # Marj artışı
        "asset_turnover_increasing": 1.0,# Verimlilik artışı
    }
    
    def calculate(self, financials: Dict, financials_prev: Dict = None) -> Dict:
        """Detaylı F-Score hesaplama."""
        score = 0
        details = {}
        
        # 1. Net income > 0
        ni = financials.get("net_income", 0)
        criterion = ni > 0
        score += criterion * self.WEIGHTS["net_income_positive"]
        details["net_income"] = {"value": ni, "passed": criterion}
        
        # 2. Operating cash flow > 0
        ocf = financials.get("operating_cf", 0)
        criterion = ocf > 0
        score += criterion * self.WEIGHTS["operating_cf_positive"]
        details["operating_cf"] = {"value": ocf, "passed": criterion}
        
        # 3. ROA increasing
        roa_curr = financials.get("roa", 0)
        roa_prev = financials_prev.get("roa", 0) if financials_prev else 0
        criterion = roa_curr > roa_prev
        score += criterion * self.WEIGHTS["roa_increasing"]
        details["roa_increasing"] = {"current": roa_curr, "previous": roa_prev, "passed": criterion}
        
        # 4. Cash flow > Net income (accruals)
        criterion = ocf > ni
        score += criterion * self.WEIGHTS["cf_gt_ni"]
        details["cf_gt_ni"] = {"cf": ocf, "ni": ni, "passed": criterion}
        
        # 5. Leverage decreasing
        lev_curr = financials.get("leverage", 0)
        lev_prev = financials_prev.get("leverage", 0) if financials_prev else 0
        criterion = lev_curr < lev_prev
        score += criterion * self.WEIGHTS["leverage_decreasing"]
        details["leverage_decreasing"] = {"current": lev_curr, "previous": lev_prev, "passed": criterion}
        
        # 6. Current ratio increasing
        cr_curr = financials.get("current_ratio", 0)
        cr_prev = financials_prev.get("current_ratio", 0) if financials_prev else 0
        criterion = cr_curr > cr_prev
        score += criterion * self.WEIGHTS["current_ratio_increasing"]
        details["current_ratio_increasing"] = {"current": cr_curr, "previous": cr_prev, "passed": criterion}
        
        # 7. No dilution
        shares_curr = financials.get("shares_outstanding", 0)
        shares_prev = financials_prev.get("shares_outstanding", 0) if financials_prev else 0
        criterion = shares_curr <= shares_prev
        score += criterion * self.WEIGHTS["no_dilution"]
        details["no_dilution"] = {"current": shares_curr, "previous": shares_prev, "passed": criterion}
        
        # 8. Gross margin increasing
        gm_curr = financials.get("gross_margin", 0)
        gm_prev = financials_prev.get("gross_margin", 0) if financials_prev else 0
        criterion = gm_curr > gm_prev
        score += criterion * self.WEIGHTS["gross_margin_increasing"]
        details["gross_margin_increasing"] = {"current": gm_curr, "previous": gm_prev, "passed": criterion}
        
        # 9. Asset turnover increasing
        at_curr = financials.get("asset_turnover", 0)
        at_prev = financials_prev.get("asset_turnover", 0) if financials_prev else 0
        criterion = at_curr > at_prev
        score += criterion * self.WEIGHTS["asset_turnover_increasing"]
        details["asset_turnover_increasing"] = {"current": at_curr, "previous": at_prev, "passed": criterion}
        
        return {
            "f_score": score,
            "max_score": 9,
            "category": "STRONG" if score >= 7 else ("MODERATE" if score >= 4 else "WEAK"),
            "details": details,
        }
```

### 3.3 Beneish M-Score (Detaylı)

```python
class BeneishMScore:
    """Beneish M-Score — Finansal manipülasyon tespiti."""
    
    # Orijinal Beneish katsayıları (1999)
    COEFFICIENTS = {
        "constant": -4.84,
        "dsri": 0.92,
        "gmi": 0.528,
        "aqi": 0.404,
        "sgi": 0.892,
        "depi": 0.115,
        "sgai": -0.172,
        "tata": 4.679,
        "lvgi": -0.327,
    }
    
    # Eşik değerleri
    THRESHOLD = -1.78  # M-Score > -1.78 → manipülasyon olabilir
    
    def calculate(self, current: Dict, previous: Dict) -> Dict:
        """Detaylı M-Score hesaplama."""
        # 1. DSRI (Days Sales in Receivables Index)
        dsri_curr = current.get("receivables", 0) / max(current.get("revenue", 1), 1)
        dsri_prev = previous.get("receivables", 0) / max(previous.get("revenue", 1), 1)
        dsri = dsri_curr / max(dsri_prev, 0.01)
        
        # 2. GMI (Gross Margin Index)
        gm_prev = previous.get("gross_margin", 0)
        gm_curr = current.get("gross_margin", 0)
        gmi = gm_prev / max(gm_curr, 0.01) if gm_curr > 0 else 1
        
        # 3. AQI (Asset Quality Index)
        aqi_curr = 1 - (current.get("current_assets", 0) + current.get("ppe", 0)) / max(current.get("total_assets", 1), 1)
        aqi_prev = 1 - (previous.get("current_assets", 0) + previous.get("ppe", 0)) / max(previous.get("total_assets", 1), 1)
        aqi = aqi_curr / max(aqi_prev, 0.01)
        
        # 4. SGI (Sales Growth Index)
        sgi = current.get("revenue", 0) / max(previous.get("revenue", 1), 1)
        
        # 5. DEPI (Depreciation Index)
        depi_prev = previous.get("depreciation", 0) / max(previous.get("depreciation", 0) + previous.get("ppe", 0), 1)
        depi_curr = current.get("depreciation", 0) / max(current.get("depreciation", 0) + current.get("ppe", 0), 1)
        depi = depi_prev / max(depi_curr, 0.01)
        
        # 6. SGAI (SGA Expense Index)
        sgai_prev = previous.get("sga", 0) / max(previous.get("revenue", 1), 1)
        sgai_curr = current.get("sga", 0) / max(current.get("revenue", 1), 1)
        sgai = sgai_curr / max(sgai_prev, 0.01)
        
        # 7. LVGI (Leverage Index)
        lvgi_prev = previous.get("total_debt", 0) / max(previous.get("total_assets", 1), 1)
        lvgi_curr = current.get("total_debt", 0) / max(current.get("total_assets", 1), 1)
        lvgi = lvgi_curr / max(lvgi_prev, 0.01)
        
        # 8. TATA (Total Accruals to Total Assets)
        tata = (current.get("net_income", 0) - current.get("operating_cf", 0)) / max(current.get("total_assets", 1), 1)
        
        # M-Score hesapla
        m_score = (
            self.COEFFICIENTS["constant"]
            + self.COEFFICIENTS["dsri"] * dsri
            + self.COEFFICIENTS["gmi"] * gmi
            + self.COEFFICIENTS["aqi"] * aqi
            + self.COEFFICIENTS["sgi"] * sgi
            + self.COEFFICIENTS["depi"] * depi
            + self.COEFFICIENTS["sgai"] * sgai
            + self.COEFFICIENTS["tata"] * tata
            + self.COEFFICIENTS["lvgi"] * lvgi
        )
        
        return {
            "m_score": round(m_score, 4),
            "threshold": self.THRESHOLD,
            "manipulation_likely": m_score > self.THRESHOLD,
            "category": "HIGH_RISK" if m_score > -1.78 else ("MODERATE" if m_score > -2.22 else "LOW_RISK"),
            "components": {
                "dsri": round(dsri, 4),
                "gmi": round(gmi, 4),
                "aqi": round(aqi, 4),
                "sgi": round(sgi, 4),
                "depi": round(depi, 4),
                "sgai": round(sgai, 4),
                "lvgi": round(lvgi, 4),
                "tata": round(tata, 4),
            },
        }
```

### 3.4 Altman Z-Score (Türkiye Düzeltmeli)

```python
class AltmanZScore:
    """Altman Z-Score — Türkiye'ye özgü düzeltme."""
    
    # Orijinal Altman katsayıları (1968)
    ORIGINAL_COEFFICIENTS = {
        "wc_ta": 1.2,
        "re_ta": 1.4,
        "ebit_ta": 3.3,
        "equity_debt": 0.6,
        "sales_ta": 1.0,
    }
    
    # Türkiye'ye özgü düzeltme katsayıları (enflasyon, kur etkisi)
    TURKEY_ADJUSTMENTS = {
        "inflation_adjustment": 0.85,  # Enflasyon düzeltmesi
        "fx_adjustment": 0.90,         # Kur düzeltmesi
        "sector_adjustment": {         # Sektör düzeltmesi
            "BANK": 1.1,
            "INDUST": 0.95,
            "TECH": 1.05,
            "ENERGY": 0.90,
        },
    }
    
    # Eşik değerleri
    ZONE_THRESHOLDS = {
        "safe": 2.99,      # Güvenli bölge
        "grey": 1.81,      # Gri bölge
        "distress": 0.0,   # İflas bölgesi
    }
    
    def calculate(self, financials: Dict, sector: str = "OTHER") -> Dict:
        """Detaylı Z-Score hesaplama (Türkiye düzeltmeli)."""
        total_assets = max(financials.get("total_assets", 1), 1)
        
        # Temel bileşenler
        wc_ta = financials.get("working_capital", 0) / total_assets
        re_ta = financials.get("retained_earnings", 0) / total_assets
        ebit_ta = financials.get("ebit", 0) / total_assets
        equity_debt = financials.get("market_cap", 0) / max(financials.get("total_debt", 1), 1)
        sales_ta = financials.get("revenue", 0) / total_assets
        
        # Orijinal Z-Score
        z_original = (
            self.ORIGINAL_COEFFICIENTS["wc_ta"] * wc_ta
            + self.ORIGINAL_COEFFICIENTS["re_ta"] * re_ta
            + self.ORIGINAL_COEFFICIENTS["ebit_ta"] * ebit_ta
            + self.ORIGINAL_COEFFICIENTS["equity_debt"] * equity_debt
            + self.ORIGINAL_COEFFICIENTS["sales_ta"] * sales_ta
        )
        
        # Türkiye düzeltmesi
        inflation_adj = self.TURKEY_ADJUSTMENTS["inflation_adjustment"]
        fx_adj = self.TURKEY_ADJUSTMENTS["fx_adjustment"]
        sector_adj = self.TURKEY_ADJUSTMENTS["sector_adjustment"].get(sector, 1.0)
        
        z_adjusted = z_original * inflation_adj * fx_adj * sector_adj
        
        # Bölge belirleme
        if z_adjusted > self.ZONE_THRESHOLDS["safe"]:
            zone = "SAFE"
        elif z_adjusted > self.ZONE_THRESHOLDS["grey"]:
            zone = "GREY"
        else:
            zone = "DISTRESS"
        
        return {
            "z_score": round(z_adjusted, 4),
            "z_score_original": round(z_original, 4),
            "zone": zone,
            "thresholds": self.ZONE_THRESHOLDS,
            "adjustments": {
                "inflation": inflation_adj,
                "fx": fx_adj,
                "sector": sector_adj,
            },
            "components": {
                "wc_ta": round(wc_ta, 4),
                "re_ta": round(re_ta, 4),
                "ebit_ta": round(ebit_ta, 4),
                "equity_debt": round(equity_debt, 4),
                "sales_ta": round(sales_ta, 4),
            },
        }
```

### 3.5 Multi-Factor Ranking (Detaylı)

```python
class MultiFactorRanking:
    """Çok faktörlü hisse sıralaması — risk-adjusted."""
    
    # Faktör ağırlıkları (regime'ye göre değişebilir)
    DEFAULT_WEIGHTS = {
        "value": 0.15,
        "momentum": 0.20,
        "quality": 0.20,
        "size": 0.10,
        "low_vol": 0.10,
        "dividend": 0.10,
        "leverage": 0.10,
        "bist_specific": 0.05,
    }
    
    # Rejime göre ağırlık ayarlamaları
    REGIME_WEIGHTS = {
        "BULL": {"momentum": 0.30, "quality": 0.15, "value": 0.10},
        "BEAR": {"quality": 0.30, "low_vol": 0.20, "dividend": 0.15},
        "SIDEWAYS": {"value": 0.25, "dividend": 0.20, "quality": 0.20},
        "HIGH_VOL": {"low_vol": 0.25, "quality": 0.25, "dividend": 0.15},
    }
    
    def rank(self, universe: List[Dict], weights: Dict = None, regime: str = "NORMAL") -> List[Dict]:
        """Risk-adjusted çok faktörlü sıralama."""
        if weights is None:
            weights = dict(self.DEFAULT_WEIGHTS)
        
        # Rejime göre ağırlık ayarla
        if regime in self.REGIME_WEIGHTS:
            weights.update(self.REGIME_WEIGHTS[regime])
        
        # Her hisse için skor hesapla
        for stock in universe:
            factors = stock.get("factors", {})
            
            # Ağırlıklı skor
            total_score = 0
            factor_contributions = {}
            for factor, weight in weights.items():
                factor_score = factors.get(factor, 0)
                contribution = factor_score * weight
                total_score += contribution
                factor_contributions[factor] = {
                    "score": factor_score,
                    "weight": weight,
                    "contribution": round(contribution, 4),
                }
            
            # Risk adjustment
            risk_score = stock.get("risk_score", 50)
            risk_adjusted_score = total_score * (risk_score / 100)
            
            stock["factor_score"] = round(total_score, 4)
            stock["risk_adjusted_score"] = round(risk_adjusted_score, 4)
            stock["factor_contributions"] = factor_contributions
        
        # Risk-adjusted skora göre sırala
        universe.sort(key=lambda s: s.get("risk_adjusted_score", 0), reverse=True)
        
        # Rank ekle
        for i, stock in enumerate(universe):
            stock["rank"] = i + 1
        
        return universe
```

### 3.6 Factor Performance Tracker (Detaylı)

```python
class FactorPerformanceTracker:
    """Faktör performans takibi — detaylı."""
    
    def track(self, factor_returns: List[float], benchmark_returns: List[float],
              factor_name: str = "unknown") -> Dict:
        """Detaylı faktör performans analizi."""
        if not factor_returns or not benchmark_returns:
            return {"error": "Insufficient data"}
        
        f = np.array(factor_returns)
        b = np.array(benchmark_returns)
        
        # Temel metrikler
        total_return = float(np.prod(1 + f) - 1)
        annual_return = float((1 + total_return) ** (252 / len(f)) - 1)
        volatility = float(np.std(f) * np.sqrt(252))
        sharpe = annual_return / max(volatility, 0.001)
        
        # Risk metrikleri
        cumulative = np.cumprod(1 + f)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak
        max_drawdown = float(np.min(drawdown))
        
        # Benchmark karşılaştırma
        excess = f - b
        alpha = float(np.mean(excess) * 252)
        tracking_error = float(np.std(excess) * np.sqrt(252))
        information_ratio = alpha / max(tracking_error, 0.001)
        
        # Factor exposure (beta)
        if len(b) > 1:
            beta = float(np.cov(f, b)[0][1] / np.var(b))
        else:
            beta = 1.0
        
        return {
            "factor": factor_name,
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "volatility": round(volatility, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "alpha": round(alpha, 4),
            "beta": round(beta, 4),
            "tracking_error": round(tracking_error, 4),
            "information_ratio": round(information_ratio, 4),
            "n_periods": len(f),
        }
```

---

## 4. BIST'e Özgü Faktörler (Araştırma Bazlı)

### 4.1 BIST Anomalyleri

| Anomaly | Tanım | BIST Kanıt |
|---------|-------|-----------|
| **Temettü Anomalisi** | Yüksek temettü verimi → excess return | ✅ BIST'te güçlü |
| **Likidite Anomalisi** | Düşük likidite → likidite premium | ✅ BIST'te çalışıyor |
| **Kur Etkisi** | USDTRY hassasiyeti → FX premium | ✅ BIST'te kritik |
| **Sektör Momentum** | Sektör rotasyonu → momentum | ✅ BIST'te çalışıyor |
| **Boyut Anomalisi** | Küçük şirketler → size premium | ⚠️ BIST'te tartışmalı |
| **Volatilite Anomalisi** | Düşük volatilite → vol premium | ✅ BIST'te çalışıyor |

### 4.2 Türkiye'ye Özgü Faktörler

```python
class BISTSpecificFactors:
    """BIST'e özgü faktörler."""
    
    def calculate(self, stock: Dict, market_data: Dict) -> Dict:
        factors = {}
        
        # 1. Kur Hassasiyeti
        factors["fx_sensitivity"] = stock.get("usdtry_beta", 0)
        
        # 2. Enflasyon Hassasiyeti
        factors["inflation_sensitivity"] = stock.get("inflation_beta", 0)
        
        # 3. Faiz Hassasiyeti
        factors["rate_sensitivity"] = stock.get("rate_beta", 0)
        
        # 4. Sektör Momentum
        factors["sector_momentum"] = stock.get("sector_momentum", 0)
        
        # 5. KAP Etkisi
        factors["kap_sentiment"] = stock.get("kap_sentiment", 0)
        
        # 6. Yabancı Yatırımcı Oranı
        factors["foreign_ownership"] = stock.get("foreign_ownership", 0)
        
        # 7. Likidite Premium
        factors["liquidity_premium"] = 1.0 - min(stock.get("avg_volume", 0) / 1000000, 1.0)
        
        # 8. Temettü Verimi
        factors["dividend_yield"] = stock.get("dividend_yield", 0)
        
        return factors
```

---

## 5. Uygulama Planı

### Faz 1: Kritik Düzeltmeler (Hemen)
1. Piotroski F-Score — ağırlıklar ekle
2. Beneish M-Score — gerçek veri entegrasyonu
3. Altman Z-Score — Türkiye düzeltmesi
4. Fama-French — gerçek factor return hesapla

### Faz 2: BIST Faktörleri (1 hafta)
1. BIST anomaly'leri detaylandır
2. Türkiye'ye özgü faktörler ekle
3. KAP sentiment faktörü
4. FX/inflasyon/faiz hassasiyeti

### Faz 3: Factor Combination (1 hafta)
1. Multi-factor ranking — risk-adjusted
2. Rejime göre faktör ağırlıkları
3. Factor correlation analizi
4. Factor rotation stratejisi

### Faz 4: Factor Performance (1 hafta)
1. Faktör performans takibi
2. Factor exposure analizi
3. Time-series factor returns
4. Benchmark karşılaştırma

### Faz 5: ML Integration (1 hafta)
1. Factor-based ML features
2. Factor importance (SHAP)
3. Dynamic factor weighting
4. Factor-based portfolio optimization

---

## 6. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 7 | 14 |
| Toplam satır | 135 | ~600 |
| Piotroski F-Score | ⚠️ Basit | ✅ Ağırlıklı |
| Beneish M-Score | ⚠️ Default values | ✅ Gerçek veri |
| Altman Z-Score | ⚠️ Orijinal | ✅ Türkiye düzeltmeli |
| Fama-French | ⚠️ Skor only | ✅ Factor returns |
| BIST anomalileri | ⚠️ 4 anomaly | ✅ 8+ anomaly |
| Multi-factor ranking | ⚠️ Basit | ✅ Risk-adjusted |
| Factor performance | ⚠️ 3 metrik | ✅ 10+ metrik |
| Factor correlation | ❌ | ✅ |
| Factor rotation | ❌ | ✅ |
| Rejime göre ağırlık | ❌ | ✅ |
| Türkiye'ye özgü faktörler | ❌ | ✅ |
