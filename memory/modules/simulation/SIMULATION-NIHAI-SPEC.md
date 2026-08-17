# Simulation Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** arXiv Agentic Trading (2026), mbrenndoerfer Market Microstructure (2026), Springer Data-Driven Monte Carlo (2026), MDPI Regime-Dependent CVaR (2026), LinkedIn Jump-Diffusion (2025)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Execution Simulator (En İyi Uygulama)

**Temel prensip:** Simülasyon gerçek broker'a ne kadar yakınsa, backtest sonuçları o kadar güvenilir.

```
EXECUTION SIMULATOR (En İyi Uygulama)

Order Lifecycle:
CREATED → VALIDATED → RISK_APPROVED → SUBMITTED → ACCEPTED →
PARTIALLY_FILLED / FILLED / REJECTED / CANCELLED / EXPIRED / FAILED

Slippage Model:
- Base slippage (spread'in yarısı)
- Volume impact (participation rate × volatility)
- Market impact (büyük emirler için)
- Regime impact (volatilite artınca slippage artar)

Transaction Cost:
- Broker komisyonu
- BIST payı
- MKK payı
- BSMV
- Minimum komisyon

Partial Fill:
- Günlük hacmin %10'undan fazlasını alamaz
- Likidite yetersizse kısmi fill
- Geri kalan kısım iptal veya beklemede
```

### 1.2 Monte Carlo Simulation (En İyi Uygulama)

| Model | Özellik | Kaynak |
|-------|---------|--------|
| **GBM** | Basit geometric Brownian motion | Temel |
| **Fat Tails** | Student-t dağılımı (df=5) | MDPI (2026) |
| **Volatility Clustering** | GARCH(1,1) | Springer (2026) |
| **Regime-Conditioned** | Rejime göre parametre | arXiv (2026) |
| **Event Shock** | Rastgele şok enjeksiyonu | En iyi uygulama |
| **Jump-Diffusion** | Ani fiyat sıçramaları | LinkedIn (2025) |

### 1.3 Stress Test (En İyi Uygulama)

