# Paper Trading

**Modül sayısı:** 7 | **Toplam satır:** ~2,068 | **Test sayısı:** 15

## Modüller

| Modül | Dosya | Sınıf/Fonksiyon | Açıklama |
|-------|-------|-----------------|----------|
| Paper Orchestrator | `paper_orchestrator.py` | PaperTradingOrchestrator | Günlük otonom döngü, champion LOCKED, replay/backtest |
| Paper Execution | `paper_execution.py` | PaperExecutionEngine | Sanal execution: slippage, commission, likidite kısıtı |
| Paper Risk Gate | `paper_risk_gate.py` | PaperRiskGate | 8 risk check, fail-closed, kill switch |
| Performance Tracker | `performance_tracker.py` | PerformanceTracker | Günlük + tam metrikler: CAGR, Sharpe, Sortino, Max DD, Win Rate |
| Virtual Portfolio | `virtual_portfolio.py` | VirtualPortfolio | Sanal portföy: cash, positions, trades, equity curve |
| State Store | `state_store.py` | PaperStateStore | SQLite persistence: portfolio, positions, trades, orders, audit, performance |
| Init | `__init__.py` | — | Public API exports, tüm singleton'lar |

## Spec Uyumu

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Champion LOCKED | ✅ TAM | Otomatik model değişikliği yok |
| Fail-closed risk gate | ✅ TAM | 8 check, herhangi biri BLOCK derse işlem olmaz |
| Signal ≠ execution price | ✅ TAM | Ertesi seans açılışında işlem |
| SQLite persistence | ✅ TAM | Atomic write (WAL mode) |
| Immutable audit log | ✅ TAM | SHA-256 hash ile bütünlük |
| Equal weight sizing | ✅ TAM | Her pozisyon %10 max |
| Kill switch | ✅ TAM | 3 ardışık hata → otomatik durdur |
| Realistic execution | ✅ TAM | Slippage + commission + BSMV + likidite kısıtı |

## Düzeltilen Sorunlar (2026-08-21)

1. **BUY bias düzeltmesi** — `max()` → güven-ağırlıklı ortalama
2. **Signal fusion yön belirleme** — `effective_weight = weight * (score/100)` → sadece `weight`
