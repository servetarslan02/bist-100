# Portfolio Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** ScienceDirect Integrated Risk Management (2026), arXiv Agentic Trading (2026), Wellington Rebalancing (2025), Resonanz Capital Total Portfolio Approach (2025), Breaking Alpha Position Sizing (2025), MDPI Hierarchical Signal-to-Policy (2026)

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Portfolio Management System (En İyi Uygulama)

**Temel prensip:** Portföy sadece "al-sat" değil — muhasebe, risk, optimizasyon, rebalancing, attribution birlikte çalışmalı.

```
PORTFOLIO MANAGEMENT SYSTEM
├── Accounting (Muhasebe)
│   ├── Cash management
│   ├── Position tracking
│   ├── P&L (realized + unrealized)
│   ├── Commission tracking
│   └── Immutable ledger
├── Risk (Risk)
│   ├── Position sizing
│   ├── Sector concentration
│   ├── Correlation risk
│   ├── Drawdown management
│   └── VaR/CVaR
├── Optimization (Optimizasyon)
│   ├── Mean-variance
│   ├── Risk parity
│   ├── Factor-based
│   └── Black-Litterman
├── Rebalancing (Yeniden Dengeleme)
│   ├── Threshold-based
│   ├── Calendar-based
│   ├── Dynamic
│   └── Transaction cost-aware
├── Attribution (Performans)
│   ├── Factor attribution
│   ├── Sector attribution
│   ├── Security selection
│   └── Timing
└── Simulation (Simülasyon)
    ├── Paper trading
    ├── Backtest integration
    ├── Scenario analysis
    └── Stress test
```

### 1.2 Position Sizing (En İyi Uygulama)

| Yöntem | Açıklama | Kaynak |
|--------|----------|--------|
| **Kelly Criterion** | Optimal boyut = edge / odds | arXiv (2026) |
| **Risk Parity** | Her pozisyon eşit risk katkısı | Springer (2026) |
| **Volatility-targeted** | Hedef volatiliteye göre boyut | MDPI (2026) |
| **Fixed Fractional** | Sabit % risk | Breaking Alpha (2025) |
| **Convex Optimization** | VaR/CVaR minimize | arXiv (2026) |

### 1.3 Rebalancing (En İyi Uygulama)

