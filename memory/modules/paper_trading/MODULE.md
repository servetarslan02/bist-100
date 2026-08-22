# PAPER TRADING — Sanal İşlem Motoru

## Giriş

Paper Trading modülü, ALPHA BIST'in **gerçek para kullanmadan strateji test eden otonom sistemidir**. Gerçek broker/API bağlantısı yoktur — tüm işlemler sanal olarak simüle edilir. Amaç: champion modelin performansını gerçek piyasa koşullarında (slippage, komisyon, likidite kısıtları dahil) ölçmek.

Modül, günlük otonom bir döngü çalıştırır: veri kalitesi kontrolü → fiyat güncelleme → champion sinyalleri → risk gate → sanal execution → portföy güncelleme → performans hesaplama → state persistence. Champion model LOCKED — otomatik değiştirilmez.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│            paper_orchestrator.py — PaperTradingOrchestrator     │
│  (Günlük otonom döngü, champion LOCKED, replay/backtest)       │
│  run_daily_cycle() → 6 stage pipeline                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 1: Data Quality Check                              │   │
│  │   data_quality_ok? min_stocks >= 50?                     │   │
│  │   FAIL → NO_TRADE + audit + error++                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 2: Mark-to-Market                                  │   │
│  │   virtual_portfolio.update_prices(prices, date)          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 3: Champion Signal Validation                      │   │
│  │   model_version == CHAMPION_VERSION?                     │   │
│  │   Non-champion sinyalleri IGNORE                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 4: Signal → Risk → Execution                       │   │
│  │   ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │   │
│  │   │ _process_   │→ │ PaperRiskGate│→ │ PaperExecution│  │   │
│  │   │ signal()    │  │ .check_all() │  │ Engine        │  │   │
│  │   │             │  │ 8 check      │  │ .execute_     │  │   │
│  │   │ position    │  │ fail-closed  │  │ signal()      │  │   │
│  │   │ sizing      │  │              │  │ slippage+     │  │   │
│  │   │ (equal wt)  │  │              │  │ commission    │  │   │
│  │   └─────────────┘  └──────────────┘  └───────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 5: Performance                                     │   │
│  │   performance_tracker.compute_daily_performance()        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ STAGE 6: State Persistence                               │   │
│  │   virtual_portfolio.save_to_store(date)                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ALT SİSTEMLER                                            │   │
│  │                                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │   │
│  │  │ Virtual      │  │ PaperRiskGate│  │ Performance   │  │   │
│  │  │ Portfolio    │  │              │  │ Tracker       │  │   │
│  │  │              │  │ Kill switch  │  │               │  │   │
│  │  │ Cash+Pos+    │  │ Max DD 20%   │  │ CAGR, Sharpe, │  │   │
│  │  │ Trade+Equity │  │ Daily loss   │  │ Sortino, Max  │  │   │
│  │  │ curve        │  │ 5%           │  │ DD, Win Rate, │  │   │
│  │  │              │  │ Sector 30%   │  │ Profit Factor │  │   │
│  │  └──────────────┘  └──────────────┘  └───────────────┘  │   │
│  │                                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐                     │   │
│  │  │ PaperState   │  │ Paper        │                     │   │
│  │  │ Store        │  │ Execution    │                     │   │
│  │  │ (SQLite)     │  │ Engine       │                     │   │
│  │  │ Portfolio,   │  │ Slippage,    │                     │   │
│  │  │ Trades,      │  │ Commission,  │                     │   │
│  │  │ Orders,      │  │ Liquidity    │                     │   │
│  │  │ Audit,       │  │ constraint   │                     │   │
│  │  │ Performance  │  │              │                     │   │
│  │  └──────────────┘  └──────────────┘                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Champion LOCKED** | Challenger doğrudan giremez. Paper trading sonucu model eğitimine geri beslenmez. Bu, overfitting'i önler. |
| **Fail-closed risk gate** | 8 ayrı check (kill switch, data quality, model validity, position size, sector, exposure, drawdown, daily loss). Herhangi biri BLOCK derse işlem olmaz. |
| **Signal price ≠ execution price** | Sinyal üretildiği fiyat ile işlem yapılan fiyat ayrı. Ertesi seans açılışında işlem gerçekleşir. Look-ahead bias önlenir. |
| **SQLite persistence** | Program kapanıp açılsa bile veri kaybolmaz. Atomic write (WAL mode). Backup/rollback desteği. |
| **Immutable audit log** | Her sinyal, order, risk check, performans kaydı append-only. SHA-256 hash ile bütünlük doğrulaması. |
| **Equal weight position sizing** | Basit ve şeffaf. Her pozisyon portföyün %10'u (max). Score-weighted sizing yok — bu paper trading, optimizasyon değil. |
| **3 ardışık hata → kill switch** | Sistem hata üretmeye başlarsa otomatik durdur. İnsan müdahalesi gerekir. |

## Uçtan Uca Veri Akışı

