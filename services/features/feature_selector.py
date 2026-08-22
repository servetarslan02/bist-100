"""
ALPHA BIST — Feature Selector v2.0

Feature seçme ve filtreleme:
- SHAP-based feature importance (importance_tracker ile entegre)
- Correlation-based filtering
- Variance threshold
- Recursive Feature Elimination (RFE)
- Feature ranking & scoring
- Auto-selection pipeline

FAZ 3: Feature Importance Tracking ile entegre
"""

import math
from typing import Dict, Any, List, Optional, Tuple
import structlog

logger = structlog.get_logger()


class FeatureSelector:
    """Feature seçme ve filtreleme v2.0.

    Kullanım:
        selector = FeatureSelector()

        # Korelasyon filtreleme
        X_filtered, names = selector.select_by_correlation(X, feature_names)

        # Varyans filtreleme
        X_filtered, names = selector.select_by_variance(X, names)

        # Importance-based selection
        selected = selector.select_by_importance(importance_snapshot, top_n=20)

        # Auto pipeline (tüm filtreleri sırayla uygula)
        X_final, names_final = selector.auto_select(X, feature_names, y)
    """

    def select_by_correlation(
        self,
        X: Any,  # np.ndarray or list of lists
        feature_names: List[str],
        threshold: float = 0.95,
    ) -> Tuple[Any, List[str]]:
        """Korelasyon-based feature filtreleme.

        Yüksek korelasyonlu feature'lardan birini kaldır.

        Args:
            X: Feature matrix (n_samples, n_features)
            feature_names: Feature isimleri
            threshold: Korelasyon eşiği (0-1)
        """
        n_features = len(feature_names)
        if hasattr(X, 'shape'):
            if X.shape[1] != n_features:
                raise ValueError("X columns and feature_names length must match")
            n_samples = X.shape[0]
        else:
            n_samples = len(X)

        # Korelasyon matrisi hesapla (pure Python fallback)
        corr_matrix = self._compute_correlation_matrix(X, n_features, n_samples)
        to_drop = set()

        for i in range(n_features):
            if i in to_drop:
                continue
            for j in range(i + 1, n_features):
                if j in to_drop:
                    continue
                if abs(corr_matrix[i][j]) > threshold:
                    # Daha düşük ortalama korelasyona sahip olanı tut
                    avg_corr_i = sum(abs(corr_matrix[i][k]) for k in range(n_features) if k != i) / max(n_features - 1, 1)
                    avg_corr_j = sum(abs(corr_matrix[j][k]) for k in range(n_features) if k != j) / max(n_features - 1, 1)
                    if avg_corr_i > avg_corr_j:
                        to_drop.add(i)
                    else:
                        to_drop.add(j)

        keep_indices = [i for i in range(n_features) if i not in to_drop]
        selected_names = [feature_names[i] for i in keep_indices]
        selected_X = self._select_columns(X, keep_indices)

        logger.info("Feature correlation filter",
                    original=n_features,
                    removed=len(to_drop),
                    remaining=len(selected_names))

        return selected_X, selected_names

    def select_by_variance(
        self,
        X: Any,
        feature_names: List[str],
        threshold: float = 0.01,
    ) -> Tuple[Any, List[str]]:
        """Variance-based feature filtreleme.

        Düşük varyanslı feature'ları kaldır.
        """
        variances = self._compute_variances(X, len(feature_names))
        keep_indices = [i for i in range(len(feature_names)) if variances[i] > threshold]
        selected_names = [feature_names[i] for i in keep_indices]
        selected_X = self._select_columns(X, keep_indices)

        logger.info("Feature variance filter",
                    original=len(feature_names),
                    removed=len(feature_names) - len(selected_names),
                    remaining=len(selected_names))

        return selected_X, selected_names

    def select_by_importance(
        self,
        importance_snapshot: Any,  # ImportanceSnapshot
        top_n: int = 20,
        min_importance: float = 0.005,
    ) -> List[str]:
        """Importance snapshot'tan en önemli feature'ları seç.

        Args:
            importance_snapshot: ImportanceSnapshot (importance_tracker'dan)
            top_n: Maksimum feature sayısı
            min_importance: Minimum importance eşiği

        Returns:
            Seçilen feature isimleri listesi
        """
        if not importance_snapshot or not hasattr(importance_snapshot, 'features'):
            return []

        selected = []
        for f in importance_snapshot.features:
            if len(selected) >= top_n:
                break
            if f.importance >= min_importance:
                selected.append(f.feature_name)

        logger.info("Feature importance selection",
                    total=importance_snapshot.total_features,
                    selected=len(selected),
                    concentration=importance_snapshot.top_10_concentration)

        return selected

    def rank_by_importance(
        self,
        importances: Any,  # np.ndarray or list
        feature_names: List[str],
        top_n: int = 20,
    ) -> List[Tuple[str, float]]:
        """Feature importance sıralaması.

        Args:
            importances: Feature importance değerleri
            feature_names: Feature isimleri
            top_n: İlk N feature
        """
        paired = list(zip(feature_names, importances))
        paired.sort(key=lambda x: abs(x[1]), reverse=True)
        return paired[:top_n]

    def select_low_vif(
        self,
        X: Any,
        feature_names: List[str],
        max_vif: float = 10.0,
    ) -> Tuple[Any, List[str]]:
        """VIF (Variance Inflation Factor) ile multicollinearity filtreleme.

        Yüksek VIF = çoklu doğrusal bağlantı problemi.
        """
        n_features = len(feature_names)
        keep_indices = list(range(n_features))

        # Iteratif olarak en yüksek VIF'li feature'ı kaldır
        while len(keep_indices) > 2:
            vifs = self._compute_vif(X, keep_indices, n_features)
            max_vif_val = max(vifs)
            if max_vif_val <= max_vif:
                break

            # En yüksek VIF'li feature'ı kaldır
            worst_idx = vifs.index(max_vif_val)
            removed = keep_indices[worst_idx]
            keep_indices.pop(worst_idx)

            logger.debug("VIF filter removed",
                        feature=feature_names[removed],
                        vif=round(max_vif_val, 2))

        selected_names = [feature_names[i] for i in keep_indices]
        selected_X = self._select_columns(X, keep_indices)

        logger.info("Feature VIF filter",
                    original=n_features,
                    remaining=len(selected_names),
                    max_vif=max_vif)

        return selected_X, selected_names

    def auto_select(
        self,
        X: Any,
        feature_names: List[str],
        y: Any = None,
        variance_threshold: float = 0.01,
        correlation_threshold: float = 0.95,
        max_features: int = 50,
    ) -> Tuple[Any, List[str]]:
        """Otomatik feature selection pipeline.

        Sırayla uygula:
        1. Variance filter (düşük varyanslıları kaldır)
        2. Correlation filter (yüksek korelasyonlu kaldır)
        3. Top N feature (max_features'a sınırla)

        Args:
            X: Feature matrix
            feature_names: Feature isimleri
            y: Target (opsiyonel, gelecekte SHAP için)
            variance_threshold: Varyans eşiği
            correlation_threshold: Korelasyon eşiği
            max_features: Maksimum feature sayısı

        Returns:
            (X_filtered, selected_names)
        """
        logger.info("Auto feature selection started",
                   initial_features=len(feature_names))

        # Step 1: Variance filter
        X_step1, names_step1 = self.select_by_variance(
            X, feature_names, variance_threshold
        )

        if not names_step1:
            logger.warning("All features removed by variance filter")
            return X, feature_names

        # Step 2: Correlation filter
        X_step2, names_step2 = self.select_by_correlation(
            X_step1, names_step1, correlation_threshold
        )

        if not names_step2:
            logger.warning("All features removed by correlation filter")
            return X_step1, names_step1

        # Step 3: Limit to max_features
        if len(names_step2) > max_features:
            # En yüksek varyansa sahip feature'ları tut
            variances = self._compute_variances(X_step2, len(names_step2))
            paired = list(zip(range(len(names_step2)), variances))
            paired.sort(key=lambda x: x[1], reverse=True)
            keep_indices = [p[0] for p in paired[:max_features]]
            keep_indices.sort()
            selected_names = [names_step2[i] for i in keep_indices]
            selected_X = self._select_columns(X_step2, keep_indices)
        else:
            selected_names = names_step2
            selected_X = X_step2

        logger.info("Auto feature selection completed",
                   initial=len(feature_names),
                   final=len(selected_names))

        return selected_X, selected_names

    # =====================================================
    # YARDIMCI FONKSİYONLAR
    # =====================================================

    @staticmethod
    def _compute_correlation_matrix(X: Any, n_features: int, n_samples: int) -> List[List[float]]:
        """Korelasyon matrisi hesapla (pure Python)."""
        # X'i list of lists'e çevir
        if hasattr(X, 'tolist'):
            data = X.tolist()
        elif isinstance(X, list):
            data = X
        else:
            data = [list(row) for row in X]

        # Her feature için mean hesapla
        means = []
        for j in range(n_features):
            col = [data[i][j] for i in range(n_samples) if data[i][j] == data[i][j]]  # NaN filter
            means.append(sum(col) / len(col) if col else 0)

        # Std hesapla
        stds = []
        for j in range(n_features):
            col = [data[i][j] for i in range(n_samples) if data[i][j] == data[i][j]]
            if len(col) > 1:
                var = sum((x - means[j]) ** 2 for x in col) / (len(col) - 1)
                stds.append(math.sqrt(var))
            else:
                stds.append(0)

        # Korelasyon matrisi
        corr = [[0.0] * n_features for _ in range(n_features)]
        for i in range(n_features):
            corr[i][i] = 1.0
            for j in range(i + 1, n_features):
                if stds[i] == 0 or stds[j] == 0:
                    corr[i][j] = 0.0
                else:
                    cov = sum(
                        (data[k][i] - means[i]) * (data[k][j] - means[j])
                        for k in range(n_samples)
                        if data[k][i] == data[k][i] and data[k][j] == data[k][j]
                    ) / max(n_samples - 1, 1)
                    corr[i][j] = cov / (stds[i] * stds[j])
                corr[j][i] = corr[i][j]

        return corr

    @staticmethod
    def _compute_variances(X: Any, n_features: int) -> List[float]:
        """Feature varyanslarını hesapla (pure Python)."""
        if hasattr(X, 'tolist'):
            data = X.tolist()
        elif isinstance(X, list):
            data = X
        else:
            data = [list(row) for row in X]

        n_samples = len(data)
        variances = []

        for j in range(n_features):
            col = [data[i][j] for i in range(n_samples) if data[i][j] == data[i][j]]
            if len(col) > 1:
                mean = sum(col) / len(col)
                var = sum((x - mean) ** 2 for x in col) / (len(col) - 1)
                variances.append(var)
            else:
                variances.append(0.0)

        return variances

    @staticmethod
    def _compute_vif(X: Any, keep_indices: List[int], n_features: int) -> List[float]:
        """VIF hesapla — korelasyon matrisinden aproximasyon.

        VIF_j = 1 / (1 - R²_j)
        R²_j: j. feature'ın diğer feature'lara karşı R²'si.
        """
        try:
            import numpy as np

            # X'i array'e çevir
            if hasattr(X, 'values'):
                data = X.values[:, keep_indices]
            elif hasattr(X, 'tolist'):
                data = np.array(X)[:, keep_indices]
            else:
                data = np.array([list(row) for row in X])[:, keep_indices]

            n_samples = data.shape[0]
            n_feats = len(keep_indices)

            if n_samples <= n_feats + 1:
                return [1.0] * n_feats

            # Korelasyon matrisi
            corr = np.corrcoef(data, rowvar=False)
            if corr.ndim < 2:
                return [1.0] * n_feats

            # VIF: 1 / (1 - R²)
            # R²_j ≈ 1 - 1/corr_jj (eğer korelasyon matrisi kullanılıyorsa)
            # Daha doğru: R²_j = 1 - 1/diag(C^{-1})_j  (C = korelasyon matrisi)
            try:
                inv_corr = np.linalg.inv(corr)
                vifs = [float(inv_corr[j, j]) for j in range(n_feats)]
                return [max(1.0, v) for v in vifs]
            except np.linalg.LinAlgError:
                # Singular matris — fallback
                return [1.0] * n_feats

        except Exception as e:
            return [1.0] * len(keep_indices)

    @staticmethod
    def _select_columns(X: Any, indices: List[int]) -> Any:
        """Sütun seç."""
        if hasattr(X, '__getitem__'):
            try:
                import numpy as np
                if isinstance(X, np.ndarray):
                    return X[:, indices]
            except ImportError:
                pass
            # DataFrame
            if hasattr(X, 'iloc'):
                return X.iloc[:, indices]
            # List of lists
            return [[row[i] for i in indices] for row in X]
        return X


# Singleton
feature_selector = FeatureSelector()