| Strateji | Açıklama | Kaynak |
|----------|----------|--------|
| **Threshold-based** | Sapma > eşik → rebalance | Wellington (2025) |
| **Calendar-based** | Haftalık/aylık rebalance | Wellington (2025) |
| **Dynamic** | Volatilite/rejime göre | Resonanz (2025) |
| **Transaction cost-aware** | Maliyeti minimize ederek | ScienceDirect (2026) |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (3 dosya, 2,040 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `portfolio_manager.py` | 1,009 | Pozisyon yönetimi, muhasebe, P&L, risk metrikleri | ✅ İyi |
| `main.py` | 802 | DB-backed portfolio service, atomic operations, lock | ✅ İyi |
| `enhancements.py` | 229 | Tax, dividend, benchmark, attribution, multi-currency | ⚠️ Basit |

### 2.2 portfolio_manager.py (1,009 satır) — Detaylı

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `Position` | 39-90 | Pozisyon modeli (ticker, direction, qty, price, P&L) | ✅ |
| `Trade` | 92-141 | Trade modeli (entry/exit, P&L, holding days) | ✅ |
| `CashLedgerEntry` | 143-164 | Nakit hareket kaydı | ✅ |
| `EquitySnapshot` | 166-195 | Equity snapshot (günlük) | ✅ |
| `PositionHistoryEntry` | 197-233 | Pozisyon değişiklik geçmişi | ✅ |
| `CommissionModel` | 235-281 | Komisyon hesaplama (broker + BIST + MKK + BSMV) | ✅ İyi |
| `open_position()` | 469-572 | Pozisyon aç (weighted average, validation) | ✅ İyi |
| `close_position()` | 574-665 | Pozisyon kapat (P&L, commission, audit) | ✅ İyi |
| `_reduce_position()` | 666-758 | Pozisyon azalt (kısmi kapatma) | ✅ İyi |
| `update_prices()` | 759-791 | Fiyat güncelle | ✅ |
| `get_portfolio()` | 792-825 | Portföy özeti | ✅ |
| `get_metrics()` | 826-915 | Performans metrikleri (CAGR, Sharpe, Sortino, win rate, profit factor) | ✅ İyi |
| `get_risk_metrics()` | 916-967 | Risk metrikleri (max position, sector concentration, drawdown) | ⚠️ Basit |
| `check_stop_loss()` | 968-980 | Stop loss kontrolü | ✅ |
| `check_target()` | 981-993 | Target fiyat kontrolü | ✅ |
| `get_accounting_summary()` | 994-1009 | Muhasebe özeti | ✅ |

### 2.3 main.py (802 satır) — PortfolioService

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `execute_buy()` | 358-419 | Alım işlemi (lock, atomic, DB persist) | ✅ İyi |
| `execute_sell()` | 420-529 | Satış işlemi (lock, atomic, oversell kontrol) | ✅ İyi |
| `update_prices()` | 530-570 | Fiyat güncelle + equity snapshot | ✅ |
| `_verify_invariant()` | 342-357 | Muhasebe invariant kontrolü | ✅ İyi |
| `get_portfolio()` | 571-600 | Portföy özeti | ✅ |
| `get_trade_history()` | 601-620 | Trade geçmişi | ✅ |

### 2.4 enhancements.py (229 satır)

| Sınıf | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `TaxModel` | 21-62 | Temettü, sermaye kazancı, komisyon vergisi | ⚠️ Basit |
| `DividendHandler` | 64-92 | Temettü işleme | ⚠️ Basit |
| `BenchmarkEngine` | 93-143 | Benchmark karşılaştırma | ⚠️ Basit |
| `PerformanceAttribution` | 144-189 | Performans attribüsyonu | ⚠️ Basit |
| `MultiCurrencyHandler` | 190-229 | Çoklu para birimi | ⚠️ Basit |

---

## 3. Eksikler (Kritik)

### 3.1 Position Sizing Entegrasyonu Zayıf

**Sorun:** `risk/position_sizing.py` var ama portfolio ile entegrasyon zayıf
**Etki:** Optimal pozisyon boyutu hesaplanamıyor
**Çözüm:** Position sizing → portfolio entegrasyonu

### 3.2 Rebalancing Yok

**Sorun:** Portföy rebalancing mekanizması yok
**Etki:** Portföy hedef dağılımdan sapıyor
**Çözüm:** Threshold-based rebalancing

### 3.3 Portfolio Optimization Yok

**Sorun:** Mean-variance, risk parity, factor-based optimization yok
**Etki:** Optimal portföy dağılımı hesaplanamıyor
**Çözüm:** Portfolio optimization engine

### 3.4 VaR/CVaR Hesaplaması Yok

**Sorun:** Risk metriklerinde VaR/CVaR yok
**Etki:** Tail risk ölçülemiyor
**Çözüm:** VaR/CVaR entegrasyonu

### 3.5 Correlation-Based Risk Yok

**Sorun:** `portfolio_correlation` sabit 0.62 değerinde
**Etki:** Gerçek korelasyon riski ölçülemiyor
**Çözüm:** Rolling correlation hesaplama

### 3.6 Factor Attribution Yok

**Sorun:** Sadece basit attribution (macro, momentum, event)
**Etki:** Faktör bazlı performans analizi eksik
**Çözüm:** Factor attribution (value, momentum, quality, size)

### 3.7 Multi-Asset Support Yok

**Sorun:** Sadece hisse — VIOP, opsiyon, tahvil yok
**Etki:** Türev ürünler portföyde kullanılamıyor
**Çözüm:** Multi-asset portfolio support

### 3.8 Transaction Cost Analysis Yok

**Sorun:** Komisyon var ama spread, slippage, market impact analizi yok
**Etki:** Gerçek işlem maliyeti bilinmiyor
**Çözüm:** Transaction cost analysis (TCA)

### 3.9 Portfolio Reconciliation Zayıf

**Sorun:** `_verify_invariant()` var ama detaylı reconciliation yok
**Etki:** Muhasebe tutarsızlıkları geç tespit edilir
**Çözüm:** Detaylı reconciliation (ledger vs positions vs cash vs equity)

### 3.10 Tax Model Basit

**Sorun:** Sadece sabit oranlar — holding period, stopaj, BSMV yok
**Etki:** Gerçek vergi maliyeti bilinmiyor
**Çözüm:** Detaylı Türkiye vergi modeli

---

## 4. Nihai Portfolio Mimarisi

### 4.1 Portfolio Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    PORTFOLIO PIPELINE                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              POSITION SIZING (Risk → Portfolio)      │   │
│  │  - Kelly Criterion                                  │   │
│  │  - Risk Parity                                      │   │
│  │  - Volatility-targeted                              │   │
│  │  - Fixed Fractional                                 │   │
│  │  - Convex Optimization (VaR/CVaR)                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ORDER EXECUTION                        │   │
│  │  - Pre-trade risk check                             │   │
│  │  - Commission calculation                           │   │
│  │  - Slippage estimation                              │   │
│  │  - Atomic execution (lock)                          │   │
│  │  - DB persistence                                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ACCOUNTING (Muhasebe)                   │   │
│  │  - Cash management                                  │   │
│  │  - Position tracking (weighted average cost)        │   │
│  │  - P&L (realized + unrealized)                      │   │
│  │  - Commission tracking                              │   │
│  │  - Immutable ledger                                 │   │
│  │  - Daily equity snapshot                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RISK MONITORING                        │   │
│  │  - Position concentration                           │   │
│  │  - Sector concentration                             │   │
│  │  - Correlation risk (rolling)                       │   │
│  │  - Drawdown tracking                                │   │
│  │  - VaR/CVaR                                         │   │
│  │  - Stop loss / target monitoring                    │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PORTFOLIO OPTIMIZATION                  │   │
│  │  - Mean-Variance (Markowitz)                        │   │
│  │  - Risk Parity                                      │   │
│  │  - Factor-based                                     │   │
│  │  - Black-Litterman                                  │   │
│  │  - Hierarchical Risk Parity (HRP)                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              REBALANCING                             │   │
│  │  - Threshold-based (sapma > eşik → rebalance)       │   │
│  │  - Calendar-based (haftalık/aylık)                  │   │
│  │  - Dynamic (volatilite/rejime göre)                 │   │
│  │  - Transaction cost-aware                           │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PERFORMANCE ATTRIBUTION                 │   │
│  │  - Factor attribution (value, momentum, quality)    │   │
│  │  - Sector attribution                               │   │
│  │  - Security selection                               │   │
│  │  - Timing                                           │   │
│  │  - Currency effect                                  │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TAX MODEL (Detaylı)                     │   │
│  │  - Holding period (kısa/uzun vadeli)                │   │
│  │  - Stopaj (temettü, faiz)                           │   │
│  │  - BSMV                                             │   │
│  │  - Wash sale rule                                   │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RECONCILIATION                          │   │
│  │  - Ledger vs Positions                              │   │
│  │  - Cash vs Equity                                   │   │
│  │  - DB vs In-memory                                  │   │
│  │  - Discrepancy alert                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TRANSACTION COST ANALYSIS               │   │
│  │  - Commission (broker + BIST + MKK + BSMV)          │   │
│  │  - Spread (bid/ask)                                 │   │
│  │  - Slippage (volatilite bazlı)                      │   │
│  │  - Market impact (büyük emirler)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Position Sizing (Nihai)

```python
class PositionSizer:
    """Pozisyon boyutlandırma — çoklu yöntem."""
    
    def kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly Criterion — optimal boyut."""
        if avg_loss == 0:
            return 0
        b = avg_win / avg_loss
        kelly = (win_rate * b - (1 - win_rate)) / b
        return max(0, min(kelly, 0.25))  # Max %25
    
    def risk_parity(self, volatilities: List[float], target_risk: float = 0.02) -> List[float]:
        """Risk Parity — her pozisyon eşit risk katkısı."""
        inv_vol = [1.0 / max(v, 0.001) for v in volatilities]
        total = sum(inv_vol)
        weights = [iv / total for iv in inv_vol]
        return weights
    
    def volatility_targeted(self, volatility: float, target_vol: float = 0.15,
                           portfolio_value: float = 100000) -> float:
        """Volatilite hedefli pozisyon boyutu."""
        if volatility <= 0:
            return 0
        position_value = (target_vol / volatility) * portfolio_value
        return position_value
    
    def fixed_fractional(self, portfolio_value: float, risk_per_trade: float = 0.02,
                        stop_distance: float = 0.05) -> float:
        """Sabit oranlı pozisyon boyutu."""
        max_loss = portfolio_value * risk_per_trade
        position_size = max_loss / stop_distance
        return min(position_size, portfolio_value * 0.10)  # Max %10
```

### 4.3 Rebalancing (Nihai)

```python
class Rebalancer:
    """Portföy yeniden dengeleme."""
    
    def __init__(self, threshold_pct: float = 5.0):
        self.threshold_pct = threshold_pct
    
    def check_rebalance(self, current_weights: Dict[str, float],
                        target_weights: Dict[str, float]) -> Dict:
        """Rebalance gerekli mi?"""
        drifts = {}
        needs_rebalance = False
        
        for ticker in set(list(current_weights.keys()) + list(target_weights.keys())):
            current = current_weights.get(ticker, 0)
            target = target_weights.get(ticker, 0)
            drift = abs(current - target)
            drifts[ticker] = round(drift, 4)
            if drift > self.threshold_pct / 100:
                needs_rebalance = True
        
        return {
            "needs_rebalance": needs_rebalance,
            "drifts": drifts,
            "max_drift": round(max(drifts.values()) if drifts else 0, 4),
        }
    
    def compute_rebalance_orders(self, current_weights: Dict[str, float],
                                 target_weights: Dict[str, float],
                                 portfolio_value: float) -> List[Dict]:
        """Rebalance emirleri oluştur."""
        orders = []
        for ticker in set(list(current_weights.keys()) + list(target_weights.keys())):
            current = current_weights.get(ticker, 0)
            target = target_weights.get(ticker, 0)
            diff = target - current
            if abs(diff) > 0.01:  # %1'den fazla sapma
                order_value = diff * portfolio_value
                orders.append({
                    "ticker": ticker,
                    "action": "BUY" if diff > 0 else "SELL",
                    "value": round(abs(order_value), 2),
                    "weight_change": round(diff * 100, 2),
                })
        return orders
```

### 4.4 VaR/CVaR (Nihai)

```python
class VaRCalculator:
    """VaR ve CVaR hesaplama."""
    
    def calculate_var(self, returns: List[float], confidence: float = 0.95) -> float:
        """Value at Risk."""
        if not returns:
            return 0
        sorted_returns = sorted(returns)
        index = int((1 - confidence) * len(sorted_returns))
        return abs(sorted_returns[index])
    
    def calculate_cvar(self, returns: List[float], confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall)."""
        if not returns:
            return 0
        sorted_returns = sorted(returns)
        index = int((1 - confidence) * len(sorted_returns))
        tail = sorted_returns[:index+1]
        return abs(np.mean(tail)) if tail else 0
    
    def portfolio_var(self, weights: List[float], returns_matrix: np.ndarray,
                     confidence: float = 0.95) -> float:
        """Portföy VaR."""
        portfolio_returns = returns_matrix @ weights
        return self.calculate_var(portfolio_returns.tolist(), confidence)
```

### 4.5 Factor Attribution (Nihai)

```python
class FactorAttribution:
    """Faktör bazlı performans attribüsyonu."""
    
    def decompose(self, portfolio_returns: List[float],
                  factor_returns: Dict[str, List[float]]) -> Dict:
        """Faktör attribüsyonu."""
        p = np.array(portfolio_returns)
        results = {}
        
        for factor_name, factor_ret in factor_returns.items():
            f = np.array(factor_ret)
            if len(f) != len(p):
                continue
            
            # Beta hesapla
            if np.std(f) > 0:
                beta = np.cov(p, f)[0][1] / np.var(f)
            else:
                beta = 0
            
            # Factor contribution
            factor_contribution = beta * np.mean(f) * 252
            
            results[factor_name] = {
                "beta": round(float(beta), 4),
                "contribution": round(float(factor_contribution), 4),
                "correlation": round(float(np.corrcoef(p, f)[0, 1]) if len(p) > 1 else 0, 4),
            }
        
        # Residual (açıklanamayan kısım)
        explained = sum(r["contribution"] for r in results.values())
        results["residual"] = {
            "contribution": round(float(np.mean(p) * 252 - explained), 4),
        }
        
        return results
```

### 4.6 Transaction Cost Analysis (Nihai)

```python
class TransactionCostAnalyzer:
    """İşlem maliyeti analizi."""
    
    def analyze(self, order_value: float, volume: float, volatility: float,
                spread_pct: float = 0.05) -> Dict:
        """Detaylı işlem maliyeti analizi."""
        # Komisyon
        commission = self._calculate_commission(order_value)
        
        # Spread
        spread_cost = order_value * spread_pct / 100
        
        # Slippage (volatilite bazlı)
        slippage_pct = volatility * 0.1  # Volatilite'nin %10'u
        slippage_cost = order_value * slippage_pct / 100
        
        # Market impact (büyük emirler)
        participation = order_value / max(volume * 100, 1)  # Günlük hacmin oranı
        impact_pct = 0.1 * participation ** 0.5  # Square root model
        impact_cost = order_value * impact_pct / 100
        
        total_cost = commission + spread_cost + slippage_cost + impact_cost
        
        return {
            "commission": round(commission, 2),
            "spread_cost": round(spread_cost, 2),
            "slippage_cost": round(slippage_cost, 2),
            "market_impact": round(impact_cost, 2),
            "total_cost": round(total_cost, 2),
            "total_cost_pct": round(total_cost / order_value * 100, 4) if order_value > 0 else 0,
        }
    
    def _calculate_commission(self, amount: float) -> float:
        """BIST komisyon hesaplama."""
        broker = amount * 0.0003
        bist = amount * 0.000056
        mkk = amount * 0.0000109
        bsmv = broker * 0.05
        return max(broker + bist + mkk + bsmv, 1.0)
```

---

## 5. Rakip Karşılaştırması

### 5.1 ScienceDirect Integrated Risk Management (2026)

| Özellik | ScienceDirect | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| Rebalancing | ✅ Dynamic | ❌ | ❌ |
| Performance attribution | ✅ Factor-based | ⚠️ Basit | ⚠️ |
| Risk parity | ✅ | ❌ | ❌ |
| Transaction cost | ✅ Detailed | ⚠️ Basit | ⚠️ |

### 5.2 arXiv Agentic Trading (2026)

| Özellik | arXiv | Bizim Sistem | Fark |
|---------|-------|-------------|------|
| Kelly criterion | ✅ | ❌ | ❌ |
| Risk parity | ✅ | ❌ | ❌ |
| Convex optimization | ✅ | ❌ | ❌ |
| Position sizing | ✅ Multiple methods | ⚠️ Basit | ⚠️ |

### 5.3 Wellington Rebalancing (2025)

| Özellik | Wellington | Bizim Sistem | Fark |
|---------|-----------|-------------|------|
| Threshold-based | ✅ | ❌ | ❌ |
| Calendar-based | ✅ | ❌ | ❌ |
| Transaction cost-aware | ✅ | ❌ | ❌ |
| Dynamic | ✅ | ❌ | ❌ |

---

## 6. Uygulama Planı

### Faz 1: Position Sizing Integration (Hemen)
1. Kelly criterion entegrasyonu
2. Risk parity entegrasyonu
3. Volatility-targeted sizing
4. Portfolio'ya bağla

### Faz 2: Rebalancing (1 hafta)
1. Threshold-based rebalancing
2. Calendar-based rebalancing
3. Transaction cost-aware orders
4. Otomatik rebalance tetikleme

### Faz 3: VaR/CVaR (1 hafta)
1. Portfolio VaR hesaplama
2. CVaR (Expected Shortfall)
3. Component VaR (pozisyon bazlı)
4. Risk metriklerine entegre et

### Faz 4: Factor Attribution (1 hafta)
1. Factor decomposition
2. Sector attribution
3. Security selection attribution
4. Timing attribution

### Faz 5: Transaction Cost Analysis (1 hafta)
1. Spread model
2. Slippage model
3. Market impact model
4. Total cost analysis

### Faz 6: Tax Model Enhancement (1 hafta)
1. Holding period (kısa/uzun vadeli)
2. Stopaj (temettü, faiz)
3. BSMV
4. Wash sale rule

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 3 | 8 |
| Toplam satır | 2,040 | ~3,500 |
| Position sizing | ⚠️ Basit | ✅ Kelly + Risk Parity + Vol-targeted |
| Rebalancing | ❌ | ✅ Threshold + Calendar + Dynamic |
| VaR/CVaR | ❌ | ✅ |
| Portfolio optimization | ❌ | ✅ Mean-variance + Risk parity |
| Factor attribution | ⚠️ Basit | ✅ Detaylı |
| Transaction cost analysis | ⚠️ Basit | ✅ Spread + Slippage + Impact |
| Tax model | ⚠️ Basit | ✅ Holding period + Stopaj + BSMV |
| Correlation risk | ⚠️ Sabit 0.62 | ✅ Rolling correlation |
| Multi-asset | ❌ | ⚠️ Future |
| Reconciliation | ⚠️ Basit | ✅ Detaylı |
