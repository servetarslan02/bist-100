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
from typing import Any, Callable, TypeVar

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
DEFAULT_EVENT_ENHANCEMENT_DB_PATH: str = "data/event_enhancements.duckdb"


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
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

    def __repr__(self) -> str:
        return (
            f"EventMetadata(event_id='{self.event_id}', correlation_id='{self.correlation_id}', "
            f"attempt={self.attempt}/{self.max_retries}, timestamp='{self.timestamp}', retry_after={self.retry_after})"
        )


@dataclass
class RetryPolicy:
    """Yeniden deneme politikası ve geri çekilme (backoff) parametreleri.

    Attributes:
        max_retries: Azami yeniden deneme adedi.
        base_delay: İlk yeniden deneme taban gecikmesi (saniye).
        max_delay: İzin verilen tavan gecikme süresi (saniye).
        exponential_base: Üstel büyüme katsayısı.
        jitter: Rastlantısal gürültü / gecikme eklenip eklenmeyeceği.
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE
    jitter: bool = True

    def __repr__(self) -> str:
        return (
            f"RetryPolicy(max_retries={self.max_retries}, base_delay={self.base_delay}s, "
            f"max_delay={self.max_delay}s, exp_base={self.exponential_base}, jitter={self.jitter})"
        )


class EventEnhancements:
    """Olay veri yolu (Event Bus) için güvenilirlik ve kurumsal orkestrasyon motoru.

    Bu sınıf aşağıdaki kurumsal nitelikleri eşzamanlı iş parçacığı güvenliğiyle (thread-safe) sağlar:
    - Idempotency (Tekrarlanan Mesaj Koruması): Aynı event_id tekrar geldiğinde mükerrer işlemeyi engeller.
    - Retry Policy: Üstel geri çekilme (exponential backoff) ve jitter ile dayanıklı yeniden deneme yönetimi.
    - Correlation ID: Dağıtık mikroservis ve işlem akışlarında olayları birbiriyle ilişkilendirir.
    - Message Ordering: Anahtar (ticker, subject vb.) bazında kesin sıralı işleme ve sıra bozulması tespiti.
    - DuckDB Audit & Polars: İşlenen olayların yerel gömülü DuckDB defterine kalıcı yazılması ve Polars DataFrame ile raporlanması.
    """

    def __init__(
        self,
        idempotency_window_hours: float = DEFAULT_IDEMPOTENCY_WINDOW_HOURS,
        retry_policy: RetryPolicy | None = None,
        db_path: str = DEFAULT_EVENT_ENHANCEMENT_DB_PATH,
    ) -> None:
        """EventEnhancements motorunu başlatır ve bellek içi veri yapılarını hazırlar.

        Args:
            idempotency_window_hours: İşlenen olay kimliklerinin bellekte tutulacağı saat cinsinden süre.
            retry_policy: Özel yeniden deneme yapılandırması (None ise varsayılan politika uygulanır).
            db_path: Kalıcı olay denetim defteri için yerel DuckDB dosya yolu.
        """
        self.idempotency_window_hours = float(idempotency_window_hours)
        self.retry_policy = retry_policy or RetryPolicy()
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._processed_events: dict[str, float] = {}  # event_id → timestamp
        self._retry_counts: dict[str, int] = {}  # event_id → attempt count
        self._retry_after: dict[str, float] = {}  # event_id → next retry time
        self._correlation_map: dict[str, list[str]] = {}  # correlation_id → [event_ids]
        self._sequence_numbers: dict[str, int] = defaultdict(int)  # key → seq
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
                        INSERT OR REPLACE INTO event_enhancements_ledger
                        (event_id, correlation_id, sequence_key, sequence_num, attempt, processed_at, retry_after)
                        VALUES (?, ?, ?, ?, ?, to_timestamp(?), CASE WHEN ? IS NOT NULL THEN to_timestamp(?) ELSE NULL END)
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
    # IDEMPOTENCY
    # =====================================================

    @otel_trace("event_enhancements.is_duplicate")
    def is_duplicate(self, event_id: str) -> bool:
        """Belirtilen olay kimliğinin daha önce işlenip işlenmediğini (mükerrerlik) denetler.

        Args:
            event_id: Denetlenecek olay kimliği.

        Returns:
            True ise olay mükerrerdir (daha önce işlenmiştir), False ise yeni olaydır.
        """
        with self._lock:
            self._cleanup_old_events()
            if event_id in self._processed_events:
                logger.debug("idempotency_duplicate_detected", event_id=event_id)
                return True
            return False

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

        if persist:
            with self._lock:
                att = self._retry_counts.get(event_id, 0)
                ra = self._retry_after.get(event_id)
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
        """Olayı idempotency güvencesiyle işler; olay mükerrer ise fonksiyonu çalıştırmadan None döner.

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
        if self.is_duplicate(event_id):
            return None

        result = handler(*args, **kwargs)
        self.mark_processed(event_id)
        return result

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
        delay = min(
            self.retry_policy.base_delay * (self.retry_policy.exponential_base**attempt),
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
    # MESSAGE ORDERING
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
        cutoff = time.time() - (self.idempotency_window_hours * 3600)
        with self._lock:
            old_events = [eid for eid, ts in self._processed_events.items() if ts < cutoff]
            for eid in old_events:
                del self._processed_events[eid]

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
            f"EventEnhancements(processed={stats['processed_events']}, "
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
        "event_id": pl.Utf8,
        "correlation_id": pl.Utf8,
        "sequence_key": pl.Utf8,
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
                [limit],
            ).pl()
    except Exception as exc:
        logger.error("export_enhancements_to_polars_hatasi", path=db_path, hata=str(exc))
        return pl.DataFrame(schema=empty_schema)


def query_enhancements_duckdb(
    query: str,
    params: list[Any] | None = None,
    db_path: str = DEFAULT_EVENT_ENHANCEMENT_DB_PATH,
) -> list[dict[str, Any]]:
    """Yerel DuckDB olay defteri üzerinde parametrik SQL sorgusu çalıştırır.

    Args:
        query: Çalıştırılacak SQL sorgusu.
        params: Sorguya bağlanacak parametreler listesi.
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        Sorgu sonuçlarını sözlükler listesi olarak döndürür.
    """
    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return []
    try:
        with duckdb.connect(db_path, read_only=True) as conn:
            cursor = conn.execute(query, params or [])
            cols = [desc[0] for desc in cursor.description]
            return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("query_enhancements_duckdb_hatasi", query=query, hata=str(exc))
        return []


# Singleton
event_enhancements = EventEnhancements()

__all__ = [
    "DEFAULT_BASE_DELAY",
    "DEFAULT_EVENT_ENHANCEMENT_DB_PATH",
    "DEFAULT_EXPONENTIAL_BASE",
    "DEFAULT_IDEMPOTENCY_WINDOW_HOURS",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MAX_RETRIES",
    "EventEnhancements",
    "EventMetadata",
    "RetryPolicy",
    "event_enhancements",
    "export_enhancements_to_polars",
    "otel_trace",
    "query_enhancements_duckdb",
]
