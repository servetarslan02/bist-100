# Risk Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** ScienceDirect Integrated Risk Management (2026), arXiv Agentic Trading (2026), SSRN Regime-Conditioned Kelly (2026), ScienceDirect RMSE-Triggered Rebalancing (2026), Resonanz Capital Tail-Risk Hedging (2025), Breaking Alpha Position Sizing (2025)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Risk Management System (En İyi Uygulama)

**Temel prensip:** Risk motoru AI'ın üzerinde çalışır — hiçbir model risk limitini bypass edemez.

```
RISK MANAGEMENT SYSTEM
├── Pre-Trade Risk (İşlem öncesi)
│   ├── Position limits
│   ├── Sector concentration
│   ├── Portfolio exposure
│   ├── Confidence threshold
│   ├── Daily loss limit
│   ├── Drawdown limit
│   ├── Liquidity check
│   └── BIST rules (short selling, halt, compliance)
├── Position Sizing (Pozisyon boyutu)
│   ├── Kelly Criterion (calibrated)
│   ├── Volatility targeting
│   ├── Risk parity
│   └── Regime-adjusted
├── Portfolio Risk (Portföy riski)
│   ├── Ledoit-Wolf covariance
│   ├── VaR/CVaR
│   ├── Drawdown tracking
│   ├── Correlation risk
│   └── Concentration risk (HHI)
├── Stress Test (Stres testi)
│   ├── Historical scenarios
│   ├── Hypothetical scenarios
│   ├── Monte Carlo
│   └── Breaking point analysis
├── Monitoring (İzleme)
│   ├── Real-time risk metrics
│   ├── Alert system
│   ├── Risk dashboard
│   └── Performance attribution
└── Calibration (Kalibrasyon)
    ├── Score → probability
    ├── Platt scaling
    ├── Isotonic regression
    └── Online learning
```

### 1.2 Kelly Criterion (En İyi Uygulama)

**Formül:** `f* = (p × b - q) / b`
- p = win probability
- q = 1 - p
- b = avg_win / avg_loss

**En İyi Uygulama:** Fractional Kelly (0.5x) — daha güvenli

**Kaynak:** SSRN Regime-Conditioned Kelly (2026) — rejime göre Kelly fraction değişmeli

### 1.3 Ledoit-Wolf Covariance (En İyi Uygulama)

**Problem:** Sample covariance gürültülü, overfitting riski
**Çözüm:** Shrinkage estimator — sample covariance ile target arasında denge

**Kaynak:** ScienceDirect RMSE-Triggered Rebalancing (2026) — Ledoit-Wolf transaction cost'u azaltıyor

### 1.4 VaR/CVaR (En İyi Uygulama)

| Metrik | Ne | Kullanım |
|--------|-----|----------|
| **VaR 95%** | %95 güvenle max kayıp | Günlük risk limiti |
| **CVaR 95%** | VaR'ı aşan ortalama kayıp | Tail risk |
| **Component VaR** | Pozisyon bazlı risk katkısı | Risk allocation |
| **Marginal VaR** | Yeni pozisyon eklenince risk değişimi | Pre-trade risk |

### 1.5 Drawdown Management (En İyi Uygulama)

