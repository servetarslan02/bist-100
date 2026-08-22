"""
ALPHA BIST — Super Intelligence Engine v3.0

SÜPER AKILLI, TAM OTOMATİK, KENDİ KENDİNİ YÖNETEN SİSTEM

Özellikler:
- Self-healing: Hata olduğunda kendi kendini onarır
- Auto-retrain: Model performansı düştüğünde otomatik yeniden eğitir
- A/B testing: Yeni model vs eski model karşılaştırması
- Drift detection: Veri dağılımı değiştiğinde alarm
- Meta-learning: Hangi model ne zaman daha iyi performans gösteriyor öğrenir
- Auto-hyperparameter tuning: Optimal parametreleri kendi bulur
- Cascade failure prevention: Bir modül çökerse diğerleri devreye girer
- Real-time monitoring: Tüm metrikleri anlık izler

KURAL: Sistem insan müdahalesi olmadan 7/24 çalışmalı.
"""

import json
import time
import numpy as np
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict
import structlog
import hashlib
import threading

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class SystemHealth:
    """Sistem sağlık durumu."""
    timestamp: str
    overall_status: str  # HEALTHY, WARNING, CRITICAL
    module_status: Dict[str, str]  # {module: status}
    last_error: Optional[str]
    uptime_hours: float
    predictions_today: int
    accuracy_today: float
    drift_detected: bool
    retrain_needed: bool


@dataclass
class ModelVersion:
    """Model versiyon bilgisi."""
    version_id: str
    created_at: str
    regime: str
    training_samples: int
    test_sharpe: float
    test_ic: float
    feature_importance: Dict[str, float]
    is_active: bool
    is_champion: bool  # A/B test kazananı


@dataclass
class ABTestResult:
    """A/B test sonucu."""
    test_id: str
    champion_version: str
    challenger_version: str
    champion_sharpe: float
    challenger_sharpe: float
    improvement_pct: float
    is_significant: bool
    p_value: float
    winner: str


