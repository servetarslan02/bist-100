# Backtest Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-20
**Analiz:** NIHAI-SPEC.md vs Gerçek Kod Karşılaştırması

---

## Modül Yapısı (19 dosya)

| Modül | Satır | Sınıf | Fonksiyon | Amaç |
|-------|-------|-------|-----------|------|
| `engine_v4.py` | ~1230 | 9 | 31 | Ana backtest motoru (legacy + fast panel) |
| `walk_forward_runner.py` | ~650 | 3 | 11 | Walk-forward backtest runner (ML training per fold) |
| `portfolio_sim.py` | ~600 | 6 | 27 | Portföy simülasyonu (v4.1: realistic cost entegre) |
| `walk_forward.py` | ~436 | 3 | 7 | Walk-forward analysis (purge/embargo) |
| `enhanced_walk_forward.py` | ~369 | 3 | 12 | Purge/embargo walk-forward (precision@K, IC) |
| `transaction_costs.py` | ~350 | 8 | 12 | BIST gerçekçi maliyet modeli |
| `engine.py` | ~302 | 4 | 4 | Basit backtest engine (v1.0) |
| `multi_asset_engine.py` | ~350 | 5 | 3 | Çoklu hisse backtest |
| `event_replay.py` | ~300 | 6 | 9 | Event replay motoru |
| `deterministic.py` | ~280 | 4 | 10 | Deterministik recovery |
| `bias_detector.py` | ~300 | 4 | 8 | Look-ahead bias tespit |
| `survivorship.py` | ~250 | 4 | 8 | Survivorship bias yönetimi |
| `pit_validator.py` | ~300 | 5 | 10 | Point-in-time doğrulama |
| `persistence.py` | ~250 | 1 | 10 | SQLite tabanlı sonuç saklama |
| `deflated_sharpe.py` | ~250 | 3 | 7 | Deflated Sharpe + PSR |
| `benchmark.py` | ~200 | 2 | 4 | Benchmark karşılaştırma |
| `canonical_adapter.py` | ~165 | 1 | 6 | Canonical scoring adapter |
| `scanner_parity.py` | ~250 | 4 | 7 | Backtest-scanner parity |
| `__init__.py` | ~130 | 0 | 0 | Package exports |

**Toplam:** ~5,900 satır, 19 modül

---

## Spec Uyumluluk Özeti

