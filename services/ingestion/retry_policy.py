"""
ALPHA BIST — Retry Policy v1.0

Exponential backoff + jitter ile retry mekanizması.

Thundering herd önleme: jitter rastgele gecikme ekler.
Retryable exceptions: TimeoutError, ConnectionError, 429, 500, 502, 503.
Non-retryable exceptions: 400, 401, 403, 404.

Kullanım:
    policy = RetryPolicy(max_attempts=3, base_delay=1.0)
    result = await policy.execute(fetch_data, ticker="THYAO")
"""

import asyncio
import random
import time
from typing import Callable, Any, Optional, Set, Type
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class RetryConfig:
    """Retry yapılandırması."""
    max_attempts: int = 3           # Maksimum deneme sayısı
    base_delay_s: float = 1.0       # Başlangıç gecikme süresi
    max_delay_s: float = 30.0       # Maksimum gecikme süresi
    backoff_factor: float = 2.0     # Gecikme çarpanı (exponential)
    jitter: bool = True             # Rastgele gecikme ekle
    jitter_range: float = 0.2       # Jitter aralığı (±%20)


@dataclass
class RetryStats:
    """Retry istatistikleri."""
    total_calls: int = 0
    total_retries: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_wait_seconds: float = 0.0
    max_attempts_used: int = 0
    last_retry_time: Optional[float] = None


# Retryable HTTP status codes
RETRYABLE_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}

# Non-retryable HTTP status codes
NON_RETRYABLE_STATUS_CODES: Set[int] = {400, 401, 403, 404, 405}


