"""ALPHA BIST — Event Bus Enhancements v1.0

Event bus geliştirmeleri:
- Idempotency (tekrarlanan mesaj koruması)
- Retry policy (exponential backoff ve jitter)
- Correlation ID (dağıtık izlenebilirlik)
- Message ordering (sıralı işleme ve out-of-order tespiti)
- Timestamps ve metadata (mesaj zaman damgası)
- DuckDB kalıcı denetim defteri ve Polars analitik aktarımı

Kullanım:
    from services.core.event_enhancements import event_enhancements

    # Idempotency kontrolü
    is_dup = event_enhancements.is_duplicate(event_id)

    # Retry policy
    should_retry = event_enhancements.should_retry(event_id, attempt)

    # Correlation ID üret
    corr_id = event_enhancements.generate_correlation_id()
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import random
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final, TypeVar

import duckdb
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.event_enhancements")

T = TypeVar("T")

DEFAULT_IDEMPOTENCY_WINDOW_HOURS: float = 24.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BASE_DELAY: float = 1.0
DEFAULT_MAX_DELAY: float = 60.0
DEFAULT_EXPONENTIAL_BASE: float = 2.0
DEFAULT_MAX_IN_MEMORY_EVENTS: int = 100_000
DEFAULT_CLEANUP_INTERVAL_SECONDS: float = 60.0
DEFAULT_EVENT_ENHANCEMENT_DB_PATH: str = "data/event_enhancements.duckdb"


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Senkron ve asenkron (coroutine) metotları otomatik algılayarak span yaşam
    döngüsünü asenkron yürütme tamamlanana kadar açık tutar.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return await func(self, *args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return func(self, *args, **kwargs)

            return sync_wrapper

    return decorator


@dataclass(slots=True)
class EventMetadata:
    """Olay (Event) üstveri modeli.

    Attributes:
        event_id: Benzersiz olay kimliği.
        correlation_id: Dağıtık takip ve nedensellik korelasyon kimliği.
        timestamp: ISO-8601 zaman damgası.
        attempt: Mevcut yeniden deneme sayısı.
        max_retries: İzin verilen azami deneme adedi.
        retry_after: Bir sonraki deneme için bekleme zamanı (epoch timestamp).
    """

    event_id: str
    correlation_id: str
    timestamp: str
    attempt: int
    max_retries: int
    retry_after: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Üstveri alanlarını sözlük formatında döndürür."""
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "retry_after": self.retry_after,
        }

    def to_orjson_bytes(self) -> bytes:
        """Üstveriyi yüksek performanslı ikili orjson baytlarına dönüştürür."""
        import orjson

        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"EventMetadata(event_id='{self.event_id}', correlation_id='{self.correlation_id}', "
            f"attempt={self.attempt}/{self.max_retries}, timestamp='{self.timestamp}', retry_after={self.retry_after})"
        )


@dataclass(slots=True)
class RetryPolicy:
    """Yeniden deneme politikası ve geri çekilme (backoff) parametreleri.

    Attributes:
        max_retries: Azami yeniden deneme adedi (>= 0).
        base_delay: İlk yeniden deneme taban gecikmesi (saniye, >= 0).
        max_delay: İzin verilen tavan gecikme süresi (saniye, >= base_delay).
        exponential_base: Üstel büyüme katsayısı (>= 1.0).
        jitter: Rastlantısal gürültü / gecikme eklenip eklenmeyeceği.
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE
    jitter: bool = True

    def __post_init__(self) -> None:
        """Parametre sınırlarını doğrular ve geçersiz değerleri sınırlar."""
        if self.max_retries < 0:
            raise ValueError("max_retries negatif olamaz.")
        if self.base_delay < 0:
            raise ValueError("base_delay negatif olamaz.")
        if self.max_delay < self.base_delay:
            self.max_delay = self.base_delay
        if self.exponential_base < 1.0:
            self.exponential_base = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Politika alanlarını sözlük formatında döndürür."""
        return {
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
            "exponential_base": self.exponential_base,
            "jitter": self.jitter,
        }

    def to_orjson_bytes(self) -> bytes:
        """Politikayı ikili orjson baytlarına dönüştürür."""
        import orjson

        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"RetryPolicy(max_retries={self.max_retries}, base_delay={self.base_delay}s, "
            f"max_delay={self.max_delay}s, exp_base={self.exponential_base}, jitter={self.jitter})"
        )


