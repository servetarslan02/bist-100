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
import inspect
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeVar

import duckdb
import orjson
import polars as pl
import structlog

from services.core.circuit_breaker import CircuitBreaker, CircuitState
from services.core.dead_letter_queue import DeadLetterQueue, dead_letter_queue
from services.core.observability import prometheus_metrics

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_BACKOFF_FACTOR: Final[float] = 0.5
DEFAULT_IDEMPOTENCY_TTL_SECONDS: Final[float] = 3600.0
DEFAULT_IDEMPOTENCY_MAX_KEYS: Final[int] = 5000
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_METRICS_DB_PATH: Final[str] = "data/service_metrics.duckdb"
DEFAULT_SERVICE_METRICS_DB: Final[str] = DEFAULT_METRICS_DB_PATH
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"
DEFAULT_EXECUTION_HISTORY_LIMIT: Final[int] = 1000

T = TypeVar("T")


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri.

    Returns:
        bytes: orjson ile kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


@dataclass(slots=True)
class ServiceExecutionRecord:
    """Mikroservis çalışma metrik ve izleme kaydı."""

    service_name: str
    correlation_id: str
    duration_ms: float
    success: bool
    error_type: str | None
    attempt_count: int
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        """Kayıt alanlarını sözlük biçimine dönüştürür."""
        return {
            "service_name": self.service_name,
            "correlation_id": self.correlation_id,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "error_type": self.error_type,
            "attempt_count": self.attempt_count,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Kayıt verilerini orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Kayıt metin temsilini döner."""
        return (
            f"ServiceExecutionRecord(servis={self.service_name!r}, "
            f"korelasyon={self.correlation_id!r}, sure_ms={self.duration_ms:.1f}, "
            f"basari={self.success})"
        )


class ServiceExecutionError(Exception):
    """Servis yürütme hatası istisnası."""

    def __init__(
        self,
        message: str,
        service_name: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """İstisna nesnesini başlatır.

        Args:
            message: Açıklayıcı hata iletisi.
            service_name: İsteğe bağlı servis adı.
            correlation_id: İsteğe bağlı işlem korelasyon kimliği.
        """
        super().__init__(message)
        self.message = message
        self.service_name = service_name
        self.correlation_id = correlation_id

    def __repr__(self) -> str:
        """İstisnanın okunabilir temsilini döner."""
        return (
            f"<ServiceExecutionError(servis={self.service_name!r}, "
            f"korelasyon={self.correlation_id!r}, mesaj={self.message!r})>"
        )


class BaseAlphaService(ABC):
    """Tüm ALPHA BIST mikroservisleri için standart ve zırhlandırılmış temel sınıf."""

    def __init__(
        self,
        service_name: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        enable_circuit_breaker: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        idempotency_ttl_seconds: float = DEFAULT_IDEMPOTENCY_TTL_SECONDS,
        idempotency_max_keys: int = DEFAULT_IDEMPOTENCY_MAX_KEYS,
        dlq: DeadLetterQueue | None = None,
    ) -> None:
        """Temel mikroservis örneğini başlatır.

        Args:
            service_name: Servisin tekil adı (örn. 'market_session', 'order_router').
            timeout_seconds: İşlem başına maksimum zaman aşımı süresi (saniye).
            enable_circuit_breaker: Circuit Breaker korumasının aktif edilip edilmeyeceği.
            max_retries: Hata durumunda izin verilen maksimum yeniden deneme sayısı.
            backoff_factor: Üstel geri çekilme (exponential backoff) çarpanı.
            idempotency_ttl_seconds: Tekrarlanan işlem önbellek saklama süresi (saniye).
            idempotency_max_keys: Tekrarlanan işlem önbelleği maksimum eleman kapasitesi.
            dlq: İsteğe bağlı özel Dead Letter Queue örneği.
        """
        self.service_name: str = service_name
        self.timeout_seconds: float = max(0.001, float(timeout_seconds))
        self.max_retries: int = max(1, int(max_retries))
        self.backoff_factor: float = max(0.0, float(backoff_factor))
        self.idempotency_ttl_seconds: float = max(1.0, float(idempotency_ttl_seconds))
        self.idempotency_max_keys: int = max(100, int(idempotency_max_keys))

        self.is_healthy: bool = True
        self.is_ready: bool = True
        self._is_shutting_down: bool = False
        self._active_requests: int = 0

        self._lock: threading.RLock = threading.RLock()
        self._circuit_breaker: CircuitBreaker | None = (
            CircuitBreaker(name=service_name) if enable_circuit_breaker else None
        )
        self._dlq: DeadLetterQueue = dlq or dead_letter_queue
        self._processed_idempotency_keys: dict[str, float] = {}
        self._in_flight_idempotency_keys: set[str] = set()
        self._execution_history: deque[ServiceExecutionRecord] = deque(maxlen=DEFAULT_EXECUTION_HISTORY_LIMIT)

    @property
    def circuit_breaker(self) -> CircuitBreaker | None:
        """Servise bağlı devre kesici nesnesini döner."""
        return self._circuit_breaker

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
        2. Idempotency Denetimi (Eşzamanlı ve geçmiş tekrarlanan işlem engelleme)
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
        corr_id = correlation_id or f"corr_{int(time.time() * 1000)}"

        with self._lock:
            if self._is_shutting_down:
                raise ServiceExecutionError(f"[{self.service_name}] Servis kapanma sürecinde, yeni istek reddedildi.")
            self._active_requests += 1

            # 1. Idempotency Check (Thread-safe, In-Flight & TTL-guarded)
            if idempotency_key:
                now = time.time()
                if idempotency_key in self._in_flight_idempotency_keys:
                    self._active_requests = max(0, self._active_requests - 1)
                    logger.warning(
                        "concurrent_idempotent_request_rejected",
                        service=self.service_name,
                        idempotency_key=idempotency_key,
                        correlation_id=corr_id,
                    )
                    raise ServiceExecutionError(
                        f"[{self.service_name}] Aynı idempotency anahtarına ({idempotency_key}) sahip bir istek halihazırda yürütülüyor."
                    )

                # Kapasite temizliği
                if len(self._processed_idempotency_keys) > self.idempotency_max_keys:
                    self._processed_idempotency_keys = {
                        k: v
                        for k, v in self._processed_idempotency_keys.items()
                        if now - v < self.idempotency_ttl_seconds
                    }

                # Tamamlanmış kayıt denetimi
                recorded_time = self._processed_idempotency_keys.get(idempotency_key)
                if recorded_time is not None:
                    if now - recorded_time < self.idempotency_ttl_seconds:
                        self._active_requests = max(0, self._active_requests - 1)
                        logger.info(
                            "idempotent_request_skipped",
                            service=self.service_name,
                            idempotency_key=idempotency_key,
                            correlation_id=corr_id,
                        )
                        return {"status": "SKIPPED_IDEMPOTENT", "idempotency_key": idempotency_key}
                    # Süresi dolmuşsa kaldır ve yeniden işlenmesine izin ver
                    del self._processed_idempotency_keys[idempotency_key]

                # Eşzamanlı çakışmaları önlemek için aktif olarak işaretle
                self._in_flight_idempotency_keys.add(idempotency_key)

        try:
            start_time = time.perf_counter()

            # 2. Pre-Execution Circuit Breaker Check (Fail-Fast)
            if self._circuit_breaker and not self._circuit_breaker.can_execute():
                prometheus_metrics.record_error(self.service_name, "circuit_breaker_open")
                raise ServiceExecutionError(
                    f"[{self.service_name}] Devre Kesici (Circuit Breaker) AÇIK! İstek reddedildi.",
                    service_name=self.service_name,
                    correlation_id=corr_id,
                )

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
                raise ServiceExecutionError(
                    f"Doğrulama başarısız: {val_err}",
                    service_name=self.service_name,
                    correlation_id=corr_id,
                ) from val_err

            # 4. Processing with Retry, Timeout and Circuit Breaker
            last_exception: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    # Circuit Breaker kontrolü - Fail-fast durumunda döngüyü hemen kır
                    if self._circuit_breaker and not self._circuit_breaker.can_execute():
                        prometheus_metrics.record_error(self.service_name, "circuit_breaker_open")
                        last_exception = ServiceExecutionError(
                            f"[{self.service_name}] Devre Kesici (Circuit Breaker) AÇIK! İstek reddedildi.",
                            service_name=self.service_name,
                            correlation_id=corr_id,
                        )
                        break

                    # Timeout ile yürüt
                    output = await asyncio.wait_for(
                        self.process_payload(validated_input),
                        timeout=self.timeout_seconds,
                    )

                    # Başarı kaydı
                    if self._circuit_breaker:
                        self._circuit_breaker.record_success()

                    self.is_healthy = True
                    duration = time.perf_counter() - start_time
                    duration_ms = duration * 1000.0
                    prometheus_metrics.record_api_call(self.service_name, duration, success=True)

                    rec = ServiceExecutionRecord(
                        service_name=self.service_name,
                        correlation_id=corr_id,
                        duration_ms=duration_ms,
                        success=True,
                        error_type=None,
                        attempt_count=attempt,
                        timestamp=time.time(),
                    )
                    with self._lock:
                        self._execution_history.append(rec)
                        if idempotency_key:
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

                except asyncio.CancelledError:
                    logger.warning(
                        "service_request_cancelled",
                        service=self.service_name,
                        correlation_id=corr_id,
                    )
                    raise

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
            duration_ms = duration * 1000.0
            prometheus_metrics.record_api_call(self.service_name, duration, success=False)
            err_name = last_exception.__class__.__name__ if last_exception else "UnknownError"

            rec = ServiceExecutionRecord(
                service_name=self.service_name,
                correlation_id=corr_id,
                duration_ms=duration_ms,
                success=False,
                error_type=err_name,
                attempt_count=self.max_retries,
                timestamp=time.time(),
            )
            with self._lock:
                self._execution_history.append(rec)

            try:
                safe_payload = payload if isinstance(payload, (dict, list, str, int, float, bool)) else str(payload)
                try:
                    payload_str = orjson.dumps(safe_payload, default=str).decode("utf-8")
                except Exception:
                    payload_str = str(safe_payload)

                event_id = corr_id
                event_type = f"{self.service_name}_failure"
                error_msg = f"Maksimum deneme ({self.max_retries}) tükendi: {last_exception}"

                dlq_res = self._dlq.push(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload_str,
                    error=error_msg,
                    retry_count=self.max_retries,
                    max_retries=self.max_retries,
                )
                if inspect.isawaitable(dlq_res):
                    await dlq_res
            except Exception as dlq_err:
                logger.warning("dlq_push_fallback_failed", service=self.service_name, error=str(dlq_err))

            if self._circuit_breaker and self._circuit_breaker.state == CircuitState.OPEN:
                self.is_healthy = False

            raise ServiceExecutionError(
                f"[{self.service_name}] Başarısız! {self.max_retries} deneme tükendi: {last_exception}",
                service_name=self.service_name,
                correlation_id=corr_id,
            ) from last_exception

        finally:
            with self._lock:
                if idempotency_key:
                    self._in_flight_idempotency_keys.discard(idempotency_key)
                self._active_requests = max(0, self._active_requests - 1)

    async def shutdown(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Servisi güvenli ve zarif şekilde kapatır (Graceful shutdown).

        Aktif isteklerin tamamlanması için belirtilen süre kadar bekler.

        Args:
            timeout: Aktif isteklerin tamamlanması için tanınan maksimum bekleme süresi (sn).
        """
        with self._lock:
            self._is_shutting_down = True
            self.is_ready = False
            active_at_start = self._active_requests

        logger.info(
            "service_graceful_shutdown_initiated",
            service=self.service_name,
            aktif_istek_sayisi=active_at_start,
        )

        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if self._active_requests <= 0:
                    break
            await asyncio.sleep(0.05)

        with self._lock:
            remaining = self._active_requests

        if remaining > 0:
            logger.warning(
                "service_graceful_shutdown_timeout_exceeded",
                service=self.service_name,
                kalan_istek=remaining,
                timeout=timeout,
            )
        else:
            logger.info(
                "service_graceful_shutdown_completed",
                service=self.service_name,
                kalan_istek=remaining,
            )

    def clear_idempotency_cache(self) -> int:
        """Önbellekte saklanan tüm idempotency anahtarlarını temizler.

        Returns:
            Temizlenen anahtar sayısı.
        """
        with self._lock:
            count = len(self._processed_idempotency_keys)
            self._processed_idempotency_keys.clear()
            self._in_flight_idempotency_keys.clear()
            return count

    def reset_circuit_breaker(self) -> None:
        """Devre kesiciyi sıfırlayarak kapalı (CLOSED) duruma getirir."""
        if self._circuit_breaker:
            with self._circuit_breaker._lock:
                old_state = self._circuit_breaker.state.value
                self._circuit_breaker.state = CircuitState.CLOSED
                self._circuit_breaker.failure_count = 0
                self._circuit_breaker.half_open_calls = 0
                if hasattr(self._circuit_breaker, "_update_telemetry"):
                    self._circuit_breaker._update_telemetry()
                if hasattr(self._circuit_breaker, "_persist_to_store"):
                    self._circuit_breaker._persist_to_store()
            if hasattr(self._circuit_breaker, "_notify_state_change"):
                self._circuit_breaker._notify_state_change(old_state, CircuitState.CLOSED.value)
            self.is_healthy = True

    def get_health_status(self) -> dict[str, Any]:
        """Servis sağlık ve hazırlık durum raporunu döner.

        Returns:
            Sağlık, hazırlık ve devre kesici durumunu özetleyen sözlük.
        """
        cb_open = bool(self._circuit_breaker and self._circuit_breaker.state == CircuitState.OPEN)
        effective_healthy = self.is_healthy and not cb_open
        cb_state = self._circuit_breaker.state.value if self._circuit_breaker else "N/A"
        with self._lock:
            active_req = self._active_requests
            idempotency_keys_count = len(self._processed_idempotency_keys)
            in_flight_count = len(self._in_flight_idempotency_keys)
            shutting_down = self._is_shutting_down
            history_count = len(self._execution_history)

        return {
            "service": self.service_name,
            "healthy": effective_healthy,
            "ready": self.is_ready and not shutting_down and not cb_open,
            "circuit_breaker": cb_state,
            "is_shutting_down": shutting_down,
            "active_requests": active_req,
            "in_flight_idempotency_keys": in_flight_count,
            "cached_idempotency_keys": idempotency_keys_count,
            "execution_history_count": history_count,
        }

    def get_execution_metrics(self, limit: int = 100) -> list[dict[str, Any]]:
        """Son çalışma kayıtlarını sözlük listesi olarak döner.

        Args:
            limit: Dönecek maksimum kayıt adedi.

        Returns:
            Son çalışma kayıtlarının sözlük listesi.
        """
        with self._lock:
            records = list(self._execution_history)[-max(1, limit):]
        return [r.to_dict() for r in records]

    def export_metrics_to_polars(self) -> pl.DataFrame:
        """Son çalışma metriklerini Polars DataFrame olarak döner.

        Returns:
            pl.DataFrame: Metrik tablosu.
        """
        with self._lock:
            records = [r.to_dict() for r in self._execution_history]

        if not records:
            return pl.DataFrame(
                schema={
                    "service_name": pl.Utf8,
                    "correlation_id": pl.Utf8,
                    "duration_ms": pl.Float64,
                    "success": pl.Boolean,
                    "error_type": pl.Utf8,
                    "attempt_count": pl.Int64,
                    "timestamp": pl.Float64,
                }
            )
        return pl.DataFrame(records)

    def export_metrics_to_duckdb(self, db_path: str = DEFAULT_METRICS_DB_PATH) -> int:
        """Çalışma metriklerini DuckDB veritabanına kaydeder.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            int: Eklenen kayıt sayısı.
        """
        df = self.export_metrics_to_polars()
        if df.is_empty():
            return 0

        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_execution_logs (
                    service_name VARCHAR,
                    correlation_id VARCHAR,
                    duration_ms DOUBLE,
                    success BOOLEAN,
                    error_type VARCHAR,
                    attempt_count BIGINT,
                    timestamp DOUBLE
                )
                """
            )
            conn.register("tmp_metrics_df", df)
            conn.execute("INSERT INTO service_execution_logs SELECT * FROM tmp_metrics_df")
            inserted_count = len(df)
        return inserted_count

    def get_performance_summary(self) -> dict[str, Any]:
        """Polars vektörizasyonu ile hesaplanmış performans özetini döner.

        Returns:
            dict: Toplam istek, başarı oranı, ortalama ve %95 persentil gecikme.
        """
        df = self.export_metrics_to_polars()
        if df.is_empty():
            return {
                "service_name": self.service_name,
                "total_executions": 0,
                "success_rate": 1.0,
                "avg_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
            }

        total = len(df)
        success_count = df.filter(pl.col("success")).height
        success_rate = (success_count / total) if total > 0 else 1.0
        avg_dur = float(df.select(pl.col("duration_ms").mean()).item() or 0.0)
        p95_dur = float(df.select(pl.col("duration_ms").quantile(0.95)).item() or 0.0)

        return {
            "service_name": self.service_name,
            "total_executions": total,
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": round(avg_dur, 2),
            "p95_duration_ms": round(p95_dur, 2),
        }

    def to_dict(self) -> dict[str, Any]:
        """Servis durumunu ve metrik özetini sözlük olarak döner."""
        return self.get_health_status()

    def to_orjson_bytes(self) -> bytes:
        """Servis durumunu orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_METRICS_DB_PATH) -> None:
        """Servis metrik DuckDB tablosunu sıfırlar."""
        clear_service_metrics_duckdb(db_path=db_path)

    def __repr__(self) -> str:
        """Servisin durum özet temsilini döner."""
        with self._lock:
            active = self._active_requests
            shutting_down = self._is_shutting_down
        return (
            f"<{self.__class__.__name__}(servis='{self.service_name}', "
            f"saglikli={self.is_healthy}, hazir={self.is_ready}, "
            f"aktif_istek={active}, kapaniyor={shutting_down})>"
        )


