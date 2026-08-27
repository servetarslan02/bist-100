"""
ALPHA BIST — Circuit Breaker v1.0

Provider sağlık kontrolü için circuit breaker pattern.

State Machine:
    CLOSED → (failure_threshold aşıldı) → OPEN
    OPEN → (recovery_timeout doldu) → HALF_OPEN
    HALF_OPEN → (success) → CLOSED
    HALF_OPEN → (failure) → OPEN

Kullanım:
    cb = CircuitBreaker(name="yfinance", failure_threshold=5, recovery_timeout=60)

    @cb.protect
    async def fetch_data():
        ...

    # veya manuel
    async with cb.context():
        result = await some_async_call()
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class CircuitState(StrEnum):
    """Circuit breaker durumları."""
    CLOSED = "CLOSED"         # Normal — istekler geçiyor
    OPEN = "OPEN"             # Açık — istekler engelleniyor
    HALF_OPEN = "HALF_OPEN"   # Yarı açık — test istekleri geçiyor


@dataclass
class CircuitStats:
    """Circuit breaker istatistikleri."""
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_rejected: int = 0      # OPEN iken reddedilen
    total_fallbacks: int = 0     # Fallback kullanılan
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_state_change: float | None = None
    state_changes: int = 0


class CircuitBreakerError(Exception):
    """Circuit breaker OPEN iken fırlatılır."""


class CircuitBreaker:
    """
    Circuit breaker — provider sağlık kontrolü.

    Args:
        name: Provider adı (logging için)
        failure_threshold: OPEN'a geçmek için ardışık hata sayısı
        recovery_timeout_s: OPEN → HALF_OPEN geçiş süresi (saniye)
        half_open_max_calls: HALF_OPEN'da izin verilen test istek sayısı
        success_threshold: HALF_OPEN → CLOSED için ardışık başarı sayısı
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Mevcut durum (OPEN timeout kontrolü ile)."""
        if self._state == CircuitState.OPEN and self._stats.last_failure_time:
            elapsed = time.time() - self._stats.last_failure_time
            if elapsed >= self.recovery_timeout_s:
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    def _transition(self, new_state: CircuitState):
        """Durum geçişi."""
        old_state = self._state
        self._state = new_state
        self._stats.last_state_change = time.time()
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._stats.consecutive_successes = 0

        logger.info("Circuit breaker state change",
                    name=self.name,
                    old_state=old_state.value,
                    new_state=new_state.value)

    def record_success(self):
        """Başarı kaydet."""
        # First check state (may trigger OPEN → HALF_OPEN transition)
        current = self.state

        self._stats.total_requests += 1
        self._stats.total_successes += 1
        self._stats.consecutive_successes += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_time = time.time()

        if current == CircuitState.HALF_OPEN and self._stats.consecutive_successes >= self.success_threshold:
            self._transition(CircuitState.CLOSED)

    def record_failure(self):
        """Hata kaydet."""
        # First check state (may trigger OPEN → HALF_OPEN transition)
        current = self.state

        self._stats.total_requests += 1
        self._stats.total_failures += 1
        self._stats.consecutive_failures += 1
        self._stats.consecutive_successes = 0
        self._stats.last_failure_time = time.time()

        if current == CircuitState.CLOSED:
            if self._stats.consecutive_failures >= self.failure_threshold:
                self._transition(CircuitState.OPEN)
        elif current == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)

    def record_rejected(self):
        """REDDEDilen istek kaydet (OPEN iken)."""
        self._stats.total_rejected += 1

    def can_execute(self) -> bool:
        """İstek yapılabilir mi?"""
        current_state = self.state  # Timeout kontrolü tetikler

        if current_state == CircuitState.CLOSED:
            return True
        elif current_state == CircuitState.OPEN:
            self.record_rejected()
            return False
        elif current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            self.record_rejected()
            return False
        return False

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Async fonksiyonu circuit breaker ile çağır."""
        if not self.can_execute():
            raise CircuitBreakerError(
                f"Circuit breaker '{self.name}' is OPEN"
            )

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def protect(self, func: Callable) -> Callable:
        """Decorator — async fonksiyonu circuit breaker ile sar."""
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    class _ContextManager:
        """async with cb.context(): ... kullanımı için."""

        def __init__(self, cb: "CircuitBreaker"):
            self._cb = cb

        async def __aenter__(self):
            if not self._cb.can_execute():
                raise CircuitBreakerError(
                    f"Circuit breaker '{self._cb.name}' is OPEN"
                )
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None:
                self._cb.record_failure()
                return False  # Exception'ı yeniden fırlat
            else:
                self._cb.record_success()
            return False

    def context(self) -> "CircuitBreaker._ContextManager":
        """async with cb.context(): ... kullanımı için."""
        return self._ContextManager(self)

    def get_state(self) -> dict:
        """Durum bilgisi (monitoring için)."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout_s,
            "consecutive_failures": self._stats.consecutive_failures,
            "total_requests": self._stats.total_requests,
            "total_successes": self._stats.total_successes,
            "total_failures": self._stats.total_failures,
            "total_rejected": self._stats.total_rejected,
            "success_rate": round(
                self._stats.total_successes / max(self._stats.total_requests, 1), 3
            ),
            "state_changes": self._stats.state_changes,
            "last_failure": datetime.fromtimestamp(
                self._stats.last_failure_time, tz=UTC
            ).isoformat() if self._stats.last_failure_time else None,
            "last_success": datetime.fromtimestamp(
                self._stats.last_success_time, tz=UTC
            ).isoformat() if self._stats.last_success_time else None,
        }

    def reset(self):
        """Sıfırla (test veya manuel recovery için)."""
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        logger.info("Circuit breaker reset", name=self.name)


class CircuitBreakerManager:
    """Tüm circuit breaker'ları yönetir."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
    ) -> CircuitBreaker:
        """Circuit breaker al veya oluştur."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
            )
        return self._breakers[name]

    def get_all_states(self) -> dict:
        """Tüm circuit breaker durumları."""
        return {
            name: cb.get_state()
            for name, cb in self._breakers.items()
        }

    def reset_all(self):
        """Tümünü sıfırla."""
        for cb in self._breakers.values():
            cb.reset()


# Singleton
circuit_breaker_manager = CircuitBreakerManager()