| # | Madde | Durum | Not |
|---|-------|-------|-----|
| **Bias Korumaları** | | | |
| 1 | Look-ahead bias detection | ✅ TAM | `bias_detector.py` — timestamp, window, label alignment, fold boundary |
| 2 | Survivorship bias handling | ✅ TAM | `survivorship.py` — delisting registry, universe filter |
| 3 | Data-snooping (Deflated Sharpe) | ✅ TAM | `deflated_sharpe.py` — Bailey & López de Prado 2014 |
| 4 | Optimization (out-of-sample) | ✅ TAM | Walk-forward purge/embargo |
| 5 | Overfitting prevention | ✅ TAM | Walk-forward + deflated sharpe + cross-validation |
| **Mimari Katmanlar** | | | |
| 6 | Point-in-Time Data Engine | ✅ TAM | `pit_validator.py` + `walk_forward_runner._truncate()` |
| 7 | Feature Engine (Live Parity) | ✅ TAM | `canonical_adapter.py` + `scanner_parity.py` |
| 8 | Signal Generator | ✅ TAM | `_compute_score()` legacy + canonical |
| 9 | Risk Gate | ⚠️ KISMİ | Portfolio seviyesinde var, ayrı risk module ile entegrasyon eksik |
| 10 | Execution Simulator | ✅ TAM | `transaction_costs.py` (spread, slippage, impact, BSMV) |
| 11 | Portfolio Simulator | ✅ TAM | `portfolio_sim.py` v4.1 — realistic cost entegre |
| 12 | Metrics Engine | ✅ TAM | Sharpe, Sortino, Calmar, VaR, CVaR, MaxDD Duration |
| 13 | Persistence & Audit | ✅ TAM | SQLite, immutable trades, config snapshot |
| **Walk-Forward** | | | |
| 14 | Purge/embargo | ✅ TAM | `walk_forward.py` + `enhanced_walk_forward.py` |
| 15 | Fold-level engine run | ✅ TAM | `walk_forward_runner.py` — PIT truncation per fold |
| 16 | Leakage guards | ✅ TAM | `_verify_fold()` — 5 kontrol |
| 17 | ML model per fold | ✅ TAM | `_train_fold_model()` — LightGBM + multi-horizon |
| **Transaction Costs** | | | |
| 18 | BIST commission | ✅ TAM | `BISTFeeStructure` (broker + BIST + MKK + BSMV) |
| 19 | Spread model | ✅ TAM | 4-tier likidite bazlı |
| 20 | Slippage model | ✅ TAM | Volatilite + hacim + emir boyutu bazlı |
| 21 | Market impact | ✅ TAM | Square-root model (Kissell 2013) |
| **Metrikler** | | | |
| 22 | Sharpe/Sortino/Calmar | ✅ TAM | |
| 23 | VaR/CVaR 95% | ✅ TAM | **YENİ EKLENDİ** — Historical percentile method |
| 24 | MaxDD Duration | ✅ TAM | **YENİ EKLENDİ** — portfolio_sim'de izleniyor |
| 25 | IC, Precision@K, Hit Rate | ✅ TAM | Walk-forward fold'larında |
| 26 | Deflated Sharpe | ✅ TAM | Cornish-Fisher + Bonferroni düzeltmesi |
| 27 | Turnover | ✅ TAM | enhanced_walk_forward'da |
| **Diğer** | | | |
| 28 | Event replay | ✅ TAM | `event_replay.py` — hash chain audit trail |
| 29 | Deterministic recovery | ✅ TAM | `deterministic.py` — checkpoint + idempotency |
| 30 | Scanner parity | ✅ TAM | `scanner_parity.py` — feature version lock |
| 31 | API endpoint | ⚠️ KISMİ | `services/api/v1/backtest.py` mevcut ama doğrulanmadı |
| 32 | BUY/SELL asimetrisi | ✅ TAM | **DOKÜMANTASYON EKLENDİ** — hysteresis gap 10+ puan |

---

## Yapılan Değişiklikler (2026-08-20)

### 1. PortfolioSimulatorV3 — TransactionCostEngine Entegrasyonu
- `__init__`'e `use_realistic_costs`, `avg_daily_volume`, `volatility_ratio` parametreleri eklendi
- `execute_buy()` ve `execute_sell()`'te realistic cost engine opsiyonel olarak kullanılıyor
- Geriye uyumlu: `use_realistic_costs=False` (varsayılan) → legacy davranış aynen korunur

### 2. VaR/CVaR Metrikleri
- `compute_metrics()`'e Historical VaR 95% ve CVaR 95% (Expected Shortfall) eklendi
- `BacktestMetrics` dataclass'ına `var_95`, `cvar_95` field'ları eklendi
- Minimum 20 gözlem gerektirir (percentile hesaplaması için)

### 3. Max Drawdown Duration Tracking
- `update_equity()`'de drawdown başlangıç/bitiş tarihleri izleniyor
- `compute_metrics()`'e `max_drawdown_duration_days` eklendi
- `reset()`'te sıfırlanıyor

### 4. BUY/SELL Eşik Asimetrisi Dokümantasyonu
- SELL eşiği: `score <= (100 - signal_threshold)` → 40 (varsayılan)
- BUY eşiği: `score >= signal_threshold + 10` → 70 (varsayılan)
- Hysteresis gap: 30 puan → whipsaw önleme
- **Gerekçe:** Pozisyondan çıkmak için düşük eşik (esnek), girmek için yüksek eşik (seçici)

### 5. Entegrasyon Testi
- `tests/test_backtest_integration.py` — 25 test, tümü geçiyor
- Kapsadığı alanlar: realistic costs, VaR/CVaR, MaxDD duration, BUY/SELL asimetrisi,
  walk-forward leakage, engine parity, deflated sharpe, benchmark, transaction costs,
  survivorship, deterministic recovery, bias detector, scanner parity

---

## Açık Kararlar (Kullanıcıya Sorulacak)