```
1. run_daily_cycle(date, market_data, sector_map, champion_signals)
       ↓
2. Data quality check
   ├── market_data yeterli mi? (>= 50 hisse)
   └── FAIL → NO_TRADE, audit, error++
       ↓
3. Mark-to-market: portfolio.update_prices(prices, date)
       ↓
4. Champion sinyalleri filtrele
   ├── model_version == LOCKED_VERSION?
   └── Geçersiz sinyalleri IGNORE
       ↓
5. Her sinyal için _process_signal():
   ├── Pozisyon zaten var mı? (açık pozisyonu tekrar açma)
   ├── Position sizing: total_value × 10% / price = quantity
   ├── PaperRiskGate.check_all() → 8 check
   │   ├── kill_switch aktif mi?
   │   ├── data_quality OK mu?
   │   ├── model_version geçerli mi?
   │   ├── position_pct <= 10%?
   │   ├── sector_pct <= 30%?
   │   ├── exposure <= 95%?
   │   ├── drawdown < 20%?
   │   └── daily_loss < 5%?
   ├── PaperExecutionEngine.execute_signal()
   │   ├── Slippage: base + volume_impact + vol_premium
   │   ├── Commission: broker + exchange + BSMV
   │   ├── Liquidity constraint: qty <= ADV × 10%
   │   └── Execution price = market_price × (1 ± slippage)
   └── Portfolio update: open_position() / close_position()
       ↓
6. Performance: compute_daily_performance()
       ↓
7. State: portfolio.save_to_store(date)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Singleton | Kritik Sınıf/Fonksiyon |
|-------|-----------|-----------|------------------------|
| `paper_orchestrator.py` | Günlük otonom döngü, champion LOCKED, replay/backtest | `paper_orchestrator` | `PaperTradingOrchestrator.run_daily_cycle()`, `run_backtest_replay()` |
| `paper_execution.py` | Sanal execution: slippage, commission, likidite kısıtı | `paper_execution` | `PaperExecutionEngine.execute_signal()` |
| `paper_risk_gate.py` | 8 risk check, fail-closed, kill switch | `paper_risk_gate` | `PaperRiskGate.check_all()`, `is_trade_allowed()` |
| `performance_tracker.py` | Günlük + tam metrikler: CAGR, Sharpe, Sortino, Max DD, Win Rate | `performance_tracker` | `PerformanceTracker.compute_daily_performance()`, `compute_full_metrics()` |
| `virtual_portfolio.py` | Sanal portföy: cash, positions, trades, equity curve | `virtual_portfolio` | `VirtualPortfolio.open_position()`, `close_position()`, `update_prices()` |
| `state_store.py` | SQLite persistence: portfolio, positions, trades, orders, audit, performance | `paper_state_store` | `PaperStateStore.save_portfolio_state()`, `append_audit()` |
| `__init__.py` | Public API exports | — | Tüm singleton'lar |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Gerçek para YOK**: Bu modül sadece simülasyon. Gerçek broker/API bağlantısı yok.
2. **Champion LOCKED**: Sadece aktif champion modelin sinyalleri kullanılır. Challenger doğrudan giremez.
3. **Fail-safe, fail-closed**: Belirsiz durumda NO_TRADE. Sistem hiçbir koşulda işlem yapmak zorunda değil.
4. **Immutable audit**: Her olay (sinyal, order, risk check, performans) append-only log'a yazılır.
5. **Persistent state**: SQLite ile crash recovery. Program kapanıp açılsa bile veri korunur.
6. **Look-ahead bias yok**: Signal price ≠ execution price. Ertesi seans açılışında işlem.

### Kırmızı Çizgiler

- ❌ Champion modeli otomatik değiştirme
- ❌ Paper trading sonucunu model eğitimine doğrudan geri besleme
- ❌ Kill switch aktifken işlem yapma
- ❌ Data quality FAIL iken işlem yapma
- ❌ Audit log'dan kayıt silme
- ❌ Gerçek para/broker kullanma

## Bilinen Sınırlamalar

1. **Basit position sizing**: Equal weight (%10). Score-weighted veya Kelly-based sizing yok.
2. **Tek champion**: Aynı anda sadece bir champion model. A/B testing yok.
3. **Sabit slippage parametreleri**: `slippage_base_pct=0.05`, `slippage_max_pct=0.5`. Gerçek piyasa koşullarına göre dinamik değil.
4. **Replay modu**: Geçmiş veri üzerinde çalışır ama gerçek zamanlı veri akışı yok.
5. **SQLite sınırları**: Yüksek concurrency'de performans düşebilir. Production'da PostgreSQL tercih edilmeli.
6. **Audit hash SHA-256 (16 char)**: Kısaltılmış hash. Tam collision resistance yok.

## Cross-Referanslar

| Bu modül | İlişki | Diğer modül |
|----------|--------|-------------|
| `paper_trading/virtual_portfolio.py` | `Position` dataclass import | `portfolio/portfolio_manager.py` |
| `paper_trading/virtual_portfolio.py` | `Portfolio`, `Position` model import | `core/models.py` |
| `paper_trading/paper_orchestrator.py` | Champion sinyalleri ← ML ranking model | `services.ml.ranking_model` |
| `paper_trading/paper_orchestrator.py` | Champion version ← ModelRegistry | `services.learning.continuous_learning` |
| `paper_trading/paper_orchestrator.py` | Audit log ← `core.audit_log` | Core audit |
| `paper_trading/paper_execution.py` | `ORDER_FILLED` event publish | Core event_bus |
| `paper_trading/paper_risk_gate.py` | Risk limitleri ← risk modülü ile uyumlu | Risk modülü |
| `paper_trading/state_store.py` | SQLite persistence | — (bağımsız) |
| `portfolio/main.py` | Benzer muhasebe mantığı (farklı implementasyon) | Portfolio modülü |
| `simulation/execution_simulator.py` | Benzer execution mantığı (farklı implementasyon) | Simulation modülü |