```
STRESS SCENARIOS:
1. Market Crash (-20%)
2. Currency Crisis (USDTRY +30%)
3. Rate Shock (+500bp)
4. Sector Rotation (-5%)
5. Black Swan (-30%)
6. Liquidity Crisis
7. Stagflation
8. Global Risk-Off
```

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (2 dosya, 601 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `execution_simulator.py` | 258 | Order lifecycle, slippage model, commission, partial fill | ✅ İyi |
| `main.py` | 343 | Monte Carlo, scenario analysis, stress test | ✅ İyi |

### 2.2 execution_simulator.py (258 satır) — Detaylı

| Sınıf/Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------------|-------|------------|-------|
| `OrderStatus` | 24-37 | 11 order durumu | ✅ İyi |
| `OrderSide` | 39-42 | BUY/SELL | ✅ |
| `OrderType` | 44-48 | MARKET/LIMIT/STOP_LIMIT | ✅ |
| `Order` | 50-73 | Emir modeli (17 alan) | ✅ İyi |
| `Fill` | 75-87 | Dolum modeli | ✅ |
| `ExecutionSimulator` | 89-258 | Ana simulator | ✅ |
| `execute_order()` | 98-116 | Emir simülasyonu (ana fonksiyon) | ✅ İyi |
| `_execute_order_internal()` | 118-182 | Internal execution logic | ✅ İyi |
| `_compute_slippage()` | 184-205 | Slippage hesaplama (base + volume impact) | ✅ İyi |
| `_compute_commission()` | 207-216 | Komisyon hesaplama (BIST yapısı) | ✅ İyi |
| `create_fill()` | 218-237 | Fill oluşturma | ✅ |

### 2.3 main.py (343 satır) — SimulationEngine

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `SimulationEngine` | 25-343 | Monte Carlo, scenario, stress test | ✅ |
| `_on_simulation_request()` | 68-98 | Event-driven simulation tetikleme | ✅ İyi |
| `_run_monte_carlo()` | 100-188 | Monte Carlo simülasyonu (GARCH, fat tails, event shock) | ✅ İyi |
| `_run_scenario_analysis()` | 190-237 | Senaryo analizi (Bull/Base/Bear/Crash) | ⚠️ Basit |
| `_run_stress_test()` | 239-298 | Stres testi (5 senaryo) | ⚠️ Basit |
| `_get_historical_volatility()` | 300-325 | Tarihsel volatilite (ClickHouse) | ✅ |

---

## 3. Eksikler (Kritik)

### 3.1 Spread Model Eksik

**Sorun:** Slippage'de spread sabit `spread_pct` parametresi — gerçek bid/ask spread kullanılmıyor
**Etki:** Spread gerçekçi değil
**Çözüm:** Bid/ask spread bazlı slippage

### 3.2 Market Impact Model Basit

**Sorun:** Volume impact = `participation_rate × volatility × 0.5` — square root model yok
**Etki:** Büyük emirlerde gerçekçi olmayan slippage
**Çözüm:** Square root market impact model

### 3.3 Regime Impact Yok

**Sorun:** Slippage rejime göre değişmiyor
**Etki:** High-volatility rejimde gerçekçi olmayan slippage
**Çözüm:** Rejime göre slippage ayarlaması

### 3.4 Liquidity Constraint Zayıf

**Sorun:** Sadece günlük hacmin %10'u limiti — daha detaylı likidite modeli yok
**Etki:** Likidite krizi simüle edilemiyor
**Çözüm:** Likidite profili (bid depth, ask depth)

### 3.5 Scenario Analysis Basit

**Sorun:** 4 sabit senaryo (Bull/Base/Bear/Crash) — beta=1 varsayım
**Etki:** Sektör bazlı etki hesaplanamıyor
**Çözüm:** Beta bazlı, sektör bazlı senaryo

### 3.6 Stress Test Basit

**Sorun:** 5 sabit stres senaryosu — USD hassasiyeti sabit 0.5
**Etki:** Şirket bazlı stres testi yapılamıyor
**Çözüm:** Şirket bazlı USD/faiz/enflasyon hassasiyeti

### 3.7 Monte Carlo — Jump-Diffusion Yok

**Sorun:** Sadece fat tails + GARCH — jump-diffusion modeli yok
**Etki:** Ani fiyat sıçramaları simüle edilemiyor
**Kaynak:** LinkedIn Jump-Diffusion (2025)
**Çözüm:** Jump-diffusion (Poisson jump process)

### 3.8 Monte Carlo — Correlated Paths Yok

**Sorun:** Her hisse bağımsız simüle ediliyor — korelasyon yok
**Etki:** Portföy bazlı Monte Carlo yapılamıyor
**Çözüm:** Cholesky decomposition ile korelli path'ler

### 3.9 Order Book Simulation Yok

**Sorun:** Emir defteri simülasyonu yok
**Etki:** Likidite ve spread gerçekçi değil
**Çözüm:** Basit order book simülasyonu

### 3.10 Backtest Integration Zayıf

**Sorun:** Simulation engine backtest'ten bağımsız
**Etki:** Backtest'te execution simulator kullanılmıyor
**Çözüm:** Backtest → execution simulator entegrasyonu

---

## 4. Nihai Simulation Mimarisi

### 4.1 Simulation Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    SIMULATION PIPELINE                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EXECUTION SIMULATOR (Gelişmiş)          │   │
│  │                                                      │   │
│  │  Order Lifecycle:                                    │   │
│  │  CREATED → VALIDATED → RISK_APPROVED → SUBMITTED →  │   │
│  │  ACCEPTED → PARTIALLY_FILLED / FILLED / REJECTED    │   │
│  │                                                      │   │
│  │  Slippage Model:                                     │   │
│  │  - Base slippage (bid/ask spread) ← GÜNCELLE        │   │
│  │  - Volume impact (square root model) ← YENİ         │   │
│  │  - Regime impact ← YENİ                             │   │
│  │  - Liquidity constraint ← YENİ                      │   │
│  │                                                      │   │
│  │  Transaction Cost:                                   │   │
│  │  - Broker komisyonu                                  │   │
│  │  - BIST payı                                         │   │
│  │  - MKK payı                                          │   │
│  │  - BSMV                                              │   │
│  │  - Minimum komisyon                                  │   │
│  │                                                      │   │
│  │  Partial Fill:                                       │   │
│  │  - Günlük hacim limiti                               │   │
│  │  - Likidite profili ← YENİ                          │   │
│  │  - Bid/Ask depth ← YENİ                             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MONTE CARLO SIMULATION (Gelişmiş)       │   │
│  │                                                      │   │
│  │  Models:                                             │   │
│  │  - GBM (temel)                                       │   │
│  │  - Fat Tails (Student-t, df=5)                       │   │
│  │  - GARCH(1,1) volatility clustering                  │   │
│  │  - Regime-conditioned parameters                     │   │
│  │  - Event shock injection                             │   │
│  │  - Jump-Diffusion ← YENİ                            │   │
│  │  - Correlated paths (Cholesky) ← YENİ                │   │
│  │                                                      │   │
│  │  Outputs:                                            │   │
│  │  - P10/P25/P50/P75/P90                              │   │
│  │  - VaR (95%, 99%)                                   │   │
│  │  - CVaR (Expected Shortfall)                         │   │
│  │  - Prob(positive), Prob(>5%), Prob(<-5%)             │   │
│  │  - Max/Min return                                    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SCENARIO ANALYSIS (Gelişmiş)            │   │
│  │                                                      │   │
│  │  - Bull / Base / Bear / Crash                        │   │
│  │  - Beta bazlı etki ← YENİ                           │   │
│  │  - Sektör bazlı etki ← YENİ                         │   │
│  │  - Macro shock senaryoları ← YENİ                   │   │
│  │  - Custom senaryo ← YENİ                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              STRESS TEST (Gelişmiş)                  │   │
│  │                                                      │   │
│  │  - Market Crash (-20%)                               │   │
│  │  - Currency Crisis (USDTRY +30%)                     │   │
│  │  - Rate Shock (+500bp)                               │   │
│  │  - Sector Rotation                                   │   │
│  │  - Black Swan (-30%)                                 │   │
│  │  - Liquidity Crisis ← YENİ                          │   │
│  │  - Stagflation ← YENİ                               │   │
│  │  - Global Risk-Off ← YENİ                           │   │
│  │  - Company-specific stress ← YENİ                   │   │
│  │  - Breaking point analysis ← YENİ                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ORDER BOOK SIMULATION ← YENİ            │   │
│  │  - Basit order book simülasyonu                      │   │
│  │  - Bid/Ask depth                                     │   │
│  │  - Spread dynamics                                   │   │
│  │  - Likidite profili                                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              BACKTEST INTEGRATION ← YENİ             │   │
│  │  - Backtest'te execution simulator kullan            │   │
│  │  - Same execution model for backtest and live        │   │
│  │  - Transaction cost comparison                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Square Root Market Impact (Nihai)

```python
class SquareRootMarketImpact:
    """Square root market impact modeli."""
    
    def calculate(self, order_value: float, adv: float,
                  volatility: float) -> float:
        """
        Market impact = σ × √(Q / V) × η
        
        σ = volatility
        Q = order size
        V = average daily volume
        η = impact coefficient (0.1-0.5)
        """
        if adv <= 0:
            return 0.001  # Default
        
        participation = order_value / adv
        impact = volatility * np.sqrt(participation) * 0.3  # η = 0.3
        
        return min(impact, 0.05)  # Max %5
```

### 4.3 Regime-Aware Slippage (Nihai)

```python
class RegimeAwareSlippage:
    """Rejime göre slippage ayarlaması."""
    
    REGIME_MULTIPLIERS = {
        "BULL": 0.8,            # Düşük slippage
        "BEAR": 1.3,            # Yüksek slippage
        "HIGH-VOLATILITY": 1.5, # Çok yüksek
        "LOW-VOLATILITY": 0.7,  # Düşük
        "RISK-OFF": 1.4,        # Yüksek
        "PANIC": 2.0,           # Çok yüksek
        "CRISIS": 2.5,          # Ekstrem
    }
    
    def adjust_slippage(self, base_slippage: float, regime: str) -> float:
        """Slippage'ı rejime göre ayarla."""
        multiplier = self.REGIME_MULTIPLIERS.get(regime, 1.0)
        return base_slippage * multiplier
```

### 4.4 Jump-Diffusion Monte Carlo (Nihai)

```python
class JumpDiffusionMonteCarlo:
    """Jump-diffusion Monte Carlo simülasyonu."""
    
    def simulate(self, current_price: float, daily_return: float,
                 daily_vol: float, num_sims: int = 10000,
                 horizon: int = 20, jump_intensity: float = 0.02,
                 jump_mean: float = 0, jump_std: float = 0.05) -> np.ndarray:
        """
        Merton jump-diffusion model:
        dS/S = (μ - λk)dt + σdW + JdN
        
        λ = jump intensity (yılda ~5 jump)
        k = E[J] = expected jump size
        J ~ N(jump_mean, jump_std²)
        N ~ Poisson(λt)
        """
        paths = np.zeros((num_sims, horizon + 1))
        paths[:, 0] = current_price
        
        dt = 1 / 252  # Günlük
        drift = daily_return - jump_intensity * jump_mean
        
        for t in range(1, horizon + 1):
            # Brownian motion
            z = np.random.standard_normal(num_sims)
            dW = z * np.sqrt(dt)
            
            # Jump process (Poisson)
            n_jumps = np.random.poisson(jump_intensity * dt, num_sims)
            jump_sizes = np.sum(
                np.random.normal(jump_mean, jump_std, (num_sims, max(n_jumps.max(), 1))),
                axis=1
            ) * (n_jumps > 0)
            
            # Price update
            paths[:, t] = paths[:, t-1] * np.exp(
                drift * dt + daily_vol * dW + jump_sizes
            )
        
        return paths
```

### 4.5 Correlated Monte Carlo (Nihai)

```python
class CorrelatedMonteCarlo:
    """Korelli Monte Carlo simülasyonu (portföy bazlı)."""
    
    def simulate_portfolio(self, prices: np.ndarray, returns_matrix: np.ndarray,
                          weights: np.ndarray, num_sims: int = 10000,
                          horizon: int = 20) -> Dict:
        """
        Portföy bazlı Monte Carlo:
        1. Korelasyon matrisi hesapla
        2. Cholesky decomposition
        3. Korelli random returns üret
        4. Portföy getirisi hesapla
        """
        n_assets = len(prices)
        
        # Korelasyon matrisi
        corr_matrix = np.corrcoef(returns_matrix.T)
        
        # Cholesky decomposition
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # Pozitif definite değilse düzelt
            eigvals, eigvecs = np.linalg.eigh(corr_matrix)
            eigvals = np.maximum(eigvals, 1e-6)
            corr_matrix = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = np.linalg.cholesky(corr_matrix)
        
        # Korelli random returns
        portfolio_returns = np.zeros(num_sims)
        
        for sim in range(num_sims):
            independent_z = np.random.standard_normal((n_assets, horizon))
            correlated_z = L @ independent_z
            
            # Her asset için getiri
            asset_returns = np.mean(returns_matrix, axis=1) + np.std(returns_matrix, axis=1) * correlated_z
            
            # Portföy getirisi
            portfolio_return = np.sum(weights * np.prod(1 + asset_returns, axis=1) - weights)
            portfolio_returns[sim] = portfolio_return
        
        return {
            "expected_return": float(np.mean(portfolio_returns)),
            "std": float(np.std(portfolio_returns)),
            "var_95": float(np.percentile(portfolio_returns, 5)),
            "cvar_95": float(np.mean(portfolio_returns[portfolio_returns <= np.percentile(portfolio_returns, 5)])),
        }
```

---

## 5. Rakip Karşılaştırması

### 5.1 arXiv Agentic Trading (2026)

| Özellik | arXiv | Bizim Sistem | Fark |
|---------|-------|-------------|------|
| Execution simulator | ✅ | ✅ | ✅ Aynı |
| Slippage calibration | ✅ | ⚠️ Basit | ⚠️ |
| Transaction cost model | ✅ | ✅ | ✅ Aynı |
| RL execution | ✅ | ❌ | ❌ |

### 5.2 mbrenndoerfer Market Microstructure (2026)

| Özellik | mbrenndoerfer | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| Order lifecycle | ✅ Full | ✅ | ✅ Aynı |
| Partial fill | ✅ | ✅ | ✅ Aynı |
| Order book simulation | ✅ | ❌ | ❌ |
| Market impact | ✅ Square root | ⚠️ Basit | ⚠️ |

### 5.3 Springer Monte Carlo (2026)

| Özellik | Springer | Bizim Sistem | Fark |
|---------|----------|-------------|------|
| Fat tails | ✅ Student-t | ✅ | ✅ Aynı |
| GARCH | ✅ | ✅ | ✅ Aynı |
| Jump-diffusion | ✅ | ❌ | ❌ |
| Correlated paths | ✅ | ❌ | ❌ |
| Regime-conditioned | ✅ | ✅ | ✅ Aynı |

---

## 6. Uygulama Planı

### Faz 1: Spread & Market Impact (Hemen)
1. Bid/ask spread bazlı slippage
2. Square root market impact model
3. Regime-aware slippage

### Faz 2: Jump-Diffusion Monte Carlo (1 hafta)
1. Merton jump-diffusion model
2. Poisson jump process
3. Event shock integration

### Faz 3: Correlated Monte Carlo (1 hafta)
1. Korelasyon matrisi
2. Cholesky decomposition
3. Portföy bazlı Monte Carlo

### Faz 4: Order Book Simulation (1 hafta)
1. Basit order book simülasyonu
2. Bid/Ask depth
3. Spread dynamics
4. Likidite profili

### Faz 5: Stress Test Enhancement (1 hafta)
1. Liquidity crisis senaryosu
2. Stagflation senaryosu
3. Global risk-off senaryosu
4. Company-specific stress
5. Breaking point analysis

### Faz 6: Backtest Integration (1 hafta)
1. Backtest'te execution simulator kullan
2. Same execution model
3. Transaction cost comparison

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 2 | 7 |
| Toplam satır | 601 | ~1,500 |
| Order lifecycle | ✅ İyi | ✅ |
| Slippage model | ⚠️ Basit | ✅ Square root + regime |
| Commission model | ✅ İyi | ✅ |
| Partial fill | ✅ İyi | ✅ |
| Monte Carlo | ✅ İyi (GARCH, fat tails) | ✅ + jump-diffusion |
| Correlated paths | ❌ | ✅ Cholesky |
| Scenario analysis | ⚠️ Basit | ✅ Beta + sektör bazlı |
| Stress test | ⚠️ 5 senaryo | ✅ 8+ senaryo |
| Order book simulation | ❌ | ✅ |
| Backtest integration | ⚠️ Zayıf | ✅ |
| Market impact | ⚠️ Basit | ✅ Square root |
| Regime impact | ❌ | ✅ |
