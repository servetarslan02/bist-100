"""ALPHA BIST — Model Degradation Monitor v1.0

Model performans degradation izleme ve otomatik müdahale:
- Rolling window ile performans trendi
- Degradation tespiti (z-score + trend analizi)
- Alert sistemi (LOW/MEDIUM/HIGH/CRITICAL)
- Otomatik model çıkarma (ensemble'dan kaldır)
- Degradation history tracking

Kullanım:
    from services.learning.model_degradation_monitor import degradation_monitor

    # Her trade sonucu sonrası kaydet
    degradation_monitor.record_outcome("lgbm", predicted=0.7, actual=1.0, return_pct=2.3)

    # Periyodik kontrol
    alerts = degradation_monitor.check_all_models()

    # Degraded modeli ensemble'dan çıkar
    degradation_monitor.auto_remove_degraded(ensemble_model, threshold=0.3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ModelOutcome:
    """Tek model sonucu."""

    timestamp: str
    predicted: float
    actual: float
    return_pct: float
    is_correct: bool


@dataclass
class DegradationReport:
    """Model degradation raporu."""

    model_id: str
    window_size: int
    current_accuracy: float
    baseline_accuracy: float
    accuracy_drop: float
    current_sharpe: float
    baseline_sharpe: float
    sharpe_drop: float
    trend: str  # improving, stable, degrading, volatile
    z_score: float
    severity: str  # OK, WARNING, ALERT, CRITICAL
    should_remove: bool
    recommendation: str
    n_outcomes: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class DegradationAlert:
    """Degradation alert."""

    model_id: str
    severity: str
    message: str
    accuracy_drop: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ModelDegradationMonitor:
    """Model performans degradation izleme motoru.

    Özellikler:
    - Rolling window performans takibi
    - Z-score tabanlı degradation tespiti
    - Trend analizi (improving/stable/degrading/volatile)
    - Severity scoring (OK/WARNING/ALERT/CRITICAL)
    - Otomatik model çıkarma
    - Alert cooldown (spam önleme)
    """

    def __init__(
        self,
        window_size: int = 50,
        baseline_window: int = 200,
        accuracy_drop_threshold: float = 0.10,
        sharpe_drop_threshold: float = 0.5,
        z_score_threshold: float = 2.0,
        alert_cooldown_hours: int = 6,
        auto_remove_threshold: float = 0.30,
    ):
        self.window_size = window_size
        self.baseline_window = baseline_window
        self.accuracy_drop_threshold = accuracy_drop_threshold
        self.sharpe_drop_threshold = sharpe_drop_threshold
        self.z_score_threshold = z_score_threshold
        self.alert_cooldown_hours = alert_cooldown_hours
        self.auto_remove_threshold = auto_remove_threshold
        self._outcomes: dict[str, list[ModelOutcome]] = {}
        self._alerts: list[DegradationAlert] = []
        self._last_alert_time: dict[str, datetime] = {}
        self._removed_models: set[str] = set()

    def record_outcome(
        self,
        model_id: str,
        predicted: float,
        actual: float,
        return_pct: float = 0.0,
    ) -> None:
        """Model sonucu kaydet.

        Args:
            model_id: Model adı
            predicted: Model tahmini (0-1 arası veya yön)
            actual: Gerçek değer
            return_pct: Gerçek getiri yüzdesi
        """
        if model_id not in self._outcomes:
            self._outcomes[model_id] = []

        # Yön doğruluğu hesapla
        pred_dir = "UP" if predicted > 0.5 else "DOWN"
        act_dir = "UP" if actual > 0 else "DOWN"
        is_correct = pred_dir == act_dir

        outcome = ModelOutcome(
            timestamp=datetime.now(UTC).isoformat(),
            predicted=predicted,
            actual=actual,
            return_pct=return_pct,
            is_correct=is_correct,
        )

        self._outcomes[model_id].append(outcome)

        # Son window_size * 3 tut (memory management)
        max_keep = self.window_size * 3
        if len(self._outcomes[model_id]) > max_keep:
            self._outcomes[model_id] = self._outcomes[model_id][-max_keep:]

    def check_model(self, model_id: str) -> DegradationReport:
        """Tek model için degradation kontrolü.

        Args:
            model_id: Model adı

        Returns:
            DegradationReport
        """
        outcomes = self._outcomes.get(model_id, [])

        if len(outcomes) < self.window_size:
            return DegradationReport(
                model_id=model_id,
                window_size=len(outcomes),
                current_accuracy=0.5,
                baseline_accuracy=0.5,
                accuracy_drop=0.0,
                current_sharpe=0.0,
                baseline_sharpe=0.0,
                sharpe_drop=0.0,
                trend="stable",
                z_score=0.0,
                severity="OK",
                should_remove=False,
                recommendation="Yetersiz veri — daha fazla sonuç gerekli",
                n_outcomes=len(outcomes),
            )

        # Son window_size outcome
        recent = outcomes[-self.window_size:]
        # Baseline: ondan önceki outcomes
        baseline = outcomes[:-self.window_size] if len(outcomes) > self.window_size else outcomes[:self.baseline_window]

        # Mevcut accuracy
        current_accuracy = sum(1 for o in recent if o.is_correct) / len(recent)

        # Baseline accuracy
        baseline_accuracy = sum(1 for o in baseline if o.is_correct) / len(baseline) if baseline else 0.5

        # Accuracy drop
        accuracy_drop = baseline_accuracy - current_accuracy

        # Mevcut Sharpe (basitleştirilmiş)
        current_returns = [o.return_pct for o in recent]
        current_sharpe = self._compute_sharpe(current_returns)

        # Baseline Sharpe
        baseline_returns = [o.return_pct for o in baseline]
        baseline_sharpe = self._compute_sharpe(baseline_returns)

        # Sharpe drop
        sharpe_drop = baseline_sharpe - current_sharpe

        # Z-score (accuracy drop'un standart sapma cinsinden)
        if len(baseline) > 10:
            # Rolling accuracy'lerin dağılımını hesapla
            rolling_accs = []
            for i in range(0, len(baseline) - self.window_size, max(1, self.window_size // 4)):
                window = baseline[i:i + self.window_size]
                acc = sum(1 for o in window if o.is_correct) / len(window)
                rolling_accs.append(acc)

            if len(rolling_accs) > 1:
                acc_std = float(np.std(rolling_accs))
                z_score = abs(accuracy_drop) / max(acc_std, 0.01)
            else:
                z_score = abs(accuracy_drop) / 0.05
        else:
            z_score = abs(accuracy_drop) / 0.05

        # Trend analizi
        trend = self._compute_trend(outcomes)

        # Severity
        severity = self._compute_severity(accuracy_drop, sharpe_drop, z_score, trend)

        # Should remove
        should_remove = (
            severity == "CRITICAL"
            or (accuracy_drop > self.auto_remove_threshold and trend == "degrading")
        )

        # Recommendation
        recommendation = self._generate_recommendation(
            model_id, accuracy_drop, sharpe_drop, trend, severity, should_remove
        )

        return DegradationReport(
            model_id=model_id,
            window_size=self.window_size,
            current_accuracy=round(current_accuracy, 4),
            baseline_accuracy=round(baseline_accuracy, 4),
            accuracy_drop=round(accuracy_drop, 4),
            current_sharpe=round(current_sharpe, 4),
            baseline_sharpe=round(baseline_sharpe, 4),
            sharpe_drop=round(sharpe_drop, 4),
            trend=trend,
            z_score=round(z_score, 4),
            severity=severity,
            should_remove=should_remove,
            recommendation=recommendation,
            n_outcomes=len(outcomes),
        )

    def check_all_models(self) -> list[DegradationAlert]:
        """Tüm modelleri kontrol et ve alert oluştur.

        Returns:
            Oluşturulan alert listesi
        """
        new_alerts: list[DegradationAlert] = []

        for model_id in self._outcomes:
            if model_id in self._removed_models:
                continue

            report = self.check_model(model_id)

            if report.severity in ("ALERT", "CRITICAL"):
                # Cooldown kontrolü
                if self._should_alert(model_id):
                    alert = DegradationAlert(
                        model_id=model_id,
                        severity=report.severity,
                        message=report.recommendation,
                        accuracy_drop=report.accuracy_drop,
                    )
                    new_alerts.append(alert)
                    self._alerts.append(alert)
                    self._last_alert_time[model_id] = datetime.now(UTC)

                    logger.warning(
                        "model_degradation_alert",
                        model=model_id,
                        severity=report.severity,
                        accuracy_drop=report.accuracy_drop,
                        trend=report.trend,
                    )

        return new_alerts

    def auto_remove_degraded(
        self,
        ensemble_model: Any,
        threshold: float | None = None,
    ) -> list[str]:
        """Degraded modelleri ensemble'dan otomatik çıkar.

        Args:
            ensemble_model: EnsembleModel instance
            threshold: Accuracy drop eşiği (None = auto_remove_threshold)

        Returns:
            Çıkarılan model isimleri
        """
        if threshold is None:
            threshold = self.auto_remove_threshold

        removed: list[str] = []

        for model_id in list(self._outcomes.keys()):
            if model_id in self._removed_models:
                continue

            report = self.check_model(model_id)

            if report.should_remove:
                self._removed_models.add(model_id)
                removed.append(model_id)

                logger.warning(
                    "model_auto_removed",
                    model=model_id,
                    accuracy_drop=report.accuracy_drop,
                    severity=report.severity,
                    trend=report.trend,
                )

        return removed

    def restore_model(self, model_id: str) -> bool:
        """Çıkarılan modeli geri al.

        Args:
            model_id: Model adı

        Returns:
            Başarılı mı?
        """
        if model_id in self._removed_models:
            self._removed_models.discard(model_id)
            logger.info("model_restored", model=model_id)
            return True
        return False

    def get_removed_models(self) -> set[str]:
        """Çıkarılmış modelleri döndür."""
        return self._removed_models.copy()

    def get_alerts(self, limit: int = 50) -> list[DegradationAlert]:
        """Son alert'leri döndür."""
        return self._alerts[-limit:]

    def get_model_summary(self) -> dict[str, Any]:
        """Tüm modellerin özet durumu."""
        summary: dict[str, Any] = {}
        for model_id in self._outcomes:
            report = self.check_model(model_id)
            summary[model_id] = {
                "current_accuracy": report.current_accuracy,
                "accuracy_drop": report.accuracy_drop,
                "trend": report.trend,
                "severity": report.severity,
                "removed": model_id in self._removed_models,
                "n_outcomes": report.n_outcomes,
            }
        return summary

    def _compute_sharpe(self, returns: list[float], risk_free_daily: float = 0.0) -> float:
        """Basitleştirilmiş Sharpe oranı."""
        if len(returns) < 2:
            return 0.0
        arr = np.array(returns)
        mean_ret = float(np.mean(arr)) - risk_free_daily
        std_ret = float(np.std(arr))
        if std_ret < 1e-6:
            return 0.0
        return float(np.sqrt(252) * mean_ret / std_ret)

    def _compute_trend(self, outcomes: list[ModelOutcome]) -> str:
        """Performans trendi hesapla."""
        if len(outcomes) < self.window_size * 2:
            return "stable"

        # Son 3 chunk'ın accuracy'si
        chunk_size = self.window_size
        chunks = []
        for i in range(max(0, len(outcomes) - 3 * chunk_size), len(outcomes), chunk_size):
            chunk = outcomes[i:i + chunk_size]
            if len(chunk) >= chunk_size // 2:
                acc = sum(1 for o in chunk if o.is_correct) / len(chunk)
                chunks.append(acc)

        if len(chunks) < 2:
            return "stable"

        # Volatile kontrolü
        if len(chunks) > 1 and np.std(chunks) > 0.15:
            return "volatile"

        # Trend kontrolü
        if len(chunks) >= 2:
            change = chunks[-1] - chunks[0]
            if change < -0.10:
                return "degrading"
            elif change > 0.10:
                return "improving"

        return "stable"

    def _compute_severity(
        self,
        accuracy_drop: float,
        sharpe_drop: float,
        z_score: float,
        trend: str,
    ) -> str:
        """Severity hesapla."""
        if z_score > 3.0 or (accuracy_drop > 0.20 and trend == "degrading"):
            return "CRITICAL"
        elif z_score > 2.5 or (accuracy_drop > 0.15 and trend == "degrading"):
            return "ALERT"
        elif z_score > 2.0 or accuracy_drop > self.accuracy_drop_threshold:
            return "WARNING"
        else:
            return "OK"

    def _generate_recommendation(
        self,
        model_id: str,
        accuracy_drop: float,
        sharpe_drop: float,
        trend: str,
        severity: str,
        should_remove: bool,
    ) -> str:
        """Öneri oluştur."""
        if should_remove:
            return (
                f"CRITICAL: '{model_id}' modeli ciddi degradation gösteriyor "
                f"(accuracy drop: {accuracy_drop:.1%}, trend: {trend}). "
                f"Ensemble'dan çıkarılması önerilir."
            )
        elif severity == "ALERT":
            return (
                f"ALERT: '{model_id}' modeli performans kaybı yaşıyor "
                f"(accuracy drop: {accuracy_drop:.1%}). Yakından izleyin."
            )
        elif severity == "WARNING":
            return (
                f"WARNING: '{model_id}' modelinde hafif düşüş "
                f"(accuracy drop: {accuracy_drop:.1%}). İzlemeye devam edin."
            )
        else:
            return f"'{model_id}' modeli stabil."

    def _should_alert(self, model_id: str) -> bool:
        """Alert cooldown kontrolü."""
        last_alert = self._last_alert_time.get(model_id)
        if last_alert is None:
            return True
        elapsed = (datetime.now(UTC) - last_alert).total_seconds() / 3600
        return elapsed >= self.alert_cooldown_hours


# Singleton
degradation_monitor = ModelDegradationMonitor()
