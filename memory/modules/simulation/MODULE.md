# SİMÜLASYON — Simulation Engine

## Giriş

Simulation modülü, ALPHA BIST'in **ileri düzey simülasyon ve senaryo analizi katmanıdır**. Monte Carlo simülasyonları, stres testleri, execution simülasyonu ve order book modelleme gibi "ne olursa ne yaparız?" sorularını cevaplar.

Modül iki katmandan oluşur: (1) `main.py` — event-driven simulation engine (Monte Carlo, scenario analysis, backtest), (2) alt sistemler — enhanced execution (square root market impact), jump-diffusion Monte Carlo, correlated paths, regime-conditioned MC, enhanced stress test (8+ senaryo) ve order book simülasyonu.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                main.py — SimulationEngine                       │
│  (Event consumer, simulation.requested → result)                │
│  Monte Carlo, Scenario Analysis, Stress Test                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         enhanced_execution.py                            │   │
│  │                                                          │   │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐   │   │
│  │  │ SquareRootMarket    │  │ RegimeAwareSlippage      │   │   │
│  │  │ Impact              │  │                          │   │   │
│  │  │                     │  │ BULL: 0.8x               │   │   │
│  │  │ Impact = σ × √(Q/V) │  │ BEAR: 1.3x              │   │   │
│  │  │       × η           │  │ PANIC: 2.0x              │   │   │
│  │  │                     │  │ CRISIS: 2.5x             │   │   │
│  │  │ η = 0.3 (default)   │  │                          │   │   │
│  │  └─────────────────────┘  └──────────────────────────┘   │   │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐   │   │
│  │  │ EnhancedExecution   │  │ LiquidityProfile         │   │   │
│  │  │ Simulator           │  │ (dataclass)              │   │   │
│  │  │                     │  │ avg_daily_volume,        │   │   │
│  │  │ BIST commission +   │  │ bid_depth, ask_depth,    │   │   │
│  │  │ slippage + partial  │  │ spread_pct, tick_size    │   │   │
│  │  │ fill                │  │                          │   │   │
│  │  └─────────────────────┘  └──────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         monte_carlo_enhanced.py                          │   │
│  │                                                          │   │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐   │   │
│  │  │ JumpDiffusion       │  │ CorrelatedMonteCarlo     │   │   │
│  │  │ MonteCarlo          │  │                          │   │   │
│  │  │                     │  │ Cholesky decomposition   │   │   │
│  │  │ dS/S = (μ-λk)dt    │  │ ile korelli random       │   │   │
│  │  │      + σdW + JdN   │  │ returns üretir           │   │   │
│  │  │                     │  │                          │   │   │
│  │  │ λ = jump intensity  │  │ Portföy bazlı risk       │   │   │
│  │  │ J ~ N(μ_j, σ_j²)   │  │ analizi                  │   │   │
│  │  │ N ~ Poisson(λt)     │  │                          │   │   │
│  │  └─────────────────────┘  └──────────────────────────┘   │   │
│  │  ┌─────────────────────┐                                 │   │
│  │  │ RegimeConditioned   │                                 │   │
│  │  │ MonteCarlo          │                                 │   │
│  │  │                     │                                 │   │
│  │  │ BULL: ret×1.5,      │                                 │   │
│  │  │       vol×0.8       │                                 │   │
│  │  │ BEAR: ret×0.3,      │                                 │   │
│  │  │       vol×1.5       │                                 │   │
│  │  │ PANIC: ret×0.0,     │                                 │   │
│  │  │        vol×3.0      │                                 │   │
│  │  └─────────────────────┘                                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         enhanced_stress_test.py                          │   │
│  │                                                          │   │
│  │  8+ Senaryo:                                             │   │
│  │  ├── Market Crash -20%        (p=0.05)                  │   │
│  │  ├── Currency Crisis +30%     (p=0.03)                  │   │
│  │  ├── Rate Shock +500bp        (p=0.08)                  │   │
│  │  ├── Sector Rotation          (p=0.15)                  │   │
│  │  ├── Black Swan -30%          (p=0.01)                  │   │
│  │  ├── Liquidity Crisis         (p=0.04)                  │   │
│  │  ├── Stagflation              (p=0.03)                  │   │
│  │  └── Global Risk-Off          (p=0.10)                  │   │
│  │                                                          │   │
│  │  Breaking point analysis: portföy ne kadar kaybeder?     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         order_book.py                                    │   │
│  │                                                          │   │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐   │   │
│  │  │ OrderBookSimulator  │  │ OrderBookSnapshot        │   │   │
│  │  │                     │  │ (dataclass)              │   │   │
│  │  │ Sentetik bid/ask    │  │ best_bid, best_ask,      │   │   │
│  │  │ depth üretimi       │  │ mid_price, spread,       │   │   │
│  │  │                     │  │ imbalance, depth         │   │   │
│  │  │ Market order walk-  │  │                          │   │   │
│  │  │ the-book simülasyon │  │                          │   │   │
│  │  │                     │  │                          │   │   │
│  │  │ Likidite skoru      │  │                          │   │   │
│  │  │ hesaplama           │  │                          │   │   │
│  │  └─────────────────────┘  └──────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         execution_simulator.py                           │   │
│  │                                                          │   │
│  │  Order lifecycle: CREATED → SUBMITTED → FILLED           │   │
│  │  Slippage: base + volume_impact                          │   │
│  │  Commission: broker + exchange + BSMV                    │   │
│  │  Partial fill: günlük hacmin %10'u                       │   │
│  │  Limit emir reddetme: fiyattan %5 uzak                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Jump-Diffusion (Merton modeli)** | Normal dağılım kuyruk riskini yakalamaz. Jump process ile %2 ihtimalle büyük hareketler eklenir. |
| **Cholesky decomposition** | Korelli varlıklar için bağımsız simülasyon yanıltıcı. Korelasyon yapısını korur. |
| **Regime-conditioned parametreler** | BULL'da farklı, PANIC'te farklı getiri/volatilite. Tek parametre seti her rejimde yanıltıcı. |
| **Square root market impact** | Lineer model büyük emirlerde aşırı tahmin eder. √(Q/V) daha gerçekçi (Almgren-Chriss). |
| **Regime-aware slippage** | PANIC'te slippage 2x, CRISIS'te 2.5x. Sabit slippage gerçekçi değil. |
| **8+ stres senaryosu** | Sadece "market crash" yetmez. Döviz krizi, faiz şoku, stagflasyon, likidite krizi ayrı ayrı test edilmeli. |
| **Breaking point analysis** | Portföyün ne kadar kayba dayanabileceğini bilmek kritik. Hangi senaryo eşiği aşıyor? |
| **Order book simülasyonu** | Gerçek order book verisi yok. Sentetik book ile VWAP, slippage, likidite skoru hesaplanabilir. |
| **GARCH(1,1) volatilite clustering** | Sabit volatilite gerçekçi değil. Büyük hareketler sonrası volatilite artar, sonra düşer. |
| **Student-t fat tails** | Normal dağılım %5'lik kayıpları hafife alır. df=5 Student-t daha gerçekçi kuyruk davranışı. |

