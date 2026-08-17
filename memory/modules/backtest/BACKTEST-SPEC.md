# Backtest Sistem Dokümanı — Geriye Dönük Test Mimarisi

**Tarih:** 2026-08-18

---

## 1. Mevcut Durum

### Backtest Modülleri (7)
```
services/backtest/
├── engine.py                (302 satır)  — Basit backtest engine
├── engine_v4.py             (1225 satır) — Gelişmiş backtest engine (v4)
├── walk_forward.py          (436 satır)  — Walk-forward analysis
├── enhanced_walk_forward.py (369 satır)  — Purge/embargo walk-forward
├── walk_forward_runner.py   (649 satır)  — Walk-forward backtest runner
├── portfolio_sim.py         (565 satır)  — Portföy simülasyonu (v3)
├── canonical_adapter.py     (165 satır)  — Canonical score adapter
└── persistence.py           (250 satır)  — Backtest sonuç saklama
```

### Test Dosyaları (7)
```
tests/test_backtest_data_parity.py
tests/test_backtest_performance.py
tests/test_backtest_v4.py
tests/test_backtest_v5_upgrade.py
tests/test_canonical_backtest.py
tests/test_faz4_backtest.py
tests/test_walkforward_canonical.py
```

---

## 2. Modül Detayları

### 2.1 engine.py — Basit Backtest Engine

**Sınıflar:**
- `BacktestTrade` — Tek işlem kaydı
- `BacktestMetrics` — Performans metrikleri
- `BacktestResult` — Backtest sonucu
- `BacktestEngine` — Ana backtest motoru

**Fonksiyonlar:**
- `run_backtest(strategy_name, signals, price_data, initial_capital, commission_rate, slippage_pct)` → BacktestResult
- `_compute_metrics(trades, equity_curve, initial_capital)` → BacktestMetrics
- `_compute_drawdown_curve(equity_curve)` → List[float]
- `get_backtest_systems()` → Dict (diğer backtest modüllerini bağlar)

**Bağlantılar:**
- `portfolio_manager.CommissionModel` — Komisyon hesaplama
- `engine_v4.BacktestEngineV4` — Gelişmiş engine
- `enhanced_walk_forward.PurgeEmbargoWalkForward` — WF
- `portfolio_sim.PortfolioSimulatorV3` — Portföy sim
- `walk_forward.WalkForwardEngine` — WF
- `walk_forward_runner.WalkForwardBacktestRunner` — WF runner
- `canonical_adapter.BacktestCanonicalAdapter` — Canonical adapter
- `persistence.BacktestPersistence` — Sonuç saklama

**Eksikler:**
- Look-ahead bias kontrolü yok
- Transaction cost model basit (sadece komisyon)
- Slippage model basit (%0.05 sabit)
- Multi-asset backtest yok

---

### 2.2 engine_v4.py — Gelişmiş Backtest Engine

**Sınıflar:**
- `BacktestConfig` — Backtest konfigürasyonu
- `BacktestMetrics` — Performans metrikleri
- `BacktestResultV4` — Backtest sonucu
- `FeatureCache` — Feature önbellek
- `QualityCache` — Kalite önbellek

**Fonksiyonlar:**
- `run_backtest(config, signals, price_data)` → BacktestResultV4
- Feature hesaplama ile entegre
- Walk-forward ile entegre

**Eksikler:**
- 1225 satır ama çoğu yerde kullanılmıyor
- API'de endpoint yok
- Persistence ile entegrasyon zayıf

---

### 2.3 walk_forward.py — Walk-Forward Analysis

**Sınıflar:**
- `WalkForwardFold` — Tek fold sonucu
- `WalkForwardResult` — Tüm fold'ların sonucu
- `WalkForwardEngine` — WF motoru

**Fonksiyonlar:**
- `create_folds(data, train_size, test_size, step_size)` → List[WalkForwardFold]
- `run_walk_forward(data, model_fn, features, target)` → WalkForwardResult
- `_calculate_fold_metrics(predictions, actuals)` → Dict
- `_deflated_sharpe(sharpe, n_obs, n_trials)` → float
- `_aggregate_results(folds)` → WalkForwardResult

**Metrikler:**
- Precision@K
- IC (Information Coefficient)
- Hit Rate
- Top-K Return
- Sharpe Ratio
- Max Drawdown
- Turnover
- Deflated Sharpe

---

### 2.4 enhanced_walk_forward.py — Purge/Embargo Walk-Forward

