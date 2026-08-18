"""ALPHA BIST — Stacking Ensemble (Nihai).

Base models → meta-learner ile model birleştirme.
Nature (2026) metodolojisi: Ridge meta-learner.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class StackingConfig:
    """Stacking ensemble konfigürasyonu."""
    meta_learner_type: str = "ridge"  # ridge, logistic, linear
    cv_folds: int = 5
    use_proba: bool = True  # predict_proba kullan
    passthrough: bool = False  # Original features de meta-learner'a gitsin


class StackingEnsemble:
    """Stacking ensemble — meta-learner ile model birleştirme.

    Nature (2026): Base model predictions → Ridge meta-learner
    Cross-validated stacking: data leakage önleme.
    """

    def __init__(self, config: Optional[StackingConfig] = None):
        self._config = config or StackingConfig()
        self._base_models: Dict[str, Any] = {}
        self._meta_learner = None
        self._model_weights: Dict[str, float] = {}
        self._is_fitted = False

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
    ) -> Dict[str, Any]:
        """Stacking ensemble eğit.

        Cross-validated stacking: base modellerin validation predictions'ı
        meta-learner'ın training verisi olarak kullanılır (data leakage yok).

        Args:
            X_train: Eğitim verisi
            y_train: Eğitim label
            X_val: Validation verisi
            y_val: Validation label

        Returns:
            Training metrics
        """
        from sklearn.model_selection import KFold
        from sklearn.linear_model import Ridge, LogisticRegression, LinearRegression

        if len(self._base_models) < 2:
            return {"error": "Need at least 2 base models"}

        # Cross-validated stacking
        kf = KFold(n_splits=self._config.cv_folds, shuffle=True, random_state=42)
        meta_features_train = np.zeros((len(X_train), len(self._base_models)))

        for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X_train)):
            X_tr, X_vl = X_train[train_idx], X_train[val_idx]
            y_tr = y_train[train_idx]

            for model_idx, (name, model) in enumerate(self._base_models.items()):
                try:
                    # Her fold'da modeli eğit
                    import copy
                    fold_model = copy.deepcopy(model)

                    if hasattr(fold_model, "fit"):
                        fold_model.fit(X_tr, y_tr)

                    # Validation predictions
                    if self._config.use_proba and hasattr(fold_model, "predict_proba"):
                        meta_features_train[val_idx, model_idx] = fold_model.predict_proba(X_vl)[:, 1]
                    else:
                        meta_features_train[val_idx, model_idx] = fold_model.predict(X_vl)

                except Exception as e:
                    logger.warning("stacking_fold_failed", model=name, fold=fold_idx, error=str(e))
                    meta_features_train[val_idx, model_idx] = 0.5

        # Meta-learner'ı eğit (tüm cross-validated predictions üzerinde)
        if self._config.passthrough:
            meta_features_train = np.hstack([meta_features_train, X_train])

        if self._config.meta_learner_type == "ridge":
            self._meta_learner = Ridge(alpha=1.0)
        elif self._config.meta_learner_type == "logistic":
            self._meta_learner = LogisticRegression(max_iter=1000)
        else:
            self._meta_learner = LinearRegression()

        self._meta_learner.fit(meta_features_train, y_train)

        # Base modelleri tüm eğitim verisi üzerinde eğit
        for name, model in self._base_models.items():
            try:
                model.fit(X_train, y_train)
            except Exception as e:
                logger.warning("base_model_fit_failed", model=name, error=str(e))

        self._is_fitted = True

        # Validation metrics
        val_pred = self.predict(X_val)
        from sklearn.metrics import roc_auc_score, mean_squared_error
        try:
            auc = float(roc_auc_score(y_val, val_pred))
        except Exception:
            auc = 0.0

        metrics = {
            "n_base_models": len(self._base_models),
            "cv_folds": self._config.cv_folds,
            "meta_learner": self._config.meta_learner_type,
            "val_auc": round(auc, 4),
        }

        logger.info("stacking_ensemble_fitted", **metrics)
        return metrics

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Stacking prediction."""
        if not self._is_fitted:
            return np.zeros(len(X))

        # Base model predictions
        meta_features = np.zeros((len(X), len(self._base_models)))
        for model_idx, (name, model) in enumerate(self._base_models.items()):
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    meta_features[:, model_idx] = model.predict_proba(X)[:, 1]
                else:
                    meta_features[:, model_idx] = model.predict(X)
            except Exception:
                meta_features[:, model_idx] = 0.5

        if self._config.passthrough:
            meta_features = np.hstack([meta_features, X])

        # Meta-learner prediction
        try:
            if hasattr(self._meta_learner, "predict_proba"):
                return self._meta_learner.predict_proba(meta_features)[:, 1]
            return self._meta_learner.predict(meta_features)
        except Exception:
            return np.zeros(len(X))

    def get_model_weights(self) -> Dict[str, float]:
        """Meta-learner katsayılarını model ağırlığı olarak döndür."""
        if self._meta_learner is None:
            return self._model_weights

        try:
            coefs = self._meta_learner.coef_
            if len(coefs) == len(self._base_models):
                total = sum(abs(c) for c in coefs)
                return {
                    name: round(float(abs(c) / total), 4)
                    for (name, _), c in zip(self._base_models.items(), coefs)
                }
        except Exception:
            pass

        return self._model_weights

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def base_model_names(self) -> List[str]:
        return list(self._base_models.keys())
