# VIOP Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** ResearchGate Optimal Hedge Ratios Turkish Futures (2021), TradingBlock Gamma Guide (2025), arXiv LLM Options Strategies (2026), DaystoExpiry Iron Condor (2025), Borsa İstanbul resmi

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 VIOP (Vadeli İşlem ve Opsiyon Piyasası) Nedir?

**VIOP**, Borsa İstanbul bünyesinde vadeli işlem ve opsiyon sözleşmelerinin işlem gördüğü piyasadır.

### 1.2 VIOP Sözleşme Türleri

| Sözleşme | Kod | Dayanak | Sözleşme Büyüklüğü | Vade |
|----------|-----|---------|-------------------|------|
| **BIST 30 Endeks** | XU030 | BIST 30 | Endeks × 10 TL | Aylık |
| **BIST 30 Endeks (Dolar)** | XU030D | BIST 30 | Endeks × 10 USD | Aylık |
| **Dolar/TL** | DOL | USD/TRY | 1.000 USD | Aylık |
| **Euro/TL** | EUR | EUR/TRY | 1.000 EUR | Aylık |
| **Gram Altın** | GAU | Gram Altın | 1 gram | Aylık |
| **Çeyrek Altın** | CAY | Çeyrek Altın | 1 çeyrek | Aylık |
| **Buğday** | BUD | Buğday | 5 ton | Aylık |
| **Pamuk** | PAM | Pamuk | 5 ton | Aylık |
| **Elektrik** | ELK | Elektrik | 1 MWh | Aylık |

### 1.3 Options Greeks (En İyi Uygulama)

| Greek | Ne Ölçer | Kullanım |
|-------|----------|----------|
| **Delta** | Fiyat hassasiyeti | Hedge ratio |
| **Gamma** | Delta değişimi | Deltayı ayarlama |
| **Theta** | Zaman aşımı | Zaman maliyeti |
| **Vega** | Volatilite hassasiyeti | Volatilite riski |
| **Rho** | Faiz hassasiyeti | Faiz riski |

### 1.4 Options Stratejileri (En İyi Uygulama)

| Strateji | Ne Zaman | Risk/Reward |
|----------|----------|-------------|
| **Covered Call** | Hisse sahibi + gelir | Sınırlı upside, sınırlı downside |
| **Protective Put** | Hisse sahibi + koruma | Sınırlı downside, unlimited upside |
| **Collar** | Covered call + protective put | Sınırlı both ways |
| **Iron Condor** | Düşük volatilite | Sınırlı both ways |
| **Straddle** | Yüksek volatilite | Unlimited both ways |
| **Strangle** | Yüksek volatilite | Unlimited both ways |

### 1.5 Hedging (En İyi Uygulama)