**Sınıflar:**
- `WalkForwardFold` — Fold tanımı
- `WalkForwardResult` — Sonuç
- `PurgeEmbargoWalkForward` — Purge/embargo ile WF

**Fonksiyonlar:**
- `split(data)` → List[Tuple[train_idx, test_idx]]
- `run(data, model_fn, features, target)` → WalkForwardResult
- `_precision_at_k(predictions, actuals, k)` → float
- `_compute_ic(predictions, actuals)` → float
- `_compute_hit_rate(predictions, actuals)` → float
- `_compute_top_k_return(predictions, actuals, k)` → float
- `_compute_daily_returns(predictions, actuals, k)` → List[float]
- `_compute_sharpe(daily_returns, risk_free)` → float
- `_compute_max_drawdown(daily_returns)` → float
- `_compute_turnover(predictions, actuals, k)` → float
- `_deflated_sharpe(sharpes, n_trials)` → float

**Purge/Embargo:**
- Purge: Train-test arasında veri sızıntısını önle
- Embargo: Test setinden sonra belirli günleri hariç tut

---

### 2.5 walk_forward_runner.py — Walk-Forward Backtest Runner

**Sınıflar:**
- `FoldBacktestResult` — Tek fold backtest sonucu
- `WalkForwardBacktestResult` — Tüm WF sonucu
- `WalkForwardBacktestRunner` — WF backtest runner

**Fonksiyonlar:**
- `run(market_data, universe)` → WalkForwardBacktestResult
- `_train_fold_model(fold_data, features, target)` → model
- `_get_canonical_feature_names()` → List[str]
- `_truncate(text, max_len)` → str
- `_verify_fold(fold_data)` → bool
- `_aggregate(fold_results)` → WalkForwardBacktestResult

---

### 2.6 portfolio_sim.py — Portföy Simülasyonu

**Sınıflar:**
- `Trade` — İşlem kaydı
- `Position` — Pozisyon
- `EquitySnapshot` — Equity snapshot
- `AuditEntry` — Audit kaydı
- `BISTCommissionModel` — BIST komisyon modeli
- `PortfolioSimulatorV3` — Portföy simülatörü

**Fonksiyonlar:**
- `execute_buy(ticker, price, quantity, date)` → Dict
- `execute_sell(ticker, price, quantity, date)` → Dict
- `update_prices(prices, date)` → None
- `get_equity()` → float
- `get_positions()` → Dict
- `get_trade_history()` → List[Trade]
- `get_equity_curve()` → List[EquitySnapshot]

**BIST Komisyon Modeli:**
- Broker: %0.03
- BIST: %0.0056
- MKK: %0.00109
- BSMV: %5 (komisyon üzerinden)
- Minimum: ₺1

---

### 2.7 canonical_adapter.py — Canonical Score Adapter

**Sınıflar:**
- `BacktestCanonicalAdapter` — Canonical scoring adapter

**Fonksiyonlar:**
- `compute_score(ticker, features, market_state)` → Dict
- `compute_score_and_decision(ticker, features, market_state)` → Tuple[Dict, Dict]
- `enrich_features_for_canonical(features)` → Dict

---

### 2.8 persistence.py — Backtest Sonuç Saklama

**Sınıflar:**
- `BacktestPersistence` — SQLite tabanlı saklama

**Fonksiyonlar:**
- `save_run(strategy, config, metrics, equity_curve)` → str (run_id)
- `save_trades(run_id, trades)` → None
- `save_equity_curve(run_id, curve)` → None
- `get_run(run_id)` → Dict
- `get_trades(run_id)` → List[Dict]
- `get_equity_curve(run_id)` → List[Dict]
- `list_runs(limit)` → List[Dict]
- `delete_run(run_id)` → None

---

## 3. Entegrasyon Haritası

### Backtest → Diğer Servisler

```
backtest/engine.py
├── portfolio_manager.CommissionModel ← Komisyon
├── backtest/engine_v4.py ← Gelişmiş engine
├── backtest/walk_forward.py ← WF analysis
├── backtest/enhanced_walk_forward.py ← Purge/embargo WF
├── backtest/walk_forward_runner.py ← WF runner
├── backtest/portfolio_sim.py ← Portföy sim
├── backtest/canonical_adapter.py ← Canonical adapter
└── backtest/persistence.py ← Sonuç saklama
```

### Diğer Servisler → Backtest

```
ml/ranking_model.py → walk_forward.py (WF engine)
ml/lightgbm_trainer.py → walk_forward.py (model eğitimi)
scanner/backtest_runner.py → backtest/engine.py (backtest tetikleme)
learning/main.py → backtest (sonuç takibi)
```

