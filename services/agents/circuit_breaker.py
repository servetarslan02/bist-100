"""
ALPHA BIST — Circuit Breaker Pattern

LLM provider çöktüğünde tüm pipeline'ın çökmesini engeller.
Durumlar: CLOSED (normal) → OPEN (engellenmiş) → HALF_OPEN (test)

Kurallar:
- 5 başarısız çağrının sonra OPEN → fallback kullan
- 30 saniye sonra HALF_OPEN → tek test çağrısı
- Test başarılı → CLOSED, başarısız → OPEN devam
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class CircuitState(StrEnum):
    """Circuit breaker durumları."""
    CLOSED = "CLOSED"        # Normal — çağrılar geçer
    OPEN = "OPEN"            # Engellenmiş — fallback kullan
    HALF_OPEN = "HALF_OPEN"  # Test — tek çağrı deneniyor


@dataclass
class CircuitBreakerStats:
    """Circuit breaker istatistikleri."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # OPEN durumunda reddedilen
    state_changes: int = 0
    last_state_change: str = ""

    def to_dict(self) -> dict[str, Any]:
        """İstatistikleri sözlük formatına çevir."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_changes": self.state_changes,
            "last_state_change": self.last_state_change,
        }

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerStats(calls={self.total_calls}, "
            f"ok={self.successful_calls}, fail={self.failed_calls}, "
            f"rejected={self.rejected_calls})"
        )


class CircuitBreaker:
    """Circuit Breaker — LLM çağrılarını korur.

    Kullanım:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        if cb.can_execute():
            try:
                result = await llm_call()
                cb.record_success()
            except:
                cb.record_failure()
        else:
            result = fallback()
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        """Circuit Breaker oluştur.

        Args:
            failure_threshold: OPEN'a geçmek için ardışık hata sayısı
            recovery_timeout: OPEN → HALF_OPEN geçiş süresi (saniye)
            half_open_max_calls: HALF_OPEN durumunda izin verilen test çağrısı
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0
        self._stats = CircuitBreakerStats()

    @property
    def state(self) -> CircuitState:
        """Mevcut durum (OPEN timeout kontrolü dahil)."""
        if self._state == CircuitState.OPEN:
            # Recovery timeout doldu mu?
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._change_state(CircuitState.HALF_OPEN)
                self._half_open_calls = 0
        return self._state

    def can_execute(self) -> bool:
        """Çağrı yapılabilir mi?"""
        current_state = self.state  # timeout kontrolü tetiklenir

        if current_state == CircuitState.CLOSED:
            return True
        elif current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self._half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        else:  # OPEN
            self._stats.rejected_calls += 1
            return False

    def record_success(self) -> None:
        """Başarılı çağrı kaydet."""
        self._stats.total_calls += 1
        self._stats.successful_calls += 1
        self._failure_count = 0

        if self._state == CircuitState.HALF_OPEN:
            # Test başarılı → CLOSED
            self._change_state(CircuitState.CLOSED)
            logger.info("Circuit breaker closed — LLM recovered")

    def record_failure(self) -> None:
        """Başarısız çağrı kaydet."""
        self._stats.total_calls += 1
        self._stats.failed_calls += 1
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Test başarısız → OPEN devam
            self._change_state(CircuitState.OPEN)
            logger.warning("Circuit breaker re-opened — LLM still failing")
        elif self._failure_count >= self._failure_threshold:
            # Eşik aşıldı → OPEN
            self._change_state(CircuitState.OPEN)
            logger.warning(
                "Circuit breaker opened",
                failures=self._failure_count,
                threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
            )

    def _change_state(self, new_state: CircuitState) -> None:
        """Durum değiştir."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1
        self._stats.last_state_change = datetime.now(UTC).isoformat()
        logger.info("Circuit breaker state change", old=old_state.value, new=new_state.value)

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri getir."""
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout": self._recovery_timeout,
            **self._stats.to_dict(),
        }

    def reset(self) -> None:
        """Sıfırla (test amaçlı)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self.state.value}, "
            f"failures={self._failure_count}/{self._failure_threshold})"
        )


class CircuitBreakerLLMClient:
    """Circuit breaker ile sarılmış LLM client.

    LLM çağrısı yapmadan önce circuit breaker kontrolü yapar.
    OPEN durumunda fallback kullanır.

    Kullanım:
        cb = CircuitBreaker()
        wrapped = CircuitBreakerLLMClient(real_client, cb)
        response = await wrapped.generate_with_retry(...)
    """

    def __init__(self, client: Any, breaker: CircuitBreaker):
        self._client = client
        self._breaker = breaker

    async def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> 'LLMResponse':
        """Circuit breaker kontrollü LLM çağrısı."""
        if not self._breaker.can_execute():
            logger.warning("Circuit breaker OPEN — LLM call rejected")
            # Boş hata response'u döndür
            from .llm_client import LLMResponse
            return LLMResponse(
                content="",
                model="circuit_breaker",
                provider="circuit_breaker",
                success=False,
                error="Circuit breaker is OPEN",
            )

        try:
            response = await self._client.generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if response.success:
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
            return response
        except Exception as e:
            self._breaker.record_failure()
            raise

    def __getattr__(self, name: str) -> object:
        """Diğer attribute'ları gerçek client'a pasla."""
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"CircuitBreakerLLMClient(breaker={self._breaker!r}, client={self._client!r})"
