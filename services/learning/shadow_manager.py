"""
ALPHA BIST — Shadow Mode Manager v1.0

Yeni model eski modelle paralel çalışır:
- Sonuçlar kaydedilir ama uygulanmaz
- Minimum observation süresi
- Statistical significance test
- Otomatik promote/reject

KURAL: Yeni model doğrudan production'a alınamaz.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import deque
import structlog

from services.learning.config.learning_config import learning_settings
from services.learning.utils.statistical_tests import StatisticalTests

logger = structlog.get_logger()


@dataclass
class ShadowPrediction:
    """Shadow prediction kaydı."""
    ticker: str
    champion_prediction: Dict
    challenger_prediction: Dict
    timestamp: str


@dataclass
class ShadowResult:
    """Shadow mode değerlendirme sonucu."""
    champion_sharpe: float
    challenger_sharpe: float
    champion_winrate: float
    challenger_winrate: float
    improvement_pct: float
    p_value: float
    significant: bool
    recommendation: str  # PROMOTE, REJECT, EXTEND
    days_elapsed: int
    prediction_count: int


class ShadowModeManager:
    """Shadow mode yöneticisi."""

    def __init__(self):
        self._shadow_active: bool = False
        self._champion_id: Optional[str] = None
        self._challenger_id: Optional[str] = None
        self._start_date: Optional[datetime] = None
        self._predictions: deque = deque(maxlen=5000)
        self._champion_returns: deque = deque(maxlen=5000)
        self._challenger_returns: deque = deque(maxlen=5000)

    def start_shadow(self, champion_id: str, challenger_id: str):
        """Shadow mode başlat."""
        self._shadow_active = True
        self._champion_id = champion_id
        self._challenger_id = challenger_id
        self._start_date = datetime.now(timezone.utc)
        self._predictions = deque(maxlen=5000)
        self._champion_returns = deque(maxlen=5000)
        self._challenger_returns = deque(maxlen=5000)

        logger.info("Shadow mode started",
                   champion=champion_id, challenger=challenger_id)

    def record_prediction(
        self,
        ticker: str,
        champion_pred: Dict,
        challenger_pred: Dict,
    ):
        """Her iki modelden prediction kaydet."""
        if not self._shadow_active:
            return

        self._predictions.append(ShadowPrediction(
            ticker=ticker,
            champion_prediction=champion_pred,
            challenger_prediction=challenger_pred,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def record_outcome(self, ticker: str, actual_return: float):
        """Outcome kaydet — her iki model için."""
        if not self._shadow_active:
            return

        # Son prediction'ı bul
        for pred in reversed(self._predictions):
            if pred.ticker == ticker:
                # Champion outcome
                champion_dir = pred.champion_prediction.get("direction", "LONG")
                if champion_dir == "LONG":
                    self._champion_returns.append(actual_return)
                else:
                    self._champion_returns.append(-actual_return)

                # Challenger outcome
                challenger_dir = pred.challenger_prediction.get("direction", "LONG")
                if challenger_dir == "LONG":
                    self._challenger_returns.append(actual_return)
                else:
                    self._challenger_returns.append(-actual_return)
                break

    def evaluate(self) -> Optional[ShadowResult]:
        """Shadow mode sonuçlarını değerlendir."""
        cfg = learning_settings.shadow

        if not self._shadow_active:
            return None

        # Minimum bekleme süresi
        days_elapsed = (datetime.now(timezone.utc) - self._start_date).days
        if days_elapsed < cfg.duration_days:
            logger.info("Shadow mode: not enough time",
                       elapsed=days_elapsed, required=cfg.duration_days)
            return None

        # Minimum prediction sayısı
        if len(self._champion_returns) < cfg.min_predictions:
            logger.info("Shadow mode: not enough predictions",
                       count=len(self._champion_returns), required=cfg.min_predictions)
            return None

        # Metrikler
        champion_sharpe = StatisticalTests.sharpe_ratio(np.array(self._champion_returns))
        challenger_sharpe = StatisticalTests.sharpe_ratio(np.array(self._challenger_returns))

        champion_wr = sum(1 for r in self._champion_returns if r > 0) / len(self._champion_returns) if self._champion_returns else 0
        challenger_wr = sum(1 for r in self._challenger_returns if r > 0) / len(self._challenger_returns) if self._challenger_returns else 0

        # Statistical test
        t_result = StatisticalTests.welch_t_test(
            np.array(self._champion_returns),
            np.array(self._challenger_returns),
            alpha=cfg.significance_p,
        )

        # Improvement
        if champion_sharpe != 0:
            improvement = ((challenger_sharpe - champion_sharpe) / abs(champion_sharpe)) * 100
        else:
            improvement = 0

        # Karar
        if improvement > cfg.promote_threshold_pct and t_result.significant:
            recommendation = "PROMOTE"
        elif improvement < -cfg.promote_threshold_pct:
            recommendation = "REJECT"
        else:
            recommendation = "EXTEND"

        result = ShadowResult(
            champion_sharpe=round(champion_sharpe, 4),
            challenger_sharpe=round(challenger_sharpe, 4),
            champion_winrate=round(champion_wr, 4),
            challenger_winrate=round(challenger_wr, 4),
            improvement_pct=round(improvement, 2),
            p_value=t_result.p_value,
            significant=t_result.significant,
            recommendation=recommendation,
            days_elapsed=days_elapsed,
            prediction_count=len(self._champion_returns),
        )

        logger.info("Shadow mode evaluated",
                   recommendation=recommendation,
                   improvement=round(improvement, 2),
                   p_value=t_result.p_value)

        return result

    def stop_shadow(self):
        """Shadow mode durdur."""
        self._shadow_active = False
        logger.info("Shadow mode stopped",
                   champion=self._champion_id,
                   challenger=self._challenger_id,
                   predictions=len(self._predictions))

    def get_status(self) -> Dict[str, Any]:
        """Shadow mode durumu."""
        return {
            "active": self._shadow_active,
            "champion_id": self._champion_id,
            "challenger_id": self._challenger_id,
            "days_elapsed": (datetime.now(timezone.utc) - self._start_date).days if self._start_date else 0,
            "prediction_count": len(self._predictions),
            "outcome_count": len(self._champion_returns),
        }


# Singleton
shadow_manager = ShadowModeManager()
