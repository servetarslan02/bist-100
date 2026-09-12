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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RetryConfig:
    """Retry yapılandırması.

    Attributes:
        max_attempts: Maksimum deneme sayısı.
        base_delay_s: Başlangıç gecikme süresi (saniye).
        max_delay_s: Maksimum gecikme süresi (saniye).
        backoff_factor: Gecikme çarpanı (exponential).
        jitter: Rastgele gecikme ekle.
        jitter_range: Jitter aralığı (±%20 = 0.2).
    """

    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0
    jitter: bool = True
    jitter_range: float = 0.2

    def __repr__(self) -> str:
        return (
            f"RetryConfig(max_attempts={self.max_attempts}, "
            f"base_delay={self.base_delay_s}s, "
            f"backoff={self.backoff_factor}x)"
        )


@dataclass
class RetryStats:
    """Retry istatistikleri.

    Attributes:
        total_calls: Toplam çağrı sayısı.
        total_retries: Toplam retry sayısı.
        total_successes: Toplam başarılı çağrı.
        total_failures: Toplam başarısız çağrı.
        total_wait_seconds: Toplam bekleme süresi.
        max_attempts_used: Kullanılan maksimum deneme sayısı.
        last_retry_time: Son retry zaman damgası (epoch).
    """

    total_calls: int = 0
    total_retries: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_wait_seconds: float = 0.0
    max_attempts_used: int = 0
    last_retry_time: float | None = None

    def __repr__(self) -> str:
        return (
            f"RetryStats(calls={self.total_calls}, "
            f"retries={self.total_retries}, "
            f"successes={self.total_successes})"
        )


# Retryable HTTP durum kodları
DEFAULT_RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}

# Non-retryable HTTP durum kodları
DEFAULT_NON_RETRYABLE_STATUS_CODES: set[int] = {400, 401, 403, 404, 405}


class HTTPStatusError(Exception):
    """HTTP durum hatası.

    Attributes:
        status_code: HTTP durum kodu.
        message: Hata mesajı.
    """

    def __init__(self, status_code: int, message: str = "") -> None:
        """HTTPStatusError örneği oluşturur.

        Args:
            status_code: HTTP durum kodu.
            message: Hata mesajı.
        """
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class RetryExhaustedError(Exception):
    """Tüm denemeler tükendi.

    Attributes:
        attempts: Toplam deneme sayısı.
        last_error: Son hata.
    """

    def __init__(self, attempts: int, last_error: Exception) -> None:
        """RetryExhaustedError örneği oluşturur.

        Args:
            attempts: Toplam deneme sayısı.
            last_error: Son yakalanan hata.
        """
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_error}")