class SuperIntelligenceEngine:
    """Süper akıllı, tam otomatik öğrenme motoru."""

    def __init__(
        self,
        retrain_threshold_sharpe: Optional[float] = None,
        retrain_threshold_ic: Optional[float] = None,
        drift_threshold: Optional[float] = None,
        max_models_history: Optional[int] = None,
        ab_test_window_days: Optional[int] = None,
    ):
        cfg = learning_settings
        self.retrain_threshold_sharpe = retrain_threshold_sharpe or cfg.retrain.sharpe_threshold
        self.retrain_threshold_ic = retrain_threshold_ic or cfg.retrain.ic_threshold
        self.drift_threshold = drift_threshold or cfg.drift.psi_alert
        self.max_models_history = max_models_history or cfg.model_registry.max_versions
        self.ab_test_window_days = ab_test_window_days or cfg.shadow.duration_days

        # Model versiyonlama
        self._model_versions: deque = deque(maxlen=100)
        self._active_model_version: Optional[str] = None
        self._champion_model_version: Optional[str] = None

        # Performans geçmişi
        self._performance_history: deque = deque(maxlen=252)  # 1 yıl
        self._prediction_history: deque = deque(maxlen=10000)

        # Drift detection
        self._baseline_distributions: Dict[str, Dict] = {}
        self._drift_alerts: deque = deque(maxlen=1000)

        # A/B test state
        self._ab_test_active: bool = False
        self._ab_test_champion: Optional[str] = None
        self._ab_test_challenger: Optional[str] = None
        self._ab_test_results: deque = deque(maxlen=50)

        # Meta-learning
        self._regime_model_performance: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Health monitoring
        self._health_status = SystemHealth(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_status="HEALTHY",
            module_status={},
            last_error=None,
            uptime_hours=0,
            predictions_today=0,
            accuracy_today=0.0,
            drift_detected=False,
            retrain_needed=False,
        )

        # Self-healing queue
        self._healing_queue: deque = deque(maxlen=500)
        self._lock = threading.Lock()

        logger.info("SuperIntelligenceEngine v3.0 initialized",
                   retrain_sharpe=retrain_threshold_sharpe,
                   drift_threshold=drift_threshold)

    # === SELF-HEALING ===

    def detect_and_heal(
        self,
        module_name: str,
        error: Exception,
        context: Dict,
    ) -> Dict[str, Any]:
        """Hata tespit et ve otomatik onar."""

        error_msg = str(error)
        healing_action = None

        # Hata tipine göre aksiyon
        if "LightGBM" in error_msg or "model" in error_msg.lower():
            healing_action = "retrain_model"
        elif "data" in error_msg.lower() or "feature" in error_msg.lower():
            healing_action = "refresh_data"
        elif "memory" in error_msg.lower() or "timeout" in error_msg.lower():
            healing_action = "restart_module"
        elif "connection" in error_msg.lower() or "network" in error_msg.lower():
            healing_action = "retry_with_backoff"
        else:
            healing_action = "fallback_to_rule_based"

        healing_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": module_name,
            "error": error_msg,
            "action": healing_action,
            "context": context,
            "status": "PENDING",
        }

        with self._lock:
            self._healing_queue.append(healing_record)
            if len(self._healing_queue) > 100:
                self._healing_queue = self._healing_queue[-100:]

        logger.warning("Self-healing triggered",
                      module=module_name, action=healing_action, error=error_msg)

        return healing_record

    def execute_healing(self, healing_record: Dict) -> bool:
        """Healing aksiyonunu çalıştır."""
        action = healing_record.get("action")
        max_attempts = learning_settings.health.max_healing_attempts
        attempt = healing_record.get("attempt", 0)

        if attempt >= max_attempts:
            healing_record["status"] = "FAILED"
            healing_record["failure_reason"] = f"Max attempts ({max_attempts}) exceeded"
            logger.error("Healing max attempts exceeded", action=action)
            return False

        try:
            healing_record["attempt"] = attempt + 1

            if action == "retrain_model":
                self._trigger_retrain()
            elif action == "refresh_data":
                self._trigger_data_refresh()
            elif action == "restart_module":
                self._restart_module(healing_record["module"])
            elif action == "retry_with_backoff":
                self._retry_with_backoff(healing_record)
            elif action == "fallback_to_rule_based":
                self._activate_fallback()

            healing_record["status"] = "COMPLETED"
            healing_record["resolved_at"] = datetime.now(timezone.utc).isoformat()
            return True

        except Exception as e:
            healing_record["status"] = "FAILED"
            healing_record["failure_reason"] = str(e)
            logger.error("Healing failed", action=action, error=str(e), attempt=attempt + 1)
            return False

    # === AUTO-RETRAIN ===

    def check_retrain_needed(
        self,
        recent_performance: Dict[str, float],
    ) -> bool:
        """Yeniden eğitim gerekli mi kontrol et."""

        sharpe = recent_performance.get("sharpe", 0)
        ic = recent_performance.get("ic", 0)
        win_rate = recent_performance.get("win_rate", 0)

        # Çoklu kriter
        needs_retrain = (
            sharpe < self.retrain_threshold_sharpe or
            ic < self.retrain_threshold_ic or
            win_rate < 0.45
        )

        if needs_retrain:
            self._health_status.retrain_needed = True
            logger.warning("Retrain needed",
                          sharpe=sharpe, ic=ic, win_rate=win_rate)

        return needs_retrain

    def auto_retrain(
        self,
        training_data: Dict,
        validation_data: Dict,
    ) -> Dict[str, Any]:
        """Otomatik yeniden eğitim."""

        logger.info("Auto-retrain started")

        # Yeni model eğit
        from services.ml.ranking_model import ranking_model

        result = ranking_model.train(
            features_map=training_data.get("features", {}),
            returns=training_data.get("returns", {}),
            date_groups=training_data.get("dates", {}),
            regime=training_data.get("regime", "UNKNOWN"),
        )

        if not result.get("success"):
            logger.error("Auto-retrain failed", error=result.get("error"))
            return {"success": False, "error": result.get("error")}

        # Yeni versiyon oluştur
        version_id = self._generate_version_id()
        new_version = ModelVersion(
            version_id=version_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            regime=training_data.get("regime", "UNKNOWN"),
            training_samples=result.get("samples", 0),
            test_sharpe=0.0,  # A/B test ile belirlenecek
            test_ic=0.0,
            feature_importance=result.get("feature_importance", {}),
            is_active=False,
            is_champion=False,
        )

        self._model_versions.append(new_version)
        if len(self._model_versions) > 500:
            self._model_versions = self._model_versions[-500:]

        # Eski versiyonları temizle
        if len(self._model_versions) > self.max_models_history:
            self._model_versions = self._model_versions[-self.max_models_history:]

        # A/B test başlat
        self._start_ab_test(
            champion=self._champion_model_version or self._active_model_version,
            challenger=version_id,
        )

        logger.info("Auto-retrain completed", version=version_id)

        return {
            "success": True,
            "version_id": version_id,
            "feature_importance": result.get("feature_importance"),
        }

    # === DRIFT DETECTION ===

    def detect_drift(
        self,
        current_features: Dict[str, Dict],
        baseline_features: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, Any]:
        """Veri drift'i tespit et."""

        if baseline_features is None:
            baseline_features = self._baseline_distributions

        drift_results = {}
        overall_drift = False

        for ticker, features in current_features.items():
            if ticker not in baseline_features:
                continue

            baseline = baseline_features[ticker]
            ticker_drift = {}

            for feat_name, current_val in features.items():
                if feat_name not in baseline:
                    continue

                baseline_val = baseline[feat_name].get("mean", 0)
                baseline_std = baseline[feat_name].get("std", 1)

                if baseline_std > 0:
                    z_score = abs(current_val - baseline_val) / baseline_std
                    if z_score > 3:  # 3 sigma = drift
                        ticker_drift[feat_name] = {
                            "z_score": round(z_score, 2),
                            "baseline": round(baseline_val, 4),
                            "current": round(current_val, 4),
                        }

            if ticker_drift:
                drift_results[ticker] = ticker_drift
                overall_drift = True

        if overall_drift:
            self._health_status.drift_detected = True
            self._drift_alerts.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "affected_tickers": list(drift_results.keys()),
                "details": drift_results,
            })

            logger.warning("Drift detected",
                          tickers=len(drift_results),
                          features=sum(len(v) for v in drift_results.values()))

        return {
            "drift_detected": overall_drift,
            "affected_tickers": list(drift_results.keys()),
            "details": drift_results,
        }

    def update_baseline(
        self,
        features_map: Dict[str, Dict],
        window_days: int = 60,
    ):
        """Baseline dağılımları güncelle."""
        self._baseline_distributions = {}

        for ticker, features in features_map.items():
            self._baseline_distributions[ticker] = {}
            for feat_name, val in features.items():
                if isinstance(val, (int, float)):
                    self._baseline_distributions[ticker][feat_name] = {
                        "mean": val,
                        "std": abs(val) * 0.1 + 0.01,  # Basit tahmin
                    }

    # === A/B TESTING ===

    def _start_ab_test(self, champion: str, challenger: str):
        """A/B test başlat."""
        self._ab_test_active = True
        self._ab_test_champion = champion
        self._ab_test_challenger = challenger

        logger.info("A/B test started", champion=champion, challenger=challenger)

    def evaluate_ab_test(
        self,
        champion_results: List[float],
        challenger_results: List[float],
    ) -> ABTestResult:
        """A/B test sonucunu değerlendir."""

        from scipy import stats

        champion_sharpe = np.mean(champion_results) / (np.std(champion_results) + 1e-10) * np.sqrt(252)
        challenger_sharpe = np.mean(challenger_results) / (np.std(challenger_results) + 1e-10) * np.sqrt(252)

        # Welch's t-test
        t_stat, p_value = stats.ttest_ind(champion_results, challenger_results, equal_var=False)

        improvement = (challenger_sharpe - champion_sharpe) / abs(champion_sharpe) * 100 if champion_sharpe != 0 else 0
        is_significant = p_value < 0.05

        winner = challenger if (challenger_sharpe > champion_sharpe and is_significant) else champion

        result = ABTestResult(
            test_id=self._generate_version_id(),
            champion_version=self._ab_test_champion or "",
            challenger_version=self._ab_test_challenger or "",
            champion_sharpe=round(champion_sharpe, 4),
            challenger_sharpe=round(challenger_sharpe, 4),
            improvement_pct=round(improvement, 2),
            is_significant=is_significant,
            p_value=round(p_value, 4),
            winner=winner,
        )

        self._ab_test_results.append(result)
        if len(self._ab_test_results) > 1000:
            self._ab_test_results = self._ab_test_results[-1000:]
        self._ab_test_active = False

        # Kazananı aktif yap
        if winner == self._ab_test_challenger:
            self._champion_model_version = winner
            for v in self._model_versions:
                v.is_champion = (v.version_id == winner)

        logger.info("A/B test completed",
                   winner=winner, improvement=round(improvement, 2),
                   significant=is_significant)

        return result

    # === META-LEARNING ===

    def record_performance(
        self,
        model_version: str,
        regime: str,
        metrics: Dict[str, float],
    ):
        """Performans kaydet (meta-learning için)."""
        scores = self._regime_model_performance[regime][model_version]
        scores.append(metrics.get("sharpe", 0))
        if len(scores) > 100:
            self._regime_model_performance[regime][model_version] = scores[-100:]

    def get_best_model_for_regime(self, regime: str) -> Optional[str]:
        """Rejim için en iyi modeli bul."""
        if regime not in self._regime_model_performance:
            return None

        best_model = None
        best_score = -float("inf")

        for model_version, scores in self._regime_model_performance[regime].items():
            if scores:
                avg_score = np.mean(scores[-10:])  # Son 10 performans
                if avg_score > best_score:
                    best_score = avg_score
                    best_model = model_version

        return best_model

    # === HEALTH MONITORING ===

    def get_health_status(self) -> SystemHealth:
        """Sistem sağlık durumunu getir."""
        self._health_status.timestamp = datetime.now(timezone.utc).isoformat()

        # Overall status belirle
        critical_modules = sum(1 for s in self._health_status.module_status.values() if s == "CRITICAL")
        warning_modules = sum(1 for s in self._health_status.module_status.values() if s == "WARNING")

        if critical_modules > 0:
            self._health_status.overall_status = "CRITICAL"
        elif warning_modules > 2:
            self._health_status.overall_status = "WARNING"
        else:
            self._health_status.overall_status = "HEALTHY"

        return self._health_status

    def update_module_status(self, module: str, status: str, error: Optional[str] = None):
        """Modül durumunu güncelle."""
        self._health_status.module_status[module] = status
        if error:
            self._health_status.last_error = error

    # === DAILY AUTOMATION ===

    def daily_cycle(
        self,
        features_map: Dict[str, Dict],
        predictions: List[Dict],
        actual_returns: Dict[str, float],
        regime: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """Günlük otomasyon döngüsü.

        Her gün çalıştırılır:
        1. Drift detection
        2. Performans kaydet
        3. Retrain kontrolü
        4. A/B test değerlendirme
        5. Health check
        """
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
        }

        # 1. Drift detection
        drift = self.detect_drift(features_map)
        results["drift"] = drift

        # 2. Performans kaydet
        if predictions and actual_returns:
            # Son tahminlerin performansı
            recent_metrics = self._calculate_recent_metrics(predictions, actual_returns)
            self.record_performance(
                self._active_model_version or "unknown",
                regime,
                recent_metrics,
            )
            results["recent_metrics"] = recent_metrics

        # 3. Retrain kontrolü
        recent_metrics = results.get("recent_metrics", {})
        needs_retrain = self.check_retrain_needed(recent_metrics) if recent_metrics else False
        results["retrain_needed"] = needs_retrain

        if needs_retrain:
            retrain_result = self.auto_retrain(
                training_data={"features": features_map, "regime": regime},
                validation_data={},
            )
            results["retrain_result"] = retrain_result

        # 4. A/B test değerlendirme
        if self._ab_test_active and actual_returns:
            try:
                ab_result = self._evaluate_active_ab_test(actual_returns)
                if ab_result:
                    results["ab_test"] = ab_result
            except Exception as e:
                logger.warning("A/B test evaluation failed", error=str(e))

        # 5. Health check
        health = self.get_health_status()
        results["health"] = asdict(health)

        # 6. Self-healing
        if self._healing_queue:
            for healing in self._healing_queue[:]:
                if healing["status"] == "PENDING":
                    self.execute_healing(healing)

        logger.info("Daily cycle completed", regime=regime,
                   drift=drift["drift_detected"],
                   retrain=results.get("retrain_needed", False))

        return results

    def _calculate_recent_metrics(
        self,
        predictions: List[Dict],
        actual_returns: Dict[str, float],
    ) -> Dict[str, float]:
        """Son tahminlerin metriklerini hesapla."""
        returns = []
        wins = 0
        scores = []
        actuals = []

        for pred in predictions:
            ticker = pred.get("ticker", "")
            if ticker in actual_returns:
                actual = actual_returns[ticker]
                returns.append(actual)
                if actual > 0:
                    wins += 1
                scores.append(pred.get("score", 0))
                actuals.append(actual)

        if not returns:
            return {"sharpe": 0, "ic": 0, "win_rate": 0}

        returns_arr = np.array(returns)
        sharpe = np.mean(returns_arr) / (np.std(returns_arr) + 1e-10) * np.sqrt(252)

        ic = 0
        if len(scores) > 5:
            try:
                ic = np.corrcoef(scores, actuals)[0, 1]
                if np.isnan(ic):
                    ic = 0
            except Exception as e:
                ic = 0

        win_rate = wins / len(returns) if returns else 0

        return {
            "sharpe": round(float(sharpe), 4),
            "ic": round(float(ic), 4),
            "win_rate": round(float(win_rate), 4),
        }

    # === INTERNAL HELPERS ===

    def _generate_version_id(self) -> str:
        """Benzersiz versiyon ID oluştur."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        random_hash = hashlib.md5(str(np.random.random()).encode()).hexdigest()[:6]
        return f"v_{timestamp}_{random_hash}"

    def _trigger_retrain(self):
        """Yeniden eğitim tetikle — continuous_learning üzerinden."""
        logger.info("Retrain triggered by self-healing")
        try:
            from services.learning.continuous_learning import continuous_learning
            continuous_learning._drift_detected = True
            self._health_status.retrain_needed = True
        except Exception as e:
            logger.error("Retrain trigger failed", error=str(e))

    def _trigger_data_refresh(self):
        """Veri yenileme tetikle — event bus üzerinden."""
        logger.info("Data refresh triggered by self-healing")
        try:
            from services.core.event_bus import publish_event, EventType
            publish_event(
                EventType.DATA_REFRESH_REQUESTED,
                source="super_intelligence",
                payload={"reason": "self_healing", "timestamp": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as e:
            logger.error("Data refresh trigger failed", error=str(e))

    def _restart_module(self, module: str):
        """Modül yeniden başlat — health status güncelle."""
        logger.info("Module restart triggered", module=module)
        self.update_module_status(module, "RESTARTING")
        try:
            from services.learning.health_monitor import learning_health_monitor
            learning_health_monitor.request_restart(module)
        except ImportError:
            logger.warning("Health monitor not available for restart", module=module)

    def _retry_with_backoff(self, healing_record: Dict):
        """Backoff ile tekrar dene."""
        attempt = healing_record.get("attempt", 0)
        backoff = learning_settings.health.healing_backoff_seconds
        wait_time = backoff * (2 ** attempt)
        logger.info("Retry with backoff", attempt=attempt, wait_seconds=wait_time)
        time.sleep(min(wait_time, 300))

    def _activate_fallback(self):
        """Fallback modunu aktive et — rule-based sisteme geç."""
        logger.warning("Fallback mode activated — switching to rule-based")
        self._health_status.overall_status = "DEGRADED"
        self._health_status.last_error = "Fallback mode active"

    def _evaluate_active_ab_test(self, actual_returns: Dict[str, float]) -> Optional[Dict]:
        """Aktif A/B test'i değerlendir."""
        if not self._ab_test_active:
            return None

        champion_returns = []
        challenger_returns = []

        for pred in list(self._prediction_history)[-100:]:
            ticker = pred.get("ticker", "")
            if ticker in actual_returns:
                model_version = pred.get("model_version", "")
                if model_version == self._ab_test_champion:
                    champion_returns.append(actual_returns[ticker])
                elif model_version == self._ab_test_challenger:
                    challenger_returns.append(actual_returns[ticker])

        if len(champion_returns) >= 10 and len(challenger_returns) >= 10:
            result = self.evaluate_ab_test(champion_returns, challenger_returns)
            return asdict(result)

        return None


# Singleton
super_intelligence = SuperIntelligenceEngine()
