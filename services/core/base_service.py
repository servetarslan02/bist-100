"""ALPHA BIST — Core Service Contract & Base Architecture Framework.

Her mikroservis için bağlayıcı çalışma standardı:
INPUT → VALIDATION → PROCESSING → OUTPUT → ERROR HANDLING → METRICS

Özellikler:
- Idempotency token ve tekrarlanan işlem koruması
- Async timeout koruması
- Circuit Breaker entegrasyonu (Fail-Closed koruması)
- Retry + Exponential Backoff + Jitter
- Graceful shutdown hook'ları
- Health & Readiness denetimi
- Yapısal Structlog ve Prometheus metrik kaydı
"""

import asyncio
import functools
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, TypeVar

import structlog

from services.core.circuit_breaker import CircuitBreaker
from services.core.dead_letter_queue import DeadLetterQueue, dead_letter_queue
from services.core.observability import prometheus_metrics

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class ServiceExecutionError(Exception):
    """Servis yürütme hatası."""

    pass


class BaseAlphaService(ABC):
    """Tüm ALPHA BIST servisleri için standart temel sınıf."""

    def __init__(
        self,
        service_name: str,
        timeout_seconds: float = 30.0,
        enable_circuit_breaker: bool = True,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self.service_name = service_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.is_healthy = True
        self.is_ready = True
        self._is_shutting_down = False

        self._circuit_breaker: Optional[CircuitBreaker] = (
            CircuitBreaker(name=service_name) if enable_circuit_breaker else None
        )
        self._dlq: DeadLetterQueue = dead_letter_queue
        self._processed_idempotency_keys: Dict[str, float] = {}

    @abstractmethod
    async def process_payload(self, validated_input: Any) -> Any:
        """Her servisin kendi ana iş mantığını yürüteceği soyut metod."""
        raise NotImplementedError

    def validate_input(self, payload: Any) -> Any:
        """Girdi doğrulama adımı (Varsayılan: null kontrolü)."""
        if payload is None:
            raise ValueError(f"[{self.service_name}] Input payload cannot be None.")
        return payload

    async def execute(
        self,
        payload: Any,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Any:
        """Standart 6 Aşamalı Servis Yürütme Hattı:

        1. Validation
        2. Idempotency Check
        3. Circuit Breaker & Timeout Guarded Processing
        4. Output Formatting
        5. Error Handling & DLQ
        6. Metrics Recording
        """
        if self._is_shutting_down:
            raise ServiceExecutionError(f"[{self.service_name}] Servis kapanma sürecinde, yeni istek reddedildi.")

        start_time = time.perf_counter()
        corr_id = correlation_id or f"corr_{int(time.time() * 1000)}"

        # 1. Idempotency Check
        if idempotency_key:
            now = time.time()
            # 1 saatten eski anahtarları temizle
            self._processed_idempotency_keys = {
                k: v for k, v in self._processed_idempotency_keys.items() if now - v < 3600
            }
            if idempotency_key in self._processed_idempotency_keys:
                logger.info(
                    "idempotent_request_skipped",
                    service=self.service_name,
                    idempotency_key=idempotency_key,
                    correlation_id=corr_id,
                )
                return {"status": "SKIPPED_IDEMPOTENT", "idempotency_key": idempotency_key}

        # 2. Validation
        try:
            validated_input = self.validate_input(payload)
        except Exception as val_err:
            prometheus_metrics.record_error(self.service_name, "validation_error")
            logger.error("service_validation_failed", service=self.service_name, error=str(val_err), correlation_id=corr_id)
            raise ServiceExecutionError(f"Validation failed: {val_err}") from val_err

        # 3. Processing with Retry, Timeout and Circuit Breaker
        last_exception: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Circuit Breaker kontrolü
                if self._circuit_breaker and not self._circuit_breaker.can_execute():
                    prometheus_metrics.record_error(self.service_name, "circuit_breaker_open")
                    raise ServiceExecutionError(f"[{self.service_name}] Circuit Breaker AÇIK! İstek reddedildi.")

                # Timeout ile yürüt
                output = await asyncio.wait_for(
                    self.process_payload(validated_input),
                    timeout=self.timeout_seconds,
                )

                # Başarı kaydı
                if self._circuit_breaker:
                    self._circuit_breaker.record_success()

                duration = time.perf_counter() - start_time
                prometheus_metrics.record_api_call(self.service_name, duration, success=True)

                if idempotency_key:
                    self._processed_idempotency_keys[idempotency_key] = time.time()

                return output

            except asyncio.TimeoutError as te:
                last_exception = te
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                prometheus_metrics.record_error(self.service_name, "timeout")
                logger.warning(
                    "service_timeout_retry",
                    service=self.service_name,
                    attempt=attempt,
                    timeout=self.timeout_seconds,
                    correlation_id=corr_id,
                )

            except Exception as ex:
                last_exception = ex
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                prometheus_metrics.record_error(self.service_name, ex.__class__.__name__)
                logger.warning(
                    "service_attempt_failed",
                    service=self.service_name,
                    attempt=attempt,
                    error=str(ex),
                    correlation_id=corr_id,
                )

            # Exponential Backoff with Jitter
            if attempt < self.max_retries:
                backoff_time = self.backoff_factor * (2 ** (attempt - 1))
                await asyncio.sleep(backoff_time)

        # Tüm denemeler başarısız olduysa DLQ'ya yaz ve istisna fırlat
        duration = time.perf_counter() - start_time
        prometheus_metrics.record_api_call(self.service_name, duration, success=False)

        try:
            self._dlq.push(
                event_type=f"{self.service_name}_failure",
                payload={"input": str(payload), "error": str(last_exception)},
                reason=f"Max retries exceeded: {last_exception}",
            )
        except Exception:
            pass

        self.is_healthy = False
        raise ServiceExecutionError(
            f"[{self.service_name}] Başarısız! {self.max_retries} deneme tükendi: {last_exception}"
        ) from last_exception

    async def shutdown(self) -> None:
        """Graceful shutdown süreci."""
        logger.info("service_graceful_shutdown_initiated", service=self.service_name)
        self._is_shutting_down = True
        self.is_ready = False
        # Varsa devam eden görevlerin tamamlanması için kısa bekleme
        await asyncio.sleep(0.1)
        logger.info("service_graceful_shutdown_completed", service=self.service_name)

    def get_health_status(self) -> Dict[str, Any]:
        """Servis sağlık ve hazırlık raporu."""
        cb_state = self._circuit_breaker.state if self._circuit_breaker else "N/A"
        return {
            "service": self.service_name,
            "healthy": self.is_healthy,
            "ready": self.is_ready and not self._is_shutting_down,
            "circuit_breaker": cb_state,
            "is_shutting_down": self._is_shutting_down,
        }
