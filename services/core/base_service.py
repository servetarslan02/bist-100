"""ALPHA BIST — Çekirdek Servis Sözleşmesi ve Temel Mimari Çerçevesi (Base Service).

Her BIST mikroservisi için bağlayıcı 6 aşamalı standart çalışma boru hattı:
GİRDİ DOĞRULAMA -> TEKRAR KORUMASI (IDEMPOTENCY) -> DEVRE KESİCİ & ZAMAN AŞIMI KORUMALI İŞLEME
-> ÇIKTI BİÇİMLENDİRME -> HATA YÖNETİMİ & DLQ -> METRİK KAYDI

Özellikler:
- Idempotency token ve tekrarlanan işlem koruması (otomatik TTL ve boyut temizliği)
- Asenkron zaman aşımı (async timeout) koruması
- Circuit Breaker entegrasyonu (Fail-Closed koruması ve erken devre dışı kalma)
- Exponential Backoff + Jitter ile akıllı yeniden deneme (retry)
- Zarif kapanma (Graceful shutdown) kancaları
- Servis sağlık ve hazırlık (Health & Readiness) denetimi
- Yapısal Structlog ve Prometheus metrik entegrasyonu
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import structlog

from services.core.circuit_breaker import CircuitBreaker
from services.core.dead_letter_queue import DeadLetterQueue, dead_letter_queue
from services.core.observability import prometheus_metrics

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BACKOFF_FACTOR: float = 0.5
DEFAULT_IDEMPOTENCY_TTL_SECONDS: float = 3600.0
DEFAULT_IDEMPOTENCY_MAX_KEYS: int = 5000

T = TypeVar("T")


class ServiceExecutionError(Exception):
    """Servis yürütme hatası istisnası."""

    def __init__(self, message: str) -> None:
        """İstisna nesnesini başlatır.

        Args:
            message: Açıklayıcı hata iletisi.
        """
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:
        """İstisnanın okunabilir temsilini döner."""
        return f"<ServiceExecutionError(mesaj='{self.message}')>"


class BaseAlphaService(ABC):
    """Tüm ALPHA BIST mikroservisleri için standart ve zırhlandırılmış temel sınıf."""

    def __init__(
        self,
        service_name: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        enable_circuit_breaker: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ) -> None:
        """Temel mikroservis örneğini başlatır.

        Args:
            service_name: Servisin tekil adı (örn. 'market_session', 'order_router').
            timeout_seconds: İşlem başına maksimum zaman aşımı süresi (saniye).
            enable_circuit_breaker: Circuit Breaker korumasının aktif edilip edilmeyeceği.
            max_retries: Hata durumunda izin verilen maksimum yeniden deneme sayısı.
            backoff_factor: Üstel geri çekilme (exponential backoff) çarpanı.
        """
        self.service_name: str = service_name
        self.timeout_seconds: float = timeout_seconds
        self.max_retries: int = max_retries
        self.backoff_factor: float = backoff_factor
        self.is_healthy: bool = True
        self.is_ready: bool = True
        self._is_shutting_down: bool = False

        self._lock: threading.Lock = threading.Lock()
        self._circuit_breaker: CircuitBreaker | None = (
            CircuitBreaker(name=service_name) if enable_circuit_breaker else None
        )
        self._dlq: DeadLetterQueue = dead_letter_queue
        self._processed_idempotency_keys: dict[str, float] = {}

    @abstractmethod
    async def process_payload(self, validated_input: Any) -> Any:
        """Her servisin kendi ana iş mantığını yürüteceği soyut metod.

        Args:
            validated_input: Doğrulanmış girdi yükü.

        Returns:
            İşlenmiş çıktı sonucu.

        Raises:
            NotImplementedError: Alt sınıfta uygulanmadığında fırlatılır.
        """
        raise NotImplementedError

    def validate_input(self, payload: Any) -> Any:
        """Girdi yükü doğrulama adımı (Varsayılan: None kontrolü).

        Args:
            payload: Servise iletilen ham veri yükü.

        Returns:
            Doğrulanmış girdi nesnesi.

        Raises:
            ValueError: payload None ise fail-closed gereği fırlatılır.
        """
        if payload is None:
            raise ValueError(f"[{self.service_name}] Girdi veri yükü (payload) None olamaz.")
        return payload

    async def execute(
        self,
        payload: Any,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        """Standart 6 Aşamalı Servis Yürütme Hattı:

        1. Doğrulama (Validation)
        2. Idempotency Denetimi (Tekrarlanan işlem engelleme)
        3. Circuit Breaker & Timeout Korumalı Yürütme
        4. Çıktı Biçimlendirme
        5. Hata Yönetimi & DLQ Kaydı
        6. Metrik ve Performans Kaydı

        Args:
            payload: Servis girdi yükü.
            idempotency_key: Tekil işlem anahtarı (varsa tekrarlar atlanır).
            correlation_id: Dağıtık izleme ve loglama korelasyon kimliği.

        Returns:
            Servis işleme sonucu veya atlama yanıtı.

        Raises:
            ServiceExecutionError: Doğrulama, zaman aşımı veya yürütme başarısız olduğunda.
        """
        if self._is_shutting_down:
            raise ServiceExecutionError(f"[{self.service_name}] Servis kapanma sürecinde, yeni istek reddedildi.")

        start_time = time.perf_counter()
        corr_id = correlation_id or f"corr_{int(time.time() * 1000)}"

        # 1. Idempotency Check (Thread-safe)
        if idempotency_key:
            now = time.time()
            with self._lock:
                if len(self._processed_idempotency_keys) > DEFAULT_IDEMPOTENCY_MAX_KEYS:
                    valid_items = {
                        k: v
                        for k, v in list(self._processed_idempotency_keys.items())
                        if now - v < DEFAULT_IDEMPOTENCY_TTL_SECONDS
                    }
                    self._processed_idempotency_keys = valid_items

                if idempotency_key in self._processed_idempotency_keys:
                    logger.info(
                        "idempotent_request_skipped",
                        service=self.service_name,
                        idempotency_key=idempotency_key,
                        correlation_id=corr_id,
                    )
                    return {"status": "SKIPPED_IDEMPOTENT", "idempotency_key": idempotency_key}

        # 2. Pre-Execution Circuit Breaker Check (Fail-Fast)
        if self._circuit_breaker and not self._circuit_breaker.can_execute():
            prometheus_metrics.record_error(self.service_name, "circuit_breaker_open")
            raise ServiceExecutionError(f"[{self.service_name}] Circuit Breaker AÇIK! İstek reddedildi.")

        # 3. Validation
        try:
            validated_input = self.validate_input(payload)
        except Exception as val_err:
            prometheus_metrics.record_error(self.service_name, "validation_error")
            logger.error(
                "service_validation_failed",
                service=self.service_name,
                error=str(val_err),
                correlation_id=corr_id,
            )
            raise ServiceExecutionError(f"Doğrulama başarısız: {val_err}") from val_err

        # 4. Processing with Retry, Timeout and Circuit Breaker
        last_exception: Exception | None = None
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
                    with self._lock:
                        self._processed_idempotency_keys[idempotency_key] = time.time()

                return output

            except TimeoutError as te:
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

            # Eğer devre açıldıysa döngüde daha fazla bekleyip retry yapma, anında sonlandır
            if self._circuit_breaker and not self._circuit_breaker.can_execute():
                break

            # Exponential Backoff with Jitter
            if attempt < self.max_retries:
                base_backoff = self.backoff_factor * (2 ** (attempt - 1))
                jitter = random.uniform(0.0, 0.2 * base_backoff)
                backoff_time = base_backoff + jitter
                await asyncio.sleep(backoff_time)

        # Tüm denemeler başarısız olduysa DLQ'ya yaz ve istisna fırlat
        duration = time.perf_counter() - start_time
        prometheus_metrics.record_api_call(self.service_name, duration, success=False)

        try:
            self._dlq.push(
                event_type=f"{self.service_name}_failure",
                payload={"input": str(payload), "error": str(last_exception)},
                reason=f"Maksimum deneme tükendi: {last_exception}",
            )
        except Exception as dlq_err:
            logger.warning("dlq_push_fallback_failed", service=self.service_name, error=str(dlq_err))

        self.is_healthy = False
        raise ServiceExecutionError(
            f"[{self.service_name}] Başarısız! {self.max_retries} deneme tükendi: {last_exception}"
        ) from last_exception

    async def shutdown(self) -> None:
        """Servisi güvenli ve zarif şekilde kapatır (Graceful shutdown)."""
        logger.info("service_graceful_shutdown_initiated", service=self.service_name)
        self._is_shutting_down = True
        self.is_ready = False
        await asyncio.sleep(0.1)
        logger.info("service_graceful_shutdown_completed", service=self.service_name)

    def get_health_status(self) -> dict[str, Any]:
        """Servis sağlık ve hazırlık durum raporunu döner.

        Returns:
            Sağlık, hazırlık ve devre kesici durumunu özetleyen sözlük.
        """
        cb_state = self._circuit_breaker.state if self._circuit_breaker else "N/A"
        return {
            "service": self.service_name,
            "healthy": self.is_healthy,
            "ready": self.is_ready and not self._is_shutting_down,
            "circuit_breaker": cb_state,
            "is_shutting_down": self._is_shutting_down,
        }

    def __repr__(self) -> str:
        """Servisin durum özet temsilini döner."""
        return (
            f"<{self.__class__.__name__}(servis='{self.service_name}', "
            f"saglikli={self.is_healthy}, hazir={self.is_ready}, "
            f"kapaniyor={self._is_shutting_down})>"
        )


__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_IDEMPOTENCY_MAX_KEYS",
    "DEFAULT_IDEMPOTENCY_TTL_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_SECONDS",
    "BaseAlphaService",
    "ServiceExecutionError",
]
