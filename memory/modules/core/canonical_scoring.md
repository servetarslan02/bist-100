# core/canonical_scoring

**Dosya:** `services/core/canonical_scoring.py`
**Satır:** 741

## Açıklama

ALPHA BIST — Canonical Scoring Pipeline v1.0

TEK KARAR MİMARİSİ:
Tüm scoring mekanizmalarını tek bir canonical pipeline altında birleştirir.

EĞİTİM MİMARİSİ:
VERİ → FEATURE CONTRACT → 9 MOTOR → CROSS-SECTIONAL → CANONICAL SCORE → DECISION → RİSK → PORTFÖY

Bu modül:
- 9 motorun çıktısını tek bir ScoreVector'da birleştirir
- Eksik/STALE/MISSING veriyi 0'a çevirmez
- Risk ve opportunity'yi ayrı tutar
- Decision Engine'e yapılandırılmış girdi sağlar

## Sınıflar (3)

- `ScoreVector`
- `CanonicalScore`
- `CanonicalScoringPipeline`

## Fonksiyonlar (19)

- `to_dict()`
- `get_opportunity_dimensions()`
- `get_nonzero_count()`
- `compute_score_vector()`
- `compute_canonical_score()`
- `_score_technical()`
- `_score_momentum()`
- `_score_relative_strength()`
- `_score_volume()`
- `_score_fundamental()`
- `_score_news_sentiment()`
- `_score_catalyst()`
- `_score_mean_reversion()`
- `_score_seasonality()`
- `_score_regime_fit()`
- `_score_risk()`
- `_score_data_quality()`
- `_determine_direction()`
- `_s()`

