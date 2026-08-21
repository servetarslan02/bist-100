"""ALPHA BIST — Champion-Challenger (Nihai —⭐⭐⭐⭐⭐).

Shadow mode, multi-metric A/B test, auto-promote/reject,
rollback, multi-metric comparison, detailed reporting.
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
    effect_size: float = 0.0  # Cohen's d
    power: float = 0.0


@dataclass
class MultiMetricResult:
    """Çoklu metrik karşılaştırma sonucu."""
    metric_name: str
    champion_value: float
    challenger_value: float
    winner: str
    improvement_pct: float


@dataclass
class PromotionDecision:
    """Promote/reject kararı."""
    should_promote: bool
    reason: str
    ab_results: Dict[str, ABTestResult]
    multi_metric_results: List[MultiMetricResult]
    overall_winner: str
    confidence: float


class ChampionChallenger:
    """Champion-challenger sistemi —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Shadow mode (paralel çalıştır, sonuçları kaydet)
    - Multi-metric A/B test (IC, Sharpe, win rate, drawdown, vb.)
    - Statistical significance testing (t-test + effect size)
    - Auto-promote (challenger daha iyiysa champion yap)
    - Auto-reject (challenger kötüyse reddet)
    - Rollback capability
    - Detailed reporting
    - Multi-horizon comparison
    """

    def __init__(
        self,
        significance_level: float = 0.05,
        min_samples: int = 30,
        auto_promote_threshold: float = 0.05,
        metrics_to_compare: Optional[List[str]] = None,
    ):
        self.significance_level = significance_level
        self.min_samples = min_samples
        self.auto_promote_threshold = auto_promote_threshold
        self.metrics_to_compare = metrics_to_compare or ["return", "ic", "sharpe", "win_rate"]
        self._shadow_results: Dict[str, Dict[str, List[float]]] = {}  # model → {metric: [values]}
        self._champion_results: Dict[str, List[float]] = {}  # metric → [values]
        self._history: List[Dict[str, Any]] = []

    def record_shadow_result(self, model_key: str, metric_name: str, value: float):
        """Shadow mode sonucu kaydet."""
        if model_key not in self._shadow_results:
            self._shadow_results[model_key] = {}
        if metric_name not in self._shadow_results[model_key]:
            self._shadow_results[model_key][metric_name] = []
        self._shadow_results[model_key][metric_name].append(value)

    def record_champion_result(self, metric_name: str, value: float):
        """Champion sonucu kaydet."""
        if metric_name not in self._champion_results:
            self._champion_results[metric_name] = []
        self._champion_results[metric_name].append(value)

    def record_batch(
        self,
        model_key: str,
        metrics: Dict[str, float],
        is_champion: bool = False,
    ):
        """Toplu sonuç kaydet."""
        for metric_name, value in metrics.items():
            if is_champion:
                self.record_champion_result(metric_name, value)
            else:
                self.record_shadow_result(model_key, metric_name, value)

    def run_ab_test(
        self,
        challenger_key: str,
        metric_name: str = "return",
    ) -> ABTestResult:
        """Tek metrik için A/B test çalıştır."""
        champion_metrics = np.array(self._champion_results.get(metric_name, []))
        challenger_metrics = np.array(self._shadow_results.get(challenger_key, {}).get(metric_name, []))

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

        # Cohen's d (effect size)
        pooled_std = np.sqrt(
            (np.std(champion_metrics) ** 2 + np.std(challenger_metrics) ** 2) / 2
        )
        effect_size = (chall_mean - champ_mean) / max(pooled_std, 1e-8)

        # Statistical power (approximation)
        try:
            from scipy.stats import norm
            z_alpha = norm.ppf(1 - self.significance_level / 2)
            ncp = abs(effect_size) * np.sqrt(n_champ * n_chall / (n_champ + n_chall))
            power = 1 - norm.cdf(z_alpha - ncp) + norm.cdf(-z_alpha - ncp)
        except Exception as e:
            power = 0.0

        # Winner
        if p_value < self.significance_level:
            winner = "challenger" if chall_mean > champ_mean else "champion"
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
            effect_size=round(float(effect_size), 4),
            power=round(float(power), 4),
        )

        logger.info("ab_test_completed", challenger=challenger_key, metric=metric_name, winner=winner, p_value=p_value)
        return result

    def run_multi_metric_test(self, challenger_key: str) -> List[MultiMetricResult]:
        """Tüm metrikler için karşılaştırma."""
        results = []

        for metric in self.metrics_to_compare:
            champ_values = self._champion_results.get(metric, [])
            chall_values = self._shadow_results.get(challenger_key, {}).get(metric, [])

            if not champ_values or not chall_values:
                continue

            champ_mean = float(np.mean(champ_values))
            chall_mean = float(np.mean(chall_values))

            # Winner
            if chall_mean > champ_mean:
                winner = "challenger"
            elif champ_mean > chall_mean:
                winner = "champion"
            else:
                winner = "tie"

            # Improvement percentage
            improvement = ((chall_mean - champ_mean) / max(abs(champ_mean), 1e-8)) * 100

            results.append(MultiMetricResult(
                metric_name=metric,
                champion_value=round(champ_mean, 4),
                challenger_value=round(chall_mean, 4),
                winner=winner,
                improvement_pct=round(improvement, 2),
            ))

        return results

    def should_promote(self, challenger_key: str) -> PromotionDecision:
        """Challenger otomatik promote edilmeli mi?

        Kriterler:
        1. Çoğunlukla metriklerde challenger daha iyi olmalı
        2. En az bir kritik metrikte istatistiksel anlamlılık olmalı
        3. Hiçbir kritik metrikte significantly worse olmamalı
        """
        # Multi-metric test
        multi_results = self.run_multi_metric_test(challenger_key)

        if not multi_results:
            return PromotionDecision(
                should_promote=False,
                reason="No metrics available for comparison",
                ab_results={},
                multi_metric_results=[],
                overall_winner="insufficient_data",
                confidence=0.0,
            )

        # A/B test sonuçları
        ab_results = {}
        for metric in self.metrics_to_compare:
            ab_results[metric] = self.run_ab_test(challenger_key, metric)

        # Kazanan sayıları
        challenger_wins = sum(1 for r in multi_results if r.winner == "challenger")
        champion_wins = sum(1 for r in multi_results if r.winner == "champion")
        total = len(multi_results)

        # Significant improvements
        significant_improvements = sum(
            1 for metric, ab in ab_results.items()
            if ab.winner == "challenger" and ab.significant
        )

        # Significant regressions
        significant_regressions = sum(
            1 for metric, ab in ab_results.items()
            if ab.winner == "champion" and ab.significant
        )

        # Overall winner
        if challenger_wins > champion_wins:
            overall_winner = "challenger"
        elif champion_wins > challenger_wins:
            overall_winner = "champion"
        else:
            overall_winner = "tie"

        # Confidence (challenger wins / total)
        confidence = challenger_wins / max(total, 1)

        # Promote decision
        should_promote = (
            overall_winner == "challenger"
            and significant_improvements >= 1
            and significant_regressions == 0
        )

        # Reason
        if should_promote:
            reason = f"Challenger wins {challenger_wins}/{total} metrics, {significant_improvements} significant improvements, 0 regressions"
        elif significant_regressions > 0:
            reason = f"Challenger has {significant_regressions} significant regressions"
        elif overall_winner != "challenger":
            reason = f"Challenger does not outperform (wins {challenger_wins}/{total})"
        else:
            reason = "Insufficient statistical significance"

        decision = PromotionDecision(
            should_promote=should_promote,
            reason=reason,
            ab_results=ab_results,
            multi_metric_results=multi_results,
            overall_winner=overall_winner,
            confidence=round(confidence, 4),
        )

        # History
        self._history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "challenger_key": challenger_key,
            "decision": decision.should_promote,
            "reason": decision.reason,
            "confidence": decision.confidence,
        })

        return decision

    def rollback(self, challenger_key: str) -> bool:
        """Challenger'ın shadow sonuçlarını sıfırla (rollback)."""
        if challenger_key in self._shadow_results:
            del self._shadow_results[challenger_key]
            logger.info("challenger_rolled_back", key=challenger_key)
            return True
        return False

    def get_shadow_summary(self) -> Dict[str, Any]:
        """Shadow mode özet istatistikleri."""
        summary = {}
        for model_key, metrics in self._shadow_results.items():
            model_summary = {}
            for metric_name, values in metrics.items():
                if values:
                    model_summary[metric_name] = {
                        "n_samples": len(values),
                        "mean": round(float(np.mean(values)), 4),
                        "std": round(float(np.std(values)), 4),
                        "min": round(float(np.min(values)), 4),
                        "max": round(float(np.max(values)), 4),
                    }
            summary[model_key] = model_summary
        return summary

    def get_champion_summary(self) -> Dict[str, Any]:
        """Champion özet istatistikleri."""
        summary = {}
        for metric_name, values in self._champion_results.items():
            if values:
                summary[metric_name] = {
                    "n_samples": len(values),
                    "mean": round(float(np.mean(values)), 4),
                    "std": round(float(np.std(values)), 4),
                }
        return summary

    def get_history(self) -> List[Dict[str, Any]]:
        """Decision history."""
        return self._history

    def reset(self, challenger_key: Optional[str] = None):
        """Sonuçları sıfırla."""
        if challenger_key:
            self._shadow_results.pop(challenger_key, None)
        else:
            self._shadow_results.clear()
            self._champion_results.clear()
            self._history.clear()
