# ml/ranking_model

**Dosya:** `services/ml/ranking_model.py`
**Satır:** 532

## Açıklama

ALPHA BIST — Ranking Model v3.0 (LambdaRank + Adjusted-MSE + Rejim-Aware)

ROADMAP v3.0 FAZ 3:
- LightGBM LambdaRank (regresyon DEĞİL sıralama)
- Adjusted-MSE Loss (yanlış yön 11x ceza)
- Rejim-Aware Training (BULL/BEAR farklı ağırlıklar)
- Feature Importance Tracking (SHAP + Permutation)
- Ensemble (LightGBM + Rule-based fallback)

KURAL: "En iyi %10'da mı?" sor, "yükselir mi?" sorma!

## Sınıflar (3)

- `OpportunityScore`
- `RankingResult`
- `RankingModel`

## Fonksiyonlar (12)

- `__init__()`
- `train()`
- `rank()`
- `_prepare_training_data()`
- `_feature_vector()`
- `_apply_regime_weights()`
- `_scalar()`
- `_rule_based_score()`
- `_normalize_score()`
- `_compute_shap_importance()`
- `get_feature_importance()`
- `get_top_opportunities()`

