# PORTFOLİO — Portfolio Management System

## Giriş

Portfolio modülü, ALPHA BIST'in **kurumsal seviye portföy muhasebe ve yönetim katmanıdır**. Sistemin "gerçek para" ile ilgilenen tek modülüdür — diğer modüller (paper trading, simulation) sanal portföyler kullanır.

Modülün temel sorumluluğu: pozisyon açma/kapama, weighted average cost bazlı muhasebe, realized/unrealized P&L takibi, komisyon muhasebesi, equity curve snapshots, drawdown tracking ve rebalancing. v2.0 ile birlikte DB-backed persistence, atomic operations ve coordinated locking eklenmiştir.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                   main.py — PortfolioService                    │
│  (Async DB-backed, coordinated lock, config watcher)            │
│  start() → _load_state() → execute_buy/sell() → _persist_*()   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            portfolio_manager.py — PortfolioManager        │   │
│  │                                                          │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐  │   │
│  │  │ Position     │ │ Trade        │ │ CashLedgerEntry  │  │   │
│  │  │ (dataclass)  │ │ (dataclass)  │ │ (dataclass)      │  │   │
│  │  └─────────────┘ └──────────────┘ └──────────────────┘  │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐  │   │
│  │  │ EquitySnapshot│ PositionHistory│ CommissionModel  │  │   │
│  │  │ (dataclass)  │ │ (dataclass)  │ │ (BIST fees)      │  │   │
│  │  └─────────────┘ └──────────────┘ └──────────────────┘  │   │
│  │                                                          │   │
│  │  open_position()  close_position()  _reduce_position()   │   │
│  │  update_prices()  check_rebalance() compute_rebalance()  │   │
│  │  get_portfolio()  get_metrics()     get_risk_metrics()    │   │
│  │  get_accounting_summary()  execute_auto_rebalance()      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            enhancements.py — Ek Servisler                 │   │
│  │                                                          │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │   │
│  │  │ TaxModel      │ │ Dividend     │ │ BenchmarkEngine  │ │   │
│  │  │ (stopaj,BSMV, │ │ Handler      │ │ (alpha, beta,    │ │   │
│  │  │  wash sale)   │ │ (temettü)    │ │  tracking error) │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │   │
│  │  │ Performance  │ │ MultiCurrency│ │ TransactionCost  │ │   │
│  │  │ Attribution  │ │ Handler      │ │ Analyzer (TCA)   │ │   │
│  │  │ (Brinson +   │ │ (TRY/USD/EUR)│ │ (spread,slippage,│ │   │
│  │  │  Factor)     │ │              │ │  market impact)  │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Weighted average cost basis** | Aynı hisseyi farklı fiyatlardan aldığında maliyet doğru hesaplanmalı. FIFO/LIFO yerine WAC daha basit ve BIST'te yaygın. |
| **Komisyon ayrı tutulma** | Entry commission pozisyona eklenir, realized P&L'den düşülür. Bu sayede gerçek net kar/zarar görünür. |
| **EQUITY = CASH + MARKET_VALUE invariant** | Her kritik işlem sonrası doğrulanır. İhlal varsa RuntimeError fırlatılır. Muhasebe tutarlılığı garanti. |
| **Coordinated lock (asyncio + DB)** | Aynı anda tek alım/satım işlemi. Multi-instance deployment'da bile race condition olmaz. |
| **Günlük equity snapshot** | Her gün bir kez equity kaydedilir. Drawdown, CAGR, Sharpe gibi metrikler için gerekli. |
| **Cash ledger (append-only)** | Nakit hareketleri silinemez, sadece eklenir. Audit trail için kritik. |
| **Position history (audit trail)** | Her pozisyon değişikliği (OPEN, ADD, REDUCE, CLOSE) kaydedilir. avg_cost_before/after, quantity_before/after. |
| **Config watcher** | `alpha_config.json` değiştiğinde otomatik reload. Servis restart gerektirmez. |
| **Auto-rebalance (score-weighted)** | Kelly kriteri + yüksek skorlu BİST liderleri. Score 90+ → %7-8, Score 75-80 → %4-5. |

## Uçtan Uca Veri Akışı

