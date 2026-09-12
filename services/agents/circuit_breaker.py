"""ALPHA BIST — Circuit Breaker (Devre Kesici) Modülü.

Bu modül, harici LLM sağlayıcılarında (Ollama, OpenAI, Anthropic vb.) veya ağ katmanında
meydana gelen kesinti, rate limit (oran sınırı) ve API çökmelerinde Alpha BIST multi-agent
pipeline'ının kilitlenmesini engellemek üzere Circuit Breaker modelini uygular.

Durum Geçişleri:
- CLOSED: Normal çalışma. Tüm istekler doğrudan LLM sağlayıcısına iletilir.
- OPEN: Hata eşiği aşıldığında devre açılır. İstekler LLM'e gönderilmeden doğrudan reddedilir / fallback işletilir.
- HALF_OPEN: İyileşme bekleme süresi dolduğunda test amaçlı sınırlı sayıda çağrıya izin verilir.
             Test başarılı olursa CLOSED durumuna dönülür; başarısız olursa OPEN durumu devam eder.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import orjson
import structlog

if TYPE_CHECKING:
    from .llm_client import LLMResponse

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "CircuitBreaker",
    "CircuitBreakerLLMClient",
    "CircuitBreakerStats",
    "CircuitState",
    "CircuitBreakerOpenError",
]


class CircuitBreakerOpenError(Exception):
    """Devre kesici AÇIK (OPEN) durumdayken çağrı yapıldığında fırlatılan özel istisna."""

    def __init__(self, message: str = "Circuit breaker AÇIK (OPEN) durumda — istek reddedildi.") -> None:
        super().__init__(message)


class CircuitState(StrEnum):
    """Circuit breaker durumları."""

    CLOSED = "CLOSED"        # Normal — tüm çağrılar iletilir
    OPEN = "OPEN"            # Engellenmiş — istekler reddedilir, fallback kullanılır
    HALF_OPEN = "HALF_OPEN"  # Yarı-açık — test çağrıları ile sistem sıhhati yoklanır


@dataclass
class CircuitBreakerStats:
    """Circuit breaker çalışma ve performans istatistikleri."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # OPEN durumunda engellenen çağrılar
    state_changes: int = 0
    last_state_change: str = ""

    def to_dict(self) -> dict[str, Any]:
        """İstatistikleri sözlük formatına çevirir.

        Returns:
            dict[str, Any]: İstatistik alanları.
        """
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_changes": self.state_changes,
            "last_state_change": self.last_state_change,
        }

    def to_json(self) -> str:
        """İstatistikleri orjson ile JSON dizgisine dönüştürür.

        Returns:
            str: JSON formatında istatistikler.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerStats(calls={self.total_calls}, "
            f"ok={self.successful_calls}, fail={self.failed_calls}, "
            f"rejected={self.rejected_calls}, state_changes={self.state_changes})"
        )


class CircuitBreaker:
    """LLM ve dış servis çağrılarını koruyan thread-safe devre kesici.

    Kullanım:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
        if cb.can_execute():
            try:
                res = await client.generate(...)
                cb.record_success()
            except Exception:
                cb.record_failure()
        else:
            res = fallback_logic()

        Veya Context Manager ile:
        async with cb:
            res = await client.generate(...)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        max_recovery_timeout: float = 300.0,
        half_open_max_calls: int = 1,
        exponential_backoff: bool = True,
    ) -> None:
        """CircuitBreaker başlatıcı.

        Args:
            failure_threshold: Devrenin OPEN durumuna geçmesi için gereken ardışık hata sayısı.
            recovery_timeout: OPEN durumundan HALF_OPEN test aşamasına geçiş taban bekleme süresi (saniye).
            max_recovery_timeout: Üstel geri çekilmede ulaşılabilecek tavan bekleme süresi (saniye).
            half_open_max_calls: HALF_OPEN durumunda aynı anda izin verilen test çağrısı adedi.
            exponential_backoff: Ardışık devre açılmalarında bekleme süresinin üstel artırılması.
        """
        self._failure_threshold: int = max(1, failure_threshold)
        self._recovery_timeout: float = max(1.0, recovery_timeout)
        self._max_recovery_timeout: float = max(self._recovery_timeout, max_recovery_timeout)
        self._half_open_max_calls: int = max(1, half_open_max_calls)
        self._exponential_backoff: bool = exponential_backoff

        self._lock: threading.RLock = threading.RLock()
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._consecutive_trips: int = 0
        self._half_open_calls: int = 0
        self._last_failure_time: float = 0.0
        self._stats: CircuitBreakerStats = CircuitBreakerStats()

    @property
    def state(self) -> CircuitState:
        """Mevcut durum (iyileşme süresi kontrolü dahil).

        Returns:
            CircuitState: Devrenin anlık durumu.
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                timeout = self._current_recovery_timeout()
                if time.monotonic() - self._last_failure_time >= timeout:
                    self._change_state(CircuitState.HALF_OPEN)
                    self._half_open_calls = 0
            return self._state

    def _current_recovery_timeout(self) -> float:
        """Üstel geri çekilme hesabı ile dinamik bekleme süresini döner."""
        if not self._exponential_backoff or self._consecutive_trips <= 1:
            return self._recovery_timeout
        mult = 2 ** min(6, self._consecutive_trips - 1)
        return min(self._max_recovery_timeout, self._recovery_timeout * mult)

    def can_execute(self) -> bool:
        """Yeni bir çağrı yapılmasına izin verilip verilmediğini denetler.

        Returns:
            bool: İstek yürütülebilirse True, devre açıksa False.
        """
        with self._lock:
            current = self.state  # Timeout kontrolünü tetikler

            if current == CircuitState.CLOSED:
                return True
            elif current == CircuitState.HALF_OPEN:
                if self._half_open_calls < self._half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            else:  # CircuitState.OPEN
                self._stats.rejected_calls += 1
                return False

    def record_success(self) -> None:
        """Başarılı bir çağrı tamamlandığında çağrılır."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._consecutive_trips = 0
                self._change_state(CircuitState.CLOSED)
                logger.info("Circuit breaker kapandı — servis sağlığı normale döndü")

    def record_failure(self) -> None:
        """Başarısız bir çağrı sonrasında çağrılır."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Test çağrısı başarısız oldu → OPEN durumuna geri dön
                self._consecutive_trips += 1
                self._change_state(CircuitState.OPEN)
                logger.warning(
                    "Circuit breaker yeniden açıldı — test çağrısı başarısız oldu",
                    consecutive_trips=self._consecutive_trips,
                    next_timeout=self._current_recovery_timeout(),
                )
            elif self._failure_count >= self._failure_threshold:
                # Hata eşiği aşıldı → Devre açılır
                self._consecutive_trips += 1
                self._change_state(CircuitState.OPEN)
                logger.warning(
                    "Circuit breaker AÇILDI — hata eşiği aşıldı",
                    failures=self._failure_count,
                    threshold=self._failure_threshold,
                    timeout_seconds=self._current_recovery_timeout(),
                )

    def _change_state(self, new_state: CircuitState) -> None:
        """Durum geçişini thread-safe olarak işletir."""
        old_state = self._state
        if old_state != new_state:
            self._state = new_state
            self._stats.state_changes += 1
            self._stats.last_state_change = datetime.now(UTC).isoformat()
            logger.info(
                "Circuit breaker durum değişikliği",
                eski_durum=old_state.value,
                yeni_durum=new_state.value,
            )

    def reset(self) -> None:
        """Tüm sayaçları ve durumu ilk fabrika ayarlarına sıfırlar."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._consecutive_trips = 0
            self._half_open_calls = 0
            self._last_failure_time = 0.0

    def get_stats(self) -> dict[str, Any]:
        """Tüm devre ve çalışma istatistiklerini yapısal sözlük olarak döner.

        Returns:
            dict[str, Any]: Güncel devre metrikleri.
        """
        with self._lock:
            return {
                "state": self.state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "current_timeout": self._current_recovery_timeout(),
                "consecutive_trips": self._consecutive_trips,
                **self._stats.to_dict(),
            }

    def __enter__(self) -> CircuitBreaker:
        """Senkron bağlam yöneticisi girişi."""
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker AÇIK (OPEN) — son hata zamanı: {self._last_failure_time}"
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Senkron bağlam yöneticisi çıkışı."""
        if exc_val is not None:
            self.record_failure()
        else:
            self.record_success()
        return False

    async def __aenter__(self) -> CircuitBreaker:
        """Asenkron bağlam yöneticisi girişi."""
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        """Asenkron bağlam yöneticisi çıkışı."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"CircuitBreaker(state={self.state.value!r}, "
                f"failures={self._failure_count}/{self._failure_threshold}, "
                f"trips={self._consecutive_trips})"
            )


