"""ALPHA BIST — Champion-Challenger (Nihai).

Shadow mode, A/B test, auto-promote/reject, rollback.
"""
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from scipy import stats
import structlog

logger = structlog.get_logger()


@dataclass
class ABTestResult:
    """A/B test sonucu."""
    champion_metric: float
    challenger_metric: float
    p_value: float
    significant: bool
    winner: str  # champion, challenger, tie
    n_samples_champion: int
    n_samples_challenger: int
    confidence_level: float


class ChampionChallenger:
    """Champion-challenger sistemi — shadow mode, A/B test, promote/reject."""

    def __init__(
        self,
        significance_level: float = 0.05,
        min_samples: int = 30,
        auto_promote_threshold: float = 0.05,
    ):
        self.significance_level = significance_level
        self.min_samples = min_samples
        self.auto_promote_threshold = auto_promote_threshold
        self._shadow_results: Dict[str, List[float]] = {}  # model_key → [metrics]
        self._champion_results: List[float] = []

    def record_shadow_result(self, model_key: str, metric: float):
        """Shadow mode sonucu kaydet."""
        if model_key not in self._shadow_results:
            self._shadow_results[model_key] = []
        self._shadow_results[model_key].append(metric)

    def record_champion_result(self, metric: float):
        """Champion sonucu kaydet."""
        self._champion_results.append(metric)

    def run_ab_test(
        self,
        challenger_key: str,
        metric_name: str = "return",
    ) -> ABTestResult:
        """A/B test çalıştır — champion vs challenger.

        Two-sample t-test ile istatistiksel karşılaştırma.
        """
        champion_metrics = np.array(self._champion_results)
        challenger_metrics = np.array(self._shadow_results.get(challenger_key, []))

        n_champ = len(champion_metrics)
        n_chall = len(challenger_metrics)

        if n_champ < self.min_samples or n_chall < self.min_samples:
            return ABTestResult(
                champion_metric=float(np.mean(champion_metrics)) if n_champ > 0 else 0,
                challenger_metric=float(np.mean(challenger_metrics)) if n_chall > 0 else 0,
                p_value=1.0,
                significant=False,
                winner="insufficient_data",
                n_samples_champion=n_champ,
                n_samples_challenger=n_chall,
                confidence_level=1 - self.significance_level,
            )

        # Two-sample t-test
        t_stat, p_value = stats.ttest_ind(challenger_metrics, champion_metrics)

        champ_mean = float(np.mean(champion_metrics))
        chall_mean = float(np.mean(challenger_metrics))

        # Winner belirle
        if p_value < self.significance_level:
            if chall_mean > champ_mean:
                winner = "challenger"
            else:
                winner = "champion"
        else:
            winner = "tie"

        result = ABTestResult(
            champion_metric=round(champ_mean, 4),
            challenger_metric=round(chall_mean, 4),
            p_value=round(float(p_value), 4),
            significant=p_value < self.significance_level,
            winner=winner,
            n_samples_champion=n_champ,
            n_samples_challenger=n_chall,
            confidence_level=round(1 - self.significance_level, 4),
        )

        logger.info("ab_test_completed", challenger=challenger_key, winner=winner, p_value=p_value)
        return result

    def should_promote(self, challenger_key: str) -> Dict[str, Any]:
        """Challenger otomatik promote edilmeli mi?"""
        ab_result = self.run_ab_test(challenger_key)

        if ab_result.winner == "challenger" and ab_result.significant:
            return {
                "promote": True,
                "reason": "Challenger statistically significantly better",
                "ab_test": ab_result,
            }
        elif ab_result.winner == "insufficient_data":
            return {
                "promote": False,
                "reason": "Insufficient data for A/B test",
                "ab_test": ab_result,
            }
        else:
            return {
                "promote": False,
                "reason": f"Challenger not significantly better (winner={ab_result.winner})",
                "ab_test": ab_result,
            }

    def get_shadow_summary(self) -> Dict[str, Any]:
        """Shadow mode özet istatistikleri."""
        summary = {}
        for key, metrics in self._shadow_results.items():
            if metrics:
                summary[key] = {
                    "n_samples": len(metrics),
                    "mean": round(float(np.mean(metrics)), 4),
                    "std": round(float(np.std(metrics)), 4),
                    "min": round(float(np.min(metrics)), 4),
                    "max": round(float(np.max(metrics)), 4),
                }
        return summary

    def reset(self, challenger_key: Optional[str] = None):
        """Shadow sonuçlarını sıfırla."""
        if challenger_key:
            self._shadow_results.pop(challenger_key, None)
        else:
            self._shadow_results.clear()
            self._champion_results.clear()