---

## 4. Eksikler ve Sorunlar

### 4.1 Kritik Eksikler

| Eksik | Açıklama | Öncelik |
|-------|----------|---------|
| **Look-ahead bias kontrolü** | Gelecek veri kullanma kontrolü yok | 🔴 Kritik |
| **Survivorship bias** | İflas eden şirketleri dahil etme | 🔴 Kritik |
| **Point-in-time data** | Sonradan düzeltilmiş veri kontrolü | 🔴 Kritik |
| **Transaction cost model** | Sadece komisyon, spread/slippage basit | 🟡 Önemli |
| **Multi-asset backtest** | Sadece tek hisse | 🟡 Önemli |
| **Event replay** | Belirli günü yeniden çalıştırma | 🟡 Önemli |
| **Deterministic recovery** | Restart sonrası aynı sonuç | 🟡 Önemli |

### 4.2 API Eksikleri

| Endpoint | Açıklama |
|----------|----------|
| `POST /api/backtests` | Backtest başlat |
| `GET /api/backtests/{id}` | Sonuç getir |
| `GET /api/backtests` | Tüm sonuçları listele |
| `POST /api/backtests/walk-forward` | WF başlat |

### 4.3 Entegrasyon Eksikleri

| Bağlantı | Durum |
|----------|-------|
| engine → engine_v4 | ⚠️ Zayıf |
| engine → persistence | ⚠️ Zayıf |
| engine → canonical_adapter | ⚠️ Zayıf |
| walk_forward → ranking_model | ⚠️ Zayıf |
| portfolio_sim → portfolio/main.py | ❌ Bağlı değil |

---

## 5. Backtest Akışı

```
Sinyal Üretimi
    ↓
┌─────────────────────────────────────┐
│         BACKTEST ENGINE             │
│                                     │
│  1. Sinyalleri al                   │
│  2. Her sinyal için:                │
│     a. Fiyat verisini al            │
│     b. Slippage uygula              │
│     c. Komisyon hesapla             │
│     d. Pozisyon aç/kapat            │
│     e. Equity güncelle              │
│     f. Trade kaydet                 │
│  3. Metrikleri hesapla              │
│  4. Sonuçları kaydet                │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│       WALK-FORWARD ANALYSIS         │
│                                     │
│  1. Veriyi train/test fold'lara böl │
│  2. Her fold için:                  │
│     a. Model eğit                   │
│     b. Test et                      │
│     c. Metrikleri hesapla           │
│  3. Tüm fold'ları birleştir         │
│  4. Deflated Sharpe hesapla         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│       PORTFOLIO SIMULATION          │
│                                     │
│  1. Sanal portföy oluştur            │
│  2. Emirleri simüle et              │
│  3. Spread/slippage uygula          │
│  4. Komisyon hesapla                │
│  5. P&L takip et                    │
│  6. Drawdown hesapla                │
└─────────────────────────────────────┘
```

---

## 6. Backtest Metrikleri

### Performans Metrikleri
- Total Return (%)
- CAGR (%)
- Sharpe Ratio
- Sortino Ratio
- Calmar Ratio
- Max Drawdown (%)
- Win Rate (%)
- Profit Factor
- Average Win / Average Loss
- Expectancy
- Turnover
- Exposure

### Risk Metrikleri
- VaR (95%, 99%)
- CVaR (95%, 99%)
- Max Drawdown
- Drawdown Duration
- Volatility
- Downside Deviation

### ML Metrikleri
- Precision@K
- IC (Information Coefficient)
- Hit Rate
- Top-K Return
- Deflated Sharpe
- Turnover

---

## 7. Uygulama Planı

### Faz 1: Bias Koruması
1. Look-ahead bias detection
2. Survivorship bias handling
3. Point-in-time data validation

### Faz 2: Transaction Cost Model
1. Spread model (bid/ask)
2. Slippage model (volatilite bazlı)
3. Market impact model (büyük emirler)
4. BIST-specific fee model

### Faz 3: API Entegrasyonu
1. `POST /api/backtests` — Backtest başlat
2. `GET /api/backtests/{id}` — Sonuç getir
3. `GET /api/backtests` — Listele
4. `POST /api/backtests/walk-forward` — WF başlat

### Faz 4: Event Replay
1. Belirli tarihten itibaren event'leri yeniden oynat
2. Deterministic recovery
3. State snapshot + event log

### Faz 5: Multi-Asset
1. Portföy bazlı backtest
2. Sektör bazlı backtest
3. Factor bazlı backtest
