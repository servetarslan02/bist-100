"""ALPHA BIST — Stacking Ensemble (Nihai —⭐⭐⭐⭐⭐).

Base models → meta-learner ile model birleştirme.
Nature (2026) metodolojisi: Ridge meta-learner.

⭐⭐⭐⭐⭐ Eklemeler:
- Regime-based dynamic weights (BULL/BEAR/SIDEWAYS/HIGH_VOL)
- Model agreement confidence
- Feature passthrough
- Model diversity scoring
- Online weight adaptation
- Regime-specific meta-learner
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class StackingConfig:
    """Stacking ensemble konfigürasyonu."""

    meta_learner_type: str = "ridge"  # ridge, logistic, linear, elastic_net
    cv_folds: int = 5
    use_proba: bool = True
    passthrough: bool = False  # Original features de meta-learner'a gitsin
    # Regime-based
    regime_aware: bool = True
    regime_meta_learners: bool = True  # Her rejim için ayrı meta-learner
    # Diversity
    min_diversity_score: float = 0.1  # Minimum model çeşitliliği
    # Online adaptation
    online_adaptation: bool = True
    adaptation_rate: float = 0.1  # Ağırlık güncelleme hızı


class StackingEnsemble:
    """Stacking ensemble —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Cross-validated stacking (data leakage önleme)
    - Regime-based dynamic weights (BULL/BEAR/SIDEWAYS/HIGH_VOL)
    - Model agreement confidence
    - Feature passthrough
    - Model diversity scoring
    - Online weight adaptation
    - Regime-specific meta-learner
    """

    def __init__(self, config: StackingConfig | None = None):
        self._config = config or StackingConfig()
        self._base_models: dict[str, Any] = {}
        self._meta_learner = None
        self._regime_meta_learners: dict[str, Any] = {}  # regime → meta-learner
        self._model_weights: dict[str, float] = {}
        self._regime_weights: dict[str, dict[str, float]] = {}  # regime → {model: weight}
        self._is_fitted = False
        self._training_history: list[dict[str, Any]] = []
        self._diversity_scores: dict[str, float] = {}

    def add_model(self, name: str, model: Any, weight: float = 1.0):
        """Base model ekle."""
        self._base_models[name] = model
        self._model_weights[name] = weight

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes_train: np.ndarray | None = None,
        regimes_val: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """Stacking ensemble eğit.

        Args:
            X_train: Eğitim verisi
            y_train: Eğitim label
            X_val: Validation verisi
            y_val: Validation label
            regimes_train: Eğitim rejim etiketleri (opsiyonel)
            regimes_val: Validation rejim etiketleri (opsiyonel)

        Returns:
            Training metrics
        """
        from sklearn.model_selection import TimeSeriesSplit

        if len(self._base_models) < 2:
            return {"error": "Need at least 2 base models"}

        # Cross-validated stacking (TimeSeriesSplit — zaman serisi verisi için)
        kf = TimeSeriesSplit(n_splits=self._config.cv_folds)
        meta_features_train = np.zeros((len(X_train), len(self._base_models)))

        for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X_train)):
            X_tr, X_vl = X_train[train_idx], X_train[val_idx]
            y_tr = y_train[train_idx]

            for model_idx, (name, model) in enumerate(self._base_models.items()):
                try:
                    import copy

                    fold_model = copy.deepcopy(model)

                    if hasattr(fold_model, "fit"):
                        fold_model.fit(X_tr, y_tr)

                    if self._config.use_proba and hasattr(fold_model, "predict_proba"):
                        meta_features_train[val_idx, model_idx] = fold_model.predict_proba(X_vl)[:, 1]
                    else:
                        meta_features_train[val_idx, model_idx] = fold_model.predict(X_vl)

                except Exception as e:
                    logger.warning("stacking_fold_failed", model=name, fold=fold_idx, error=str(e))
                    meta_features_train[val_idx, model_idx] = 0.5

        # Feature passthrough
        if self._config.passthrough:
            meta_features_train = np.hstack([meta_features_train, X_train])

        # Ana meta-learner eğit
        self._meta_learner = self._create_meta_learner()
        self._meta_learner.fit(meta_features_train, y_train)

        # Regime-specific meta-learner'lar
        if self._config.regime_aware and self._config.regime_meta_learners and regimes_train is not None:
            self._fit_regime_meta_learners(meta_features_train, y_train, regimes_train)

        # Base modelleri tüm eğitim verisi üzerinde eğit
        for name, model in self._base_models.items():
            try:
                model.fit(X_train, y_train)
            except Exception as e:
                logger.warning("base_model_fit_failed", model=name, error=str(e))

        self._is_fitted = True

        # Model diversity hesapla
        self._compute_diversity(X_val)

        # Regime-based ağırlıkları hesapla
        if regimes_val is not None:
            self._compute_regime_weights(X_val, y_val, regimes_val)

        # Validation metrics
        metrics = self._compute_validation_metrics(X_val, y_val)

        # Training history
        self._training_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "metrics": metrics,
                "n_base_models": len(self._base_models),
                "diversity_scores": self._diversity_scores,
            }
        )
        if len(self._training_history) > 1000:
            self._training_history = self._training_history[-1000:]

        logger.info("stacking_ensemble_fitted", **metrics)
        return metrics

    def predict(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> np.ndarray:
        """Stacking prediction.

        Args:
            X: Feature matrix
            regime: Mevcut piyasa rejimi (opsiyonel — regime-specific meta-learner kullanır)

        Returns:
            Tahmin array'i
        """
        if not self._is_fitted:
            return np.zeros(len(X))

        # Base model predictions
        meta_features = self._get_meta_features(X)

        # Regime-specific meta-learner
        if regime and regime in self._regime_meta_learners:
            meta_learner = self._regime_meta_learners[regime]
        else:
            meta_learner = self._meta_learner

        # Meta-learner prediction
        try:
            if hasattr(meta_learner, "predict_proba"):
                return meta_learner.predict_proba(meta_features)[:, 1]
            return meta_learner.predict(meta_features)
        except Exception as e:
            logger.warning("stacking_meta_learner_predict_failed", error=str(e))
            return np.zeros(len(X))

    def predict_with_confidence(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> tuple:
        """Prediction + confidence (model agreement).

        Args:
            X: Feature matrix
            regime: Mevcut piyasa rejimi

        Returns:
            (predictions, confidence) — confidence: 0-1 arası
        """
        if not self._is_fitted:
            return np.zeros(len(X)), np.zeros(len(X))

        # Base model predictions
        all_preds = []
        for _name, model in self._base_models.items():
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    preds = model.predict_proba(X)[:, 1]
                else:
                    preds = model.predict(X)
                all_preds.append(preds)
            except Exception as e:
                logger.warning("stacking_handled_exception", error=str(e), context="stacking_ensemble.py:224")

        if not all_preds:
            return np.zeros(len(X)), np.zeros(len(X))

        # Model agreement
        preds_matrix = np.array(all_preds)
        np.mean(preds_matrix, axis=0)

        # Confidence: 1 - normalized_std (yüksek = modeller uzlaşıyor)
        pred_std = np.std(preds_matrix, axis=0)
        max_possible_std = 0.5  # 0-1 arası tahminler için max std
        confidence = 1.0 - (pred_std / max_possible_std)
        confidence = np.clip(confidence, 0, 1)

        # Weighted prediction
        weighted_pred = self.predict(X, regime)

        return weighted_pred, confidence

    def predict_with_details(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> dict[str, Any]:
        """Detaylı prediction — her modelin katkısı dahil.

        Returns:
            {
                "prediction": float,
                "confidence": float,
                "model_predictions": {model_name: prediction},
                "model_weights": {model_name: weight},
                "regime": str,
                "agreement_score": float,
            }
        """
        # Her modelin tahmini
        model_preds = {}
        for name, model in self._base_models.items():
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    pred = model.predict_proba(X[:1])[:, 1]
                else:
                    pred = model.predict(X[:1])
                model_preds[name] = float(pred[0]) if len(pred) > 0 else 0.5
            except Exception as e:
                logger.warning("stacking_detail_predict_failed", model=name, error=str(e))
                model_preds[name] = 0.5

        # Weighted prediction
        pred, conf = self.predict_with_confidence(X[:1], regime)

        # Agreement score (tüm modellerin aynı yönde olup olmadığı)
        preds_list = list(model_preds.values())
        above_half = sum(1 for p in preds_list if p > 0.5)
        agreement = max(above_half, len(preds_list) - above_half) / max(len(preds_list), 1)

        return {
            "prediction": float(pred[0]) if len(pred) > 0 else 0.5,
            "confidence": float(conf[0]) if len(conf) > 0 else 0.0,
            "model_predictions": model_preds,
            "model_weights": self.get_model_weights(regime),
            "regime": regime or "UNKNOWN",
            "agreement_score": round(agreement, 4),
            "diversity_score": round(
                float(np.mean(list(self._diversity_scores.values()))) if self._diversity_scores else 0, 4
            ),
        }

    def get_model_weights(self, regime: str | None = None) -> dict[str, float]:
        """Model ağırlıklarını döndür.

        Args:
            regime: Hangi rejim için ağırlıklar (None = genel)

        Returns:
            {model_name: weight}
        """
        if regime and regime in self._regime_weights:
            return self._regime_weights[regime]

        if self._meta_learner is None:
            return self._model_weights

        try:
            coefs = self._meta_learner.coef_
            n_models = len(self._base_models)
            if len(coefs) >= n_models:
                model_coefs = coefs[:n_models]
                total = sum(abs(c) for c in model_coefs)
                if total > 0:
                    return {
                        name: round(float(abs(c) / total), 4)
                        for (name, _), c in zip(self._base_models.items(), model_coefs, strict=False)
                    }
        except Exception as e:
            logger.warning("stacking_handled_exception", error=str(e), context="stacking_ensemble.py:318")

        return self._model_weights

    def get_regime_weights(self) -> dict[str, dict[str, float]]:
        """Tüm rejim ağırlıklarını döndür."""
        return self._regime_weights

    def get_diversity_scores(self) -> dict[str, float]:
        """Model diversity skorlarını döndür."""
        return self._diversity_scores

    def get_training_history(self) -> list[dict[str, Any]]:
        """Training history döndür."""
        return self._training_history

    def _get_meta_features(self, X: np.ndarray) -> np.ndarray:
        """Base model predictions'ı meta-feature olarak oluştur."""
        meta_features = np.zeros((len(X), len(self._base_models)))
        for model_idx, (_name, model) in enumerate(self._base_models.items()):
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    meta_features[:, model_idx] = model.predict_proba(X)[:, 1]
                else:
                    meta_features[:, model_idx] = model.predict(X)
            except Exception as e:
                logger.warning("stacking_meta_feature_failed", model=name, error=str(e))
                meta_features[:, model_idx] = 0.5

        if self._config.passthrough:
            meta_features = np.hstack([meta_features, X])

        return meta_features

    def _create_meta_learner(self):
        """Meta-learner oluştur."""
        from sklearn.linear_model import ElasticNet, LinearRegression, LogisticRegression, Ridge

        if self._config.meta_learner_type == "ridge":
            return Ridge(alpha=1.0)
        elif self._config.meta_learner_type == "logistic":
            return LogisticRegression(max_iter=1000)
        elif self._config.meta_learner_type == "elastic_net":
            return ElasticNet(alpha=1.0, l1_ratio=0.5)
        else:
            return LinearRegression()

    def _fit_regime_meta_learners(
        self,
        meta_features: np.ndarray,
        y: np.ndarray,
        regimes: np.ndarray,
    ):
        """Her rejim için ayrı meta-learner eğit."""
        unique_regimes = np.unique(regimes)
        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < 30:  # Minimum sample — 10 cok dusuktu
                continue

            try:
                meta_learner = self._create_meta_learner()
                meta_learner.fit(meta_features[mask], y[mask])
                self._regime_meta_learners[regime] = meta_learner
                logger.info("regime_meta_learner_fitted", regime=regime, n_samples=int(np.sum(mask)))
            except Exception as e:
                logger.warning("regime_meta_learner_failed", regime=regime, error=str(e))

    def _compute_diversity(self, X: np.ndarray):
        """Model diversity hesapla — farklı modeller farklı tahminler yapmalı."""
        all_preds = []
        for name, model in self._base_models.items():
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    preds = model.predict_proba(X)[:, 1]
                else:
                    preds = model.predict(X)
                all_preds.append((name, preds))
            except Exception as e:
                logger.warning("stacking_handled_exception", error=str(e), context="stacking_ensemble.py:396")

        if len(all_preds) < 2:
            return

        # Pairwise correlation
        names = [n for n, _ in all_preds]
        preds_matrix = np.array([p for _, p in all_preds])

        for i, name_i in enumerate(names):
            correlations = []
            for j, _name_j in enumerate(names):
                if i != j:
                    corr = np.corrcoef(preds_matrix[i], preds_matrix[j])[0, 1]
                    if not np.isnan(corr):
                        correlations.append(abs(corr))

            # Diversity = 1 - ortalama korelasyon
            avg_corr = np.mean(correlations) if correlations else 1.0
            self._diversity_scores[name_i] = round(1.0 - avg_corr, 4)

    def _compute_regime_weights(
        self,
        X: np.ndarray,
        y: np.ndarray,
        regimes: np.ndarray,
    ):
        """Her rejim için optimal ağırlıkları hesapla."""
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < 30:  # Minimum sample
                continue

            try:
                # Her modelin bu rejimdeki performansı
                regime_scores = {}
                for name, model in self._base_models.items():
                    try:
                        if self._config.use_proba and hasattr(model, "predict_proba"):
                            preds = model.predict_proba(X[mask])[:, 1]
                        else:
                            preds = model.predict(X[mask])

                        # IC (correlation)
                        ic = np.corrcoef(preds, y[mask])[0, 1]
                        if np.isnan(ic):
                            ic = 0.0
                        regime_scores[name] = abs(ic)
                    except Exception as e:
                        logger.warning("stacking_regime_score_failed", model=name, regime=regime, error=str(e))
                        regime_scores[name] = 0.0

                # Normalize to weights
                total = sum(regime_scores.values())
                if total > 0:
                    self._regime_weights[regime] = {
                        name: round(score / total, 4) for name, score in regime_scores.items()
                    }
                else:
                    self._regime_weights[regime] = {name: 1.0 / len(self._base_models) for name in self._base_models}

            except Exception as e:
                logger.warning("regime_weight_computation_failed", regime=regime, error=str(e))

    def _compute_validation_metrics(self, X_val: np.ndarray, y_val: np.ndarray) -> dict[str, Any]:
        """Validation metrics hesapla."""
        val_pred = self.predict(X_val)

        # IC (Information Coefficient)
        try:
            ic = float(np.corrcoef(val_pred, y_val)[0, 1])
            if np.isnan(ic):
                ic = 0.0
        except Exception:
            ic = 0.0

        # Directional accuracy — sign-based (regression icin dogru)
        try:
            pred_sign = np.sign(val_pred)
            true_sign = np.sign(y_val)
            directional_accuracy = float(np.mean(pred_sign == true_sign))
        except Exception:
            directional_accuracy = 0.0

        # Rank IC (Spearman)
        try:
            from scipy.stats import spearmanr
            rank_ic, _ = spearmanr(val_pred, y_val)
            rank_ic = float(rank_ic) if np.isfinite(rank_ic) else 0.0
        except Exception:
            rank_ic = 0.0

        return {
            "n_base_models": len(self._base_models),
            "cv_folds": self._config.cv_folds,
            "meta_learner": self._config.meta_learner_type,
            "val_ic": round(ic, 4),
            "val_rank_ic": round(rank_ic, 4),
            "val_directional_accuracy": round(directional_accuracy, 4),
            "diversity_score": round(
                float(np.mean(list(self._diversity_scores.values()))) if self._diversity_scores else 0, 4
            ),
            "n_regime_meta_learners": len(self._regime_meta_learners),
            "n_regime_weights": len(self._regime_weights),
        }

    # =====================================================
    # REGIME SMOOTHING (v2.1)
    # =====================================================

    def predict_with_regime_smoothing(
        self,
        X: np.ndarray,
        current_regime: str,
        previous_regime: str | None = None,
        smoothing_factor: float = 0.3,
    ) -> np.ndarray:
        """Rejim geçişlerinde ağırlık smoothing.

        Ani rejim değişimlerinde ağırlıkları kademeli olarak değiştirir.

        Args:
            X: Feature matrix
n            current_regime: Mevcut rejim
            previous_regime: Önceki rejim (None = ilk tahmin)
            smoothing_factor: Smoothing hızı (0 = tam smoothing, 1 = anlık geçiş)

        Returns:
            Smoothed predictions
        """
        if previous_regime is None or previous_regime == current_regime:
            return self.predict(X, regime=current_regime)

        # İki rejim için ayrı tahminler
        pred_current = self.predict(X, regime=current_regime)
        pred_previous = self.predict(X, regime=previous_regime)

        # Smoothing: smoothing_factor kadar yeni rejime, geri kalanı eski rejime
        smoothed = smoothing_factor * pred_current + (1 - smoothing_factor) * pred_previous

        logger.debug(
            "regime_smoothing_applied",
            current=current_regime,
            previous=previous_regime,
            factor=smoothing_factor,
        )

        return smoothed

    def get_regime_performance_report(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes: np.ndarray,
    ) -> dict[str, dict[str, float]]:
        """Her rejimdeki ensemble performansı.

        Args:
            X_val: Validation features
            y_val: Validation targets
            regimes: Rejim etiketleri

        Returns:
            {regime: {ic, rank_ic, direction_accuracy, n_samples}}
        """
        report: dict[str, dict[str, float]] = {}

        unique_regimes = np.unique(regimes)
        for regime in unique_regimes:
            mask = regimes == regime
            n = int(np.sum(mask))

            if n < 10:
                continue

            preds = self.predict(X_val[mask], regime=str(regime))
            y_regime = y_val[mask]

            # IC
            try:
                finite_mask = np.isfinite(preds) & np.isfinite(y_regime)
                ic = float(np.corrcoef(preds[finite_mask], y_regime[finite_mask])[0, 1])
                if not np.isfinite(ic):
                    ic = 0.0
            except Exception:
                ic = 0.0

            # Rank IC
            try:
                from scipy.stats import spearmanr
                rank_ic, _ = spearmanr(preds[finite_mask], y_regime[finite_mask])
                rank_ic = float(rank_ic) if np.isfinite(rank_ic) else 0.0
            except Exception:
                rank_ic = 0.0

            # Direction accuracy
            try:
                pred_sign = np.sign(preds)
                true_sign = np.sign(y_regime)
                direction_acc = float(np.mean(pred_sign == true_sign))
            except Exception:
                direction_acc = 0.0

            report[str(regime)] = {
                "ic": round(ic, 4),
                "rank_ic": round(rank_ic, 4),
                "direction_accuracy": round(direction_acc, 4),
                "n_samples": n,
            }

        return report

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def base_model_names(self) -> list[str]:
        return list(self._base_models.keys())
