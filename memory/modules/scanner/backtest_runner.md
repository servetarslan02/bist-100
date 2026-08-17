# scanner/backtest_runner

**Dosya:** `services/scanner/backtest_runner.py`
**Satır:** 557

## Açıklama

ALPHA BIST — Scanner Backtest Runner v3.0

Production-grade performans optimizasyonu.

Optimizasyonlar:
- Feature'lar ticker bazında bir kez hesaplanır (vectorized)
- Data quality sonucu cache'lenir
- Ranking batch çalıştırılır
- Signal üretimi toplu yapılır
- Portfolio simulator iyileştirildi

Geçmiş versiyonla aynı finansal sonuçları üretir.

## Sınıflar (8)

- `BacktestTrade`
- `BacktestSignal`
- `DailySnapshot`
- `BacktestResult`
- `FeatureCache`
- `QualityCache`
- `PortfolioSimulator`
- `ScannerBacktestRunner`

## Fonksiyonlar (24)

- `to_dict()`
- `to_dict()`
- `to_dict()`
- `to_dict()`
- `__init__()`
- `get()`
- `set()`
- `invalidate()`
- `clear()`
- `__init__()`
- `get()`
- `set()`
- `clear()`
- `__init__()`
- `can_buy()`
- `execute_buy()`
- `execute_sell()`
- `update_equity()`
- `get_summary()`
- `__init__()`
- `run()`
- `_empty_result()`
- `_compute_score()`
- `_determine_signal()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/tradability_mask`
- `core/data_quality`
- `features/calculator`

