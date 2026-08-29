"""ALPHA BIST — Walk-Forward Ensemble Engine v1.0

Walk-forward cross-validation ile ensemble eğitimi.
Her fold'da:
  1. Base modelleri train set üzerinde eğit
  2. Stacking meta-learner'ı train-val split ile eğit
  3. Ensemble ağırlıklarını validation sonucuyla hesapla
  4. Fold sonucunu kaydet (IC, diversity, benefit)

Purge/Embargo gap ile veri sızıntısı önleme.
Zaman serisi verisi için TimeSeriesSplit kullanır.

Kullanım:
    from services.learning.walkforward_ensemble import walkforward_ensemble

    result = walkforward_ensemble.run(
        X=X_array, y=y_array,
        regimes=regime_array,
        dates=date_array,
        base_models={"lgbm": lgbm_model, "xgb": xgb_model, "cat": cat_model},
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class FoldResult:
    """Tek walk-forward fold sonucu."""

    fold_idx: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    n_train: int
    n_val: int
    ensemble_ic: float
    ensemble_rank_ic: float
    ensemble_direction_accuracy: float
    best_individual_ic: float
    best_individual_name: str
    ic_improvement: float
    diversity_score: float
    model_weights: dict[str, float]
    model_ics: dict[str, float]
    is_beneficial: bool
    regime: str | None = None


@dataclass
class WalkForwardResult:
    """Walk-forward ensemble tam sonuç."""

    n_folds: int
    fold_results: list[FoldResult]
    mean_ensemble_ic: float
    mean_ic_improvement: float
    mean_diversity_score: float
    mean_direction_accuracy: float
    beneficial_ratio: float  # Kaç fold'da ensemble faydalıydı
    final_weights: dict[str, float]
    final_diversity: dict[str, float]
    training_timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class WalkForwardEnsemble:
    """Walk-forward ile ensemble eğitimi ve değerlendirme.

    Özellikler:
    - Purge/Embargo gap ile veri sızıntısı önleme
    - Her fold'da stacking meta-learner eğitimi
    - Diversity + benefit gate entegrasyonu
    - Regime-specific ağırlık hesaplama
    - Fold history tracking
    """

    def __init__(
        self,
        n_splits: int = 5,
        embargo_days: int = 5,
        min_train_size: int = 200,
        min_val_size: int = 30,
        diversity_threshold: float = 0.85,
        benefit_tolerance: float = 0.95,
    ):
        """Otomatik eklendi."""
        self.n_splits = n_splits
        self.embargo_days = embargo_days
        self.min_train_size = min_train_size
        self.min_val_size = min_val_size
        self.diversity_threshold = diversity_threshold
        self.benefit_tolerance = benefit_tolerance
        self._history: list[WalkForwardResult] = []

    def run(
        self,
        X: np.ndarray,
        y: np.ndarray,
        base_models: dict[str, Any],
        regimes: np.ndarray | None = None,
        dates: np.ndarray | None = None,
    ) -> WalkForwardResult:
        """Walk-forward ensemble eğitimi çalıştır.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target array (n_samples,)
            base_models: {model_name: sklearn-compatible model instance}
            regimes: Rejim etiketleri (n_samples,) — opsionel
            dates: Tarih array'i (n_samples,) — opsionel, log için

        Returns:
            WalkForwardResult
        """
        from services.ml.ensemble import EnsembleModel
        from services.ml.stacking_ensemble import StackingConfig, StackingEnsemble

        n = len(X)
        if n < self.min_train_size + self.min_val_size:
            logger.warning("walkforward_insufficient_data", n=n, min_required=self.min_train_size + self.min_val_size)
            return self._empty_result()

        # Walk-forward split'leri oluştur (expanding window)
        splits = self._create_splits(n)

        fold_results: list[FoldResult] = []
        all_final_weights: list[dict[str, float]] = []

        for fold_idx, (train_idx, val_idx) in enumerate(splits):
            logger.info(
                "walkforward_fold_start",
                fold=fold_idx,
                n_train=len(train_idx),
                n_val=len(val_idx),
            )

            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            regimes_train = regimes[train_idx] if regimes is not None else None
            regimes_val = regimes[val_idx] if regimes is not None else None

            # Tarih bilgisi
            train_start = str(dates[train_idx[0]]) if dates is not None else f"idx_{train_idx[0]}"
            train_end = str(dates[train_idx[-1]]) if dates is not None else f"idx_{train_idx[-1]}"
            val_start = str(dates[val_idx[0]]) if dates is not None else f"idx_{val_idx[0]}"
            val_end = str(dates[val_idx[-1]]) if dates is not None else f"idx_{val_idx[-1]}"

            # 1. Base modelleri eğit
            trained_models: dict[str, Any] = {}
            for name, model in base_models.items():
                try:
                    import copy

                    fold_model = copy.deepcopy(model)
                    fold_model.fit(X_train, y_train)
                    trained_models[name] = fold_model
                except Exception as e:
                    logger.warning("walkforward_model_fit_failed", model=name, fold=fold_idx, error=str(e))

            if len(trained_models) < 2:
                logger.warning("walkforward_too_few_models", fold=fold_idx, n=len(trained_models))
                continue

            # 2. Stacking ensemble eğit
            stacking = StackingEnsemble(
                StackingConfig(
                    cv_folds=3,  # WF fold içindeki CV
                    regime_aware=regimes_train is not None,
                    regime_meta_learners=regimes_train is not None,
                )
            )
            for name, model in trained_models.items():
                stacking.add_model(name, model)

            stacking.fit(X_train, y_train, X_val, y_val, regimes_train, regimes_val)

            # 3. EnsembleModel ile diversity + benefit analizi
            ensemble_model = EnsembleModel()

            # Individual predictions
            individual_preds: dict[str, np.ndarray] = {}
            for name, model in trained_models.items():
                try:
                    if hasattr(model, "predict_proba"):
                        preds = model.predict_proba(X_val)[:, 1]
                    else:
                        preds = model.predict(X_val)
                    individual_preds[name] = preds
                except Exception as e:
                    logger.warning("walkforward_predict_failed", model=name, fold=fold_idx, error=str(e))

            # Ensemble prediction
            ensemble_preds = stacking.predict(X_val, regime=None)

            # Diversity analizi
            diversity_report = ensemble_model.analyze_diversity(individual_preds, self.diversity_threshold)

            # Benefit analizi
            benefit_report = ensemble_model.check_benefit(
                ensemble_preds, individual_preds, y_val, self.benefit_tolerance
            )

            # Model IC'leri
            model_ics: dict[str, float] = {}
            for name, preds in individual_preds.items():
                try:
                    mask = np.isfinite(preds) & np.isfinite(y_val)
                    ic = float(np.corrcoef(preds[mask], y_val[mask])[0, 1])
                    model_ics[name] = round(ic, 4) if np.isfinite(ic) else 0.0
                except Exception:
                    model_ics[name] = 0.0

            # Ensemble IC
            try:
                mask = np.isfinite(ensemble_preds) & np.isfinite(y_val)
                ensemble_ic = float(np.corrcoef(ensemble_preds[mask], y_val[mask])[0, 1])
                if not np.isfinite(ensemble_ic):
                    ensemble_ic = 0.0
            except Exception:
                ensemble_ic = 0.0

            # Rank IC
            try:
                from scipy.stats import spearmanr

                rank_ic, _ = spearmanr(ensemble_preds[mask], y_val[mask])
                rank_ic = float(rank_ic) if np.isfinite(rank_ic) else 0.0
            except Exception:
                rank_ic = 0.0

            # Direction accuracy
            try:
                pred_sign = np.sign(ensemble_preds)
                true_sign = np.sign(y_val)
                direction_acc = float(np.mean(pred_sign == true_sign))
            except Exception:
                direction_acc = 0.0

            # Regime bilgisi
            regime_val = None
            if regimes_val is not None:
                unique_regimes, counts = np.unique(regimes_val, return_counts=True)
                regime_val = str(unique_regimes[np.argmax(counts)])

            # Model ağırlıkları
            model_weights = stacking.get_model_weights()

            fold_result = FoldResult(
                fold_idx=fold_idx,
                train_start=train_start,
                train_end=train_end,
                val_start=val_start,
                val_end=val_end,
                n_train=len(train_idx),
                n_val=len(val_idx),
                ensemble_ic=round(ensemble_ic, 4),
                ensemble_rank_ic=round(rank_ic, 4),
                ensemble_direction_accuracy=round(direction_acc, 4),
                best_individual_ic=round(max(model_ics.values()) if model_ics else 0.0, 4),
                best_individual_name=max(model_ics, key=model_ics.get) if model_ics else "",
                ic_improvement=round(ensemble_ic - (max(model_ics.values()) if model_ics else 0.0), 4),
                diversity_score=round(diversity_report.diversity_score, 4),
                model_weights=model_weights,
                model_ics=model_ics,
                is_beneficial=benefit_report.is_beneficial,
                regime=regime_val,
            )

            fold_results.append(fold_result)
            all_final_weights.append(model_weights)

            logger.info(
                "walkforward_fold_complete",
                fold=fold_idx,
                ensemble_ic=fold_result.ensemble_ic,
                ic_improvement=fold_result.ic_improvement,
                diversity=fold_result.diversity_score,
                beneficial=fold_result.is_beneficial,
            )

        if not fold_results:
            return self._empty_result()

        # Final ağırlıklar: Tüm fold'ların ağırlıklarının ortalaması
        final_weights = self._average_weights(all_final_weights)

        # Final diversity skorları
        final_diversity: dict[str, float] = {}
        for fr in fold_results:
            for name, ic in fr.model_ics.items():
                if name not in final_diversity:
                    final_diversity[name] = []
                final_diversity[name].append(ic)
        final_diversity = {name: round(float(np.mean(ics)), 4) for name, ics in final_diversity.items()}

        result = WalkForwardResult(
            n_folds=len(fold_results),
            fold_results=fold_results,
            mean_ensemble_ic=round(float(np.mean([fr.ensemble_ic for fr in fold_results])), 4),
            mean_ic_improvement=round(float(np.mean([fr.ic_improvement for fr in fold_results])), 4),
            mean_diversity_score=round(float(np.mean([fr.diversity_score for fr in fold_results])), 4),
            mean_direction_accuracy=round(float(np.mean([fr.ensemble_direction_accuracy for fr in fold_results])), 4),
            beneficial_ratio=round(sum(1 for fr in fold_results if fr.is_beneficial) / len(fold_results), 4),
            final_weights=final_weights,
            final_diversity=final_diversity,
        )

        self._history.append(result)

        logger.info(
            "walkforward_complete",
            n_folds=result.n_folds,
            mean_ic=result.mean_ensemble_ic,
            mean_improvement=result.mean_ic_improvement,
            beneficial_ratio=result.beneficial_ratio,
        )

        return result

    def _create_splits(self, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """Expanding window walk-forward split'leri oluştur.

        Her split'te:
        - Train: expanding window (baştan günümüze kadar)
        - Val: bir sonraki blok
        - Embargo: train ve val arasında gap
        """
        splits = []
        val_size = max(self.min_val_size, (n - self.min_train_size) // self.n_splits)

        for i in range(self.n_splits):
            val_end = n - (self.n_splits - i - 1) * val_size
            val_start = val_end - val_size
            train_end = val_start - self.embargo_days

            if train_end < self.min_train_size:
                continue
            if val_start >= n or val_end > n:
                continue

            train_idx = np.arange(0, train_end)
            val_idx = np.arange(val_start, min(val_end, n))

            if len(train_idx) >= self.min_train_size and len(val_idx) >= self.min_val_size:
                splits.append((train_idx, val_idx))

        return splits

    def _average_weights(self, weight_list: list[dict[str, float]]) -> dict[str, float]:
        """Tüm fold'ların ağırlıklarının ortalamasını al."""
        if not weight_list:
            return {}

        all_models: set[str] = set()
        for w in weight_list:
            all_models.update(w.keys())

        avg_weights: dict[str, float] = {}
        for model in all_models:
            values = [w.get(model, 0.0) for w in weight_list]
            avg_weights[model] = round(float(np.mean(values)), 4)

        # Normalize
        total = sum(avg_weights.values())
        if total > 0:
            avg_weights = {k: round(v / total, 4) for k, v in avg_weights.items()}

        return avg_weights

    def _empty_result(self) -> WalkForwardResult:
        """Boş sonuç döndür."""
        return WalkForwardResult(
            n_folds=0,
            fold_results=[],
            mean_ensemble_ic=0.0,
            mean_ic_improvement=0.0,
            mean_diversity_score=0.0,
            mean_direction_accuracy=0.0,
            beneficial_ratio=0.0,
            final_weights={},
            final_diversity={},
        )

    def get_history(self) -> list[WalkForwardResult]:
        """Geçmiş walk-forward sonuçları."""
        return self._history

    def get_last_result(self) -> WalkForwardResult | None:
        """Son walk-forward sonucu."""
        return self._history[-1] if self._history else None


# Singleton
walkforward_ensemble = WalkForwardEnsemble()