class CircuitBreakerLLMClient:
    """Circuit breaker ile zırhlandırılmış LLM istemci sarmalayıcısı (Decorator).

    Hedef istemcinin tüm çağrılarını devre kesici koruması altına alır. Devre OPEN
    olduğunda istek göndermeden fail-closed yanıt döner.
    """

    def __init__(self, client: Any, breaker: CircuitBreaker | None = None) -> None:
        """CircuitBreakerLLMClient başlatıcı.

        Args:
            client: Gerçek LLM istemcisi (Ollama, OpenAI, Anthropic vb.).
            breaker: İsteğe bağlı özel CircuitBreaker örneği. Yoksa varsayılan oluşturulur.
        """
        self._client: Any = client
        self._breaker: CircuitBreaker = breaker or CircuitBreaker()

    @property
    def breaker(self) -> CircuitBreaker:
        """Bağlı devre kesici örneğini döner."""
        return self._breaker

    @property
    def client(self) -> Any:
        """Sarmalanan ham istemci örneğini döner."""
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Devre kesici korumalı doğrudan üretim çağrısı."""
        if not self._breaker.can_execute():
            logger.warning("Circuit breaker OPEN — generate çağrısı engellendi")
            from .llm_client import LLMResponse
            return LLMResponse(
                content="",
                model=getattr(self._client, "model", "circuit_breaker"),
                provider=getattr(self._client, "provider", "circuit_breaker"),
                success=False,
                error="Circuit breaker is OPEN",
            )

        try:
            response = await self._client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if getattr(response, "success", False):
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
            return response
        except Exception:
            self._breaker.record_failure()
            raise

    async def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Devre kesici korumalı yeniden denemeli (retry) üretim çağrısı."""
        if not self._breaker.can_execute():
            logger.warning("Circuit breaker OPEN — generate_with_retry çağrısı engellendi")
            from .llm_client import LLMResponse
            return LLMResponse(
                content="",
                model=getattr(self._client, "model", "circuit_breaker"),
                provider=getattr(self._client, "provider", "circuit_breaker"),
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
            if getattr(response, "success", False):
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
            return response
        except Exception:
            self._breaker.record_failure()
            raise

    async def health_check(self) -> bool:
        """Alttaki istemcinin sağlık durumunu devre kesiciyi zorlamadan denetler."""
        if hasattr(self._client, "health_check"):
            try:
                return await self._client.health_check()
            except Exception:
                return False
        return self._breaker.state != CircuitState.OPEN

    async def close(self) -> None:
        """İstemci kaynaklarını güvenle kapatır."""
        if hasattr(self._client, "close"):
            await self._client.close()

    def __getattr__(self, name: str) -> Any:
        """Belirtilmeyen diğer tüm metot ve özellikleri asıl istemciye delege eder."""
        return getattr(self._client, name)

    def __repr__(self) -> str:
        return f"CircuitBreakerLLMClient(breaker={self._breaker!r}, client={self._client!r})"
