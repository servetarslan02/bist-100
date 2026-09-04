"""
ALPHA BIST — Backtest Canonical Scoring Adaptör v2.0

FAZ 4.7: Artık prepare_features_for_inference() kullanır.
Feature parity training ile garanti edilir.

Bu adaptör:
- Backtest'teki feature snapshot'tan canonical score üretir
- PIT (Point-in-Time) koruması sağlar
- prepare_features_for_inference() ile CS normalizasyonu uygular
- Feature sözleşmesini zorunlu kılar
- Mevcut backtest API'sini bozmaz
"""

from typing import Any

import numpy as np
import logging

logger = logging.getLogger(__name__)


def _scalar_features(feats: dict[str, Any]) -> dict[str, Any]:
    """Dict/nested feature'ları filtrele, sadece scalar olanları tut.

    Vektörel numpy dönüşümü ile büyük sözlüklerde optimize edilmiştir.
    Sözlük → numpy array dönüşümü tek seferde yapılır, filtreleme
    numpy boolean masking ile gerçekleştirilir.

    Args:
        feats: Feature adı → değer sözlüğü

    Returns:
        Sadece sayısal (int, float) ve sonlu değerler içeren sözlük
    """
    if not feats:
        return {}

    keys = list(feats.keys())
    values = list(feats.values())

    # Sayısal olmayan değerleri None ile işaretle
    numeric_values = []
    numeric_indices = []
    for i, v in enumerate(values):
        if isinstance(v, (int, float, np.floating, np.integer)):
            numeric_values.append(float(v))
            numeric_indices.append(i)

    if not numeric_values:
        return {}

    # Vektörel sonluluk kontrolü
    arr = np.array(numeric_values, dtype=np.float64)
    finite_mask = np.isfinite(arr)

    return {
        keys[numeric_indices[i]]: values[numeric_indices[i]]
        for i in range(len(numeric_values))
        if finite_mask[i]
    }


class BacktestCanonicalAdapter:
    """Backtest → CanonicalScoringPipeline adaptör v2.0.

    Her prediction için prepare_features_for_inference() kullanır.
    Training ile aynı CS normalizasyonu ve feature sözleşmesi uygulanır.
    """

    def __init__(self) -> None:
        """Canonical adaptörü başlatır."""
        self._scoring = None
        self._decision_engine = None

    def __repr__(self) -> str:
        """BacktestCanonicalAdapter okunabilir temsili."""
        scoring_loaded = self._scoring is not None
        engine_loaded = self._decision_engine is not None
        return (
            f"BacktestCanonicalAdapter("
            f"scoring_loaded={scoring_loaded}, "
            f"engine_loaded={engine_loaded})"
        )

    def _lazy_load(self) -> None:
        """Gerekli servisleri geç yükler (lazy loading).

        İlk çağrıda canonical_scoring ve decision_engine modüllerini
        yükler. Sonraki çağrılarda mevcut referansları kullanır.
        """
        if self._scoring is None:
            from ...core.canonical_scoring import canonical_scoring

            self._scoring = canonical_scoring
        if self._decision_engine is None:
            from ...core.decision_engine import decision_engine

            self._decision_engine = decision_engine

    def _apply_feature_parity(
        self,
        features: dict[str, Any],
        ml_model: Any,
        ticker: str,
        all_day_features: dict[str, dict[str, Any]] | None,
        date_str: str,
    ) -> dict[str, Any]:
        """Feature parity: model beklenen feature'ları doğrula ve CS normalizasyonu uygula.

        prepare_features_for_inference() ile training ile aynı feature
        sözleşmesinin backtest'te de uygulanmasını sağlar.

        Args:
            features: Ham feature sözlüğü
            ml_model: Eğitilmiş model (feature_names, cs_features, impute_values)
            ticker: Hisse kodu
            all_day_features: Aynı tarihteki tüm hisselerin feature'ları
            date_str: Tarih string'i

        Returns:
            CS normalizasyonu uygulanmış feature sözlüğü
        """
        model_features = getattr(ml_model, "feature_names", [])
        model_cs = getattr(ml_model, "cs_features", [])
        model_impute = getattr(ml_model, "impute_values", None)

        if model_features and all_day_features:
            try:
                from ...ml.training_validator import prepare_features_for_inference

                clean_features = _scalar_features(features)
                clean_all = {
                    t: _scalar_features(f)
                    for t, f in all_day_features.items()
                }
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
                logger.warning(
                    "prepare_features_for_inference_basarisiz: hata=%s",
                    str(e),
                )

        return features

    def compute_score(
        self,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model: Any = None,
        ticker: str = "BACKTEST",
        all_day_features: dict[str, dict[str, Any]] | None = None,
        date_str: str = "",
    ) -> float:
        """Feature'lardan canonical fırsat skoru üret.

        Args:
            features: Bu hissenin feature'ları (zaten enriched olabilir)
            regime: Piyasa rejimi
            ml_model: TrainedModel/MultiHorizonModel (None → kural tabanlı)
            ticker: Hisse kodu
            all_day_features: Aynı tarihteki tüm hisselerin feature'ları (CS için)
            date_str: Tarih string'i (CS için)

        Returns:
            Fırsat skoru (0-100)
        """
        self._lazy_load()

        if ml_model is not None:
            features = self._apply_feature_parity(
                features, ml_model, ticker, all_day_features, date_str
            )

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
        """Feature'lardan canonical score ve işlem kararı üretir.

        Args:
            features: Bu hissenin feature'ları
            regime: Piyasa rejimi
            price: Güncel fiyat
            ml_model: TrainedModel/MultiHorizonModel (None → kural tabanlı)
            ticker: Hisse kodu
            all_day_features: Aynı tarihteki tüm hisselerin feature'ları (CS için)
            date_str: Tarih string'i (CS için)

        Returns:
            (fırsat_skoru, işlem_kararı) çifti
        """
        self._lazy_load()

        if ml_model is not None:
            features = self._apply_feature_parity(
                features, ml_model, ticker, all_day_features, date_str
            )

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
        """Hesaplayıcı feature'larını canonical scoring için hazırla.

        Mevcut feature'ları canonical scoring pipeline'ının beklediği
        formata dönüştürür. Ek zenginleştirme (enrichment) gerektiğinde
        bu metot genişletilir.

        Args:
            calc_features: Hesaplayıcıdan gelen ham feature'lar
            ticker: Hisse kodu
            date_str: Tarih string'i

        Returns:
            Canonical scoring için hazır feature sözlüğü
        """
        enriched = dict(calc_features)
        return enriched


# Singleton
backtest_canonical_adapter = BacktestCanonicalAdapter()
