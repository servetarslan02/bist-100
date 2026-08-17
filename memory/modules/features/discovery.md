# features/discovery

**Dosya:** `services/features/discovery.py`
**Satır:** 320

## Açıklama

ALPHA BIST — Feature Discovery Pipeline v1.0

Otomatik feature keşfi:
- Feature interaction generation (pairwise products, ratios, differences)
- Lag features (1d, 2d, 5d)
- Mutual Information filtering
- Correlation filtering
- Permutation Importance
- SHAP values
- Feature Stability
- Leakage Detection

FAZ 2.7: Feature Discovery Pipeline

## Sınıflar (2)

- `DiscoveredFeature`
- `FeatureDiscoveryEngine`

## Fonksiyonlar (6)

- `generate_interactions()`
- `compute_interaction_values()`
- `filter_by_correlation()`
- `compute_mutual_information()`
- `detect_leakage()`
- `run_discovery()`