class HTTPStatusError(Exception):
    """HTTP durum hatası."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class RetryExhaustedError(Exception):
    """Tüm denemeler tükendi."""

    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Retry exhausted after {attempts} attempts: {last_error}"
        )


class RetryPolicy:
    """
    Exponential backoff + jitter ile retry.

    Args:
        max_attempts: Maksimum deneme sayısı
        base_delay_s: Başlangıç gecikme süresi (saniye)
        max_delay_s: Maksimum gecikme süresi (saniye)
        backoff_factor: Gecikme çarpanı
        jitter: Rastgele gecikme ekle
        retryable_exceptions: Retry yapılabilir exception tipleri
        non_retryable_exceptions: Retry yapılamaz exception tipleri
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        max_delay_s: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        jitter_range: float = 0.2,
        retryable_exceptions: Optional[Set[Type[Exception]]] = None,
        non_retryable_exceptions: Optional[Set[Type[Exception]]] = None,
    ):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay_s=base_delay_s,
            max_delay_s=max_delay_s,
            backoff_factor=backoff_factor,
            jitter=jitter,
            jitter_range=jitter_range,
        )
        self.stats = RetryStats()

        # Varsayılan retryable exceptions
        self.retryable_exceptions = retryable_exceptions or {
            ConnectionError,
            TimeoutError,
            OSError,
            asyncio.TimeoutError,
        }

        # Varsayılan non-retryable exceptions
        self.non_retryable_exceptions = non_retryable_exceptions or set()

    def _is_retryable(self, error: Exception) -> bool:
        """Bu hata retry yapılabilir mi?"""
        # Non-retryable kontrolü
        for exc_type in self.non_retryable_exceptions:
            if isinstance(error, exc_type):
                return False

        # HTTP status code kontrolü
        if isinstance(error, HTTPStatusError):
            if error.status_code in NON_RETRYABLE_STATUS_CODES:
                return False
            if error.status_code in RETRYABLE_STATUS_CODES:
                return True

        # Retryable exception kontrolü
        for exc_type in self.retryable_exceptions:
            if isinstance(error, exc_type):
                return True

        return False

    def _calculate_delay(self, attempt: int) -> float:
        """Gecikme süresini hesapla (exponential backoff + jitter)."""
        # Exponential backoff
        delay = self.config.base_delay_s * (
            self.config.backoff_factor ** (attempt - 1)
        )

        # Max delay sınırı
        delay = min(delay, self.config.max_delay_s)

        # Jitter ekle
        if self.config.jitter:
            jitter_amount = delay * self.config.jitter_range
            delay += random.uniform(-jitter_amount, jitter_amount)
            delay = max(0.1, delay)  # Minimum 100ms

        return delay

    async def execute(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        Async fonksiyonu retry ile çalıştır.

        Args:
            func: Async fonksiyon
            *args, **kwargs: Fonksiyon argümanları

        Returns:
            Fonksiyon sonucu

        Raises:
            RetryExhaustedError: Tüm denemeler tükendiğinde
            Exception: Non-retryable hata
        """
        self.stats.total_calls += 1
        last_error = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = await func(*args, **kwargs)
                self.stats.total_successes += 1
                if attempt > 1:
                    logger.info("Retry succeeded",
                               attempt=attempt,
                               total_attempts=self.config.max_attempts)
                return result

            except Exception as e:
                last_error = e

                # Non-retryable hata → hemen fırlat
                if not self._is_retryable(e):
                    logger.warning("Non-retryable error",
                                  error=str(e),
                                  error_type=type(e).__name__)
                    self.stats.total_failures += 1
                    raise

                # Son deneme → fırlat
                if attempt >= self.config.max_attempts:
                    break

                # Gecikme hesapla
                delay = self._calculate_delay(attempt)
                self.stats.total_retries += 1
                self.stats.total_wait_seconds += delay
                self.stats.last_retry_time = time.time()
                self.stats.max_attempts_used = max(
                    self.stats.max_attempts_used, attempt
                )

                logger.warning("Retry attempt",
                              attempt=attempt,
                              max_attempts=self.config.max_attempts,
                              delay_seconds=round(delay, 2),
                              error=str(e),
                              error_type=type(e).__name__)

                await asyncio.sleep(delay)

        # Tüm denemeler tükendi
        self.stats.total_failures += 1
        raise RetryExhaustedError(
            attempts=self.config.max_attempts,
            last_error=last_error,
        )

    def execute_sync(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """Sync fonksiyonu retry ile çalıştır."""
        import time as time_module
        self.stats.total_calls += 1
        last_error = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                self.stats.total_successes += 1
                return result

            except Exception as e:
                last_error = e

                if not self._is_retryable(e):
                    self.stats.total_failures += 1
                    raise

                if attempt >= self.config.max_attempts:
                    break

                delay = self._calculate_delay(attempt)
                self.stats.total_retries += 1
                self.stats.total_wait_seconds += delay

                logger.warning("Retry attempt (sync)",
                              attempt=attempt,
                              delay_seconds=round(delay, 2),
                              error=str(e))

                time_module.sleep(delay)

        self.stats.total_failures += 1
        raise RetryExhaustedError(
            attempts=self.config.max_attempts,
            last_error=last_error,
        )

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "total_calls": self.stats.total_calls,
            "total_retries": self.stats.total_retries,
            "total_successes": self.stats.total_successes,
            "total_failures": self.stats.total_failures,
            "success_rate": round(
                self.stats.total_successes / max(self.stats.total_calls, 1), 3
            ),
            "avg_retries_per_call": round(
                self.stats.total_retries / max(self.stats.total_calls, 1), 2
            ),
            "total_wait_seconds": round(self.stats.total_wait_seconds, 2),
            "max_attempts_used": self.stats.max_attempts_used,
        }


# BIST'e özgü retry policy'ler
BIST_RETRY_POLICIES = {
    "yfinance": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "kap": RetryPolicy(max_attempts=3, base_delay_s=2.0, max_delay_s=60.0),
    "tcmb": RetryPolicy(max_attempts=3, base_delay_s=2.0, max_delay_s=60.0),
    "bist": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "matriks": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "social": RetryPolicy(max_attempts=2, base_delay_s=2.0, max_delay_s=60.0),
    "news": RetryPolicy(max_attempts=2, base_delay_s=1.0, max_delay_s=60.0),
}


def get_retry_policy(provider: str) -> RetryPolicy:
    """Provider için retry policy al."""
    return BIST_RETRY_POLICIES.get(
        provider,
        RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=30.0),
    )
