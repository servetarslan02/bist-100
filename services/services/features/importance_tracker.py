"""
ALPHA BIST — Feature Importance Tracker v1.0

Feature önem takibi ve seçimi:
- SHAP-based importance (model-agnostic)
- Model native importance (feature_importances_)
- Recursive Feature Elimination (RFE)
- Importance history tracking
- Importance concentration analysis
- Feature ranking & selection

Kaynaklar:
- SHAP (Lundberg & Lee, 2017)
- arXiv SHAP-Based RFE (2025)
- SciOpen Hybrid Feature Selection (2025)

FAZ 3: Feature Importance Tracking
"""

import json
import math
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


# =====================================================
# Data Classes
# =====================================================

@dataclass
class FeatureImportance:
    """Tek bir feature'ın importance bilgisi."""
    feature_name: str
    importance: float           # Normalize edilmiş importance (0-1)
    rank: int                   # Sıralama (1=en önemli)
    method: str                 # "shap", "native", "permutation"
    confidence: float = 1.0     # Importance güvenilirliği
    direction: str = "neutral"  # "positive" (pozitif etki), "negative", "neutral"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature_name,
            "importance": round(self.importance, 6),
            "rank": self.rank,
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "direction": self.direction,
        }


@dataclass
class ImportanceSnapshot:
    """Belirli bir zamandaki importance snapshot'ı."""
    timestamp: str
    ticker: str
    model_name: str
    method: str
    features: List[FeatureImportance]
    total_features: int
    top_10_concentration: float  # İlk 10 feature'ın toplam importance'ı
    gini_coefficient: float      # Importance dağılım eşitsizliği

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "ticker": self.ticker,
            "model_name": self.model_name,
            "method": self.method,
            "total_features": self.total_features,
            "top_10_concentration": round(self.top_10_concentration, 4),
            "gini_coefficient": round(self.gini_coefficient, 4),
            "top_features": [f.to_dict() for f in self.features[:20]],
        }


@dataclass
class RFEResult:
    """Recursive Feature Elimination sonucu."""
    selected_features: List[str]
    eliminated_features: List[str]
    ranking: List[Tuple[str, int]]  # (feature, rank)
    n_selected: int
    scores_per_step: List[float]    # Her adımda model skoru

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_features": self.selected_features,
            "eliminated_features": self.eliminated_features,
            "n_selected": self.n_selected,
            "ranking": [{"feature": f, "rank": r} for f, r in self.ranking],
            "scores_per_step": [round(s, 4) for s in self.scores_per_step],
        }


@dataclass
class ImportanceDrift:
    """Feature importance değişimi (zaman içinde)."""
    feature_name: str
    importance_trend: str         # "increasing", "decreasing", "stable"
    current_importance: float
    previous_importance: float
    change_pct: float             # Yüzde değişim
    is_significant: bool          # Anlamlı değişim mi?

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature_name,
            "trend": self.importance_trend,
            "current": round(self.current_importance, 6),
            "previous": round(self.previous_importance, 6),
            "change_pct": round(self.change_pct, 2),
            "significant": self.is_significant,
        }


# =====================================================
# Importance Tracker
# =====================================================