| Yöntem | Ne | Kullanım |
|--------|-----|----------|
| **Beta Hedge** | Portfolio beta × futures | Market risk hedge |
| **Delta Hedge** | Options delta × hisse | Options risk hedge |
| **Tail Risk Hedge** | Out-of-the-money put | Kriz koruması |
| **Dynamic Hedge** | Sürekli delta ayarlama | Options hedge |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (6 dosya, 82 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `options_pricing.py` | 17 | Black-Scholes opsiyon fiyatlaması | ⚠️ Basit |
| `greeks.py` | 21 | Delta, Gamma, Theta, Vega, Rho | ⚠️ Basit |
| `strategies.py` | 15 | Covered Call, Protective Put | ⚠️ Çok basit |
| `parity.py` | 10 | Put-Call Parity kontrolü | ⚠️ Çok basit |
| `margin.py` | 11 | SPAN teminat (basitleştirilmiş) | ⚠️ Çok basit |
| `hedging.py` | 8 | Portföy hedge (beta × futures) | ⚠️ Çok basit |

### 2.2 İlişkili Modüller

| Modül | Satır | VIOP Entegrasyonu | Durum |
|-------|-------|-------------------|-------|
| `core/viop_monitor.py` | 73 | Teminat kontrolü | ✅ İyi |
| `risk/enhanced_risk.py` | 318 | `hedge_portfolio()`, `check_options_strategy()` | ⚠️ Basit entegrasyon |
| `risk/main.py` | 456 | VIOP entegrasyonu yok | ❌ |

### 2.3 Mevcut Fonksiyonlar

| Fonksiyon | Modül | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `black_scholes()` | options_pricing.py | Call/Put fiyatlaması | ⚠️ Basit |
| `calculate_greeks()` | greeks.py | 5 Greek hesaplama | ⚠️ Basit |
| `create_covered_call()` | strategies.py | Covered call | ⚠️ Çok basit |
| `create_protective_put()` | strategies.py | Protective put | ⚠️ Çok basit |
| `check_put_call_parity()` | parity.py | Parity kontrolü | ⚠️ Çok basit |
| `calculate_span_margin()` | margin.py | SPAN teminat | ⚠️ Çok basit |
| `hedge_portfolio()` | hedging.py | Beta hedge | ⚠️ Çok basit |
| `check_viop_margin()` | viop_monitor.py | Teminat yeterliliği | ✅ İyi |

---

## 3. Eksikler (Kritik)

### 3.1 VIOP Sözleşme Verileri Yok

**Sorun:** VIOP sözleşme tanımları (dayanak, büyüklük, vade) yok
**Etki:** Gerçek VIOP verisi kullanılamıyor
**Çözüm:** VIOP sözleşme kataloğu

### 3.2 Opsiyon Zinciri Yok

**Sorun:** Opsiyon zinciri (farklı strike ve vadeler) yok
**Etki:** Opsiyon stratejileri gerçek veriyle çalışamıyor
**Çözüm:** Opsiyon zinciri veri modeli

### 3.3 Implied Volatility Yok

**Sorun:** Opsiyon piyasasından implied volatility hesaplanamıyor
**Etki:** Gerçek volatilite fiyatı bilinmiyor
**Çözüm:** Implied volatility hesaplama (Newton-Raphson)

### 3.4 Greeks Portföy Bazlı Yok

**Sorun:** Sadece tek opsiyon Greeks — portföy bazlı Greeks yok
**Etki:** Toplam delta/gamma/vega riski ölçülemiyor
**Çözüm:** Portfolio Greeks aggregation

### 3.5 Delta Hedging Yok

**Sorun:** Otomatik delta hedging yok
**Etki:** Options pozisyonlarında delta riski yönetilemiyor
**Çözüm:** Dynamic delta hedging

### 3.6 Strateji Analizi Eksik

**Sorun:** Sadece covered call ve protective put — collar, iron condor, straddle, strangle yok
**Etki:** Opsiyon stratejileri sınırlı
**Çözüm:** Kapsamlı strateji kütüphanesi

### 3.7 SPAN Teminat Modeli Basit

**Sorun:** Sadece `value × margin_rate` — gerçek SPAN daha karmaşık
**Etki:** Teminat hesabı gerçekçi değil
**Çözüm:** SPAN teminat modeli (senaryo bazlı)

### 3.8 VIOP-Hisse Arbitraj Yok

**Sorun:** Futures-spot arbitraj tespiti yok
**Etki:** Arbitraj fırsatları kaçırılıyor
**Çözüm:** Futures-spot basis analizi

### 3.9 VIOP Risk Entegrasyonu Zayıf

**Sorun:** `risk/main.py`'de VIOP entegrasyonu yok
**Etki:** VIOP pozisyonları risk hesabına dahil değil
**Çözüm:** VIOP risk entegrasyonu

### 3.10 VIOP Backtest Yok

**Sorun:** VIOP stratejileri backtest edilemiyor
**Etki:** Strateji doğrulama yapılamıyor
**Çözüm:** VIOP backtest engine

---

## 4. Nihai VIOP Mimarisi

### 4.1 VIOP Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    VIOP PIPELINE                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              VIOP CONTRACT CATALOG ← YENİ            │   │
│  │  - Sözleşme türleri (endeks, döviz, emtia)          │   │
│  │  - Sözleşme büyüklüğü                               │   │
│  │  - Vade tarihleri                                   │   │
│  │  - Tick size                                        │   │
│  │  - Margin requirements                              │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              OPTIONS CHAIN ← YENİ                    │   │
│  │  - Farklı strike'lar                                │   │
│  │  - Farklı vadeler                                   │   │
│  │  - Bid/Ask fiyatları                               │   │
│  │  - Açık pozisyon                                    │   │
│  │  - Hacim                                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              OPTIONS PRICING (Gelişmiş)              │   │
│  │  - Black-Scholes (temel)                             │   │
│  │  - Implied Volatility ← YENİ                        │   │
│  │  - Binomial model ← YENİ                            │   │
│  │  - Monte Carlo pricing ← YENİ                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              GREEKS (Gelişmiş)                       │   │
│  │  - Tek opsiyon Greeks                                │   │
│  │  - Portfolio Greeks ← YENİ                          │   │
│  │  - Greeks aggregation                               │   │
│  │  - Greeks monitoring                                │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              STRATEGIES (Gelişmiş)                   │   │
│  │  - Covered Call                                     │   │
│  │  - Protective Put                                   │   │
│  │  - Collar ← YENİ                                    │   │
│  │  - Iron Condor ← YENİ                               │   │
│  │  - Straddle ← YENİ                                  │   │
│  │  - Strangle ← YENİ                                  │   │
│  │  - Bull/Bear Spread ← YENİ                          │   │
│  │  - Butterfly ← YENİ                                 │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              HEDGING (Gelişmiş)                      │   │
│  │  - Beta Hedge (futures)                              │   │
│  │  - Delta Hedge (options) ← YENİ                     │   │
│  │  - Dynamic Delta Hedging ← YENİ                     │   │
│  │  - Tail Risk Hedge ← YENİ                           │   │
│  │  - Gamma Scalping ← YENİ                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MARGIN (Gelişmiş)                       │   │
│  │  - SPAN teminat modeli (senaryo bazlı) ← YENİ       │   │
│  │  - Teminat yeterliliği kontrolü                     │   │
│  │  - Margin call tespiti                              │   │
│  │  - Teminat optimizasyonu ← YENİ                     │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FUTURES-SPOT ARBITRAGE ← YENİ           │   │
│  │  - Basis analizi (futures - spot)                    │   │
│  │  - Carry cost hesaplama                             │   │
│  │  - Arbitraj sinyali                                 │   │
│  │  - Risk-free profit hesaplama                       │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RISK INTEGRATION ← YENİ                 │   │
│  │  - VIOP pozisyonları risk hesabına dahil             │   │
│  │  - Portfolio Greeks risk metrikleri                  │   │
│  │  - VIOP-specific risk limitleri                     │   │
│  │  - Teminat risk yönetimi                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              VIOP BACKTEST ← YENİ                    │   │
│  │  - Options strateji backtest                         │   │
│  │  - Greeks-based backtest                            │   │
│  │  - Hedging strateji backtest                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Implied Volatility (Nihai)

```python
class ImpliedVolatility:
    """Implied volatility hesaplama (Newton-Raphson)."""
    
    def calculate(self, market_price: float, S: float, K: float,
                  T: float, r: float, option_type: str = "call",
                  max_iterations: int = 100, tolerance: float = 1e-6) -> float:
        """
        Newton-Raphson ile implied volatility bul.
        
        market_price: Piyasa opsiyon fiyatı
        S: Dayanak fiyat
        K: Kullanım fiyatı
        T: Vade (yıl)
        r: Risksiz faiz
        """
        sigma = 0.30  # Başlangıç tahmini
        
        for i in range(max_iterations):
            price = black_scholes(S, K, T, r, sigma, option_type)
            diff = price - market_price
            
            if abs(diff) < tolerance:
                return round(sigma, 4)
            
            # Vega (fiyatın volatiliteye türevi)
            d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
            vega = S * norm.pdf(d1) * np.sqrt(T)
            
            if abs(vega) < 1e-10:
                break
            
            # Newton-Raphson güncelleme
            sigma = sigma - diff / vega
            
            # Sınır kontrolü
            sigma = max(0.01, min(sigma, 2.0))
        
        return round(sigma, 4)
```

### 4.3 Portfolio Greeks (Nihai)

```python
class PortfolioGreeks:
    """Portföy bazlı Greeks aggregation."""
    
    def aggregate(self, positions: List[Dict]) -> Dict:
        """
        Tüm opsiyon pozisyonlarının Greeks'lerini topla.
        
        positions: [{"option_type": "call", "S": 100, "K": 105, "T": 0.25,
                     "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"}]
        """
        total_delta = 0
        total_gamma = 0
        total_theta = 0
        total_vega = 0
        total_rho = 0
        
        for pos in positions:
            greeks = calculate_greeks(
                pos["S"], pos["K"], pos["T"], pos["r"], pos["sigma"], pos["option_type"]
            )
            
            multiplier = pos.get("quantity", 1) * (1 if pos.get("side") == "long" else -1)
            
            total_delta += greeks["delta"] * multiplier
            total_gamma += greeks["gamma"] * multiplier
            total_theta += greeks["theta"] * multiplier
            total_vega += greeks["vega"] * multiplier
            total_rho += greeks["rho"] * multiplier
        
        return {
            "total_delta": round(total_delta, 4),
            "total_gamma": round(total_gamma, 6),
            "total_theta": round(total_theta, 4),
            "total_vega": round(total_vega, 4),
            "total_rho": round(total_rho, 4),
            "n_positions": len(positions),
            "delta_neutral": abs(total_delta) < 0.05,
        }
```

### 4.4 Dynamic Delta Hedging (Nihai)

```python
class DeltaHedger:
    """Dynamic delta hedging."""
    
    def hedge(self, portfolio_greeks: Dict, spot_price: float,
              hedge_instrument: str = "futures") -> Dict:
        """
        Delta'yı sıfıra yaklaştırmak için hedge pozisyonu öner.
        
        portfolio_greeks: Portföy Greeks
        spot_price: Dayanak fiyat
        hedge_instrument: Hedge aracı (futures/options)
        """
        target_delta = 0  # Delta neutral
        current_delta = portfolio_greeks.get("total_delta", 0)
        delta_gap = target_delta - current_delta
        
        if hedge_instrument == "futures":
            # Futures delta = 1
            contracts_needed = int(round(-delta_gap))
        else:
            # Options delta (ATM call ~0.5)
            contracts_needed = int(round(-delta_gap / 0.5))
        
        return {
            "current_delta": round(current_delta, 4),
            "target_delta": target_delta,
            "delta_gap": round(delta_gap, 4),
            "contracts_needed": contracts_needed,
            "hedge_instrument": hedge_instrument,
            "action": "BUY" if contracts_needed > 0 else "SELL",
        }
```

### 4.5 SPAN Teminat Modeli (Nihai)

```python
class SPANMarginCalculator:
    """SPAN teminat hesaplama (senaryo bazlı)."""
    
    # SPAN senaryoları (16 senaryo)
    SCENARIOS = [
        {"price_change": 0, "vol_change": 0},      # Base
        {"price_change": 0.03, "vol_change": 0},    # +3%
        {"price_change": -0.03, "vol_change": 0},   # -3%
        {"price_change": 0.03, "vol_change": 0.02}, # +3% + vol up
        {"price_change": -0.03, "vol_change": 0.02},# -3% + vol up
        {"price_change": 0.06, "vol_change": 0},    # +6%
        {"price_change": -0.06, "vol_change": 0},   # -6%
        {"price_change": 0.06, "vol_change": 0.04}, # +6% + vol up
        {"price_change": -0.06, "vol_change": 0.04},# -6% + vol up
        {"price_change": 0.10, "vol_change": 0},    # +10%
        {"price_change": -0.10, "vol_change": 0},   # -10%
        {"price_change": 0.10, "vol_change": 0.06}, # +10% + vol up
        {"price_change": -0.10, "vol_change": 0.06},# -10% + vol up
        {"price_change": 0.15, "vol_change": 0},    # +15%
        {"price_change": -0.15, "vol_change": 0},   # -15%
        {"price_change": 0, "vol_change": 0.08},    # Vol up only
    ]
    
    def calculate(self, positions: List[Dict]) -> Dict:
        """SPAN teminat hesaplama."""
        total_margin = 0
        position_margins = []
        
        for pos in positions:
            worst_loss = 0
            
            for scenario in self.SCENARIOS:
                # Her senaryo için P&L hesapla
                pnl = self._calculate_scenario_pnl(pos, scenario)
                worst_loss = min(worst_loss, pnl)
            
            margin = abs(worst_loss)
            total_margin += margin
            position_margins.append({
                "ticker": pos.get("ticker", ""),
                "margin": round(margin, 2),
            })
        
        return {
            "total_margin": round(total_margin, 2),
            "position_margins": position_margins,
            "scenarios_tested": len(self.SCENARIOS),
        }
    
    def _calculate_scenario_pnl(self, position: Dict, scenario: Dict) -> float:
        """Senaryo P&L hesaplama."""
        # Basitleştirilmiş — gerçek implementation daha karmaşık
        value = position.get("value", 0)
        delta = position.get("delta", 1.0)
        gamma = position.get("gamma", 0)
        vega = position.get("vega", 0)
        
        price_pnl = value * delta * scenario["price_change"]
        gamma_pnl = 0.5 * gamma * (scenario["price_change"] ** 2) * value
        vol_pnl = vega * scenario["vol_change"] * 100
        
        return price_pnl + gamma_pnl + vol_pnl
```

### 4.6 Futures-Spot Arbitraj (Nihai)

```python
class FuturesSpotArbitrage:
    """Futures-spot arbitraj tespiti."""
    
    def analyze(self, spot_price: float, futures_price: float,
                risk_free_rate: float, dividend_yield: float,
                time_to_expiry: float) -> Dict:
        """
        Futures-spot basis analizi.
        
        Theoretical futures = S × e^((r-q)×T)
        Basis = futures - spot
        Fair basis = S × (e^((r-q)×T) - 1)
        """
        # Teorik futures fiyatı
        theoretical = spot_price * np.exp((risk_free_rate - dividend_yield) * time_to_expiry)
        
        # Basis
        basis = futures_price - spot_price
        fair_basis = theoretical - spot_price
        
        # Basis farkı
        basis_diff = basis - fair_basis
        basis_pct = basis_diff / spot_price * 100
        
        # Arbitraj sinyali
        arbitrage_opportunity = abs(basis_pct) > 0.5  # %0.5'ten fazla
        
        if basis_diff > 0:
            # Futures pahalı → Sell futures, buy spot
            strategy = "SELL_FUTURES_BUY_SPOT"
        elif basis_diff < 0:
            # Futures ucuz → Buy futures, sell spot
            strategy = "BUY_FUTURES_SELL_SPOT"
        else:
            strategy = "NO_ARBITRAGE"
        
        return {
            "spot_price": spot_price,
            "futures_price": futures_price,
            "theoretical_futures": round(theoretical, 2),
            "basis": round(basis, 2),
            "fair_basis": round(fair_basis, 2),
            "basis_diff": round(basis_diff, 2),
            "basis_pct": round(basis_pct, 4),
            "arbitrage_opportunity": arbitrage_opportunity,
            "strategy": strategy,
        }
```

---

## 5. Rakip Karşılaştırması

### 5.1 TradingBlock Gamma Guide (2025)

| Özellik | TradingBlock | Bizim Sistem | Fark |
|---------|-------------|-------------|------|
| Greeks explanation | ✅ Detaylı | ⚠️ Basit | ⚠️ |
| Gamma scalping | ✅ | ❌ | ❌ |
| Delta hedging | ✅ | ❌ | ❌ |
| Portfolio Greeks | ✅ | ❌ | ❌ |

### 5.2 arXiv LLM Options (2026)

| Özellik | arXiv | Bizim Sistem | Fark |
|---------|-------|-------------|------|
| NL-to-strategy | ✅ | ❌ | ❌ |
| Strategy optimization | ✅ | ❌ | ❌ |
| Backtest | ✅ | ❌ | ❌ |

### 5.3 DaystoExpiry Iron Condor (2025)

| Özellik | DaystoExpiry | Bizim Sistem | Fark |
|---------|-------------|-------------|------|
| Iron Condor | ✅ Detaylı | ❌ | ❌ |
| DTE optimization | ✅ | ❌ | ❌ |
| Profit target | ✅ | ❌ | ❌ |

---

## 6. Uygulama Planı

### Faz 1: Contract Catalog + Options Chain (Hemen)
1. VIOP sözleşme kataloğu
2. Opsiyon zinciri veri modeli
3. Veri entegrasyonu

### Faz 2: Implied Volatility + Portfolio Greeks (1 hafta)
1. Newton-Raphson IV hesaplama
2. Portfolio Greeks aggregation
3. Greeks monitoring

### Faz 3: Strategy Library (1 hafta)
1. Collar, Iron Condor, Straddle, Strangle
2. Bull/Bear Spread
3. Butterfly
4. Strateji analizi (max profit, max loss, breakeven)

### Faz 4: Dynamic Hedging (1 hafta)
1. Delta hedging
2. Gamma scalping
3. Tail risk hedge
4. Dynamic hedge adjustment

### Faz 5: SPAN Margin + Arbitraj (1 hafta)
1. SPAN teminat modeli (16 senaryo)
2. Futures-spot arbitraj
3. Basis analizi
4. Risk entegrasyonu

### Faz 6: VIOP Backtest (1 hafta)
1. Options strateji backtest
2. Greeks-based backtest
3. Hedging strateji backtest

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 6 | 12 |
| Toplam satır | 82 | ~800 |
| Black-Scholes | ✅ Basit | ✅ + IV |
| Greeks | ✅ Tek opsiyon | ✅ Portfolio Greeks |
| Strategies | ⚠️ 2 strateji | ✅ 8+ strateji |
| Hedging | ⚠️ Beta only | ✅ Delta + Gamma + Tail |
| Margin | ⚠️ Basit | ✅ SPAN (16 senaryo) |
| Parity | ✅ Basit | ✅ |
| Contract catalog | ❌ | ✅ |
| Options chain | ❌ | ✅ |
| Implied volatility | ❌ | ✅ |
| Delta hedging | ❌ | ✅ |
| Arbitraj | ❌ | ✅ |
| VIOP backtest | ❌ | ✅ |
| Risk integration | ⚠️ Zayıf | ✅ |
