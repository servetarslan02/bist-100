"""
ALPHA BIST — Continuous Learning Pipeline v3.0

ROADMAP v3.0 FAZ 7:
- Her gün otomatik güncelleme
- Drift tespiti
- A/B test
- Model versiyonlama
- Meta-learning
- Self-healing

KURAL: Sistem durmadan kendini güncellemeli, dünkü model bugünün piyasasına uymayabilir.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class LearningCycle:
    """Tek öğrenme döngüsü kaydı."""

    cycle_id: str
    timestamp: str
    regime: str
    action: str  # RETRAIN, DRIFT_DETECTED, A_B_TEST, HEALTH_CHECK
    status: str  # SUCCESS, FAILED, PENDING
    metrics_before: dict[str, float]
    metrics_after: dict[str, float]
    model_version: str
    notes: str = ""


@dataclass
class ModelRegistry:
    """Model kayıt defteri."""

    versions: list[dict] = field(default_factory=list)
    active_version: str = ""
    champion_version: str = ""
    performance_history: list[dict] = field(default_factory=list)


class ContinuousLearningPipeline:
    """Sürekli öğrenme pipeline'ı — tam otomatik."""

    def __init__(
        self,
        retrain_interval_days: int | None = None,
        drift_check_interval: int | None = None,
        performance_window: int | None = None,
        min_samples_for_retrain: int | None = None,
    ):
        cfg = learning_settings
        self.retrain_interval_days = retrain_interval_days or cfg.retrain.max_interval_days
        self.drift_check_interval = drift_check_interval or cfg.drift.check_interval_days
        self.performance_window = performance_window or cfg.retrain.performance_window
        self.min_samples_for_retrain = min_samples_for_retrain or cfg.retrain.min_samples

        # Öğrenme döngüsü geçmişi
        self._cycles: deque = deque(maxlen=100)

        # Model kayıt defteri
        self._registry = ModelRegistry()

        # Performans geçmişi
        self._daily_performance: deque = deque(maxlen=252)

        # Son eğitim tarihi
        self._last_retrain_date: datetime | None = None

        # Drift durumu
        self._drift_detected = False
        self._drift_features: list[str] = []

        logger.info(
            "ContinuousLearningPipeline v3.0 initialized",
            retrain_interval=retrain_interval_days,
            drift_interval=drift_check_interval,
        )

    def run_daily_pipeline(
        self,
        date: str,
        features_map: dict[str, dict],
        predictions: list[dict],
        actual_returns: dict[str, float],
        regime: str = "UNKNOWN",
    ) -> dict[str, Any]:
        """Günlük pipeline çalıştır.

        Her gün sabah çalıştırılır:
        1. Dünkü performansı kaydet
        2. Drift kontrolü
        3. Retrain gerekli mi?
        4. A/B test değerlendirme
        5. Model kayıt defterini güncelle
        """
        results = {
            "date": date,
            "regime": regime,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # 1. Performans kaydet
        daily_metrics = self._record_daily_performance(date, predictions, actual_returns)
        results["daily_metrics"] = daily_metrics
        self._daily_performance.append(daily_metrics)
        if len(self._daily_performance) > 1000:
            self._daily_performance = self._daily_performance[-1000:]

        # 2. Drift kontrolü
        if self._should_check_drift(date):
            drift_result = self._check_drift(features_map)
            results["drift_check"] = drift_result
            self._drift_detected = drift_result.get("drift_detected", False)

        # 2.5 Macro regime + surprise kontrolü
        try:
            from services.macro import macro_regime_detector

            # Macro features
            all_macro_features = {}
            for _ticker, feats in features_map.items():
                all_macro_features.update(feats)

            if all_macro_features:
                macro_regime = macro_regime_detector.detect_regime(all_macro_features)
                results["macro_regime"] = {
                    "regime": macro_regime.regime,
                    "confidence": macro_regime.confidence,
                    "description": macro_regime.description,
                }

                # Macro regime değişikliği retrain tetikleyebilir
                if macro_regime.regime in ("STAGFLATION", "RISK_OFF"):
                    logger.warning("Macro regime unfavorable", regime=macro_regime.regime)
                    results["macro_alert"] = True
        except Exception as e:
            logger.debug("Macro check failed", error=str(e))

        # 3. Retrain kararı
        should_retrain = self._should_retrain(date, daily_metrics)
        results["should_retrain"] = should_retrain

        if should_retrain:
            retrain_result = self._execute_retrain(features_map, actual_returns, regime)
            results["retrain_result"] = retrain_result

            cycle = LearningCycle(
                cycle_id=f"retrain_{date}",
                timestamp=datetime.now(UTC).isoformat(),
                regime=regime,
                action="RETRAIN",
                status="SUCCESS" if retrain_result.get("success") else "FAILED",
                metrics_before=daily_metrics,
                metrics_after=retrain_result.get("metrics", {}),
                model_version=retrain_result.get("version_id", ""),
            )
            self._cycles.append(cycle)
            if len(self._cycles) > 500:
                self._cycles = self._cycles[-500:]

        # 4. A/B test değerlendirme
        ab_result = self._evaluate_ab_test(date)
        if ab_result:
            results["ab_test"] = ab_result

        # 5. Kayıt defteri güncelle
        self._update_registry(date, results)

        logger.info(
            "Daily pipeline completed", date=date, regime=regime, retrain=should_retrain, drift=self._drift_detected
        )

        return results

    def _record_daily_performance(
        self,
        date: str,
        predictions: list[dict],
        actual_returns: dict[str, float],
    ) -> dict[str, float]:
        """Günlük performans kaydet."""
        if not predictions or not actual_returns:
            return {"date": date, "sharpe": 0, "ic": 0, "win_rate": 0, "return": 0}

        returns = []
        wins = 0
        scores = []
        actuals = []

        for pred in predictions:
            ticker = pred.get("ticker", "")
            if ticker in actual_returns:
                actual = actual_returns[ticker]
                returns.append(actual)
                scores.append(pred.get("score", 0))
                actuals.append(actual)
                if actual > 0:
                    wins += 1

        if not returns:
            return {"date": date, "sharpe": 0, "ic": 0, "win_rate": 0, "return": 0}

        from services.core.metrics_math import calculate_ic, calculate_sharpe_ratio, calculate_win_rate

        returns_arr = np.array(returns)
        scores_arr = np.array(scores)
        actuals_arr = np.array(actuals)

        sharpe = calculate_sharpe_ratio(returns_arr)
        ic = calculate_ic(scores_arr, actuals_arr)
        win_rate = calculate_win_rate(returns_arr)
        total_return = float(np.sum(returns_arr))

        metrics = {
            "date": date,
            "sharpe": round(sharpe, 4),
            "ic": round(ic, 4),
            "win_rate": round(win_rate, 4),
            "return": round(total_return, 4),
            "n_predictions": len(predictions),
        }

        logger.info("Daily performance recorded", date=date, sharpe=metrics["sharpe"], ic=metrics["ic"])

        return metrics

    def _should_check_drift(self, date: str) -> bool:
        """Drift kontrolü yapılması gerekli mi?"""
        # Her gün kontrol et
        return True

    def _check_drift(self, features_map: dict[str, dict]) -> dict[str, Any]:
        """Feature drift kontrolü."""
        from services.learning.super_intelligence import super_intelligence

        return super_intelligence.detect_drift(features_map)

    def _should_retrain(
        self,
        date: str,
        daily_metrics: dict[str, float],
    ) -> bool:
        """Yeniden eğitim gerekli mi?"""
        cfg = learning_settings.retrain

        # Zorunlu interval
        if self._last_retrain_date:
            days_since = (datetime.strptime(date, "%Y-%m-%d") - self._last_retrain_date).days
            if days_since < cfg.min_interval_days:
                return False

        # Performans düşüşü
        recent_sharpes = [m["sharpe"] for m in list(self._daily_performance)[-self.performance_window :]]
        if recent_sharpes:
            avg_sharpe = np.mean(recent_sharpes)
            if avg_sharpe < cfg.sharpe_threshold:
                logger.warning(
                    "Retrain triggered: low Sharpe", avg_sharpe=round(avg_sharpe, 4), threshold=cfg.sharpe_threshold
                )
                return True

        # Drift tespiti
        if self._drift_detected:
            logger.warning("Retrain triggered: drift detected")
            return True

        # Win rate düşüşü
        recent_win_rates = [m["win_rate"] for m in list(self._daily_performance)[-self.performance_window :]]
        if recent_win_rates and np.mean(recent_win_rates) < cfg.winrate_threshold:
            logger.warning(
                "Retrain triggered: low win rate",
                avg=round(np.mean(recent_win_rates), 4),
                threshold=cfg.winrate_threshold,
            )
            return True

        # Zorunlu interval doldu
        if self._last_retrain_date:
            days_since = (datetime.strptime(date, "%Y-%m-%d") - self._last_retrain_date).days
            if days_since >= cfg.max_interval_days:
                logger.warning("Retrain triggered: max interval exceeded", days=days_since)
                return True

        return False

    def _execute_retrain(
        self,
        features_map: dict[str, dict],
        actual_returns: dict[str, float],
        regime: str,
    ) -> dict[str, Any]:
        """Yeniden eğitim çalıştır."""
        from services.learning.super_intelligence import super_intelligence
        from services.ml.ranking_model import ranking_model

        logger.info("Executing retrain", regime=regime)

        # Eğitim verisi hazırla
        # Son N günün verilerini kullan
        training_data = {
            "features": features_map,
            "returns": actual_returns,
            "regime": regime,
        }

        # Model eğit
        result = ranking_model.train(
            features_map=features_map,
            returns=actual_returns,
            date_groups={t: datetime.now(UTC).strftime("%Y-%m-%d") for t in features_map},
            regime=regime,
        )

        if result.get("success"):
            self._last_retrain_date = datetime.now(UTC)

            # Super intelligence'a bildir
            super_intelligence.auto_retrain(training_data, {})

        return result

    def _evaluate_ab_test(self, date: str) -> dict | None:
        """A/B test değerlendir."""
        from services.learning.super_intelligence import super_intelligence

        if not super_intelligence._ab_test_active:
            return None

        # A/B test sonuçlarını topla
        # Gerçek implementasyonda son N günün sonuçları kullanılır
        return {
            "active": True,
            "champion": super_intelligence._ab_test_champion,
            "challenger": super_intelligence._ab_test_challenger,
            "date": date,
        }

    def _update_registry(self, date: str, results: dict):
        """Model kayıt defterini güncelle."""
        self._registry.performance_history.append(
            {
                "date": date,
                "metrics": results.get("daily_metrics", {}),
                "retrain": results.get("should_retrain", False),
                "drift": results.get("drift_check", {}).get("drift_detected", False),
            }
        )

    def get_learning_report(self) -> dict[str, Any]:
        """Öğrenme raporu oluştur."""
        recent_cycles = list(self._cycles)[-10:]
        recent_performance = list(self._daily_performance)[-30:]

        return {
            "total_cycles": len(self._cycles),
            "recent_cycles": [
                {
                    "cycle_id": c.cycle_id,
                    "action": c.action,
                    "status": c.status,
                    "regime": c.regime,
                    "model_version": c.model_version,
                }
                for c in recent_cycles
            ],
            "performance_summary": {
                "avg_sharpe_30d": round(np.mean([m["sharpe"] for m in recent_performance]), 4)
                if recent_performance
                else 0,
                "avg_ic_30d": round(np.mean([m["ic"] for m in recent_performance]), 4) if recent_performance else 0,
                "avg_win_rate_30d": round(np.mean([m["win_rate"] for m in recent_performance]), 4)
                if recent_performance
                else 0,
            },
            "registry": {
                "versions": len(self._registry.versions),
                "active_version": self._registry.active_version,
                "champion_version": self._registry.champion_version,
            },
            "drift_status": {
                "detected": self._drift_detected,
                "features": self._drift_features,
            },
            "last_retrain": self._last_retrain_date.isoformat() if self._last_retrain_date else None,
        }

    def export_state(self) -> dict[str, Any]:
        """Pipeline durumunu dışa aktar."""
        return {
            "cycles": [
                {
                    "cycle_id": c.cycle_id,
                    "timestamp": c.timestamp,
                    "regime": c.regime,
                    "action": c.action,
                    "status": c.status,
                    "model_version": c.model_version,
                }
                for c in self._cycles
            ],
            "registry": {
                "versions": self._registry.versions,
                "active_version": self._registry.active_version,
                "champion_version": self._registry.champion_version,
            },
            "daily_performance": list(self._daily_performance),
            "last_retrain": self._last_retrain_date.isoformat() if self._last_retrain_date else None,
            "drift_detected": self._drift_detected,
        }

    def import_state(self, state: dict[str, Any]):
        """Pipeline durumunu içe aktar."""
        self._registry.versions = state.get("registry", {}).get("versions", [])
        self._registry.active_version = state.get("registry", {}).get("active_version", "")
        self._registry.champion_version = state.get("registry", {}).get("champion_version", "")
        self._daily_performance = deque(state.get("daily_performance", []), maxlen=252)
        if state.get("last_retrain"):
            self._last_retrain_date = datetime.fromisoformat(state["last_retrain"])
        self._drift_detected = state.get("drift_detected", False)


# Singleton
continuous_learning = ContinuousLearningPipeline()