class FeatureImportanceTracker:
    """Feature importance takip motoru.

    Kullanım:
        tracker = FeatureImportanceTracker()

        # SHAP ile importance hesapla
        snapshot = tracker.compute_shap(model, X, feature_names, ticker="THYAO")

        # Native importance
        snapshot = tracker.compute_native(model, feature_names, ticker="THYAO")

        # RFE ile feature seçimi
        rfe_result = tracker.recursive_feature_elimination(model, X, y, feature_names)

        # Importance değişimini takip
        drifts = tracker.detect_importance_drift("THYAO")
    """

    def __init__(
        self,
        max_history_per_ticker: int = 100,
        significant_change_pct: float = 20.0,  # %20+ değişim anlamlı
    ):
        self._history: Dict[str, List[ImportanceSnapshot]] = {}
        self._max_history = max_history_per_ticker
        self._significant_change = significant_change_pct

    # =====================================================
    # SHAP-BASED IMPORTANCE
    # =====================================================

    def compute_shap(
        self,
        model: Any,
        X: Any,  # np.ndarray or DataFrame
        feature_names: List[str],
        ticker: str = "",
        model_name: str = "unknown",
        sample_size: int = 500,
    ) -> ImportanceSnapshot:
        """SHAP ile feature importance hesapla.

        Args:
            model: Eğitilmiş model (tree-based veya linear)
            X: Feature matrix
            feature_names: Feature isimleri
            ticker: Hisse kodu
            model_name: Model adı
            sample_size: SHAP için örneklem boyutu

        Returns:
            ImportanceSnapshot
        """
        try:
            import shap

            # Örnekleme (büyük dataset için)
            if hasattr(X, 'shape') and X.shape[0] > sample_size:
                import numpy as np
                indices = np.random.choice(X.shape[0], sample_size, replace=False)
                X_sample = X[indices] if hasattr(X, '__getitem__') else X.iloc[indices]
            else:
                X_sample = X

            # Explainer seçimi
            model_type = type(model).__name__.lower()
            if any(t in model_type for t in ['forest', 'tree', 'gradient', 'xgb', 'lgb']):
                explainer = shap.TreeExplainer(model)
            else:
                explainer = shap.LinearExplainer(model, X_sample)

            shap_values = explainer.shap_values(X_sample)

            # Mean absolute SHAP values
            if isinstance(shap_values, list):
                # Multi-class: ortalama
                import numpy as np
                importance_values = np.abs(shap_values).mean(axis=0).mean(axis=1) if shap_values[0].ndim > 1 else np.abs(shap_values).mean(axis=0)
            else:
                import numpy as np
                importance_values = np.abs(shap_values).mean(axis=0)

            # Normalize
            total = importance_values.sum()
            if total > 0:
                importance_values = importance_values / total

            snapshot = self._create_snapshot(
                ticker=ticker,
                model_name=model_name,
                method="shap",
                feature_names=feature_names,
                importance_values=importance_values.tolist() if hasattr(importance_values, 'tolist') else list(importance_values),
            )

            self._store_snapshot(ticker, snapshot)
            return snapshot

        except ImportError:
            logger.warning("SHAP not installed, falling back to native importance")
            return self.compute_native(model, feature_names, ticker, model_name)
        except Exception as e:
            logger.warning("SHAP computation failed", error=str(e))
            return self.compute_native(model, feature_names, ticker, model_name)

    # =====================================================
    # NATIVE IMPORTANCE
    # =====================================================

    def compute_native(
        self,
        model: Any,
        feature_names: List[str],
        ticker: str = "",
        model_name: str = "unknown",
    ) -> ImportanceSnapshot:
        """Model native feature importance (feature_importances_).

        LightGBM, XGBoost, RandomForest, sklearn modelleri için çalışır.
        """
        importance_values = None

        # Farklı model tiplerinden importance al
        if hasattr(model, 'feature_importances_'):
            importance_values = model.feature_importances_
        elif hasattr(model, 'coef_'):
            import numpy as np
            importance_values = np.abs(model.coef_).flatten()
        elif hasattr(model, 'get_booster'):
            # XGBoost
            imp = model.get_booster().get_score(importance_type='gain')
            importance_values = [
                imp.get(f, 0.0) for f in feature_names
            ]
        elif hasattr(model, 'feature_name'):
            # LightGBM
            importance_values = model.feature_importances_

        if importance_values is None:
            logger.warning("Cannot extract native importance, using uniform")
            importance_values = [1.0 / len(feature_names)] * len(feature_names)

        # Normalize
        total = sum(importance_values)
        if total > 0:
            importance_values = [v / total for v in importance_values]

        snapshot = self._create_snapshot(
            ticker=ticker,
            model_name=model_name,
            method="native",
            feature_names=feature_names,
            importance_values=list(importance_values),
        )

        self._store_snapshot(ticker, snapshot)
        return snapshot

    # =====================================================
    # RECURSIVE FEATURE ELIMINATION (RFE)
    # =====================================================

    def recursive_feature_elimination(
        self,
        model_factory: Callable,  # () -> model
        X: Any,
        y: Any,
        feature_names: List[str],
        min_features: int = 10,
        step: int = 5,
        scoring_fn: Optional[Callable] = None,
    ) -> RFEResult:
        """Recursive Feature Elimination.

        Her adımda en az önemli feature'ları kaldır, modeli yeniden eğit.

        Args:
            model_factory: Yeni model üreten fonksiyon
            X: Feature matrix
            y: Target
            feature_names: Feature isimleri
            min_features: Minimum feature sayısı
            step: Her adımda kaldırılacak feature sayısı
            scoring_fn: Skor fonksiyonu (model, X, y) -> float

        Returns:
            RFEResult
        """
        import numpy as np

        current_features = list(feature_names)
        current_X = X.copy() if hasattr(X, 'copy') else X
        eliminated = []
        scores = []
        ranking = {}

        iteration = 0
        while len(current_features) > min_features:
            iteration += 1

            # Model eğit
            model = model_factory()
            if hasattr(current_X, 'values'):
                model.fit(current_X.values, y)
            else:
                model.fit(current_X, y)

            # Skor hesapla
            if scoring_fn:
                score = scoring_fn(model, current_X, y)
            else:
                score = model.score(
                    current_X.values if hasattr(current_X, 'values') else current_X,
                    y,
                )
            scores.append(score)

            # Importance al
            if hasattr(model, 'feature_importances_'):
                importances = model.feature_importances_
            elif hasattr(model, 'coef_'):
                importances = np.abs(model.coef_).flatten()
            else:
                break

            # En az önemli feature'ları bul
            paired = list(zip(current_features, importances))
            paired.sort(key=lambda x: x[1])

            # En düşük importance'a sahip feature'ları kaldır
            n_remove = min(step, len(current_features) - min_features)
            to_remove = [f for f, _ in paired[:n_remove]]

            for f in to_remove:
                eliminated.append(f)
                ranking[f] = len(feature_names) - len(eliminated) + 1

                # X'den kaldır
                if hasattr(current_X, 'drop'):
                    current_X = current_X.drop(columns=[f])
                else:
                    idx = current_features.index(f)
                    current_X = np.delete(current_X, idx, axis=1)

                current_features.remove(f)

        # Kalan feature'lar en yüksek rank
        for f in current_features:
            ranking[f] = 1

        result = RFEResult(
            selected_features=current_features,
            eliminated_features=eliminated,
            ranking=sorted(ranking.items(), key=lambda x: x[1]),
            n_selected=len(current_features),
            scores_per_step=scores,
        )

        logger.info(
            "RFE completed",
            selected=len(current_features),
            eliminated=len(eliminated),
            final_score=scores[-1] if scores else 0,
        )

        return result

    # =====================================================
    # IMPORTANCE DRIFT DETECTION
    # =====================================================

    def detect_importance_drift(
        self,
        ticker: str,
        min_snapshots: int = 2,
    ) -> List[ImportanceDrift]:
        """Feature importance değişimini tespit et.

        Son iki snapshot arasındaki farkı analiz eder.
        """
        history = self._history.get(ticker, [])
        if len(history) < min_snapshots:
            return []

        current = history[-1]
        previous = history[-2]

        current_map = {f.feature_name: f.importance for f in current.features}
        previous_map = {f.feature_name: f.importance for f in previous.features}

        drifts = []
        for feature_name in set(current_map.keys()) | set(previous_map.keys()):
            curr_imp = current_map.get(feature_name, 0.0)
            prev_imp = previous_map.get(feature_name, 0.0)

            if prev_imp == 0:
                change_pct = 100.0 if curr_imp > 0 else 0.0
            else:
                change_pct = ((curr_imp - prev_imp) / prev_imp) * 100

            # Trend belirle
            if abs(change_pct) < self._significant_change:
                trend = "stable"
            elif change_pct > 0:
                trend = "increasing"
            else:
                trend = "decreasing"

            drifts.append(ImportanceDrift(
                feature_name=feature_name,
                importance_trend=trend,
                current_importance=curr_imp,
                previous_importance=prev_imp,
                change_pct=change_pct,
                is_significant=abs(change_pct) >= self._significant_change,
            ))

        # Değerine göre sırala
        drifts.sort(key=lambda x: abs(x.change_pct), reverse=True)

        significant = [d for d in drifts if d.is_significant]
        if significant:
            logger.info(
                "Importance drift detected",
                ticker=ticker,
                significant_count=len(significant),
                top_drift=significant[0].feature_name,
            )

        return drifts

    # =====================================================
    # FEATURE SELECTION
    # =====================================================

    def select_top_features(
        self,
        snapshot: ImportanceSnapshot,
        top_n: int = 20,
        min_importance: float = 0.005,
    ) -> List[str]:
        """En önemli feature'ları seç.

        Args:
            snapshot: Importance snapshot
            top_n: Maksimum feature sayısı
            min_importance: Minimum importance eşiği

        Returns:
            Seçilen feature isimleri
        """
        selected = []
        for f in snapshot.features:
            if len(selected) >= top_n:
                break
            if f.importance >= min_importance:
                selected.append(f.feature_name)

        return selected

    def compute_concentration(
        self,
        features: List[FeatureImportance],
        top_n: int = 10,
    ) -> float:
        """Importance konsantrasyonu: ilk N feature'ın toplam importance'ı.

        Yüksek konsantrasyon → az sayıda feature çok önemli
        Düşük konsantrasyon → feature'lar eşit dağılmış
        """
        if not features:
            return 0.0
        top_features = sorted(features, key=lambda f: f.importance, reverse=True)[:top_n]
        return sum(f.importance for f in top_features)

    def compute_gini(
        self,
        features: List[FeatureImportance],
    ) -> float:
        """Importance dağılımının Gini katsayısı.

        0 = mükemmel eşitlik (tüm feature'lar eşit önemli)
        1 = mükemmel eşitsizlik (tek bir feature dominant)

        Gini = (2 * Σ(i * x_i)) / (n * Σ(x_i)) - (n+1)/n
        (x_i sıralı, i 1-den başlar)
        """
        if not features:
            return 0.0

        values = sorted([f.importance for f in features])
        n = len(values)
        if n == 0 or sum(values) == 0:
            return 0.0

        total = sum(values)
        weighted_sum = sum((i + 1) * v for i, v in enumerate(values))
        gini = 2 * weighted_sum / (n * total) - (n + 1) / n
        return max(0.0, min(1.0, gini))

    # =====================================================
    # HISTORY & REPORTING
    # =====================================================

    def get_history(
        self,
        ticker: str,
        limit: int = 10,
    ) -> List[Dict]:
        """Importance snapshot geçmişini getir."""
        history = self._history.get(ticker, [])
        return [s.to_dict() for s in history[-limit:]]

    def get_latest(self, ticker: str) -> Optional[ImportanceSnapshot]:
        """En son snapshot'ı getir."""
        history = self._history.get(ticker, [])
        return history[-1] if history else None

    def get_importance_summary(self, ticker: str) -> Dict[str, Any]:
        """Importance özet raporu."""
        latest = self.get_latest(ticker)
        if not latest:
            return {"ticker": ticker, "available": False}

        return {
            "ticker": ticker,
            "available": True,
            "model_name": latest.model_name,
            "method": latest.method,
            "total_features": latest.total_features,
            "top_10_concentration": round(latest.top_10_concentration, 4),
            "gini_coefficient": round(latest.gini_coefficient, 4),
            "top_5": [f.to_dict() for f in latest.features[:5]],
            "bottom_5": [f.to_dict() for f in latest.features[-5:]],
            "snapshot_count": len(self._history.get(ticker, [])),
        }

    # =====================================================
    # YARDIMCI
    # =====================================================

    def _create_snapshot(
        self,
        ticker: str,
        model_name: str,
        method: str,
        feature_names: List[str],
        importance_values: List[float],
    ) -> ImportanceSnapshot:
        """Snapshot oluştur."""
        # Feature importance listesi oluştur
        features = []
        for name, imp in zip(feature_names, importance_values):
            features.append(FeatureImportance(
                feature_name=name,
                importance=float(imp),
                rank=0,
                method=method,
            ))

        # Sırala ve rank ata
        features.sort(key=lambda f: f.importance, reverse=True)
        for i, f in enumerate(features):
            f.rank = i + 1

        # Konsantrasyon ve Gini
        concentration = self.compute_concentration(features, top_n=10)
        gini = self.compute_gini(features)

        return ImportanceSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ticker=ticker,
            model_name=model_name,
            method=method,
            features=features,
            total_features=len(features),
            top_10_concentration=concentration,
            gini_coefficient=gini,
        )

    def _store_snapshot(self, ticker: str, snapshot: ImportanceSnapshot):
        """Snapshot'ı history'ye ekle."""
        if ticker not in self._history:
            self._history[ticker] = []
        self._history[ticker].append(snapshot)
        if len(self._history[ticker]) > self._max_history:
            self._history[ticker] = self._history[ticker][-self._max_history:]


# Singleton
importance_tracker = FeatureImportanceTracker()
