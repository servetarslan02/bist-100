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
    """Circuit breaker durumları.

    Attributes:
        CLOSED: Normal çalışır durum — istekler geçiyor.
        OPEN: Devre açık — istekler engelleniyor.
        HALF_OPEN: Yarı açık — test istekleri geçiyor.
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitStats:
    """Circuit breaker istatistikleri.

    Attributes:
        total_requests: Toplam istek sayısı.
        total_successes: Toplam başarılı istek.
        total_failures: Toplam başarısız istek.
        total_rejected: OPEN iken reddedilen istek sayısı.
        total_fallbacks: Fallback kullanılan sayısı.
        consecutive_failures: Ardışık hata sayısı.
        consecutive_successes: Ardışık başarı sayısı.
        last_failure_time: Son hata zaman damgası (epoch).
        last_success_time: Son başarı zaman damgası (epoch).
        last_state_change: Son durum değişikliği zaman damgası.
        state_changes: Toplam durum değişikliği sayısı.
    """

    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_rejected: int = 0
    total_fallbacks: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_state_change: float | None = None
    state_changes: int = 0

    def __repr__(self) -> str:
        return (
            f"CircuitStats(requests={self.total_requests}, "
            f"successes={self.total_successes}, "
            f"failures={self.total_failures}, "
            f"rejected={self.total_rejected})"
        )


class CircuitBreakerError(Exception):
    """Circuit breaker OPEN iken fırlatılır.

    İstek reddedildiğinde bu istisna yükseltilir.
    """


class CircuitBreaker:
    """Circuit breaker — provider sağlık kontrolü.

    Provider hatalarını izler, eşik aşıldığında devreyi açar
    ve otomatik kurtarma mekanizması sağlar.

    Args:
        name: Provider adı (logging için).
        failure_threshold: OPEN'a geçmek için ardışık hata sayısı.
        recovery_timeout_s: OPEN → HALF_OPEN geçiş süresi (saniye).
        half_open_max_calls: HALF_OPEN'da izin verilen test istek sayısı.
        success_threshold: HALF_OPEN → CLOSED için ardışık başarı sayısı.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
    ) -> None:
        """CircuitBreaker örneği oluşturur.

        Args:
            name: Provider adı.
            failure_threshold: OPEN'a geçmek için ardışık hata sayısı.
            recovery_timeout_s: OPEN → HALF_OPEN geçiş süresi (saniye).
            half_open_max_calls: HALF_OPEN'da izin verilen test istek sayısı.
            success_threshold: HALF_OPEN → CLOSED için ardışık başarı sayısı.
        """
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
        """Mevcut durumu döndürür (OPEN timeout kontrolü ile).

        Returns:
            Mevcut CircuitState değeri.
        """
        if self._state == CircuitState.OPEN and self._stats.last_failure_time:
            elapsed = time.time() - self._stats.last_failure_time
            if elapsed >= self.recovery_timeout_s:
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    def _transition(self, new_state: CircuitState) -> None:
        """Durum geçişi yapar.

        Args:
            new_state: Geçilecek yeni durum.
        """
        old_state = self._state
        self._state = new_state
        self._stats.last_state_change = time.time()
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._stats.consecutive_successes = 0

        logger.info(
            "Circuit breaker state change",
            name=self.name,
            old_state=old_state.value,
            new_state=new_state.value,
        )

    def record_success(self) -> None:
        """Başarılı istek kaydı yapar.

        HALF_OPEN durumunda eşik aşıldığında CLOSED geçişi tetikler.
        """
        current = self.state

        self._stats.total_requests += 1
        self._stats.total_successes += 1
        self._stats.consecutive_successes += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_time = time.time()

        if current == CircuitState.HALF_OPEN and self._stats.consecutive_successes >= self.success_threshold:
            self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """Başarısız istek kaydı yapar.

        CLOSED durumunda eşik aşıldığında OPEN geçişi tetikler.
        HALF_OPEN durumunda hemen OPEN'a döner.
        """
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

    def record_rejected(self) -> None:
        """OPEN iken reddedilen istek kaydı yapar."""
        self._stats.total_rejected += 1

    def can_execute(self) -> bool:
        """İstek yapılabilir mi kontrol eder.

        Returns:
            İstek yapılabilirse True, engellenmişse False.
        """
        current_state = self.state

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

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Async fonksiyonu circuit breaker ile çağırır.

        Args:
            func: Çağrılacak async fonksiyon.
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            Fonksiyon dönüş değeri.

        Raises:
            CircuitBreakerError: Devre OPEN iken.
            Exception: Fonksiyon hata fırlattığında (kayıt yapıldıktan sonra yeniden yükseltilir).
        """
        if not self.can_execute():
            raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def protect(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator — async fonksiyonu circuit breaker ile sarar.

        Args:
            func: Korunacak async fonksiyon.

        Returns:
            Circuit breaker ile sarılmış wrapper fonksiyonu.
        """

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await self.call(func, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    class _ContextManager:
        """async with cb.context(): ... kullanımı için bağlam yöneticisi.

        Args:
            cb: Üst CircuitBreaker örneği.
        """

        def __init__(self, cb: "CircuitBreaker") -> None:
            self._cb = cb

        async def __aenter__(self) -> "CircuitBreaker._ContextManager":
            """Bağlama girer — istek izni kontrol eder.

            Returns:
                Kendisi (context manager).

            Raises:
                CircuitBreakerError: Devre OPEN iken.
            """
            if not self._cb.can_execute():
                raise CircuitBreakerError(f"Circuit breaker '{self._cb.name}' is OPEN")
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: Any,
        ) -> bool:
            """Bağlamdan çıkar — başarı/hata kaydı yapar.

            Args:
                exc_type: Yakalanan istisna tipi (varsa).
                exc_val: Yakalanan istisna değeri (varsa).
                exc_tb: Traceback (varsa).

            Returns:
                False — istisnayı yeniden fırlatır.
            """
            if exc_type is not None:
                self._cb.record_failure()
                return False
            else:
                self._cb.record_success()
            return False

    def context(self) -> "CircuitBreaker._ContextManager":
        """async with cb.context(): ... kullanımı için bağlam yöneticisi döndürür.

        Returns:
            _ContextManager örneği.
        """
        return self._ContextManager(self)

    def get_state(self) -> dict[str, Any]:
        """Durum bilgisini döndürür (monitoring için).

        Returns:
            Durum ve istatistik sözlüğü.
        """
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
            "success_rate": round(self._stats.total_successes / max(self._stats.total_requests, 1), 3),
            "state_changes": self._stats.state_changes,
            "last_failure": datetime.fromtimestamp(self._stats.last_failure_time, tz=UTC).isoformat()
            if self._stats.last_failure_time
            else None,
            "last_success": datetime.fromtimestamp(self._stats.last_success_time, tz=UTC).isoformat()
            if self._stats.last_success_time
            else None,
        }

    def reset(self) -> None:
        """Circuit breaker'ı sıfırlar (test veya manuel recovery için)."""
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        logger.info("Circuit breaker reset", name=self.name)


class CircuitBreakerManager:
    """Tüm circuit breaker'ları yöneten merkezi yönetici.

    Provider bazlı circuit breaker örneklerini oluşturur,
    izler ve toplu yönetim sağlar.
    """

    def __init__(self) -> None:
        """CircuitBreakerManager örneği oluşturur."""
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
    ) -> CircuitBreaker:
        """Circuit breaker alır veya oluşturur.

        Args:
            name: Provider adı.
            failure_threshold: OPEN'a geçmek için ardışık hata sayısı.
            recovery_timeout_s: OPEN → HALF_OPEN geçiş süresi (saniye).

        Returns:
            CircuitBreaker örneği.
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
            )
        return self._breakers[name]

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Tüm circuit breaker durumlarını döndürür.

        Returns:
            {provider_adı: durum_sözlüğü} yapısı.
        """
        return {name: cb.get_state() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Tüm circuit breaker'ları sıfırlar."""
        for cb in self._breakers.values():
            cb.reset()


# Singleton
circuit_breaker_manager = CircuitBreakerManager()