class RetryPolicy:
    """Exponential backoff + jitter ile retry.

    Args:
        max_attempts: Maksimum deneme sayısı.
        base_delay_s: Başlangıç gecikme süresi (saniye).
        max_delay_s: Maksimum gecikme süresi (saniye).
        backoff_factor: Gecikme çarpanı.
        jitter: Rastgele gecikme ekle.
        jitter_range: Jitter aralığı.
        retryable_exceptions: Retry yapılabilir exception tipleri.
        non_retryable_exceptions: Retry yapılamaz exception tipleri.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        max_delay_s: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        jitter_range: float = 0.2,
        retryable_exceptions: set[type[Exception]] | None = None,
        non_retryable_exceptions: set[type[Exception]] | None = None,
    ) -> None:
        """RetryPolicy örneği oluşturur.

        Args:
            max_attempts: Maksimum deneme sayısı.
            base_delay_s: Başlangıç gecikme süresi (saniye).
            max_delay_s: Maksimum gecikme süresi (saniye).
            backoff_factor: Gecikme çarpanı.
            jitter: Rastgele gecikme ekle.
            jitter_range: Jitter aralığı.
            retryable_exceptions: Retry yapılabilir exception tipleri.
            non_retryable_exceptions: Retry yapılamaz exception tipleri.
        """
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay_s=base_delay_s,
            max_delay_s=max_delay_s,
            backoff_factor=backoff_factor,
            jitter=jitter,
            jitter_range=jitter_range,
        )
        self.stats = RetryStats()
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

        self.retryable_exceptions = retryable_exceptions or {
            ConnectionError,
            TimeoutError,
            OSError,
            asyncio.TimeoutError,
        }

        self.non_retryable_exceptions = non_retryable_exceptions or set()

    def _is_retryable(self, error: Exception) -> bool:
        """Bu hata retry yapılabilir mi kontrol eder.

        Args:
            error: Yakalanan hata.

        Returns:
            True: Retry yapılabilir, False: Yapılamaz.
        """
        for exc_type in self.non_retryable_exceptions:
            if isinstance(error, exc_type):
                return False

        if isinstance(error, HTTPStatusError):
            if error.status_code in DEFAULT_NON_RETRYABLE_STATUS_CODES:
                return False
            if error.status_code in DEFAULT_RETRYABLE_STATUS_CODES:
                return True

        return any(isinstance(error, exc_type) for exc_type in self.retryable_exceptions)

    def _calculate_delay(self, attempt: int) -> float:
        """Gecikme süresini hesaplar (exponential backoff + jitter).

        Args:
            attempt: Mevcut deneme numarası (1'den başlar).

        Returns:
            Gecikme süresi (saniye).
        """
        delay = self.config.base_delay_s * (self.config.backoff_factor ** (attempt - 1))

        delay = min(delay, self.config.max_delay_s)

        if self.config.jitter:
            jitter_amount = delay * self.config.jitter_range
            delay += random.uniform(-jitter_amount, jitter_amount)
            delay = max(0.1, delay)

        return delay

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Async fonksiyonu retry ile çalıştırır.

        Args:
            func: Async fonksiyon.
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            Fonksiyon sonucu.

        Raises:
            RetryExhaustedError: Tüm denemeler tükendiğinde.
            Exception: Non-retryable hata.
        """
        async with self._lock:
            self.stats.total_calls += 1
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = await func(*args, **kwargs)
                async with self._lock:
                    self.stats.total_successes += 1
                if attempt > 1:
                    logger.info("Retry succeeded", attempt=attempt, total_attempts=self.config.max_attempts)
                return result

            except Exception as exc:
                last_error = exc

                if not self._is_retryable(exc):
                    logger.warning("Non-retryable error", error=str(exc), error_type=type(exc).__name__)
                    async with self._lock:
                        self.stats.total_failures += 1
                    raise

                if attempt >= self.config.max_attempts:
                    break

                delay = self._calculate_delay(attempt)
                async with self._lock:
                    self.stats.total_retries += 1
                    self.stats.total_wait_seconds += delay
                    self.stats.last_retry_time = time.time()
                    self.stats.max_attempts_used = max(self.stats.max_attempts_used, attempt)

                logger.warning(
                    "Retry attempt",
                    attempt=attempt,
                    max_attempts=self.config.max_attempts,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

                await asyncio.sleep(delay)

        async with self._lock:
            self.stats.total_failures += 1
        raise RetryExhaustedError(
            attempts=self.config.max_attempts,
            last_error=last_error,  # type: ignore[arg-type]
        )

    def execute_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Senkron fonksiyonu retry ile çalıştırır.

        Args:
            func: Senkron fonksiyon.
            *args: Fonksiyon argümanları.
            **kwargs: Fonksiyon anahtar kelime argümanları.

        Returns:
            Fonksiyon sonucu.

        Raises:
            RetryExhaustedError: Tüm denemeler tükendiğinde.
            Exception: Non-retryable hata.
        """
        with self._sync_lock:
            self.stats.total_calls += 1
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                with self._sync_lock:
                    self.stats.total_successes += 1
                return result

            except Exception as exc:
                last_error = exc

                if not self._is_retryable(exc):
                    with self._sync_lock:
                        self.stats.total_failures += 1
                    raise

                if attempt >= self.config.max_attempts:
                    break

                delay = self._calculate_delay(attempt)
                with self._sync_lock:
                    self.stats.total_retries += 1
                    self.stats.total_wait_seconds += delay

                logger.warning("Retry attempt (sync)", attempt=attempt, delay_seconds=round(delay, 2), error=str(exc))

                time.sleep(delay)

        with self._sync_lock:
            self.stats.total_failures += 1
        raise RetryExhaustedError(
            attempts=self.config.max_attempts,
            last_error=last_error,  # type: ignore[arg-type]
        )

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndürür.

        Returns:
            Retry istatistik sözlüğü.
        """
        return {
            "total_calls": self.stats.total_calls,
            "total_retries": self.stats.total_retries,
            "total_successes": self.stats.total_successes,
            "total_failures": self.stats.total_failures,
            "success_rate": round(self.stats.total_successes / max(self.stats.total_calls, 1), 3),
            "avg_retries_per_call": round(self.stats.total_retries / max(self.stats.total_calls, 1), 2),
            "total_wait_seconds": round(self.stats.total_wait_seconds, 2),
            "max_attempts_used": self.stats.max_attempts_used,
        }


# BIST'e özgü retry policy'ler
DEFAULT_BIST_RETRY_POLICIES: dict[str, RetryPolicy] = {
    "yfinance": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "kap": RetryPolicy(max_attempts=3, base_delay_s=2.0, max_delay_s=60.0),
    "tcmb": RetryPolicy(max_attempts=3, base_delay_s=2.0, max_delay_s=60.0),
    "bist": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "matriks": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=60.0),
    "social": RetryPolicy(max_attempts=2, base_delay_s=2.0, max_delay_s=60.0),
    "news": RetryPolicy(max_attempts=2, base_delay_s=1.0, max_delay_s=60.0),
}


# Bilinmeyen provider için varsayılan retry policy
DEFAULT_RETRY_POLICY: RetryPolicy = RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=30.0)


def get_retry_policy(provider: str) -> RetryPolicy:
    """Provider için retry policy döndürür.

    Args:
        provider: Provider adı.

    Returns:
        RetryPolicy örneği (bilinmeyen provider için varsayılan).
    """
    return DEFAULT_BIST_RETRY_POLICIES.get(provider, DEFAULT_RETRY_POLICY)


__all__ = [
    "RetryConfig",
    "RetryStats",
    "HTTPStatusError",
    "RetryExhaustedError",
    "RetryPolicy",
    "DEFAULT_RETRYABLE_STATUS_CODES",
    "DEFAULT_NON_RETRYABLE_STATUS_CODES",
    "DEFAULT_BIST_RETRY_POLICIES",
    "get_retry_policy",
    "DEFAULT_RETRY_POLICY",
]
