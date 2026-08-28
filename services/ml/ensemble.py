"""ALPHA BIST — Ensemble Model v2.0 (Production-Hardened).

Ağırlıklı ortalama + stacking ensemble desteği.
Eski weighted average korunurken, stacking_ensemble.py ile entegrasyon eklendi.

v2.0 Eklemeleri:
- Diversity analysis (model correlation matrix, otomatik eleme)
- Ensemble benefit gate (tek modelden daha iyi değilse reddet)
- Save/load (ensemble durumu persistansı)
- Model degradation tracking
- Ensemble diagnostics
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


# =====================================================
# DATA CLASSES
# =====================================================


@dataclass
class DiversityReport:
    """Model diversity analiz sonucu."""

    correlation_matrix: dict[str, dict[str, float]]
    mean_correlation: float
    diversity_score: float  # 1 - mean_correlation
    redundant_models: list[str]  # Çok benzer modeller (corr > threshold)
    recommendation: str


@dataclass
class BenefitReport:
    """Ensemble benefit analiz sonucu."""

    ensemble_ic: float
    best_individual_ic: float
    best_individual_name: str
    ic_improvement: float  # ensemble_ic - best_individual_ic
    is_beneficial: bool
    recommendation: str


@dataclass
class EnsembleDiagnostics:
    """Ensemble teşhis raporu."""

    model_weights: dict[str, float]
    model_ics: dict[str, float]
    diversity: DiversityReport
    benefit: BenefitReport
    n_models: int
    n_successful: int
    timestamp: str


@dataclass
class EnsembleState:
    """Ensemble kaydetme/yükleme durumu."""

    weights: dict[str, float]
    model_names: list[str]
    diversity_scores: dict[str, float]
    benefit_report: BenefitReport | None
    training_history: list[dict[str, Any]]
    created_at: str
    version: int = 1


# =====================================================
# ENSEMBLE MODEL
# =====================================================


class EnsembleModel:
    """Ensemble prediction — weighted average + stacking desteği.

    v2.0 Özellikler:
    - Diversity analysis: Modeller arası korelasyon, benzer modelleri otomatik ele
    - Benefit gate: Ensemble tek modelden daha iyi değilse reddet
    - Save/load: Ensemble durumunu persistansı
    - Diagnostics: "Neden bu ağırlıklar?" sorusunu cevapla
    """

    def __init__(self):
        self._state: EnsembleState | None = None
        self._diversity_threshold = 0.85  # Bu üstünde → redundant
        self._benefit_tolerance = 0.95  # Ensemble IC < best * tolerance → not beneficial

    # =====================================================
    # PREDICTION
    # =====================================================

    def predict(
        self,
        models: dict[str, Callable],
        weights: dict[str, float],
        X: np.ndarray,
    ) -> np.ndarray:
        """Ağırlıklı ensemble prediction.

        Args:
            models: {model_name: predict_fn}
            weights: {model_name: weight}
            X: Feature matrix

        Returns:
            Ağırlıklı ortalama tahminler
        """
        if not models:
            logger.warning("ensemble_no_models")
            return np.full(len(X), np.nan)

        total_weight = 0.0
        weighted_sum = np.zeros(len(X))
        failed_models = []

        for name, fn in models.items():
            w = weights.get(name, 1.0)
            try:
                preds = fn(X)
                if len(preds) != len(X):
                    logger.warning("ensemble_prediction_length_mismatch", model=name, expected=len(X), got=len(preds))
                    failed_models.append(name)
                    continue
                if not np.all(np.isfinite(preds)):
                    logger.warning("ensemble_prediction_non_finite", model=name)
                    preds = np.nan_to_num(preds, nan=0.0, posinf=0.0, neginf=0.0)
                weighted_sum += preds * w
                total_weight += w
            except Exception as e:
                logger.warning("ensemble_model_failed", model=name, error=str(e))
                failed_models.append(name)

        if failed_models:
            logger.info("ensemble_failed_models", failed=failed_models, succeeded=len(models) - len(failed_models))

        if total_weight <= 0:
            logger.error("ensemble_all_models_failed", model_count=len(models))
            return np.full(len(X), np.nan)

        return weighted_sum / total_weight

    def predict_with_confidence(
        self,
        models: dict[str, Callable],
        weights: dict[str, float],
        X: np.ndarray,
    ) -> tuple:
        """Ensemble prediction + confidence (model agreement).

        Args:
            models: {model_name: predict_fn}
            weights: {model_name: weight}
            X: Feature matrix

        Returns:
            (predictions, confidence) — confidence: 0-1 arası
        """
        all_preds = []

        for name, fn in models.items():
            try:
                preds = fn(X)
                if len(preds) == len(X) and np.all(np.isfinite(preds)):
                    all_preds.append(preds)
                else:
                    logger.warning("ensemble_confidence_skip", model=name)
            except Exception as e:
                logger.warning("ensemble_confidence_failed", model=name, error=str(e))

        if not all_preds:
            return np.full(len(X), np.nan), np.zeros(len(X))

        preds_matrix = np.array(all_preds)
        mean_pred = np.mean(preds_matrix, axis=0)

        pred_range = np.max(preds_matrix) - np.min(preds_matrix)
        max_possible_std = max(pred_range / 2, 1e-6)
        pred_std = np.std(preds_matrix, axis=0)
        confidence = 1.0 - (pred_std / max_possible_std)

        return mean_pred, np.clip(confidence, 0, 1)

    def predict_stacking(
        self,
        stacking_ensemble: Any,
        X: np.ndarray,
    ) -> np.ndarray:
        """Stacking ensemble ile tahmin."""
        if not hasattr(stacking_ensemble, "is_fitted") or not stacking_ensemble.is_fitted:
            logger.warning("stacking_not_fitted")
            return np.full(len(X), np.nan)

        return stacking_ensemble.predict(X)

    def predict_dynamic(
        self,
        models: dict[str, Callable],
        X: np.ndarray,
        regime: str = "NORMAL",
        regime_weights: dict[str, dict[str, float]] | None = None,
    ) -> np.ndarray:
        """Rejime göre dinamik ağırlıklı ensemble."""
        valid_regimes = {"BULL", "BEAR", "SIDEWAYS", "HIGH_VOL", "NORMAL"}
        if regime not in valid_regimes:
            logger.warning("ensemble_unknown_regime", regime=regime, valid=sorted(valid_regimes))

        if regime_weights is None:
            weights = {name: 1.0 for name in models}
        else:
            weights = regime_weights.get(regime, {name: 1.0 for name in models})

        return self.predict(models, weights, X)

    # =====================================================
    # DIVERSITY ANALYSIS
    # =====================================================

    def analyze_diversity(
        self,
        model_predictions: dict[str, np.ndarray],
        threshold: float | None = None,
    ) -> DiversityReport:
        """Model diversity analizi.

        Modeller arası korelasyon matrisi hesaplar.
        Yüksek korelasyonlu modelleri "redundant" olarak işaretler.

        Args:
            model_predictions: {model_name: predictions_array}
            threshold: Redundant eşik değeri (varsayılan: 0.85)

        Returns:
            DiversityReport
        """
        if threshold is None:
            threshold = self._diversity_threshold

        names = sorted(model_predictions.keys())
        n = len(names)

        if n < 2:
            return DiversityReport(
                correlation_matrix={},
                mean_correlation=0.0,
                diversity_score=1.0,
                redundant_models=[],
                recommendation="Tek model var — diversity analizi anlamsız",
            )

        # Korelasyon matrisi
        corr_matrix: dict[str, dict[str, float]] = {}
        correlations = []

        for i, name_i in enumerate(names):
            corr_matrix[name_i] = {}
            for j, name_j in enumerate(names):
                if i == j:
                    corr_matrix[name_i][name_j] = 1.0
                elif name_j in corr_matrix and name_i in corr_matrix[name_j]:
                    corr_matrix[name_i][name_j] = corr_matrix[name_j][name_i]
                else:
                    try:
                        pred_i = model_predictions[name_i]
                        pred_j = model_predictions[name_j]
                        # Finite mask
                        mask = np.isfinite(pred_i) & np.isfinite(pred_j)
                        if np.sum(mask) < 10:
                            corr = 0.0
                        else:
                            corr = float(np.corrcoef(pred_i[mask], pred_j[mask])[0, 1])
                            if np.isnan(corr):
                                corr = 0.0
                        corr_matrix[name_i][name_j] = round(corr, 4)
                        if i < j:  # Sadece üst üçgen
                            correlations.append(abs(corr))
                    except Exception as e:
                        logger.warning("diversity_corr_failed", model_i=name_i, model_j=name_j, error=str(e))
                        corr_matrix[name_i][name_j] = 0.0

        mean_corr = float(np.mean(correlations)) if correlations else 0.0
        diversity_score = 1.0 - mean_corr

        # Redundant modeller
        redundant = []
        for i, name_i in enumerate(names):
            for j, name_j in enumerate(names):
                if i < j and abs(corr_matrix[name_i].get(name_j, 0)) > threshold:
                    redundant.append(f"{name_i}↔{name_j}")

        if redundant:
            recommendation = f"Redundant model çiftleri: {redundant}. Birini çıkarmayı düşün."
        elif diversity_score < 0.3:
            recommendation = "Düşük diversity — modeller çok benzer. Farklı feature set veya algoritma dene."
        else:
            recommendation = "Yeterli diversity — ensemble faydalı olabilir."

        return DiversityReport(
            correlation_matrix=corr_matrix,
            mean_correlation=round(mean_corr, 4),
            diversity_score=round(diversity_score, 4),
            redundant_models=redundant,
            recommendation=recommendation,
        )

    # =====================================================
    # BENEFIT GATE
    # =====================================================

    def check_benefit(
        self,
        ensemble_predictions: np.ndarray,
        individual_predictions: dict[str, np.ndarray],
        y_true: np.ndarray,
        tolerance: float | None = None,
    ) -> BenefitReport:
        """Ensemble benefit kontrolü.

        Ensemble tek modelden daha iyi değilse reddet.

        Args:
            ensemble_predictions: Ensemble tahminleri
            individual_predictions: {model_name: predictions}
            y_true: Gerçek değerler
            tolerance: Tolerans (ensemble IC < best * tolerance → not beneficial)

        Returns:
            BenefitReport
        """
        if tolerance is None:
            tolerance = self._benefit_tolerance

        # Ensemble IC
        try:
            mask = np.isfinite(ensemble_predictions) & np.isfinite(y_true)
            ensemble_ic = float(np.corrcoef(ensemble_predictions[mask], y_true[mask])[0, 1])
            if np.isnan(ensemble_ic):
                ensemble_ic = 0.0
        except Exception:
            ensemble_ic = 0.0

        # Individual ICs
        individual_ics = {}
        for name, preds in individual_predictions.items():
            try:
                mask = np.isfinite(preds) & np.isfinite(y_true)
                ic = float(np.corrcoef(preds[mask], y_true[mask])[0, 1])
                individual_ics[name] = round(ic, 4) if np.isfinite(ic) else 0.0
            except Exception:
                individual_ics[name] = 0.0

        if not individual_ics:
            return BenefitReport(
                ensemble_ic=round(ensemble_ic, 4),
                best_individual_ic=0.0,
                best_individual_name="",
                ic_improvement=round(ensemble_ic, 4),
                is_beneficial=True,
                recommendation="Bireysel model yok — ensemble kullan",
            )

        best_name = max(individual_ics, key=individual_ics.get)
        best_ic = individual_ics[best_name]
        improvement = ensemble_ic - best_ic

        is_beneficial = ensemble_ic >= best_ic * tolerance

        if is_beneficial:
            if improvement > 0.02:
                recommendation = f"Ensemble belirgin şekilde daha iyi (+{improvement:.4f}). Kullan."
            else:
                recommendation = f"Ensemble kabul edilebilir ({improvement:+.4f}). Kullan."
        else:
            recommendation = (
                f"Ensemble tek modelden daha kötü (ensemble={ensemble_ic:.4f}, "
                f"best={best_ic:.4f} [{best_name}]). En iyi tek modeli kullan."
            )

        return BenefitReport(
            ensemble_ic=round(ensemble_ic, 4),
            best_individual_ic=round(best_ic, 4),
            best_individual_name=best_name,
            ic_improvement=round(improvement, 4),
            is_beneficial=is_beneficial,
            recommendation=recommendation,
        )

    # =====================================================
    # DIAGNOSTICS
    # =====================================================

    def diagnose(
        self,
        models: dict[str, Callable],
        weights: dict[str, float],
        X: np.ndarray,
        y_true: np.ndarray,
    ) -> EnsembleDiagnostics:
        """Ensemble teşhis raporu.

        "Neden bu ağırlıklar?" sorusunu cevaplar.

        Args:
            models: {model_name: predict_fn}
            weights: {model_name: weight}
            X: Feature matrix
            y_true: Gerçek değerler

        Returns:
            EnsembleDiagnostics
        """
        # Her modelin tahmini
        individual_preds = {}
        for name, fn in models.items():
            try:
                preds = fn(X)
                if len(preds) == len(X):
                    individual_preds[name] = preds
            except Exception as e:
                logger.warning("diagnose_model_failed", model=name, error=str(e))

        # Diversity
        diversity = self.analyze_diversity(individual_preds)

        # Benefit
        ensemble_preds = self.predict(models, weights, X)
        benefit = self.check_benefit(ensemble_preds, individual_preds, y_true)

        # Individual ICs
        model_ics = {}
        for name, preds in individual_preds.items():
            try:
                mask = np.isfinite(preds) & np.isfinite(y_true)
                ic = float(np.corrcoef(preds[mask], y_true[mask])[0, 1])
                model_ics[name] = round(ic, 4) if np.isfinite(ic) else 0.0
            except Exception:
                model_ics[name] = 0.0

        return EnsembleDiagnostics(
            model_weights=weights,
            model_ics=model_ics,
            diversity=diversity,
            benefit=benefit,
            n_models=len(models),
            n_successful=len(individual_preds),
            timestamp=datetime.now(UTC).isoformat(),
        )

    # =====================================================
    # SAVE / LOAD
    # =====================================================

    def save_state(
        self,
        path: str,
        weights: dict[str, float],
        model_names: list[str],
        diversity_scores: dict[str, float] | None = None,
        benefit_report: BenefitReport | None = None,
        training_history: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Ensemble durumunu kaydet.

        Args:
            path: Kayıt dosyası yolu
            weights: Model ağırlıkları
            model_names: Model isimleri
            diversity_scores: Diversity skorları
            benefit_report: Benefit raporu
            training_history: Eğitim geçmişi

        Returns:
            Başarılı mı?
        """
        try:
            from services.core.safe_pickle import safe_pickle_dump

            state = EnsembleState(
                weights=weights,
                model_names=model_names,
                diversity_scores=diversity_scores or {},
                benefit_report=benefit_report,
                training_history=training_history or [],
                created_at=datetime.now(UTC).isoformat(),
            )

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            safe_pickle_dump(state, path)
            self._state = state

            logger.info("ensemble_state_saved", path=path, models=len(model_names))
            return True
        except Exception as e:
            logger.error("ensemble_save_failed", path=path, error=str(e))
            return False

    def load_state(self, path: str) -> bool:
        """Ensemble durumunu yükle.

        Args:
            path: Kayıt dosyası yolu

        Returns:
            Başarılı mı?
        """
        try:
            from services.core.safe_pickle import safe_pickle_load

            state = safe_pickle_load(path)
            if not isinstance(state, EnsembleState):
                logger.error("ensemble_invalid_state", path=path)
                return False

            self._state = state
            logger.info(
                "ensemble_state_loaded",
                path=path,
                models=len(state.model_names),
                created_at=state.created_at,
            )
            return True
        except Exception as e:
            logger.error("ensemble_load_failed", path=path, error=str(e))
            return False

    @property
    def state(self) -> EnsembleState | None:
        return self._state

    @property
    def is_loaded(self) -> bool:
        return self._state is not None


# Singleton
ensemble_model = EnsembleModel()