```
Drawdown Tracking:
- Peak equity → Current equity → Drawdown %
- Max drawdown tracking
- Drawdown duration
- Recovery time

Drawdown Response:
- Drawdown > 5% → Pozisyon boyutunu azalt
- Drawdown > 10% → Yeni pozisyon durdur
- Drawdown > 15% → Pozisyon kapat
- Drawdown > 20% → Sistem durdur
```

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (7 dosya, 1,654 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `main.py` (risk) | 456 | Risk engine, event consumer, position/sector/daily/drawdown checks | ✅ İyi |
| `position_sizing.py` | 335 | Kelly criterion, volatility targeting, regime-adjusted sizing | ✅ İyi |
| `enhanced_risk.py` | 318 | Ledoit-Wolf covariance, volatility targeting, rebalance, concentration | ✅ İyi |
| `covariance.py` | 153 | Ledoit-Wolf shrinkage covariance estimation | ✅ İyi |
| `calibration.py` | 122 | Score → probability calibration (Platt scaling) | ✅ İyi |
| `reconciliation.py` | 90 | Portfolio reconciliation (ledger vs DB) | ✅ İyi |
| `risk_gate.py` (core) | 180 | Pre-trade risk check, BIST rules integration | ✅ İyi |

### 2.2 risk/main.py (456 satır) — RiskEngine

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `_load_risk_limits()` | 84-129 | DB'den risk limitleri yükle | ✅ |
| `_on_decision()` | 130-226 | Decision event → risk kontrolü | ✅ İyi |
| `_on_signal()` | 227-249 | Signal event → risk kontrolü | ✅ |
| `_check_position_limit()` | 250-282 | Pozisyon limiti kontrolü | ✅ |
| `_check_sector_concentration()` | 283-332 | Sektör konsantrasyon kontrolü | ✅ |
| `_check_daily_loss()` | 333-366 | Günlük zarar limiti | ✅ |
| `_check_drawdown()` | 367-405 | Drawdown limiti | ✅ |

### 2.3 position_sizing.py (335 satır) — PositionSizer

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `calculate_position_sizes()` | 52-210 | Tüm pozisyon boyutlarını hesapla | ✅ İyi |
| `_fractional_kelly()` | 211-243 | Fractional Kelly criterion | ✅ İyi |
| `_volatility_leverage()` | 244-251 | Volatilite targeting leverage | ✅ İyi |

### 2.4 enhanced_risk.py (318 satır)

| Sınıf | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `LedoitWolfCovariance` | 49-93 | Shrinkage covariance | ✅ İyi |
| `VolatilityTargeter` | 94-136 | Volatilite targeting | ✅ İyi |
| `PositionSizer` | 137-197 | Kelly criterion + position sizing | ✅ İyi |
| `RebalanceEngine` | 198-257 | Rebalance motoru | ✅ İyi |
| `ConcentrationRisk` | 258-318 | HHI, sektör konsantrasyonu | ✅ İyi |

### 2.5 calibration.py (122 satır) — ScoreCalibrator

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `fit_from_trades()` | 35-78 | Historical trades'ten Platt scaling fit | ✅ İyi |
| `calibrate()` | 79-92 | Score → win_probability | ✅ İyi |
| `add_trade()` | 93-105 | Online learning (her 50 trade'te refit) | ✅ İyi |

### 2.6 covariance.py (153 satır) — CovarianceEstimator

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `estimate()` | 26-98 | Ledoit-Wolf shrinkage covariance | ✅ İyi |
| `compute_portfolio_volatility()` | 133-139 | Portföy volatilitesi | ✅ |
| `compute_diversification_ratio()` | 141-153 | Diversification ratio | ✅ |

### 2.7 risk_gate.py (180 satır) — RiskGate

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `check_order()` | 48-170 | 9 check: circuit, market, data, exposure, order size, position, confidence, daily loss, BIST rules | ✅ İyi |
| BIST entegrasyonu | 131-165 | Short selling, halt, price limits, compliance | ✅ İyi |

---

## 3. Eksikler (Kritik)

### 3.1 VaR/CVaR Yok

**Sorun:** Risk metriklerinde VaR/CVaR hesaplanmıyor
**Etki:** Tail risk ölçülemiyor
**Çözüm:** Portfolio VaR/CVaR, Component VaR, Marginal VaR

### 3.2 Stress Test Entegrasyonu Zayıf

**Sorun:** Scenario engine var ama risk ile entegrasyon zayıf
**Etki:** Stres testi sonuçları risk kararlarına yansımıyor
**Çözüm:** Stress test → risk gate entegrasyonu

### 3.3 Regime-Conditioned Kelly Yok

**Sorun:** Kelly fraction sabit (0.5) — rejime göre değişmiyor
**Etki:** Bull market'te çok muhafazakar, bear market'te çok agresif olabilir
**Kaynak:** SSRN (2026) — rejime göre Kelly fraction değişmeli
**Çözüm:** Regime-conditioned Kelly

### 3.4 Dynamic Risk Limits Yok

**Sorun:** Risk limitleri sabit (DB'den yükleniyor ama değişmiyor)
**Etki:** Volatilite artınca limitler otomatik sıkılaşmıyor
**Çözüm:** Volatilite bazlı dinamik limitler

### 3.5 Risk Dashboard Yok

**Sorun:** Risk metrikleri API'de var ama görsel dashboard yok
**Etki:** Risk durumu hızlı değerlendirilemiyor
**Çözüm:** Real-time risk dashboard

### 3.6 Alert System Zayıf

**Sorun:** Alert var ama özelleştirilebilir değil
**Etki:** Kritik risk durumları yeterince bildirilmiyor
**Çözüm:** Özelleştirilebilir alert kuralları

### 3.7 Tail Risk Hedging Yok

**Sorun:** Tail risk koruma stratejisi yok
**Etki:** Kriz durumlarında büyük kayıp
**Kaynak:** Resonanz Capital (2025) — stratejik tail-risk hedging
**Çözüm:** Protective put, tail risk hedge

### 3.8 Correlation Risk Basit

**Sorun:** `portfolio_correlation` sabit değer (enhanced_risk'te)
**Etki:** Gerçek korelasyon riski ölçülemiyor
**Çözüm:** Rolling correlation, regime-aware correlation

---

## 4. Nihai Risk Mimarisi

### 4.1 Risk Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    RISK PIPELINE                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PRE-TRADE RISK GATE                    │   │
│  │  - Circuit breaker check                            │   │
│  │  - Market session check                             │   │
│  │  - Data validity check                              │   │
│  │  - Portfolio exposure check                         │   │
│  │  - Order size check                                 │   │
│  │  - Position concentration check                     │   │
│  │  - Confidence threshold check                       │   │
│  │  - Daily loss limit check                           │   │
│  │  - Drawdown limit check                             │   │
│  │  - BIST rules (short selling, halt, compliance)     │   │
│  │  - Liquidity check ← YENİ                          │   │
│  │  - Volatility limit check ← YENİ                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              POSITION SIZING                        │   │
│  │  - Kelly Criterion (calibrated)                     │   │
│  │  - Fractional Kelly (0.5x default)                  │   │
│  │  - Regime-conditioned Kelly ← YENİ                  │   │
│  │  - Volatility targeting                             │   │
│  │  - Risk parity ← YENİ                               │   │
│  │  - Max position limit                               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PORTFOLIO RISK                         │   │
│  │  - Ledoit-Wolf covariance                           │   │
│  │  - Portfolio volatility                             │   │
│  │  - VaR (95%, 99%) ← YENİ                           │   │
│  │  - CVaR (95%, 99%) ← YENİ                          │   │
│  │  - Component VaR ← YENİ                             │   │
│  │  - Drawdown tracking                                │   │
│  │  - Correlation risk (rolling) ← YENİ                │   │
│  │  - Concentration risk (HHI)                         │   │
│  │  - Sector concentration                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DYNAMIC RISK LIMITS ← YENİ             │   │
│  │  - Volatilite artınca limitler sıkılaşır            │   │
│  │  - Rejim değişince limitler ayarlanır               │   │
│  │  - Drawdown olunca limitler düşürülür               │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              STRESS TEST                            │   │
│  │  - Historical scenarios (2008, 2020, 2022)          │   │
│  │  - Hypothetical scenarios (USDTRY +10%, BIST -15%)  │   │
│  │  - Monte Carlo simulation                           │   │
│  │  - Breaking point analysis                          │   │
│  │  - Portfolio impact                                 │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CALIBRATION                            │   │
│  │  - Score → probability (Platt scaling)              │   │
│  │  - Online learning (her 50 trade'te refit)          │   │
│  │  - Calibration curve monitoring                     │   │
│  │  - Brier score tracking                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RECONCILIATION                         │   │
│  │  - Ledger vs Positions                              │   │
│  │  - Cash vs Equity                                   │   │
│  │  - DB vs In-memory                                  │   │
│  │  - Discrepancy alert                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TAIL RISK HEDGING ← YENİ               │   │
│  │  - Protective put strategy                          │   │
│  │  - Tail risk hedge                                  │   │
│  │  - Crisis alpha                                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MONITORING & ALERTS ← GELİŞMİŞ        │   │
│  │  - Real-time risk metrics                           │   │
│  │  - Alert rules (özelleştirilebilir)                 │   │
│  │  - Risk dashboard                                   │   │
│  │  - Performance attribution                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 VaR/CVaR (Nihai)

```python
class VaRCalculator:
    """Value at Risk ve Conditional VaR."""
    
    def calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Parametrik VaR (normal dağılım)."""
        mu = np.mean(returns)
        sigma = np.std(returns)
        from scipy.stats import norm
        var = mu + sigma * norm.ppf(1 - confidence)
        return abs(float(var))
    
    def calculate_historical_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Tarihsel VaR."""
        sorted_returns = np.sort(returns)
        index = int((1 - confidence) * len(sorted_returns))
        return abs(float(sorted_returns[index]))
    
    def calculate_cvar(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall)."""
        var = self.calculate_historical_var(returns, confidence)
        tail = returns[returns <= -var]
        return abs(float(np.mean(tail))) if len(tail) > 0 else var
    
    def calculate_component_var(self, weights: np.ndarray, cov_matrix: np.ndarray,
                                confidence: float = 0.95) -> np.ndarray:
        """Component VaR — her pozisyonun portföy VaR'ına katkısı."""
        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        from scipy.stats import norm
        var_multiplier = norm.ppf(confidence)
        marginal_var = cov_matrix @ weights / portfolio_vol * var_multiplier
        component_var = weights * marginal_var
        return component_var
    
    def calculate_marginal_var(self, weights: np.ndarray, cov_matrix: np.ndarray,
                               confidence: float = 0.95) -> np.ndarray:
        """Marginal VaR — yeni pozisyon eklenince risk değişimi."""
        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        from scipy.stats import norm
        var_multiplier = norm.ppf(confidence)
        return cov_matrix @ weights / portfolio_vol * var_multiplier
```

### 4.3 Regime-Conditioned Kelly (Nihai)

```python
class RegimeConditionedKelly:
    """Rejime göre Kelly fraction."""
    
    # Rejim bazlı Kelly fraction (araştırma bazlı)
    REGIME_KELLY_FRACTIONS = {
        "BULL": 0.6,           # Agresif
        "BEAR": 0.3,           # Muhafazakar
        "SIDEWAYS": 0.4,       # Orta
        "HIGH_VOLATILITY": 0.25,  # Çok muhafazakar
        "LOW_VOLATILITY": 0.5,    # Normal
        "RISK_ON": 0.55,       # Biraz agresif
        "RISK_OFF": 0.3,       # Muhafazakar
        "CRISIS": 0.15,        # Çok muhafazakar
        "RECOVERY": 0.45,      # Orta-agresif
    }
    
    def calculate(self, win_rate: float, avg_win: float, avg_loss: float,
                  regime: str = "SIDEWAYS") -> float:
        """Rejime göre Kelly fraction hesapla."""
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0
        
        b = avg_win / avg_loss
        q = 1 - win_rate
        raw_kelly = (win_rate * b - q) / b
        
        if raw_kelly <= 0:
            return 0.0
        
        # Rejime göre fraction
        fraction = self.REGIME_KELLY_FRACTIONS.get(regime, 0.4)
        
        return raw_kelly * fraction
```

### 4.4 Dynamic Risk Limits (Nihai)

```python
class DynamicRiskLimits:
    """Volatilite ve rejime göre dinamik risk limitleri."""
    
    BASE_LIMITS = {
        "max_position_pct": 10.0,
        "max_sector_pct": 30.0,
        "max_drawdown_pct": 20.0,
        "daily_loss_limit_pct": 5.0,
        "max_exposure_pct": 95.0,
    }
    
    def get_limits(self, volatility: float, regime: str,
                   current_drawdown: float = 0) -> Dict[str, float]:
        """Dinamik limitler hesapla."""
        limits = dict(self.BASE_LIMITS)
        
        # Volatilite bazlı ayarlama
        vol_ratio = volatility / 0.20  # 20% baz volatilite
        if vol_ratio > 1.5:
            # Yüksek volatilite → limitleri sıkılaştır
            scale = 0.7
        elif vol_ratio > 1.2:
            scale = 0.85
        elif vol_ratio < 0.8:
            # Düşük volatilite → limitleri gevşet
            scale = 1.15
        else:
            scale = 1.0
        
        limits["max_position_pct"] *= scale
        limits["max_sector_pct"] *= scale
        limits["max_exposure_pct"] *= scale
        
        # Rejim bazlı ayarlama
        if regime in ["CRISIS", "RISK_OFF"]:
            limits["max_position_pct"] *= 0.5
            limits["max_exposure_pct"] *= 0.6
        elif regime == "BEAR":
            limits["max_position_pct"] *= 0.7
            limits["max_exposure_pct"] *= 0.8
        
        # Drawdown bazlı ayarlama
        if current_drawdown > 10:
            dd_scale = max(0.5, 1 - current_drawdown / 100)
            limits["max_position_pct"] *= dd_scale
            limits["max_exposure_pct"] *= dd_scale
        
        return limits
```

### 4.5 Stress Test (Nihai)

```python
class StressTestEngine:
    """Stres test motoru."""
    
    HISTORICAL_SCENARIOS = {
        "2008_CRISIS": {"bist": -0.52, "usdtry": 0.30, "vix": 80},
        "2020_COVID": {"bist": -0.35, "usdtry": 0.15, "vix": 65},
        "2022_INFLATION": {"bist": -0.25, "usdtry": 0.40, "vix": 35},
    }
    
    HYPOTHETICAL_SCENARIOS = {
        "USDTRY_10_PCT": {"usdtry": 0.10},
        "BIST_CRASH_15_PCT": {"bist": -0.15},
        "TCMB_RATE_HIKE_500BP": {"rate": 0.05},
        "GLOBAL_RISK_OFF": {"vix": 0.50, "bist": -0.10},
    }
    
    def run_stress_test(self, portfolio: Dict, scenario: str) -> Dict:
        """Stres testi çalıştır."""
        scenario_data = self.HISTORICAL_SCENARIOS.get(scenario) or \
                       self.HYPOTHETICAL_SCENARIOS.get(scenario)
        if not scenario_data:
            return {"error": f"Unknown scenario: {scenario}"}
        
        # Her pozisyon için etki hesapla
        total_impact = 0
        position_impacts = []
        
        for pos in portfolio.get("positions", []):
            ticker = pos.get("ticker", "")
            value = pos.get("value", 0)
            sector = pos.get("sector", "OTHER")
            
            # Sektör bazlı etki
            impact = self._calculate_sector_impact(sector, scenario_data)
            position_impact = value * impact
            total_impact += position_impact
            
            position_impacts.append({
                "ticker": ticker,
                "impact_pct": round(impact * 100, 2),
                "impact_value": round(position_impact, 2),
            })
        
        return {
            "scenario": scenario,
            "scenario_data": scenario_data,
            "total_impact": round(total_impact, 2),
            "total_impact_pct": round(total_impact / portfolio.get("total_value", 1) * 100, 2),
            "position_impacts": position_impacts,
        }
```

---

## 5. Rakip Karşılaştırması

### 5.1 ScienceDirect Integrated Risk Management (2026)

| Özellik | ScienceDirect | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| VaR/CVaR | ✅ | ❌ | ❌ |
| Ledoit-Wolf | ✅ | ✅ | ✅ Aynı |
| Stress testing | ✅ Comprehensive | ⚠️ Basit | ⚠️ |
| Dynamic limits | ✅ | ❌ | ❌ |
| Rebalancing | ✅ | ✅ | ✅ Aynı |

### 5.2 arXiv Agentic Trading (2026)

| Özellik | arXiv | Bizim Sistem | Fark |
|---------|-------|-------------|------|
| Kelly criterion | ✅ | ✅ | ✅ Aynı |
| Risk parity | ✅ | ⚠️ Basit | ⚠️ |
| VaR/CVaR | ✅ | ❌ | ❌ |
| Drawdown control | ✅ | ✅ | ✅ Aynı |

### 5.3 SSRN Regime-Conditioned Kelly (2026)

| Özellik | SSRN | Bizim Sistem | Fark |
|---------|------|-------------|------|
| Regime-conditioned Kelly | ✅ | ❌ | ❌ |
| Bayesian changepoint | ✅ | ❌ | ❌ |
| Fractional Kelly | ✅ | ✅ | ✅ Aynı |

---

## 6. Uygulama Planı

### Faz 1: VaR/CVaR (Hemen)
1. Parametrik VaR
2. Tarihsel VaR
3. CVaR (Expected Shortfall)
4. Component VaR
5. Risk metriklerine entegre et

### Faz 2: Regime-Conditioned Kelly (1 hafta)
1. Rejim bazlı Kelly fraction
2. Position sizing'a entegre et
3. Online learning ile güncelle

### Faz 3: Dynamic Risk Limits (1 hafta)
1. Volatilite bazlı limitler
2. Rejim bazlı limitler
3. Drawdown bazlı limitler
4. Risk gate'e entegre et

### Faz 4: Stress Test Enhancement (1 hafta)
1. Historical scenarios (2008, 2020, 2022)
2. Hypothetical scenarios
3. Monte Carlo stress test
4. Breaking point analysis
5. Risk gate'e entegre et

### Faz 5: Tail Risk Hedging (1 hafta)
1. Protective put strategy
2. Tail risk hedge
3. Crisis alpha
4. Portfolio'ya entegre et

### Faz 6: Monitoring Enhancement (1 hafta)
1. Real-time risk dashboard
2. Alert rules (özelleştirilebilir)
3. Performance attribution
4. API endpoint'leri

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 7 | 12 |
| Toplam satır | 1,654 | ~3,000 |
| Pre-trade risk gate | ✅ İyi | ✅ + dynamic limits |
| Kelly criterion | ✅ İyi | ✅ + regime-conditioned |
| Volatility targeting | ✅ İyi | ✅ |
| Ledoit-Wolf covariance | ✅ İyi | ✅ |
| Calibration | ✅ İyi | ✅ |
| Reconciliation | ✅ İyi | ✅ |
| VaR/CVaR | ❌ | ✅ |
| Stress test | ⚠️ Basit | ✅ Comprehensive |
| Dynamic risk limits | ❌ | ✅ |
| Tail risk hedging | ❌ | ✅ |
| Correlation risk | ⚠️ Basit | ✅ Rolling |
| Risk dashboard | ❌ | ✅ |
| Alert system | ⚠️ Basit | ✅ Özelleştirilebilir |
