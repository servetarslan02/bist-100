# scanner/opportunity_engine

**Dosya:** `services/scanner/opportunity_engine.py`
**Satır:** 499

## Açıklama

ALPHA BIST — Opportunity Discovery Engine v1.0

BIST'in tamamından en güçlü fırsatları bulur:
- Candidate filtering (likidite, veri kalitesi)
- Technical filter (momentum, trend, breakout)
- Fundamental filter (değerleme, kalite, büyüme)
- Macro compatibility (rejim uyumu)
- Sentiment (haber, KAP, sosyal)
- AI evidence (agent sonuçları)
- Risk filter (volatilite, korelasyon)
- Opportunity score (risk-adjusted)
- Ranking

FAZ 8: Opportunity Discovery Engine

## Sınıflar (2)

- `OpportunityScore`
- `OpportunityDiscoveryEngine`

## Fonksiyonlar (12)

- `compute_opportunity_score()`
- `_compute_technical_score()`
- `_compute_momentum_score()`
- `_compute_volume_score()`
- `_compute_volatility_score()`
- `_compute_regime_fit()`
- `_compute_risk_score()`
- `_determine_signal()`
- `_generate_evidence()`
- `_generate_risks()`
- `scan_universe()`
- `get_top_opportunities()`

