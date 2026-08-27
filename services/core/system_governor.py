"""
ALPHA BIST — Graceful Degradation & System State Machine

Sistem durumu makinesi ve kademeli bozulma yönetimi.

Durumlar:
- FULL: Tüm özellikler aktif
- DEGRADED: Kritik olmayan özellikler devre dışı
- READ_ONLY: Sadece okuma, yeni pozisyon yok
- RECOVERY: Kurtarma modu

Referanslar:
- CORE-NIHAI-SPEC.md - Section 3.5
- 02-SISTEM-MIMARISI.md - 2.5 Hata modeli
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class SystemState(StrEnum):
    """Sistem durumları."""

    FULL = "FULL"  # Tüm özellikler aktif
    DEGRADED = "DEGRADED"  # Kritik olmayan özellikler devre dışı
    READ_ONLY = "READ_ONLY"  # Sadece okuma
    RECOVERY = "RECOVERY"  # Kurtarma modu
    SHUTDOWN = "SHUTDOWN"  # Kapatılıyor


class FeatureFlag(StrEnum):
    """Feature flag'ler."""

    LIVE_TRADING = "live_trading"
    NEW_POSITIONS = "new_positions"
    SCANNING = "scanning"
    ML_PREDICTIONS = "ml_predictions"
    NEWS_FEED = "news_feed"
    ALTERNATIVE_DATA = "alternative_data"
    BACKTESTING = "backtesting"
    ALERTING = "alerting"
    REPORTING = "reporting"
    LEARNING = "learning"


@dataclass
class StateTransition:
    """Durum geçiş kaydı."""

    from_state: SystemState
    to_state: SystemState
    reason: str
    timestamp: datetime
    triggered_by: str  # manual, auto, health_check

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state.value,
            "to": self.to_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "triggered_by": self.triggered_by,
        }


