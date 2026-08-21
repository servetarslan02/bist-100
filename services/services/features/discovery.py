"""
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
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class DiscoveredFeature:
    """Keşfedilen feature."""
    name: str
    formula: str
    category: str  # interaction, ratio, difference, lag
    source_features: List[str]
    importance_score: float = 0.0
    stability_score: float = 0.0
    leakage_risk: float = 0.0
    selected: bool = False


class FeatureDiscoveryEngine:
    """Feature discovery pipeline.

    1. Raw features → interaction generation
    2. Candidate filtering
    3. Feature selection
    """

    def generate_interactions(
        self,
        features: Dict[str, List[float]],
        max_interactions: int = 500,
        top_k_for_interactions: int = 30,
    ) -> List[DiscoveredFeature]:
        """Feature interaction'ları üret — akıllı filtreleme ile.

        Matematiksel yaklaşım:
        1. Tüm feature'lar için lag features (düşük maliyet)
        2. Varyans filtreleme → düşük varyanslı feature'ları ele
        3. Sadece en önemli top-K feature için pairwise interaction üret
        4. Top-K ile O(K²) = O(900) — O(N²) = O(4950) yerine

        Args:
            features: {"rsi_14": [50, 55, 60, ...], ...}
            max_interactions: Maksimum toplam candidate
            top_k_for_interactions: Interaction için kullanılacak top feature sayısı
        """
        discovered = []
        feature_names = list(features.keys())
        n = len(feature_names)

        if n == 0:
            return discovered

        # ━━━ STEP 1: Lag features (tüm feature'lar için — düşük maliyet) ━━━
        for f in feature_names:
            for lag in [1, 2, 5]:
                discovered.append(DiscoveredFeature(
                    name=f"{f}_lag{lag}",
                    formula=f"{f}[t-{lag}]",
                    category="lag",
                    source_features=[f],
                ))

        # ━━━ STEP 2: Varyans filtreleme ━━━
        variances = {}
        for name, values in features.items():
            if len(values) > 1:
                v = np.array(values, dtype=float)
                v = v[~np.isnan(v)]
                if len(v) > 1:
                    variances[name] = float(np.var(v))

        if not variances:
            logger.info("No valid features for interaction generation")
            return discovered

        # Varyansa göre sırala (yüksek varyans = daha bilgilendirici)
        sorted_by_var = sorted(variances.items(), key=lambda x: x[1], reverse=True)

        # Sıfır/aşırı düşük varyanslı feature'ları ele
        median_var = np.median([v for _, v in sorted_by_var])
        valid_features = [
            name for name, var in sorted_by_var
            if var > median_var * 0.01  # Median'ın %1'inden yüksek varyans
        ]

        # ━━━ STEP 3: Top-K feature seç (varyansa göre) ━━━
        top_k = valid_features[:top_k_for_interactions]

        logger.info(
            "Interaction generation: variance filter",
            total=n,
            valid=len(valid_features),
            top_k=len(top_k),
        )

        # ━━━ STEP 4: Pairwise interactions (sadece top-K için) ━━━
        # Products: C(K, 2) = K*(K-1)/2
        for i in range(len(top_k)):
            for j in range(i + 1, len(top_k)):
                f1, f2 = top_k[i], top_k[j]
                discovered.append(DiscoveredFeature(
                    name=f"{f1}_x_{f2}",
                    formula=f"{f1} * {f2}",
                    category="interaction",
                    source_features=[f1, f2],
                ))

        # Ratios: sadece top-K'in ilk 15'i arası (daha agresif filtre)
        ratio_k = min(15, len(top_k))
        for i in range(ratio_k):
            for j in range(ratio_k):
                if i != j:
                    f1, f2 = top_k[i], top_k[j]
                    discovered.append(DiscoveredFeature(
                        name=f"{f1}_div_{f2}",
                        formula=f"{f1} / {f2}",
                        category="ratio",
                        source_features=[f1, f2],
                    ))

        # Differences: sadece top-K'in ilk 10'u arası
        diff_k = min(10, len(top_k))
        for i in range(diff_k):
            for j in range(i + 1, diff_k):
                f1, f2 = top_k[i], top_k[j]
                discovered.append(DiscoveredFeature(
                    name=f"{f1}_minus_{f2}",
                    formula=f"{f1} - {f2}",
                    category="difference",
                    source_features=[f1, f2],
                ))

        # ━━━ STEP 5: Hard cap ━━━
        if len(discovered) > max_interactions:
            # Lag'leri koru, interaction'ları kırp
            lags = [d for d in discovered if d.category == "lag"]
            others = [d for d in discovered if d.category != "lag"]
            remaining = max_interactions - len(lags)
            discovered = lags + others[:max(0, remaining)]

        logger.info(
            "Feature interactions generated",
            total=len(discovered),
            lags=sum(1 for d in discovered if d.category == "lag"),
            interactions=sum(1 for d in discovered if d.category == "interaction"),
            ratios=sum(1 for d in discovered if d.category == "ratio"),
            differences=sum(1 for d in discovered if d.category == "difference"),
        )
        return discovered

    def compute_interaction_values(
        self,
        features: Dict[str, List[float]],
        discovered: List[DiscoveredFeature],
    ) -> Dict[str, List[float]]:
        """Interaction feature'ların değerlerini hesapla."""
        result = {}

        for feat in discovered:
            if feat.category == "interaction" and len(feat.source_features) == 2:
                f1, f2 = feat.source_features
                v1 = features.get(f1, [])
                v2 = features.get(f2, [])
                if len(v1) == len(v2) and len(v1) > 0:
                    result[feat.name] = [a * b for a, b in zip(v1, v2)]

            elif feat.category == "ratio" and len(feat.source_features) == 2:
                f1, f2 = feat.source_features
                v1 = features.get(f1, [])
                v2 = features.get(f2, [])
                if len(v1) == len(v2) and len(v1) > 0:
                    result[feat.name] = [a / b if abs(b) > 1e-10 else 0 for a, b in zip(v1, v2)]

            elif feat.category == "difference" and len(feat.source_features) == 2:
                f1, f2 = feat.source_features
                v1 = features.get(f1, [])
                v2 = features.get(f2, [])
                if len(v1) == len(v2) and len(v1) > 0:
                    result[feat.name] = [a - b for a, b in zip(v1, v2)]

            elif feat.category == "lag" and len(feat.source_features) == 1:
                f = feat.source_features[0]
                v = features.get(f, [])
                lag = int(feat.name.split("_lag")[-1])
                if len(v) > lag:
                    result[feat.name] = [0] * lag + v[:-lag]

        return result

    def filter_by_correlation(
        self,
        features: Dict[str, List[float]],
        target: List[float],
        max_features: int = 100,
        correlation_threshold: float = 0.95,
    ) -> List[str]:
        """Korelasyon filtreleme.

        1. Target ile yüksek korelasyonlu feature'ları seç
        2. Kendi aralarında yüksek korelasyonlu olanları ele
        """
        if not target:
            return list(features.keys())[:max_features]

        # Target ile korelasyon
        correlations = {}
        for name, values in features.items():
            if len(values) == len(target) and len(values) > 2:
                corr = abs(np.corrcoef(values, target)[0, 1])
                if not np.isnan(corr):
                    correlations[name] = corr

        # Target'a göre sırala
        sorted_features = sorted(correlations.items(), key=lambda x: x[1], reverse=True)

        # Kendi aralarında yüksek korelasyonlu olanları ele
        selected = []
        selected_values = []

        for name, corr in sorted_features:
            if len(selected) >= max_features:
                break

            values = features[name]
            is_redundant = False

            for sel_values in selected_values:
                if len(values) == len(sel_values):
                    inter_corr = abs(np.corrcoef(values, sel_values)[0, 1])
                    if not np.isnan(inter_corr) and inter_corr > correlation_threshold:
                        is_redundant = True
                        break

            if not is_redundant:
                selected.append(name)
                selected_values.append(values)

        logger.info("Correlation filtering", input=len(features), output=len(selected))
        return selected

    def compute_mutual_information(
        self,
        features: Dict[str, List[float]],
        target: List[float],
        n_bins: int = 10,
    ) -> Dict[str, float]:
        """Mutual Information hesapla (basitleştirilmiş)."""
        mi_scores = {}

        for name, values in features.items():
            if len(values) != len(target) or len(values) < 10:
                continue

            # Discretize
            v = np.array(values)
            t = np.array(target)

            v_bins = np.digitize(v, np.percentile(v, np.linspace(0, 100, n_bins + 1)[1:-1]))
            t_bins = np.digitize(t, np.percentile(t, np.linspace(0, 100, n_bins + 1)[1:-1]))

            # Joint probability
            joint = np.zeros((n_bins, n_bins))
            for vb, tb in zip(v_bins, t_bins):
                joint[min(vb, n_bins-1), min(tb, n_bins-1)] += 1
            joint /= joint.sum()

            # Marginal probabilities
            p_v = joint.sum(axis=1)
            p_t = joint.sum(axis=0)

            # MI
            mi = 0
            for i in range(n_bins):
                for j in range(n_bins):
                    if joint[i, j] > 0 and p_v[i] > 0 and p_t[j] > 0:
                        mi += joint[i, j] * np.log2(joint[i, j] / (p_v[i] * p_t[j]))

            mi_scores[name] = max(0, mi)

        return mi_scores

    def detect_leakage(
        self,
        features: Dict[str, List[float]],
        target: List[float],
        threshold: float = 0.99,
    ) -> List[str]:
        """Feature leakage tespiti.

        Eğer bir feature target ile neredeyse mükemmel korelasyona sahipse,
        gelecek bilgisi sızıntısı olabilir.
        """
        leaked = []
        for name, values in features.items():
            if len(values) == len(target) and len(values) > 2:
                corr = abs(np.corrcoef(values, target)[0, 1])
                if not np.isnan(corr) and corr > threshold:
                    leaked.append(name)
                    logger.warning("Potential feature leakage detected", feature=name, correlation=corr)
        return leaked

    def run_discovery(
        self,
        raw_features: Dict[str, List[float]],
        target: List[float],
        max_features: int = 100,
    ) -> Tuple[List[DiscoveredFeature], Dict[str, float]]:
        """Tam feature discovery pipeline.

        1. Generate interactions
        2. Compute values
        3. Filter by correlation
        4. Compute MI
        5. Detect leakage
        6. Select top features
        """
        # 1. Generate interactions
        discovered = self.generate_interactions(raw_features)

        # 2. Compute interaction values
        interaction_values = self.compute_interaction_values(raw_features, discovered)

        # 3. Merge raw + interaction features
        all_features = {**raw_features, **interaction_values}

        # 4. Filter by correlation
        selected_names = self.filter_by_correlation(all_features, target, max_features)

        # 5. Compute MI
        selected_features = {k: v for k, v in all_features.items() if k in selected_names}
        mi_scores = self.compute_mutual_information(selected_features, target)

        # 6. Detect leakage
        leaked = self.detect_leakage(selected_features, target)

        # 7. Update discovered features
        for feat in discovered:
            if feat.name in selected_names and feat.name not in leaked:
                feat.selected = True
                feat.importance_score = mi_scores.get(feat.name, 0)

        # 8. Add raw features
        for name in raw_features:
            if name in selected_names and name not in leaked:
                discovered.append(DiscoveredFeature(
                    name=name, formula=name, category="raw",
                    source_features=[name],
                    importance_score=mi_scores.get(name, 0),
                    selected=True,
                ))

        selected_count = sum(1 for f in discovered if f.selected)
        logger.info("Feature discovery completed",
                   generated=len(discovered),
                   selected=selected_count,
                   leaked=len(leaked))

        return discovered, mi_scores


# Singleton
feature_discovery_engine = FeatureDiscoveryEngine()
