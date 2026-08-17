# scanner/tiered_scanner

**Dosya:** `services/scanner/tiered_scanner.py`
**Satır:** 602

## Açıklama

ALPHA BIST — Katmanlı Tarama Motoru v1.0

800 hisseyi her saniye baştan analiz ETMEZ.
Katmanlı filtreleme: ucuz → pahalı → çok pahalı

Tier 0: Continuous Watch    → 800 hisse, çok ucuz state tracking
Tier 1: Quant Scan          → 800 hisse, matematiksel filtreler
Tier 2: Opportunity Engine  → 800 → 50, en ilginç hisseler
Tier 3: Deep Analysis       → 50 → 10, pahalı işlemler
Tier 4: Gemma               → 10 → 3-5, LLM reasoning
Tier 5: Decision            → 3-5 → 0-3, risk kontrollü karar

Haber

## Sınıflar (4)

- `Tier`
- `AssetTierState`
- `MarketRegime`
- `TieredScanner`

## Fonksiyonlar (22)

- `update_weights()`
- `__init__()`
- `register_asset()`
- `register_assets()`
- `process_tick()`
- `run_quant_scan()`
- `select_opportunities()`
- `run_deep_analysis()`
- `select_for_gemma()`
- `make_decisions()`
- `escalate_by_event()`
- `update_regime()`
- `_score_momentum()`
- `_score_volume_anomaly()`
- `_score_breakout()`
- `_score_volatility()`
- `_score_relative_strength()`
- `_score_sector_divergence()`
- `_score_flow_correlation()`
- `_score_liquidity()`
- `get_tier_summary()`
- `get_top_opportunities()`