def read_service_metrics_from_duckdb(
    db_path: str = DEFAULT_METRICS_DB_PATH,
    service_name: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB'de depolanan mikroservis metriklerini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        service_name: İsteğe bağlı servis adı filtresi.
        limit: Dönecek maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan metrikler.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame(
            schema={
                "service_name": pl.Utf8,
                "correlation_id": pl.Utf8,
                "duration_ms": pl.Float64,
                "success": pl.Boolean,
                "error_type": pl.Utf8,
                "attempt_count": pl.Int64,
                "timestamp": pl.Float64,
            }
        )

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'service_execution_logs'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(
                    schema={
                        "service_name": pl.Utf8,
                        "correlation_id": pl.Utf8,
                        "duration_ms": pl.Float64,
                        "success": pl.Boolean,
                        "error_type": pl.Utf8,
                        "attempt_count": pl.Int64,
                        "timestamp": pl.Float64,
                    }
                )

            query = "SELECT * FROM service_execution_logs"
            clauses: list[str] = []
            params: list[Any] = []
            if service_name:
                clauses.append("service_name = ?")
                params.append(service_name)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY timestamp DESC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            arrow_table = conn.execute(query, params).arrow()
            return pl.from_arrow(arrow_table)
    except Exception as exc:
        logger.warning("duckdb_servis_metrikleri_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(
            schema={
                "service_name": pl.Utf8,
                "correlation_id": pl.Utf8,
                "duration_ms": pl.Float64,
                "success": pl.Boolean,
                "error_type": pl.Utf8,
                "attempt_count": pl.Int64,
                "timestamp": pl.Float64,
            }
        )


def clear_service_metrics_duckdb(db_path: str = DEFAULT_METRICS_DB_PATH) -> None:
    """DuckDB'de depolanan mikroservis metrikleri tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS service_execution_logs;")
    except Exception as exc:
        logger.error("duckdb_servis_metrikleri_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_EXECUTION_HISTORY_LIMIT",
    "DEFAULT_IDEMPOTENCY_MAX_KEYS",
    "DEFAULT_IDEMPOTENCY_TTL_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_METRICS_DB_PATH",
    "DEFAULT_SERVICE_METRICS_DB",
    "DEFAULT_SHUTDOWN_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_WAL_SIZE",
    "BaseAlphaService",
    "ServiceExecutionError",
    "ServiceExecutionRecord",
    "clear_service_metrics_duckdb",
    "configure_duckdb_wal",
    "read_service_metrics_from_duckdb",
    "to_orjson_bytes",
]