```
1. Alım Sinyali Gelir
       ↓
2. PortfolioService.execute_buy(ticker, quantity, price)
       ↓
3. CoordinatedLock.acquire() — tek işlem garantisi
       ↓
4. _execute_buy_atomic():
   ├── Cash kontrolü (in-memory + DB)
   ├── PortfolioManager.open_position()
   │   ├── Weighted average cost hesapla
   │   ├── Cash düş
   │   ├── Commission hesapla (BIST modeli)
   │   ├── Position history kaydet
   │   └── Cash ledger kaydet
   ├── _persist_buy() → DB'ye yaz
   │   ├── portfolios.cash_balance güncelle
   │   ├── positions tablosu (INSERT/UPDATE)
   │   ├── cash_ledger INSERT
   │   └── position_history INSERT
   └── _verify_invariant() → EQUITY = CASH + MV
       ↓
5. CoordinatedLock.release()
       ↓
6. update_prices() → equity snapshot (günlük)
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Singleton | Kritik Sınıf/Fonksiyon |
|-------|-----------|-----------|------------------------|
| `main.py` | Async DB-backed servis, coordinated lock, config watcher, state load/save | `portfolio_service` | `PortfolioService.execute_buy()`, `execute_sell()`, `_load_state()` |
| `portfolio_manager.py` | Kurumsal muhasebe: WAC, P&L, cash ledger, equity curve, rebalancing | `portfolio_manager` | `PortfolioManager.open_position()`, `close_position()`, `get_accounting_summary()` |
| `enhancements.py` | Vergi, temettü, benchmark, attribüsyon, çoklu para birimi, TCA | `tax_model`, `dividend_handler`, `benchmark_engine`, `performance_attribution`, `multi_currency`, `tca` | `TaxModel`, `BenchmarkEngine.compare()`, `PerformanceAttribution.decompose()` |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Invariant koruma**: `EQUITY = CASH + MARKET_VALUE` her işlem sonrası doğrulanır. İhlal = RuntimeError.
2. **Atomic operations**: Her kritik işlem lock altında. Multi-instance'da bile race condition yok.
3. **Audit trail**: Cash ledger ve position history append-only. Silinemez.
4. **Geriye uyumluluk**: v1.0 API'leri %100 korunur. v2.0 yeni alanlar ekler ama mevcut bozmaz.
5. **Memory safety**: `MAX_TRADES=10000`, `MAX_CASH_LEDGER=50000`, `MAX_EQUITY_CURVE=5000` sınırları.
6. **DB-first**: Tek gerçek muhasebe kaynağı DB. In-memory state DB ile senkronize.

### Kırmızı Çizgiler

- ❌ Invariant ihlalinde işlemi devam ettirme
- ❌ Lock olmadan pozisyon açma/kapama
- ❌ Cash ledger'dan kayıt silme
- ❌ Negatif cash'e izin verme (margin trading yok)
- ❌ Oversell'e izin verme (DB atomic check)
- ❌ Komisyon hesaplamadan işlem yapma

## Bilinen Sınırlamalar

1. **Sadece LONG pozisyon**: SHORT pozisyon desteği var ama `_reduce_position()` ile sınırlı. Tam short selling implementasyonu yok.
2. **Tek portföy**: `_portfolio_id` tek bir portföyü işaret eder. Multi-portfolio desteği yok.
3. **In-memory + DB senkronizasyonu**: `_pm._positions` ve DB arasında tutarsızlık olabilir (crash durumunda). `_load_state()` ile restore edilir.
4. **Config watcher polling**: 5 saniyede bir dosya değişikliği kontrolü. Gerçek zamanlı değil.
5. **Auto-rebalance sabit sinyaller**: `execute_auto_rebalance()` sinyal verilmezse hardcoded THYAO, ASELS, GARAN vb. kullanır.
6. **TCA modeli basit**: Square root market impact modeli var ama gerçek order book verisi yok.

## Cross-Referanslar

| Bu modül | İlişki | Diğer modül |
|----------|--------|-------------|
| `portfolio/main.py` | `dev_db` → SQLite/PostgreSQL | Core database_dev |
| `portfolio/main.py` | `CoordinatedLock` → `core.db_lock` | Core db_lock |
| `portfolio/main.py` | `ConfigWatcher` → `core.config_watcher` | Core config_watcher |
| `portfolio/portfolio_manager.py` | `get_risk_metrics()` → `risk.var_cvar.var_calculator` | Risk modülü |
| `portfolio/portfolio_manager.py` | `execute_auto_rebalance()` → `core.holy_grail_strategy` | Core strategy |
| `portfolio/enhancements.py` | `TaxModel` → BIST vergi yapısı | — |
| `portfolio/enhancements.py` | `BenchmarkEngine` → XU100 karşılaştırma | — |
| `paper_trading/virtual_portfolio.py` | `Position` dataclass import | Portfolio modülü |
| `risk/main.py` | Portföy verisi okur (`portfolios` tablosu) | Portfolio DB |
