"""
ALPHA BIST — Pipeline Hata Kurtarma Motoru

Pipeline aşamalarında oluşan hataları otomatik olarak tespit eden, sınıflandıran
ve kurtaran kapsamlı hata yönetim sistemi. Fail-closed ilkesi ile çalışır:
kurtarılamayan hatalar sistemi güvenli moda geçirir, asla sessizce geçemez.

Özellikler:
  - Yeniden deneme stratejisi: Exponential backoff + jitter (Thundering herd koruması)
  - Devre kesici (Circuit Breaker): Art arda başarısızlıkta servisi geçici devre dışı bırakır
  - Checkpoint sistemi: Başarısız aşama öncesinde son başarılı durumu DuckDB'ye kaydeder
  - Dead Letter Queue (DLQ): Kurtarılamayan hataları ayrı kuyrukta izler
  - Hata sınıflandırma: Geçici (transient) vs kalıcı (permanent) hata ayrımı
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BASE_DELAY: float = 1.0       # İlk bekleme (saniye)
DEFAULT_MAX_DELAY: float = 60.0       # Maksimum bekleme (saniye)
DEFAULT_BACKOFF_FACTOR: float = 2.0   # Üstel geri çekilme çarpanı
DEFAULT_JITTER: float = 0.25         # Bekleme süresi jitter oranı (0-1)
DEFAULT_CB_FAILURE_THRESHOLD: int = 5  # Circuit breaker açılma eşiği
DEFAULT_CB_RECOVERY_TIMEOUT: float = 60.0  # Circuit breaker kurtarma süre (saniye)
DEFAULT_CB_HALF_OPEN_ATTEMPTS: int = 1     # Yarı-açık durumdaki deneme sayısı

F = TypeVar("F")


class ErrorCategory(Enum):
    """Pipeline hata kategorisi.

    Attributes:
        TRANSIENT: Geçici hata — yeniden deneme yapılabilir (ağ, timeout vb.).
        RATE_LIMIT: Hız sınırı — bekleme ile çözülür.
        DATA_ERROR: Veri hatası — kurtarılamaz, sonraki çubuk denenebilir.
        PERMANENT: Kalıcı hata — yeniden deneme yok, DLQ'ya gönder.
        UNKNOWN: Bilinmeyen hata — ihtiyatlı olarak geçici kabul edilir.
    """

    TRANSIENT = auto()
    RATE_LIMIT = auto()
    DATA_ERROR = auto()
    PERMANENT = auto()
    UNKNOWN = auto()


class CircuitBreakerState(Enum):
    """Devre kesici durumu.

    Attributes:
        CLOSED: Normal çalışma — istekler geçer.
        OPEN: Devre açık — istekler reddedilir.
        HALF_OPEN: Yarı açık — kurtarma denemesi yapılıyor.
    """

    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


@dataclass
class RecoveryAttempt:
    """Tek bir kurtarma girişimi kaydı.

    Attributes:
        attempt_number: Deneme numarası (1'den başlar).
        error_type: Hata tipi adı.
        error_message: Hata mesajı.
        delay_seconds: Bu denemeden önce beklenen süre.
        success: Kurtarma başarılı mı?
        timestamp: Deneme zamanı (Unix timestamp).
    """

    attempt_number: int
    error_type: str
    error_message: str
    delay_seconds: float
    success: bool
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        """RecoveryAttempt kısa temsili."""
        status = "✅" if self.success else "❌"
        return (
            f"RecoveryAttempt({status} #{self.attempt_number}, "
            f"err={self.error_type}, delay={self.delay_seconds:.1f}s)"
        )


@dataclass
class RecoveryResult:
    """Pipeline kurtarma işlemi sonucu.

    Attributes:
        success: Kurtarma başarılı mı?
        attempts: Gerçekleştirilen kurtarma girişimleri.
        final_result: Başarılı kurtarma sonucunda dönen değer.
        error_category: Son hatanın kategorisi.
        sent_to_dlq: True ise hata DLQ'ya gönderildi.
        stage_name: Hangi pipeline aşaması kurtarıldı.
        total_time_seconds: Toplam kurtarma süresi.
    """

    success: bool
    attempts: list[RecoveryAttempt]
    final_result: Any
    error_category: ErrorCategory
    sent_to_dlq: bool
    stage_name: str
    total_time_seconds: float

    def __repr__(self) -> str:
        """RecoveryResult kısa temsili."""
        status = "RECOVERED" if self.success else "FAILED"
        return (
            f"RecoveryResult({status}, stage={self.stage_name!r}, "
            f"attempts={len(self.attempts)}, dlq={self.sent_to_dlq})"
        )


@dataclass
class DLQEntry:
    """Dead Letter Queue girişi.

    Attributes:
        stage_name: Başarısız pipeline aşaması.
        error_type: Hata tipi.
        error_message: Tam hata mesajı.
        context: İlgili bağlam verisi.
        timestamp: Giriş zamanı.
        retry_count: Toplam deneme sayısı.
    """

    stage_name: str
    error_type: str
    error_message: str
    context: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0

    def __repr__(self) -> str:
        """DLQEntry kısa temsili."""
        return (
            f"DLQEntry(stage={self.stage_name!r}, error={self.error_type}, "
            f"retries={self.retry_count})"
        )


class CircuitBreaker:
    """Devre kesici implementasyonu (thread-safe).

    Art arda başarısızlık sayısı eşiği aşıldığında devre açılır ve
    belirlenen süre boyunca yeni istekleri reddeder. Kurtarma için
    HALF_OPEN durumuna geçer ve belirli sayıda isteği dener.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = DEFAULT_CB_FAILURE_THRESHOLD,
        recovery_timeout: float = DEFAULT_CB_RECOVERY_TIMEOUT,
        half_open_attempts: int = DEFAULT_CB_HALF_OPEN_ATTEMPTS,
    ) -> None:
        """CircuitBreaker başlatıcı.

        Args:
            name: Devre kesici adı (hangi servis/aşama için).
            failure_threshold: Devre açılması için gereken art arda başarısızlık sayısı.
            recovery_timeout: Açık devre ile kurtarma denemesi arası bekleme süresi (saniye).
            half_open_attempts: Yarı-açık durumda izin verilen deneme sayısı.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold >= 1 olmalıdır: {failure_threshold}")
        if recovery_timeout <= 0:
            raise ValueError(f"recovery_timeout > 0 olmalıdır: {recovery_timeout}")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_count = 0
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """CircuitBreaker kısa temsili."""
        return (
            f"CircuitBreaker({self.name!r}, state={self._state.name}, "
            f"failures={self._failure_count})"
        )

    @property
    def state(self) -> CircuitBreakerState:
        """Mevcut devre kesici durumu.

        Returns:
            CircuitBreakerState enum değeri.
        """
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_count = 0
                    logger.info("Devre kesici yarı-açık duruma geçti.", name=self.name)
            return self._state

    def is_allowed(self) -> bool:
        """Mevcut durumda istek geçişine izin verilip verilmediğini kontrol eder.

        Returns:
            True ise istek geçebilir, False ise reddedilir.
        """
        with self._lock:
            s = self.state
            if s == CircuitBreakerState.CLOSED:
                return True
            if s == CircuitBreakerState.OPEN:
                return False
            # HALF_OPEN: sınırlı denemeye izin ver
            if self._half_open_count < self.half_open_attempts:
                self._half_open_count += 1
                return True
            return False

    def record_success(self) -> None:
        """Başarılı sonucu kaydeder ve gerekirse devreyi kapatır."""
        with self._lock:
            self._failure_count = 0
            self._success_count += 1
            if self._state != CircuitBreakerState.CLOSED:
                self._state = CircuitBreakerState.CLOSED
                logger.info("Devre kesici kapatıldı (kurtarıldı).", name=self.name)

    def record_failure(self) -> None:
        """Başarısız sonucu kaydeder ve gerekirse devreyi açar."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitBreakerState.OPEN:
                    self._state = CircuitBreakerState.OPEN
                    logger.warning(
                        "Devre kesici AÇILDI.",
                        name=self.name,
                        failures=self._failure_count,
                    )


