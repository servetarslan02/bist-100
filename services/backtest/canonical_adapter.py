"""
ALPHA BIST — Backtest Canonical Scoring Adapter

Backtest engine ile CanonicalScoringPipeline arasında köprü.

Bu adapter:
- Backtest'teki feature snapshot'tan canonical score üretir
- PIT (Point-in-Time) koruması sağlar
- Mevcut backtest API'sini bozmaz
- Eksik motor feature'larını graceful handle eder

KURAL: Bu adapter backtest'in strateji kurallarını DEĞİŞTİRMEZ.
Sadece skor hesaplama mekanizmasını canonical hale getirir.
"""

from typing import Dict, Any, Optional
import numpy as np
import structlog

logger = structlog.get_logger()


class BacktestCanonicalAdapter:
    """Backtest → CanonicalScoringPipeline adapter.

    Backtest'te mevcut olan feature'lardan canonical score üretir.
    Motor5 (KAP/news), Motor6 (catalyst), Motor9 (seasonality) gibi
    anlık veri gerektiren motorlar backtest'te mevcut değildir;
    bu durumda ilgili boyut0 (bilgi yok) olarak işaretlenir.
    """

    def __init__(self):
        self._scoring = None
        self._decision_engine = None

    def _lazy_load(self):
        if self._scoring is None:
            from services.core.canonical_scoring import canonical_scoring
            self._scoring = canonical_scoring
        if self._decision_engine is None:
            from services.core.decision_engine import decision_engine
            self._decision_engine = decision_engine

    def compute_score(
        self,
        features: Dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model=None,
    ) -> float:
        """Feature'lardan canonical opportunity score üret.

        Backtest engine bu skoru BUY/SELL kararı için kullanır.

        Args:
            features: Calculator output (teknik feature'lar)
            regime: Piyasa rejimi
            ml_model: TrainedModel instance (None → rule-based only)

        Returns:
            Opportunity score (0-100)
        """
        self._lazy_load()

        # Canonical score hesapla
        cs = self._scoring.compute_canonical_score(
            ticker="BACKTEST",
            features=features,
            regime=regime,
            ml_model=ml_model,
        )

        return cs.opportunity_score

    def compute_score_and_decision(
        self,
        features: Dict[str, Any],
        regime: str = "UNKNOWN",
        price: float = 0,
        ml_model=None,
    ):
        """Feature'lardan canonical score + decision üret.

        Returns:
            (opportunity_score, decision_action)
        """
        self._lazy_load()

        cs = self._scoring.compute_canonical_score(
            ticker="BACKTEST",
            features=features,
            regime=regime,
            ml_model=ml_model,
        )

        decision = self._decision_engine.decide_from_canonical(cs, price=price)

        return cs.opportunity_score, decision.action

    def enrich_features_for_canonical(
        self,
        calc_features: Dict[str, Any],
        ticker: str = "",
        date_str: str = "",
    ) -> Dict[str, Any]:
        """Calculator feature'larını canonical scoring için hazırla.

        Backtest'te sadece calculator feature'ları mevcuttur.
        Motor5/6/9 gibi anlık veri gerektiren motorlar çalıştırılamaz.
        Bu fonksiyon, calculator output'unu canonical scoring'in
        beklediği formata dönüştürür.

        PIT KORUMASI: Bu fonksiyon gelecekteki veriyi KULLANMAZ.
        Sadece mevcut calculator feature'larını dönüştürür.
        """
        enriched = dict(calc_features)

        # Calculator feature'larından canonical boyutlara mapping
        # (canonical_scoring._score_* metodları bu isimleri bekler)

        # Motor 1 (RS) — calculator'da rs_vs_bist yok, ama
        # cross-sectional rank feature'ları var
        # → canonical scoring bu feature'ları0 olarak işler (bilgi yok)

        # Motor 4 (Fundamental) — backtest'te mevcut değil
        # → canonical scoring fundamental boyutunu0 olarak işler

        # Motor 5 (KAP/News) — backtest'te mevcut değil
        # → canonical scoring news_sentiment boyutunu50 (nötr) olarak işler

        # Motor 6 (Catalyst) — backtest'te mevcut değil
        # → canonical scoring catalyst boyutunu50 (nötr) olarak işler

        # Motor 9 (Seasonality) — tarih varsa hesaplanabilir
        # Ama backtest'te dates DataFrame'de mevcut
        # → canonical scoring seasonality boyutunu50 (nötr) olarak işler

        # Canonical scoring zaten eksik feature'ları graceful handle eder.
        # Bu fonksiyon sadece mapping'i doğrular.

        return enriched


# Singleton
backtest_canonical_adapter = BacktestCanonicalAdapter()