@dataclass
class HealthCheck:
    """Sağlık kontrolü sonucu."""

    component: str
    is_healthy: bool
    latency_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class SystemStateGovernor:
    """
    Sistem durumu yöneticisi (Governor).

    Sistem durumunu yönetir, feature flag'leri kontrol eder,
    otomatik degradation ve recovery sağlar.

    Kullanım:
        governor = SystemStateGovernor()

        # Check if action is allowed
        if governor.is_allowed(FeatureFlag.NEW_POSITIONS):
            # Open position

        # Manual state change
        governor.transition(SystemState.DEGRADED, "High volatility detected")

        # Auto health check
        await governor.run_health_checks()
    """

    def __init__(self):
        self._state = SystemState.FULL
        self._feature_flags: dict[FeatureFlag, bool] = {f: True for f in FeatureFlag}
        self._transition_history: list[StateTransition] = []
        self._health_checks: dict[str, Callable] = {}
        self._health_results: dict[str, HealthCheck] = {}
        self._callbacks: list[Callable] = []
        self._auto_recovery_enabled = True
        self._degradation_threshold = 0.5  # %50 unhealthy → DEGRADED
        self._readonly_threshold = 0.75  # %75 unhealthy → READ_ONLY

        # State-specific feature overrides
        self._state_features: dict[SystemState, set[FeatureFlag]] = {
            SystemState.FULL: set(),  # No restrictions
            SystemState.DEGRADED: {
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.LEARNING,
                FeatureFlag.REPORTING,
            },
            SystemState.READ_ONLY: {
                FeatureFlag.LIVE_TRADING,
                FeatureFlag.NEW_POSITIONS,
                FeatureFlag.SCANNING,
                FeatureFlag.ML_PREDICTIONS,
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.LEARNING,
            },
            SystemState.RECOVERY: {
                FeatureFlag.LIVE_TRADING,
                FeatureFlag.NEW_POSITIONS,
                FeatureFlag.SCANNING,
                FeatureFlag.ML_PREDICTIONS,
                FeatureFlag.NEWS_FEED,
                FeatureFlag.ALTERNATIVE_DATA,
                FeatureFlag.BACKTESTING,
                FeatureFlag.LEARNING,
            },
            SystemState.SHUTDOWN: {f for f in FeatureFlag},  # All disabled
        }

        # Apply initial state
        self._apply_state()

    @property
    def state(self) -> SystemState:
        return self._state

    def is_allowed(self, feature: FeatureFlag) -> bool:
        """Feature kullanılabiliyor mu?"""
        return self._feature_flags.get(feature, False)

    def transition(
        self,
        new_state: SystemState,
        reason: str,
        triggered_by: str = "manual",
    ) -> bool:
        """
        Durum geçişi yap.

        Args:
            new_state: Yeni durum
            reason: Geçiş nedeni
            triggered_by: Tetikleyen (manual/auto/health_check)

        Returns:
            Geçiş yapıldı mı?
        """
        if new_state == self._state:
            return False

        old_state = self._state
        self._state = new_state

        # Apply state-specific feature flags
        self._apply_state()

        # Record transition
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            timestamp=datetime.now(UTC),
            triggered_by=triggered_by,
        )
        self._transition_history.append(transition)
        if len(self._transition_history) > 1000:
            self._transition_history = self._transition_history[-1000:]

        logger.warning(
            "System state transition",
            old=old_state.value,
            new=new_state.value,
            reason=reason,
            triggered_by=triggered_by,
        )

        # Notify callbacks (handle both sync and async contexts)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify_callbacks(old_state, new_state, reason))
        except RuntimeError:
            # No running event loop — schedule for later or skip
            logger.warning("Runtime error in transition", exc_info=True)

        return True

    def _apply_state(self):
        """Duruma göre feature flag'leri ayarla."""
        # Reset all to True
        for f in FeatureFlag:
            self._feature_flags[f] = True

        # Disable features for current state
        disabled = self._state_features.get(self._state, set())
        for f in disabled:
            self._feature_flags[f] = False

    def register_health_check(self, component: str, check_func: Callable):
        """Sağlık kontrolü kaydet."""
        self._health_checks[component] = check_func

    def register_callback(self, callback: Callable):
        """State change callback'i kaydet."""
        self._callbacks.append(callback)
        if len(self._callbacks) > 100:
            self._callbacks = self._callbacks[-100:]

    async def run_health_checks(self) -> dict[str, HealthCheck]:
        """
        Tüm sağlık kontrollerini çalıştır.

        Returns:
            Component → HealthCheck mapping
        """
        results = {}

        for component, check_func in self._health_checks.items():
            start = time.monotonic()
            try:
                if asyncio.iscoroutinefunction(check_func):
                    is_healthy = await check_func()
                else:
                    is_healthy = check_func()

                latency = (time.monotonic() - start) * 1000

                results[component] = HealthCheck(
                    component=component,
                    is_healthy=is_healthy,
                    latency_ms=round(latency, 2),
                )
            except Exception as e:
                latency = (time.monotonic() - start) * 1000
                results[component] = HealthCheck(
                    component=component,
                    is_healthy=False,
                    latency_ms=round(latency, 2),
                    error=str(e),
                )

        self._health_results = results

        # Auto-degradation
        if self._auto_recovery_enabled:
            self._auto_degrade_or_recover(results)

        return results

    def _auto_degrade_or_recover(self, results: dict[str, HealthCheck]):
        """Otomatik degradation veya recovery."""
        if not results:
            return

        total = len(results)
        unhealthy = sum(1 for r in results.values() if not r.is_healthy)
        unhealthy_ratio = unhealthy / total

        if self._state == SystemState.FULL:
            if unhealthy_ratio >= self._readonly_threshold:
                self.transition(
                    SystemState.READ_ONLY,
                    f"Auto: {unhealthy}/{total} components unhealthy ({unhealthy_ratio:.0%})",
                    "auto",
                )
            elif unhealthy_ratio >= self._degradation_threshold:
                self.transition(
                    SystemState.DEGRADED,
                    f"Auto: {unhealthy}/{total} components unhealthy ({unhealthy_ratio:.0%})",
                    "auto",
                )

        elif self._state in (SystemState.DEGRADED, SystemState.READ_ONLY, SystemState.RECOVERY):
            if unhealthy_ratio < self._degradation_threshold:
                self.transition(
                    SystemState.FULL,
                    f"Auto recovery: {unhealthy}/{total} components unhealthy ({unhealthy_ratio:.0%})",
                    "auto",
                )

    async def _notify_callbacks(
        self,
        old_state: SystemState,
        new_state: SystemState,
        reason: str,
    ):
        """Callback'leri bildir."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_state, new_state, reason)
                else:
                    callback(old_state, new_state, reason)
            except Exception as e:
                logger.error("State change callback error", error=str(e))

    def get_status(self) -> dict[str, Any]:
        """Sistem durumu özeti."""
        return {
            "state": self._state.value,
            "feature_flags": {f.value: v for f, v in self._feature_flags.items()},
            "enabled_features": [f.value for f, v in self._feature_flags.items() if v],
            "disabled_features": [f.value for f, v in self._feature_flags.items() if not v],
            "health": {
                comp: {"healthy": h.is_healthy, "latency_ms": h.latency_ms} for comp, h in self._health_results.items()
            },
            "transitions": len(self._transition_history),
        }

    def get_transition_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Geçiş geçmişi."""
        return [t.to_dict() for t in self._transition_history[-limit:]]

    def force_feature(self, feature: FeatureFlag, enabled: bool):
        """Feature flag'i zorla ayarla."""
        self._feature_flags[feature] = enabled
        logger.info("Feature flag forced", feature=feature.value, enabled=enabled)

    def get_fallback_response(self, feature: FeatureFlag) -> dict[str, Any] | None:
        """
        Feature devre dışıysa fallback response döndür.

        Bu, client'ın graceful handling yapmasını sağlar.
        """
        if self.is_allowed(feature):
            return None  # No fallback needed

        fallbacks = {
            FeatureFlag.ML_PREDICTIONS: {
                "predictions": [],
                "status": "degraded",
                "message": "ML predictions temporarily unavailable",
            },
            FeatureFlag.SCANNING: {
                "opportunities": [],
                "status": "degraded",
                "message": "Scanner temporarily unavailable",
            },
            FeatureFlag.NEWS_FEED: {
                "news": [],
                "status": "degraded",
                "message": "News feed temporarily unavailable",
            },
            FeatureFlag.LIVE_TRADING: {
                "status": "read_only",
                "message": "Live trading disabled - system in read-only mode",
            },
        }

        return fallbacks.get(
            feature,
            {
                "status": "unavailable",
                "message": f"Feature {feature.value} is currently disabled",
            },
        )


# Singleton
system_governor = SystemStateGovernor()
