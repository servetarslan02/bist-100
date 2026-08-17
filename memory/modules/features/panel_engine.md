# features/panel_engine

**Dosya:** `services/features/panel_engine.py`
**Satır:** 364

## Açıklama

ALPHA BIST — Panel Feature Engine v1.0 (Vectorized / Batch)

Amaç:
    FeatureCalculator (scalar, mask-aware) ile BİREBİR AYNI sonuçları üreten,
    tek geçişli (single-pass) vektörize feature motoru.

Neden:
    Backtest engine v4.0 her (ticker, gün) çifti için feature'ları sıfırdan
    hesaplıyordu (FeatureCache tarih bazlı olduğu için hiç hit olmuyordu).
    Bu motor, skor hesaplamasında kullanılan feature'ları (rsi_14, momentum_20d,
    roc_5d, volume_zscore) her hisse için TÜM tarihlere tek

## Sınıflar (3)

- `TickerPanel`
- `PanelStore`
- `PanelFeatureEngine`

## Fonksiyonlar (8)

- `__init__()`
- `compute()`
- `features_at()`
- `_compute_ticker()`
- `_window_counts()`
- `_panel_ratio()`
- `_panel_rsi()`
- `_panel_volume_zscore()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/tradability_mask`