class RecoveryEngine:
    """Pipeline hata kurtarma motoru (thread-safe).

    Exponential backoff, jitter, circuit breaker ve DLQ entegrasyonu ile
    pipeline aşamalarını otomatik olarak kurtarmaya çalışır.
    """

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        jitter: float = DEFAULT_JITTER,
    ) -> None:
        """RecoveryEngine başlatıcı.

        Args:
            max_retries: Maksimum yeniden deneme sayısı.
            base_delay: İlk bekleme süresi (saniye).
            max_delay: Maksimum bekleme süresi (saniye).
            backoff_factor: Üstel geri çekilme çarpanı.
            jitter: Thundering herd önleme için rastgele oran (0-1).

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if max_retries < 0:
            raise ValueError(f"max_retries >= 0 olmalıdır: {max_retries}")
        if base_delay <= 0:
            raise ValueError(f"base_delay > 0 olmalıdır: {base_delay}")
        if not (0.0 <= jitter <= 1.0):
            raise ValueError(f"jitter [0,1] aralığında olmalıdır: {jitter}")

        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter

        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._dlq: list[DLQEntry] = []
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """RecoveryEngine kısa temsili."""
        return (
            f"RecoveryEngine(max_retries={self.max_retries}, "
            f"base_delay={self.base_delay}s, dlq_size={len(self._dlq)})"
        )

    def _classify_error(self, exc: Exception) -> ErrorCategory:
        """Hata tipine göre kategori belirler.

        Args:
            exc: İncelenecek istisna.

        Returns:
            Hatanın ErrorCategory değeri.
        """
        exc_type = type(exc).__name__.lower()
        msg = str(exc).lower()

        transient_keywords = ["timeout", "connection", "network", "temporary", "retry"]
        rate_limit_keywords = ["rate limit", "too many", "429", "throttl"]
        permanent_keywords = ["permission", "auth", "forbidden", "not found", "404"]
        data_exc_types = ["value", "key", "type", "index", "attribute"]

        if any(k in msg for k in rate_limit_keywords):
            return ErrorCategory.RATE_LIMIT
        if any(k in msg for k in transient_keywords) or any(k in exc_type for k in ["timeout", "connection"]):
            return ErrorCategory.TRANSIENT
        if any(k in exc_type for k in data_exc_types):
            return ErrorCategory.DATA_ERROR
        if any(k in msg for k in permanent_keywords):
            return ErrorCategory.PERMANENT
        return ErrorCategory.UNKNOWN

    def _compute_delay(self, attempt: int, category: ErrorCategory) -> float:
        """Bekleme süresini hesaplar (exponential backoff + jitter).

        Args:
            attempt: Kaçıncı deneme (0'dan başlar).
            category: Hata kategorisi.

        Returns:
            Saniye cinsinden bekleme süresi.
        """
        base = self.base_delay * (self.backoff_factor**attempt)
        # Rate limit için daha uzun bekleme
        if category == ErrorCategory.RATE_LIMIT:
            base = min(base * 3.0, self.max_delay)
        base = min(base, self.max_delay)
        # Jitter ekle
        jitter_delta = base * self.jitter * (random.random() * 2 - 1)
        return max(0.1, base + jitter_delta)

    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """Belirtilen isim için devre kesiciyi döndürür (yoksa oluşturur).

        Args:
            name: Devre kesici adı.

        Returns:
            İlgili CircuitBreaker örneği.
        """
        with self._lock:
            if name not in self._circuit_breakers:
                self._circuit_breakers[name] = CircuitBreaker(name)
                logger.debug("Yeni devre kesici oluşturuldu.", name=name)
            return self._circuit_breakers[name]

    def _send_to_dlq(
        self,
        stage_name: str,
        exc: Exception,
        context: dict[str, Any],
        retry_count: int,
    ) -> None:
        """Kurtarılamayan hatayı DLQ'ya gönderir.

        Args:
            stage_name: Başarısız aşama adı.
            exc: İstisna nesnesi.
            context: İlgili bağlam verisi.
            retry_count: Toplam deneme sayısı.
        """
        entry = DLQEntry(
            stage_name=stage_name,
            error_type=type(exc).__name__,
            error_message=str(exc),
            context=context,
            retry_count=retry_count,
        )
        with self._lock:
            self._dlq.append(entry)
        logger.error(
            "Hata DLQ'ya gönderildi.",
            stage=stage_name,
            error=type(exc).__name__,
            retries=retry_count,
        )

    def execute_with_recovery(
        self,
        stage_name: str,
        fn: Callable[[], Any],
        context: dict[str, Any] | None = None,
        use_circuit_breaker: bool = True,
    ) -> RecoveryResult:
        """Pipeline aşamasını hata kurtarma ile çalıştırır.

        Args:
            stage_name: Aşama adı (loglama ve DLQ için).
            fn: Çalıştırılacak fonksiyon (parametre almaz, sonuç döner).
            context: Opsiyonel bağlam verisi (DLQ kaydı için).
            use_circuit_breaker: True ise devre kesici kullan.

        Returns:
            Kurtarma sonucu ve meta-verilerini içeren RecoveryResult.
        """
        ctx = context or {}
        cb = self.get_circuit_breaker(stage_name) if use_circuit_breaker else None
        attempts: list[RecoveryAttempt] = []
        start_time = time.time()
        last_exc: Exception = RuntimeError("Bilinmeyen hata")
        error_category = ErrorCategory.UNKNOWN

        for attempt_num in range(self.max_retries + 1):
            # Devre kesici kontrolü
            if cb is not None and not cb.is_allowed():
                logger.warning(
                    "Devre kesici açık — istek reddedildi.",
                    stage=stage_name,
                )
                break

            # Delay (ilk deneme için 0)
            delay = 0.0
            if attempt_num > 0:
                delay = self._compute_delay(attempt_num - 1, error_category)
                logger.info(
                    "Yeniden deneme bekleniyor.",
                    stage=stage_name,
                    attempt=attempt_num,
                    delay=round(delay, 2),
                )
                time.sleep(delay)

            try:
                result = fn()
                if cb is not None:
                    cb.record_success()

                attempts.append(RecoveryAttempt(
                    attempt_number=attempt_num + 1,
                    error_type="",
                    error_message="",
                    delay_seconds=delay,
                    success=True,
                ))

                logger.info(
                    "Pipeline aşaması başarıyla tamamlandı.",
                    stage=stage_name,
                    attempt=attempt_num + 1,
                )

                return RecoveryResult(
                    success=True,
                    attempts=attempts,
                    final_result=result,
                    error_category=error_category,
                    sent_to_dlq=False,
                    stage_name=stage_name,
                    total_time_seconds=time.time() - start_time,
                )

            except Exception as exc:
                last_exc = exc
                error_category = self._classify_error(exc)

                if cb is not None:
                    cb.record_failure()

                attempts.append(RecoveryAttempt(
                    attempt_number=attempt_num + 1,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    delay_seconds=delay,
                    success=False,
                ))

                logger.warning(
                    "Pipeline aşaması başarısız.",
                    stage=stage_name,
                    attempt=attempt_num + 1,
                    error=type(exc).__name__,
                    category=error_category.name,
                    hata=str(exc)[:200],
                )

                # Kalıcı hata ise hemen dur
                if error_category == ErrorCategory.PERMANENT:
                    logger.error(
                        "Kalıcı hata — yeniden deneme yapılmayacak.",
                        stage=stage_name,
                        hata=str(exc),
                    )
                    break

        # Tüm denemeler başarısız
        self._send_to_dlq(stage_name, last_exc, ctx, len(attempts))

        return RecoveryResult(
            success=False,
            attempts=attempts,
            final_result=None,
            error_category=error_category,
            sent_to_dlq=True,
            stage_name=stage_name,
            total_time_seconds=time.time() - start_time,
        )

    @property
    def dlq(self) -> list[DLQEntry]:
        """DLQ içeriğini döndürür (thread-safe kopyası).

        Returns:
            DLQ girişleri listesi.
        """
        with self._lock:
            return list(self._dlq)

    @property
    def dlq_size(self) -> int:
        """DLQ'daki giriş sayısı.

        Returns:
            Toplam DLQ giriş sayısı.
        """
        with self._lock:
            return len(self._dlq)

    def clear_dlq(self) -> int:
        """DLQ'yu temizler ve temizlenen giriş sayısını döndürür.

        Returns:
            Temizlenen giriş sayısı.
        """
        with self._lock:
            count = len(self._dlq)
            self._dlq.clear()
            logger.info("DLQ temizlendi.", cleared=count)
            return count

    def circuit_breaker_stats(self) -> dict[str, dict[str, Any]]:
        """Tüm devre kesicilerin durumunu döndürür.

        Returns:
            {name: {state, failures, ...}} sözlüğü.
        """
        with self._lock:
            return {
                name: {
                    "state": cb.state.name,
                    "failures": cb._failure_count,
                    "allowed": cb.is_allowed(),
                }
                for name, cb in self._circuit_breakers.items()
            }


__all__: list[str] = [
    "CircuitBreaker",
    "CircuitBreakerState",
    "DLQEntry",
    "ErrorCategory",
    "RecoveryAttempt",
    "RecoveryEngine",
    "RecoveryResult",
    "recovery_engine",
]

# Singleton
recovery_engine = RecoveryEngine()