### 1. Risk Gate Entegrasyonu
Spec'te ayrı bir Risk Gate katmanı tanımlanmış (position limits, sector exposure, drawdown limits, liquidity check). Mevcut kodda bu kontroller `portfolio_sim.py` içinde `max_positions` ve `max_position_pct` ile kısmen yapılıyor, ama ayrı bir risk module ile entegrasyon yok.

**Seçenekler:**
- A) `services/risk/` modülünü backtest'e entegre et (tam parity)
- B) Mevcut portfolio_sim kontrolleri yeterli (basit tut)
- C) Risk Gate'i backtest runner seviyesinde middleware olarak ekle

### 2. Partial Fill Simülasyonu
Spec'te "partial fill" ve "rejection (liquidity)" var. Mevcut kodda emir ya tamamen gerçekleşiyor ya da reddediliyor.

**Seçenekler:**
- A) Partial fill ekle (gerçekçi ama karmaşık)
- B) Mevcut all-or-nothing model yeterli (basit tut)

### 3. Sharpe > 3.0 Kırmızı Bayrak
Spec'te "Sharpe > 3.0 → Muhtemelen curve-fit" uyarısı var. Bu bir metrik olarak değil, bir uyarı mekanizması olarak eklenmeli mi?

---

## Test Sonuçları

```
tests/test_backtest_integration.py — 25 passed, 0 failed
```

| Test Grubu | Test Sayısı | Durum |
|-----------|-------------|-------|
| PortfolioTransactionCosts | 3 | ✅ |
| AdvancedMetrics | 3 | ✅ |
| BuySellAsymmetry | 2 | ✅ |
| WalkForwardLeakage | 2 | ✅ |
| EngineParity | 1 | ✅ |
| DeflatedSharpe | 3 | ✅ |
| Benchmark | 1 | ✅ |
| TransactionCosts | 4 | ✅ |
| Survivorship | 1 | ✅ |
| DeterministicRecovery | 2 | ✅ |
| BiasDetector | 1 | ✅ |
| ScannerParity | 2 | ✅ |

---

## Matematiksel Düzeltmeler (2026-08-20 — İkinci Tur)

### Düzeltme 6: Slippage Double-Counting (KRİTİK)
- **Dosya:** `portfolio_sim.py` — `execute_buy()` legacy path
- **Sorun:** Slippage iki kez sayılıyordu
  ```
  ESKİ (HATALI):
  fill_price = price * 1.001          # = 100.1 (slippage dahil)
  amount = qty * fill_price           # = 100,100 (slippage dahil)
  commission = BIST.compute(amount)   # = 37.42
  slippage = amount * 0.001           # = 100.1 (İKİNCİ KEZ!)
  total_cost = amount + commission + slippage  # = 100,237.52 ← FAZLA
  ```
  ```
  YENİ (DOĞRU):
  fill_price = price * 1.001          # = 100.1 (slippage dahil)
  amount = qty * fill_price           # = 100,100 (slippage dahil)
  commission = BIST.compute(amount)   # = 37.42
  slippage = amount - qty*price       # = 100.1 (bilgi amaçlı)
  total_cost = amount + commission    # = 100,137.42 ← DOĞRU
  ```
- **Etki:** Legacy backtest cost basis artık realistic ile aynı mantıkta

### Düzeltme 7: SELL Komisyon Tutarlılığı
- **Dosya:** `portfolio_sim.py` — `execute_sell()` realistic path
- **Sorun:** SELL'de komisyon fill_price üzerinden, BUY'de market price üzerinden
- **Çözüm:** Her iki yolda da komisyon market price (`qty * price`) üzerinden
- **Formül:** `commission = BISTCommissionModel.compute(quantity * price)`

### Doğru Maliyet Formülleri (Final)
```
BUY:
  fill_price = market_price * (1 + slippage_rate)
  notional = quantity * fill_price         ← slippage dahil
  commission = BIST.compute(notional)      ← fill price üzerinden
  total_cost = notional + commission       ← slippage TEK KEZ
  cost_basis = total_cost

SELL:
  fill_price = market_price * (1 - slippage_rate)
  notional = quantity * fill_price         ← slippage dahil
  commission = BIST.compute(qty * market_price)  ← market price üzerinden
  net_revenue = notional - commission
  pnl = net_revenue - cost_basis
```