## Uçtan Uca Veri Akışı

```
1. simulation.requested event → SimulationEngine._on_simulation_request()
       ↓
2. Simülasyon tipi seçimi:
   ├── "monte_carlo" → _run_monte_carlo()
   ├── "scenario"    → _run_scenario_analysis()
   └── "stress_test" → _run_stress_test()
       ↓
3. Monte Carlo (_run_monte_carlo):
   ├── ClickHouse'dan tarihsel volatilite al
   ├── Regime-conditioned parametreler
   ├── Student-t fat tails (df=5)
   ├── GARCH(1,1) volatilite clustering
   ├── Event shock injection (%2 ihtimalle ±%3-5)
   ├── 10,000 simülasyon × 20 gün
   └── VaR/CVaR, percentiles, olasılıklar
       ↓
4. Scenario Analysis (_run_scenario_analysis):
   ├── 4 senaryo: Bull/Base/Bear/Crash
   ├── Her pozisyon için:
   │   ├── Beta bazlı market etkisi
   │   ├── Sektör rotasyon etkisi
   │   └── USD hassasiyeti
   └── Expected impact = Σ(impact × probability)
       ↓
5. Stress Test (_run_stress_test):
   ├── 5 senaryo: Crash, Currency, Rate, Rotation, Black Swan
   ├── Her pozisyon için: market + USD etkisi
   └── Worst case analizi
       ↓
6. Sonuç DB'ye kaydet + SIMULATION_COMPLETED event publish
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Singleton | Kritik Sınıf/Fonksiyon |
|-------|-----------|-----------|------------------------|
| `main.py` | Event-driven simulation engine, Monte Carlo, scenario, stress test | — | `SimulationEngine._run_monte_carlo()`, `_run_scenario_analysis()` |
| `execution_simulator.py` | Order lifecycle, slippage, commission, partial fill | `execution_simulator` | `ExecutionSimulator.execute_order()` |
| `enhanced_execution.py` | Square root market impact, regime-aware slippage, liquidity profile | `enhanced_execution` | `EnhancedExecutionSimulator.execute_order()`, `SquareRootMarketImpact.calculate()` |
| `monte_carlo_enhanced.py` | Jump-diffusion, correlated paths, regime-conditioned MC | `jump_diffusion_mc`, `correlated_mc`, `regime_mc` | `JumpDiffusionMonteCarlo.simulate()`, `CorrelatedMonteCarlo.simulate_portfolio()` |
| `enhanced_stress_test.py` | 8+ stres senaryosu, breaking point analysis | `enhanced_stress_test` | `EnhancedStressTestEngine.run_stress_test()`, `find_breaking_point()` |
| `order_book.py` | Sentetik order book, market order walk-the-book, likidite skoru | `order_book_sim` | `OrderBookSimulator.generate_book()`, `simulate_market_order()` |
| `__init__.py` | Public API exports | — | Tüm singleton'lar ve dataclass'lar |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Gerçekçilik**: Slippage, komisyon, likidite kısıtı, partial fill — hepsi simülasyonda var.
2. **Regime-aware**: Parametreler piyasa rejimine göre değişir. Sabit parametre seti yok.
3. **Fat tails**: Normal dağılım yerine Student-t ve jump process. Kuyruk riski yakalanır.
4. **Korelasyon yapısı**: Cholesky ile korelli random returns. Bağımsız simülasyon yanıltıcı.
5. **Reproducibility**: Seed parametresi ile deterministik sonuçlar.
6. **Extensibility**: `add_custom_scenario()` ile yeni senaryo eklenebilir.

### Kırmızı Çizgiler

- ❌ Normal dağılım varsayımı ile kuyruk riskini görmezden gelme
- ❌ Korelasyon yapısını ihmal etme (bağımsız simülasyon)
- ❌ Sabit volatilite kullanma (GARCH olmadan)
- ❌ Likidite kısıtı olmadan büyük emir simülasyonu
- ❌ Regime-conditioned parametreler kullanmadan simülasyon

## Bilinen Sınırlamalar

1. **ClickHouse bağımlılığı**: `_get_historical_volatility()` ClickHouse'dan veri çeker. Yoksa simülasyon çalışamaz.
2. **Sentetik order book**: Gerçek order book verisi yok. `order_book.py` sentetik book üretir — gerçek piyasa microstructure'dan farklı olabilir.
3. **GARCH basitleştirilmiş**: Gerçek GARCH(1,1) parametreleri kalibrasyon gerektirir. Burada sabit α=0.1, β=0.85 kullanılır.
4. **Stres testi statik sektör etkileri**: Sektör etkileri sabit. Gerçek sektör korelasyonları dinamik.
5. **Monte Carlo 10,000 simülasyon**: Daha yüksek simülasyon sayısı daha güvenilir sonuç verir ama hesaplama maliyeti artar.
6. **Order book seviyeleri sabit**: `depth_levels=5`. Gerçek order book çok daha derin olabilir.
7. **Execution simulator vs enhanced execution**: İki farklı execution simülatörü var (basit ve gelişmiş). Hangisinin kullanılacağı çağrıcıya bağlı.

## Cross-Referanslar

| Bu modül | İlişki | Diğer modül |
|----------|--------|-------------|
| `simulation/main.py` | ClickHouse → `core.database.ch_execute` | Core database |
| `simulation/main.py` | Event bus → `simulation.requested`, `simulation.completed` | Core event_bus |
| `simulation/main.py` | DB → `simulations` tablosu | Core PostgreSQL |
| `simulation/execution_simulator.py` | Benzer slippage/commission mantığı | `paper_trading/paper_execution.py` |
| `simulation/enhanced_execution.py` | `LiquidityProfile` → `order_book.py` | Order book (iç) |
| `simulation/monte_carlo_enhanced.py` | `JumpDiffusionMonteCarlo` ← `main.py` tarafından çağrılabilir | Simulation main (iç) |
| `simulation/enhanced_stress_test.py` | Benzer stres testi mantığı | `risk/stress_test.py` |
| `simulation/order_book.py` | Likidite skoru → execution simülasyonu | Enhanced execution (iç) |
| `risk/var_cvar.py` | Monte Carlo VaR (farklı implementasyon) | Risk modülü |
| `risk/stress_test.py` | Stres testi (farklı senaryo seti) | Risk modülü |
| `paper_trading/paper_execution.py` | Execution simülasyonu (farklı implementasyon) | Paper trading modülü |