# Geriye dönük uyumluluk takma adı
EventRetryPolicy: Final = RetryPolicy


class EventEnhancements:
    """Olay veri yolu (Event Bus) için güvenilirlik ve kurumsal orkestrasyon motoru.

    Bu sınıf aşağıdaki kurumsal nitelikleri eşzamanlı iş parçacığı güvenliğiyle (thread-safe) sağlar:
    - Idempotency (Tekrarlanan Mesaj Koruması): Aynı event_id tekrar geldiğinde mükerrer işlemeyi engeller.
    - Atomic Claim: Çoklu thread veya tüketici durumunda aynı olayın eşzamanlı çift çalıştırılmasını (TOCTOU race condition) önler.
    - Retry Policy: Üstel geri çekilme (exponential backoff) ve jitter ile dayanıklı yeniden deneme yönetimi.
    - Correlation ID: Dağıtık mikroservis ve işlem akışlarında olayları birbiriyle ilişkilendirir.
    - Message Ordering & Gap Detection: Anahtar (ticker, subject vb.) bazında kesin sıralı işleme ve sıra bozulması / paket kaybı tespiti.
    - DuckDB Audit & Polars: İşlenen olayların yerel gömülü DuckDB defterine kalıcı yazılması ve Polars DataFrame ile raporlanması.
    """

    def __init__(
        self,
        idempotency_window_hours: float = DEFAULT_IDEMPOTENCY_WINDOW_HOURS,
        retry_policy: RetryPolicy | None = None,
        db_path: str = DEFAULT_EVENT_ENHANCEMENT_DB_PATH,
        max_in_memory_events: int = DEFAULT_MAX_IN_MEMORY_EVENTS,
        cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS,
    ) -> None:
        """EventEnhancements motorunu başlatır ve bellek içi veri yapılarını hazırlar.

        Args:
            idempotency_window_hours: İşlenen olay kimliklerinin bellekte tutulacağı saat cinsinden süre.
            retry_policy: Özel yeniden deneme yapılandırması (None ise varsayılan politika uygulanır).
            db_path: Kalıcı olay denetim defteri için yerel DuckDB dosya yolu.
            max_in_memory_events: Bellekte tutulacak azami olay kimliği tavanı (bellek şişmesini önler).
            cleanup_interval_seconds: Otomatik bellek temizliği tetikleme periyodu (saniye).
        """
        self.idempotency_window_hours = float(idempotency_window_hours)
        self.retry_policy = retry_policy or RetryPolicy()
        self.db_path = str(db_path)
        self.max_in_memory_events = int(max_in_memory_events)
        self.cleanup_interval_seconds = float(cleanup_interval_seconds)

        self._lock = threading.RLock()
        self._processed_events: dict[str, float] = {}  # event_id → timestamp
        self._in_flight_events: set[str] = set()  # halihazırda yürütülen olaylar (race condition koruması)
        self._retry_counts: dict[str, int] = {}  # event_id → attempt count
        self._retry_after: dict[str, float] = {}  # event_id → next retry time
        self._correlation_map: dict[str, list[str]] = {}  # correlation_id → [event_ids]
        self._sequence_numbers: dict[str, int] = defaultdict(int)  # key → seq
        self._last_cleanup_ts: float = time.time()
        self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """Kalıcı olay ve mükerrerlik denetim defterini DuckDB üzerinde ilklendirir."""
        try:
            target = Path(self.db_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == 0:
                with contextlib.suppress(OSError):
                    target.unlink()
            with self._lock:
                with duckdb.connect(self.db_path) as conn:
                    from services.core.debounce import configure_duckdb_wal

                    configure_duckdb_wal(conn)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS event_enhancements_ledger (
                            event_id VARCHAR PRIMARY KEY,
                            correlation_id VARCHAR,
                            sequence_key VARCHAR,
                            sequence_num BIGINT,
                            attempt INT,
                            processed_at TIMESTAMP,
                            retry_after TIMESTAMP
                        )
                    """)
        except Exception as exc:
            logger.warning("event_enhancements_duckdb_init_hatasi", path=self.db_path, hata=str(exc))

    def record_to_ledger(
        self,
        event_id: str,
        correlation_id: str | None = None,
        sequence_key: str | None = None,
        sequence_num: int | None = None,
        attempt: int = 0,
        retry_after: float | None = None,
    ) -> None:
        """Olay üstverisini kalıcı DuckDB denetim defterine yazar.

        Args:
            event_id: Benzersiz olay kimliği.
            correlation_id: Korelasyon kimliği.
            sequence_key: Sıralama anahtarı.
            sequence_num: Sıra numarası.
            attempt: Deneme adedi.
            retry_after: Sonraki deneme epoch damgası.
        """
        try:
            target = Path(self.db_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with duckdb.connect(self.db_path) as conn:
                    from services.core.debounce import configure_duckdb_wal

                    configure_duckdb_wal(conn)
                    conn.execute(
                        """
                        INSERT INTO event_enhancements_ledger
                        (event_id, correlation_id, sequence_key, sequence_num, attempt, processed_at, retry_after)
                        VALUES (?, ?, ?, ?, ?, to_timestamp(?), CASE WHEN ? IS NOT NULL THEN to_timestamp(?) ELSE NULL END)
                        ON CONFLICT (event_id) DO UPDATE SET
                            correlation_id = EXCLUDED.correlation_id,
                            sequence_key = EXCLUDED.sequence_key,
                            sequence_num = EXCLUDED.sequence_num,
                            attempt = EXCLUDED.attempt,
                            processed_at = EXCLUDED.processed_at,
                            retry_after = EXCLUDED.retry_after
                        """,
                        [
                            event_id,
                            correlation_id or "",
                            sequence_key or "",
                            sequence_num or 0,
                            attempt,
                            time.time(),
                            retry_after,
                            retry_after,
                        ],
                    )
        except Exception as exc:
            logger.warning("event_enhancements_ledger_kayit_hatasi", event_id=event_id, hata=str(exc))

    # =====================================================
    # IDEMPOTENCY & CONCURRENCY
    # =====================================================

    @otel_trace("event_enhancements.is_duplicate")
    def is_duplicate(self, event_id: str) -> bool:
        """Belirtilen olay kimliğinin daha önce işlenip işlenmediğini veya şu an işleniyor olup olmadığını denetler.

        Args:
            event_id: Denetlenecek olay kimliği.

        Returns:
            True ise olay mükerrerdir (daha önce işlenmiş veya halihazırda işlemde), False ise yeni olaydır.
        """
        with self._lock:
            now = time.time()
            if (
                now - self._last_cleanup_ts >= self.cleanup_interval_seconds
                or len(self._processed_events) >= self.max_in_memory_events
            ):
                self._cleanup_old_events()

            if event_id in self._processed_events or event_id in self._in_flight_events:
                logger.debug("idempotency_duplicate_detected", event_id=event_id)
                return True
            return False

    def claim_event(self, event_id: str) -> bool:
        """Olayı işleme almak üzere atomik olarak rezerve eder.

        Çoklu iş parçacığı veya asenkron görevlerin aynı event_id ile eşzamanlı
        olarak çalışmasını (TOCTOU race condition) engeller.

        Args:
            event_id: Talep edilecek benzersiz olay kimliği.

        Returns:
            True ise olay başarıyla rezerve edilmiştir (çalıştırılabilir).
            False ise olay zaten işlenmiştir veya başka bir görev tarafından yürütülmektedir.
        """
        with self._lock:
            if event_id in self._processed_events or event_id in self._in_flight_events:
                return False
            self._in_flight_events.add(event_id)
            return True

    def release_in_flight(self, event_id: str) -> None:
        """İşlemi tamamlanan veya hata alan olayın rezervasyon kilidini serbest bırakır.

        Args:
            event_id: Serbest bırakılacak olay kimliği.
        """
        with self._lock:
            self._in_flight_events.discard(event_id)

    @otel_trace("event_enhancements.mark_processed")
    def mark_processed(
        self,
        event_id: str,
        correlation_id: str | None = None,
        sequence_key: str | None = None,
        sequence_num: int | None = None,
        persist: bool = True,
    ) -> None:
        """Olayı işlenmiş olarak kaydeder ve mükerrerlik havuzuna ekler.

        Args:
            event_id: Benzersiz olay kimliği.
            correlation_id: Opsiyonel korelasyon kimliği.
            sequence_key: Opsiyonel sıralama anahtarı.
            sequence_num: Opsiyonel sıra numarası.
            persist: DuckDB kalıcı defterine yazılıp yazılmayacağı.
        """
        with self._lock:
            self._processed_events[event_id] = time.time()
            self._in_flight_events.discard(event_id)
            att = self._retry_counts.pop(event_id, 0)
            ra = self._retry_after.pop(event_id, None)

        if persist:
            self.record_to_ledger(
                event_id=event_id,
                correlation_id=correlation_id,
                sequence_key=sequence_key,
                sequence_num=sequence_num,
                attempt=att,
                retry_after=ra,
            )

    @otel_trace("event_enhancements.process_with_idempotency")
    def process_with_idempotency(
        self,
        event_id: str,
        handler: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T | None:
        """Olayı idempotency ve atomik rezervasyon güvencesiyle işler.

        Olay mükerrer veya halihazırda başka bir thread tarafından yürütülüyorsa
        fonksiyon çalıştırılmadan None döner.

        Args:
            event_id: Benzersiz olay kimliği.
            handler: Yürütülecek işleyici fonksiyon veya callable nesne.
            *args: İşleyiciye iletilecek konumsal parametreler.
            **kwargs: İşleyiciye iletilecek anahtar parametreler.

        Returns:
            İşleyicinin ürettiği sonuç veya mükerrer olması durumunda None.

        Raises:
            Exception: İşleyici fonksiyon bir hata fırlatırsa hata yutulmaz, üst katmana aktarılır.
        """
        if not self.claim_event(event_id):
            logger.debug("idempotency_event_already_claimed_or_processed", event_id=event_id)
            return None

        try:
            result = handler(*args, **kwargs)
            self.mark_processed(event_id)
            return result
        finally:
            self.release_in_flight(event_id)

    @otel_trace("event_enhancements.process_with_idempotency_async")
    async def process_with_idempotency_async(
        self,
        event_id: str,
        handler: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any | None:
        """Asenkron olayları idempotency ve atomik rezervasyon güvencesiyle işler.

        Args:
            event_id: Benzersiz olay kimliği.
            handler: Yürütülecek asenkron veya senkron işleyici.
            *args: Konumsal parametreler.
            **kwargs: Anahtar parametreler.

        Returns:
            İşleyicinin ürettiği sonuç veya mükerrer ise None.

        Raises:
            Exception: İşleyici hata fırlatırsa fail-closed prensibiyle üst katmana aktarılır.
        """
        if not self.claim_event(event_id):
            logger.debug("idempotency_async_event_already_claimed_or_processed", event_id=event_id)
            return None

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(*args, **kwargs)
            else:
                result = handler(*args, **kwargs)
            self.mark_processed(event_id)
            return result
        finally:
            self.release_in_flight(event_id)

    # =====================================================
    # RETRY POLICY
    # =====================================================

    @otel_trace("event_enhancements.should_retry")
    def should_retry(self, event_id: str, attempt: int) -> bool:
        """Belirtilen olay ve deneme sayısı için yeniden deneme yapılıp yapılamayacağını doğrular.

        Args:
            event_id: Benzersiz olay kimliği.
            attempt: Mevcut deneme sayısı (0 tabanlı).

        Returns:
            True ise yeniden deneme yapılabilir, False ise deneme hakkı dolmuştur veya bekleme süresi geçmemiştir.
        """
        if attempt < 0:
            return False

        with self._lock:
            if attempt >= self.retry_policy.max_retries:
                logger.warning(
                    "retry_exhausted",
                    event_id=event_id,
                    attempt=attempt,
                    max_retries=self.retry_policy.max_retries,
                )
                return False

            retry_after = self._retry_after.get(event_id, 0.0)
            if time.time() < retry_after:
                return False

            return True

    @otel_trace("event_enhancements.get_retry_delay")
    def get_retry_delay(self, attempt: int) -> float:
        """Üstel geri çekilme (exponential backoff) ve opsiyonel rastlantısal gecikme (jitter) hesaplar.

        Args:
            attempt: Deneme sayısı.

        Returns:
            Saniye cinsinden bekleme gecikmesi.
        """
        clamped_attempt = max(0, min(attempt, 20))
        delay = min(
            self.retry_policy.base_delay * (self.retry_policy.exponential_base**clamped_attempt),
            self.retry_policy.max_delay,
        )

        if self.retry_policy.jitter:
            delay *= 0.5 + random.random()

        return float(delay)

    @otel_trace("event_enhancements.schedule_retry")
    def schedule_retry(self, event_id: str, attempt: int) -> float:
        """Olay için bir sonraki yeniden deneme zamanını planlar ve durumu kaydeder.

        Args:
            event_id: Benzersiz olay kimliği.
            attempt: Mevcut deneme sayısı.

        Returns:
            Yeniden denemenin yapılacağı epoch zaman damgası (saniye).
        """
        delay = self.get_retry_delay(attempt)
        retry_time = time.time() + delay

        with self._lock:
            self._retry_after[event_id] = retry_time
            self._retry_counts[event_id] = attempt + 1

        logger.debug(
            "retry_scheduled",
            event_id=event_id,
            attempt=attempt,
            delay=round(delay, 2),
            retry_at=round(retry_time, 2),
        )

        return retry_time

    @otel_trace("event_enhancements.reset_retry")
    def reset_retry(self, event_id: str) -> None:
        """Olayın yeniden deneme sayaçlarını ve zaman kısıtlamalarını sıfırlar.

        Args:
            event_id: Sıfırlanacak olay kimliği.
        """
        with self._lock:
            self._retry_counts.pop(event_id, None)
            self._retry_after.pop(event_id, None)

    # =====================================================
    # CORRELATION ID
    # =====================================================

    def generate_correlation_id(self) -> str:
        """Yeni bir evrensel benzersiz korelasyon kimliği (UUID4) üretir.

        Returns:
            UUID4 formatında metin.
        """
        return str(uuid.uuid4())

    def link_event(self, correlation_id: str, event_id: str) -> None:
        """Belirtilen olayı bir korelasyon kimliğine bağlayarak dağıtık izleme haritasına ekler.

        Args:
            correlation_id: Korelasyon kimliği.
            event_id: Bağlanacak olay kimliği.
        """
        with self._lock:
            if correlation_id not in self._correlation_map:
                if len(self._correlation_map) >= 20_000:
                    # En eski korelasyon kayıtlarını tahliye et (bellek koruması)
                    keys_to_remove = list(self._correlation_map.keys())[:5_000]
                    for k in keys_to_remove:
                        del self._correlation_map[k]
                self._correlation_map[correlation_id] = []
            self._correlation_map[correlation_id].append(event_id)

    def get_linked_events(self, correlation_id: str) -> list[str]:
        """Bir korelasyon kimliğine bağlı tüm olay kimliklerinin kopyasını döndürür.

        Args:
            correlation_id: Sorgulanacak korelasyon kimliği.

        Returns:
            İlişkili olay kimliklerini içeren liste.
        """
        with self._lock:
            return list(self._correlation_map.get(correlation_id, []))

    # =====================================================
    # MESSAGE ORDERING & GAP DETECTION (SELF-HEALING)
    # =====================================================

    def get_next_sequence(self, key: str) -> int:
        """Belirtilen anahtar için sıradaki artan sıra numarasını (sequence number) döndürür.

        Args:
            key: Sıralama anahtarı (örneğin ticker sembolü 'THYAO' veya kanal adı).

        Returns:
            Yeni sıra numarası (1 tabanlı).
        """
        with self._lock:
            self._sequence_numbers[key] += 1
            return self._sequence_numbers[key]

    def get_current_sequence(self, key: str) -> int:
        """Belirtilen anahtarın kaydedilmiş en son sıra numarasını döndürür.

        Args:
            key: Sıralama anahtarı.

        Returns:
            Mevcut en son sıra numarası (kayıt yoksa 0).
        """
        with self._lock:
            return self._sequence_numbers.get(key, 0)

    def is_out_of_order(self, key: str, seq: int) -> bool:
        """Gelen mesaj sıra numarasının güncel sıraya göre bozulmuş veya eski olup olmadığını denetler.

        Args:
            key: Sıralama anahtarı (örneğin 'THYAO.ticks').
            seq: Gelen mesajın sıra numarası.

        Returns:
            True ise mesaj sıra dışıdır (daha önce işlenmiş veya eski sıra), False ise geçerli sıradadır.
        """
        with self._lock:
            last_seq = self._sequence_numbers.get(key, 0)
            return seq <= last_seq if last_seq > 0 else False

    def has_sequence_gap(self, key: str, seq: int) -> bool:
        """Gelen mesaj sıra numarasının bir paket kaybı veya atlama (gap) oluşturup oluşturmadığını denetler.

        Tam otomatik algoritmik ticarette (zero-touch / self-healing) veri kaybı veya
        kaçan tick tespiti ve otomatik yeniden eşitleme (resync) için kullanılır.

        Args:
            key: Sıralama anahtarı.
            seq: Gelen mesajın sıra numarası.

        Returns:
            True ise arada eksik mesajlar vardır (seq > last_seq + 1), False ise sıralı akıştır.
        """
        with self._lock:
            last_seq = self._sequence_numbers.get(key, 0)
            if last_seq == 0:
                return False
            return seq > (last_seq + 1)

    def record_sequence(self, key: str, seq: int) -> None:
        """En son işlenen sıra numarasını günceller.

        Args:
            key: Sıralama anahtarı.
            seq: İşlenen sıra numarası.
        """
        with self._lock:
            if seq > self._sequence_numbers.get(key, 0):
                self._sequence_numbers[key] = seq

    def create_metadata(
        self,
        event_id: str,
        correlation_id: str | None = None,
    ) -> EventMetadata:
        """Yeni bir olay için kurumsal üstveri (metadata) nesnesi oluşturur.

        Args:
            event_id: Benzersiz olay kimliği.
            correlation_id: İsteğe bağlı korelasyon kimliği (belirtilmezse otomatik üretilir).

        Returns:
            Hazırlanan EventMetadata nesnesi.
        """
        with self._lock:
            attempt = self._retry_counts.get(event_id, 0)
            retry_after = self._retry_after.get(event_id)

        corr = correlation_id or self.generate_correlation_id()
        return EventMetadata(
            event_id=event_id,
            correlation_id=corr,
            timestamp=datetime.now(UTC).isoformat(),
            attempt=attempt,
            max_retries=self.retry_policy.max_retries,
            retry_after=retry_after,
        )

    # =====================================================
    # CLEANUP & AUDIT
    # =====================================================

    def _cleanup_old_events(self) -> None:
        """İdempotency zaman penceresini aşan eski olay kayıtlarını bellekten temizler."""
        now = time.time()
        cutoff = now - (self.idempotency_window_hours * 3600)
        with self._lock:
            self._last_cleanup_ts = now
            # 1. Süresi dolan olayları temizle
            old_events = [eid for eid, ts in self._processed_events.items() if ts < cutoff]
            for eid in old_events:
                self._processed_events.pop(eid, None)
                self._retry_counts.pop(eid, None)
                self._retry_after.pop(eid, None)

            # 2. Tavan kapasite aşılmışsa en eski kayıtları tahliye et (LRU/FIFO bellek koruması)
            if len(self._processed_events) > self.max_in_memory_events:
                excess = len(self._processed_events) - self.max_in_memory_events
                sorted_eids = sorted(self._processed_events.keys(), key=lambda k: self._processed_events[k])
                for eid in sorted_eids[:excess]:
                    self._processed_events.pop(eid, None)
                    self._retry_counts.pop(eid, None)
                    self._retry_after.pop(eid, None)

    def export_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """Kalıcı olay defterini sıfır kopyalı Arrow entegrasyonuyla Polars DataFrame'e aktarır.

        Args:
            limit: Sorgulanacak azami kayıt adedi.

        Returns:
            Olay defteri kayıtlarını içeren polars.DataFrame.
        """
        return export_enhancements_to_polars(db_path=self.db_path, limit=limit)

    def get_stats(self) -> dict[str, Any]:
        """Olay geliştirme motorunun anlık çalışma ve kuyruk istatistiklerini döndürür.

        Returns:
            İstatistik anahtarlarını ve sayısal değerlerini içeren sözlük.
        """
        with self._lock:
            return {
                "processed_events": len(self._processed_events),
                "in_flight_events": len(self._in_flight_events),
                "pending_retries": len(self._retry_after),
                "correlation_groups": len(self._correlation_map),
                "sequence_keys": len(self._sequence_numbers),
                "idempotency_window_hours": self.idempotency_window_hours,
                "db_path": self.db_path,
            }

    def __repr__(self) -> str:
        with self._lock:
            stats = self.get_stats()
        return (
            f"EventEnhancements(processed={stats['processed_events']}, in_flight={stats['in_flight_events']}, "
            f"retries={stats['pending_retries']}, groups={stats['correlation_groups']}, "
            f"seq_keys={stats['sequence_keys']}, window={self.idempotency_window_hours}h)"
        )


def export_enhancements_to_polars(
    db_path: str = DEFAULT_EVENT_ENHANCEMENT_DB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """Olay defteri kayıtlarını doğrudan yerel DuckDB dosyasından Polars DataFrame'e aktarır.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        limit: Çekilecek azami kayıt sayısı.

    Returns:
        Kayıtları içeren polars.DataFrame nesnesi.
    """
    empty_schema = {
        "event_id": pl.String,
        "correlation_id": pl.String,
        "sequence_key": pl.String,
        "sequence_num": pl.Int64,
        "attempt": pl.Int32,
        "processed_at": pl.Datetime("us"),
        "retry_after": pl.Datetime("us"),
    }
    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return pl.DataFrame(schema=empty_schema)
    try:
        with duckdb.connect(db_path, read_only=True) as conn:
            return conn.execute(
                """
                SELECT event_id, correlation_id, sequence_key, sequence_num, attempt, processed_at, retry_after
                FROM event_enhancements_ledger
                ORDER BY processed_at DESC
                LIMIT ?
                """,
                [max(1, int(limit))],
            ).pl()
    except Exception as exc:
        logger.error("export_enhancements_to_polars_hatasi", path=db_path, hata=str(exc))
        return pl.DataFrame(schema=empty_schema)


def query_enhancements_duckdb(
    query: str,
    params: list[Any] | None = None,
    db_path: str = DEFAULT_EVENT_ENHANCEMENT_DB_PATH,
) -> list[dict[str, Any]]:
    """Yerel DuckDB olay defteri üzerinde parametrik ve korumalı SQL sorgusu çalıştırır.

    Args:
        query: Çalıştırılacak SQL sorgusu.
        params: Sorguya bağlanacak parametreler listesi.
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        Sorgu sonuçlarını sözlükler listesi olarak döndürür.

    Raises:
        ValueError: Sorgu çoklu ifade (;) veya zararlı yorum blokları içeriyorsa.
    """
    clean_query = query.strip()
    # SQL Enjeksiyonu ve çoklu ifade (multi-statement) koruması
    if ";" in clean_query.rstrip(";"):
        raise ValueError("Çoklu SQL ifadeleri yasaktır.")
    if "--" in clean_query or "/*" in clean_query:
        raise ValueError("SQL yorum blokları yasaktır.")

    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return []
    try:
        with duckdb.connect(db_path, read_only=True) as conn:
            cursor = conn.execute(clean_query, params or [])
            if cursor.description is None:
                return []
            cols = [desc[0] for desc in cursor.description]
            return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("query_enhancements_duckdb_hatasi", query=query, hata=str(exc))
        return []


# Singleton
event_enhancements: Final[EventEnhancements] = EventEnhancements()

__all__: Final[list[str]] = [
    "DEFAULT_BASE_DELAY",
    "DEFAULT_CLEANUP_INTERVAL_SECONDS",
    "DEFAULT_EVENT_ENHANCEMENT_DB_PATH",
    "DEFAULT_EXPONENTIAL_BASE",
    "DEFAULT_IDEMPOTENCY_WINDOW_HOURS",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MAX_IN_MEMORY_EVENTS",
    "DEFAULT_MAX_RETRIES",
    "EventEnhancements",
    "EventMetadata",
    "EventRetryPolicy",
    "RetryPolicy",
    "event_enhancements",
    "export_enhancements_to_polars",
    "otel_trace",
    "query_enhancements_duckdb",
]

