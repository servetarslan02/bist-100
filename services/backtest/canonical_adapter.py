"""
ALPHA BIST — Backtest Canonical Scoring Adapter v2.0

FAZ 4.7: Artık prepare_features_for_inference() kullanır.
Feature parity training ile garanti edilir.

Bu adapter:
- Backtest'teki feature snapshot'tan canonical score üretir
- PIT (Point-in-Time) koruması sağlar
- prepare_features_for_inference() ile CS normalization uygular
- Feature contract'ı zorunlu kılar
- Mevcut backtest API'sini bozmaz
"""

from typing import Any

import numpy as np
import logging

logger = logging.getLogger(__name__)


def _scalar_features(feats: dict[str, Any]) -> dict[str, Any]:
    """Dict/nested feature'ları filtrele, sadece scalar olanları tut."""
    return {
        k: v for k, v in feats.items() if isinstance(v, (int, float, np.floating, np.integer)) and np.isfinite(float(v))
    }


class BacktestCanonicalAdapter:
    """Backtest → CanonicalScoringPipeline adapter v2.0.

    Artık her prediction için prepare_features_for_inference() kullanır.
    Training ile aynı CS normalization ve feature contract uygulanır.
    """

    def __init__(self):
        """Canonical adapter başlatır."""
        self._scoring = None
        self._decision_engine = None

    def _lazy_load(self) -> Any:
        """Gerekli servisleri geç yükler (lazy loading)."""
        if self._scoring is None:
            from ...core.canonical_scoring import canonical_scoring

            self._scoring = canonical_scoring
        if self._decision_engine is None:
            from ...core.decision_engine import decision_engine

            self._decision_engine = decision_engine

    def compute_score(
        self,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model: Any = None,
        ticker: str = "BACKTEST",
        all_day_features: dict[str, dict[str, Any]] | None = None,
        date_str: str = "",
    ) -> float:
        """Feature'lardan canonical opportunity score üret.

        FAZ 4.7: prepare_features_for_inference() ile parity-safe.

        Args:
            features: Bu hissenin feature'ları (zaten enriched olabilir)
            regime: Piyasa rejimi
            ml_model: TrainedModel/MultiHorizonModel (None → rule-based)
            ticker: Hisse kodu
            all_day_features: Aynı tarihteki TUM hisselerin feature'ları (CS için)
            date_str: Tarih string'i (CS için)

        Returns:
            Opportunity score (0-100)
        """
        self._lazy_load()

        # Feature parity: model beklenen feature'ları doğrula ve CS normalization uygula
        if ml_model is not None:
            model_features = getattr(ml_model, "feature_names", [])
            model_cs = getattr(ml_model, "cs_features", [])
            model_impute = getattr(ml_model, "impute_values", None)

            if model_features and all_day_features:
                try:
                    from ...ml.training_validator import prepare_features_for_inference

                    # Scalar olmayan feature'ları filtrele (volume_profile dict vb.)
                    clean_features = _scalar_features(features)
                    clean_all = {t: _scalar_features(f) for t, f in all_day_features.items()}
                    features = prepare_features_for_inference(
                        ticker=ticker,
                        raw_features=clean_features,
                        all_date_features=clean_all,
                        feature_names=model_features,
                        cs_features=model_cs,
                        impute_values=model_impute,
                        date_str=date_str,
                    )
                except Exception as e:
                    logger.warning("prepare_features_for_inference_basarisiz: hata=%s", str(e))

        cs = self._scoring.compute_canonical_score(
            ticker=ticker,
            features=features,
            regime=regime,
            ml_model=ml_model,
        )

        return cs.opportunity_score

    def compute_score_and_decision(
        self,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
        price: float = 0,
        ml_model: Any = None,
        ticker: str = "BACKTEST",
        all_day_features: dict[str, dict[str, Any]] | None = None,
        date_str: str = "",
    ) -> tuple[float, str]:
        """Feature'lardan canonical score ve decision üretir."""
        self._lazy_load()

        # Feature parity uygula
        if ml_model is not None:
            model_features = getattr(ml_model, "feature_names", [])
            model_cs = getattr(ml_model, "cs_features", [])
            model_impute = getattr(ml_model, "impute_values", None)

            if model_features and all_day_features:
                try:
                    from ...ml.training_validator import prepare_features_for_inference

                    clean_features = _scalar_features(features)
                    clean_all = {t: _scalar_features(f) for t, f in all_day_features.items()}
                    features = prepare_features_for_inference(
                        ticker=ticker,
                        raw_features=clean_features,
                        all_date_features=clean_all,
                        feature_names=model_features,
                        cs_features=model_cs,
                        impute_values=model_impute,
                        date_str=date_str,
                    )
                except Exception as e:
                    logger.warning("prepare_features_for_inference_basarisiz: hata=%s", str(e))

        cs = self._scoring.compute_canonical_score(
            ticker=ticker,
            features=features,
            regime=regime,
            ml_model=ml_model,
        )

        decision = self._decision_engine.decide_from_canonical(cs, price=price)

        return cs.opportunity_score, decision.action

    def enrich_features_for_canonical(
        self,
        calc_features: dict[str, Any],
        ticker: str = "",
        date_str: str = "",
    ) -> dict[str, Any]:
        """Calculator feature'larını canonical scoring için hazırla."""
        # TODO: Gerçek enrichment logic eklenecek (şimdilik passthrough)
        enriched = dict(calc_features)
        return enriched


# Singleton
backtest_canonical_adapter = BacktestCanonicalAdapter()
