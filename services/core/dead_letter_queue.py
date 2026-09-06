"""ALPHA BIST — Dead Letter Queue (DLQ) Kalıcı Olay ve Hata Yönetim Motoru.

Bu modül, mikroservisler, asenkron olay hatları (EventBus, NATS) ve arka plan
görevleri sırasında başarısız olan tüm olayların (events) güvenli şekilde muhafaza
edilmesini ve üstel geri çekilme (exponential backoff) ile yeniden işlenmesini sağlar:

1. Kalıcı Saklama (Persistence):
   - Birincil motor olarak `PersistentDeadLetterQueue` (DuckDB WAL destekli) kullanılır.
   - Sistem veya süreç yeniden başladığında (restart) başarısız olaylar asla kaybolmaz.
2. Esnek ve Kurumsal Geri Çekilme (Exponential Backoff):
   - Her başarısız denemede bekleme süresi katlanarak artar (`5 * 2^retry_count`),
     `DEFAULT_MAX_BACKOFF_SECONDS` (3600 sn) ile tavan sınırlandırılır.
3. Thread & Coroutine Eşzamanlılık Güvenliği:
   - Çoklu iş parçacığı ve asyncio ortamında reentrant kilit (`threading.RLock`) ile
     veri bütünlüğü ve Windows DuckDB dosya kilidi koruması sağlanır.
4. Sıfır Kopyalı Polars Analitiği:
   - Kuyruktaki olaylar analitik inceleme ve monitoring için doğrudan DuckDB `.pl()`
     aracılığıyla sıfır kopyalı Polars DataFrame olarak sunulur.
5. Fail-Closed ve Dayanıklılık Garantisi:
   - DuckDB veritabanına erişilemediği olağanüstü durumlarda, olay kaybını önlemek
     amacıyla tam fonksiyonel ve thread-safe `InMemoryDeadLetterQueue` devreye girer.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace
from services.core.persistent_dlq import (
    DLQEntry as PersistentDLQEntry,
)
from services.core.persistent_dlq import (
    DLQStatus as PersistentDLQStatus,
)
from services.core.persistent_dlq import (
    PersistentDeadLetterQueue,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# Modül Seviyesi Yapılandırma Sabitleri (GEMINI.md Kural 4)
DEFAULT_DLQ_DB_PATH: Final[str] = "data/dlq.db"
DEFAULT_MAX_ENTRIES: Final[int] = 50000
DEFAULT_MAX_IN_MEMORY_ENTRIES: Final[int] = 10000
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_DLQ_MAX_RETRIES: Final[int] = DEFAULT_MAX_RETRIES
DEFAULT_BASE_BACKOFF_SECONDS: Final[float] = 5.0
DEFAULT_MAX_BACKOFF_SECONDS: Final[float] = 3600.0  # Azami 1 saat backoff sınırı
DEFAULT_BATCH_SIZE: Final[int] = 100


class DLQStatus(StrEnum):
    """Dead Letter Queue kayıt durum kodları."""

    PENDING = "PENDING"  # Yeniden denenmeyi bekliyor
    RETRYING = "RETRYING"  # Şu anda işleniyor
    RESOLVED = "RESOLVED"  # Başarıyla tamamlandı/çözüldü
    EXHAUSTED = "EXHAUSTED"  # Maksimum deneme sayısına ulaştı ve tükendi


@dataclass(slots=True)
class DLQEntry:
    """Kalıcı DLQ olay kaydı veri modeli.

    Attributes:
        entry_id: Kuyruk kayıt kimliği (MD5 özeti).
        event_id: Orijinal olayın benzersiz kimliği.
        event_type: Olayın türü veya kanalı (örn. "ORDER_EXECUTION").
        payload: Olayın serileştirilmiş JSON içeriği.
        error: Oluşan hatanın açıklama veya izleme metni.
        retry_count: Şu ana kadar yapılan yeniden deneme sayısı.
        max_retries: İzin verilen azami yeniden deneme adedi.
        status: Kaydın güncel işlem durumu.
        created_at: Kuyruğa ilk eklenme UTC zaman damgası.
        last_retry_at: Son deneme UTC zaman damgası.
        next_retry_at: Bir sonraki planlanan deneme UTC zaman damgası.
        resolved_at: Çözülme/başarı UTC zaman damgası.
    """

    entry_id: str
    event_id: str
    event_type: str
    payload: str
    error: str
    retry_count: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    status: DLQStatus = DLQStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_retry_at: datetime | None = None
    next_retry_at: datetime | None = None
    resolved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Kayıt alanlarını JSON uyumlu sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: Tüm veri alanlarını eksiksiz içeren sözlük.
        """
        return {
            "entry_id": self.entry_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def to_orjson_bytes(self) -> bytes:
        """Kayıt alanlarını yüksek hızlı ikili orjson baytlarına dönüştürür (GEMINI.md Kural 5).

        Returns:
            bytes: UTF-8 serileştirilmiş orjson çıktısı.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @property
    def is_retryable(self) -> bool:
        """Kaydın tekrar denenmeye uygun olup olmadığını doğrular."""
        return self.status == DLQStatus.PENDING and self.retry_count < self.max_retries

    @property
    def is_ready_for_retry(self) -> bool:
        """Kaydın geri çekilme (backoff) süresinin dolup dolmadığını denetler."""
        if not self.is_retryable:
            return False
        if self.next_retry_at is None:
            return True
        return datetime.now(UTC) >= self.next_retry_at

    def __repr__(self) -> str:
        """Kayıt için açıklayıcı durum temsili."""
        return (
            f"DLQEntry(id={self.entry_id!r}, event_type={self.event_type!r}, "
            f"status={self.status.value}, retries={self.retry_count}/{self.max_retries})"
        )


class InMemoryDeadLetterQueue:
    """Yedek (Fallback) Bellek İçi Dead Letter Queue Motoru.

    DuckDB bağlantısının kurulamadığı olağanüstü durumlarda veri kaybını
    önlemek üzere devreye giren tam teşekküllü, thread-safe bellek kuyruğu.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_IN_MEMORY_ENTRIES) -> None:
        """InMemoryDeadLetterQueue örneğini başlatır.

        Args:
            max_entries: Saklanabilecek maksimum kayıt sayısı.
        """
        self._entries: dict[str, DLQEntry] = {}
        self._max_entries = max(10, max_entries)
        self._retry_handlers: dict[str, Callable[..., Any]] = {}
        self._lock = threading.RLock()
        self._total_pushed: int = 0
        self._total_retried: int = 0
        self._total_resolved: int = 0
        self._total_exhausted: int = 0

    def register_retry_handler(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Belirli bir olay tipi için yeniden deneme işleyicisi kaydeder.

        Args:
            event_type: Olay tipi (örn. "order_failed").
            handler: Çağrılacak eşzamanlı veya asenkron fonksiyon.
        """
        with self._lock:
            self._retry_handlers[event_type] = handler

    @otel_trace("dead_letter_queue.in_memory.push")
    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: Any,
        error: str,
        retry_count: int = 0,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        """Başarısız bir olayı asenkron olarak bellek içi kuyruğa ekler ve entry_id döner.

        Args:
            event_id: Orijinal olayın benzersiz kimliği.
            event_type: Olay türü.
            payload: Serileştirilmiş metin veya serileştirilebilir nesne.
            error: Oluşan hatanın açıklama metni.
            retry_count: Mevcut deneme sayısı.
            max_retries: Maksimum deneme adedi.

        Returns:
            str: Üretilen kayıt kimliği (entry_id).
        """
        return self.push_sync(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
        )

    def push_sync(
        self,
        event_id: str,
        event_type: str,
        payload: Any,
        error: str,
        retry_count: int = 0,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        """Başarısız bir olayı senkron olarak bellek içi kuyruğa ekler.

        Args:
            event_id: Orijinal olayın benzersiz kimliği.
            event_type: Olay türü.
            payload: Serileştirilmiş metin veya serileştirilebilir nesne.
            error: Oluşan hatanın açıklama metni.
            retry_count: Mevcut deneme sayısı.
            max_retries: Maksimum deneme adedi.

        Returns:
            str: Üretilen kayıt kimliği (entry_id).
        """
        # Payload güvenli serileştirme
        if not isinstance(payload, str):
            try:
                payload_str = orjson.dumps(payload, default=str).decode("utf-8")
            except Exception:
                payload_str = str(payload)
        else:
            payload_str = payload

        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest_id = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
                del self._entries[oldest_id]

            entry_id = hashlib.md5(f"dlq_{event_id}_{time.time()}".encode()).hexdigest()[:12]
            clamped_retries = min(20, max(0, retry_count))
            backoff_seconds = min(
                DEFAULT_MAX_BACKOFF_SECONDS,
                DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped_retries),
            )
            now = datetime.now(UTC)

            entry = DLQEntry(
                entry_id=entry_id,
                event_id=str(event_id),
                event_type=str(event_type),
                payload=payload_str,
                error=str(error),
                retry_count=max(0, retry_count),
                max_retries=max(1, max_retries),
                status=DLQStatus.PENDING,
                created_at=now,
                next_retry_at=now + timedelta(seconds=backoff_seconds),
            )
            self._entries[entry_id] = entry
            self._total_pushed += 1
            logger.info("dlq_in_memory_olay_eklendi", entry_id=entry_id, event_type=event_type)
            return entry_id

    @otel_trace("dead_letter_queue.in_memory.retry_failed")
    async def retry_failed(self, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
        """Zamanı gelen başarısız olayları kayıtlı işleyicilerle yeniden çalıştırır.

        Args:
            batch_size: Tek seferde işlenecek azami kayıt adedi.

        Returns:
            int: Başarıyla çözülen olay sayısı.
        """
        with self._lock:
            candidates = [
                entry
                for entry in self._entries.values()
                if entry.is_ready_for_retry
            ][:max(1, batch_size)]

        resolved_count = 0
        for entry in candidates:
            with self._lock:
                handler = self._retry_handlers.get(entry.event_type)
                entry.status = DLQStatus.RETRYING
                entry.last_retry_at = datetime.now(UTC)
                entry.retry_count += 1
                self._total_retried += 1

            if handler is None:
                with self._lock:
                    entry.status = DLQStatus.PENDING
                continue

            try:
                if asyncio.iscoroutinefunction(handler):
                    success = await handler(entry.payload)
                else:
                    success = handler(entry.payload)

                with self._lock:
                    if success:
                        entry.status = DLQStatus.RESOLVED
                        entry.resolved_at = datetime.now(UTC)
                        self._total_resolved += 1
                        resolved_count += 1
                    elif entry.retry_count >= entry.max_retries:
                        entry.status = DLQStatus.EXHAUSTED
                        self._total_exhausted += 1
                    else:
                        clamped = min(20, entry.retry_count)
                        backoff = min(DEFAULT_MAX_BACKOFF_SECONDS, DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped))
                        entry.status = DLQStatus.PENDING
                        entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)
            except Exception as exc:
                logger.error("dlq_retry_isleyici_hatasi", entry_id=entry.entry_id, error=str(exc))
                with self._lock:
                    if entry.retry_count >= entry.max_retries:
                        entry.status = DLQStatus.EXHAUSTED
                        self._total_exhausted += 1
                    else:
                        clamped = min(20, entry.retry_count)
                        backoff = min(DEFAULT_MAX_BACKOFF_SECONDS, DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped))
                        entry.status = DLQStatus.PENDING
                        entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)

        return resolved_count

    @otel_trace("dead_letter_queue.in_memory.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """Kuyruk durum istatistiklerini döndürür.

        Returns:
            dict[str, Any]: Detaylı durum ve yaşam döngüsü istatistikleri.
        """
        with self._lock:
            pending = sum(1 for e in self._entries.values() if e.status == DLQStatus.PENDING)
            resolved = sum(1 for e in self._entries.values() if e.status == DLQStatus.RESOLVED)
            exhausted = sum(1 for e in self._entries.values() if e.status == DLQStatus.EXHAUSTED)
            retrying = sum(1 for e in self._entries.values() if e.status == DLQStatus.RETRYING)
            return {
                "engine": "InMemory",
                "total_entries": len(self._entries),
                "by_status": {
                    "PENDING": pending,
                    "RETRYING": retrying,
                    "RESOLVED": resolved,
                    "EXHAUSTED": exhausted,
                },
                "pending": pending,
                "retrying": retrying,
                "resolved": resolved,
                "exhausted": exhausted,
                "lifetime": {
                    "total_pushed": self._total_pushed,
                    "total_retried": self._total_retried,
                    "total_resolved": self._total_resolved,
                    "total_exhausted": self._total_exhausted,
                },
                "persistent": False,
            }

    @otel_trace("dead_letter_queue.in_memory.get_entries")
    async def get_entries(
        self,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Kuyruktaki kayıtları filtreleyerek getirir.

        Args:
            status: İsteğe bağlı durum filtresi (örn. "PENDING").
            event_type: İsteğe bağlı olay türü filtresi.
            limit: Maksimum döndürülecek kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Filtrelenmiş kayıt sözlükleri.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            for entry in self._entries.values():
                if status and entry.status.value != status:
                    continue
                if event_type and entry.event_type != event_type:
                    continue
                results.append(entry.to_dict())
                if len(results) >= max(1, limit):
                    break
            return results

    @otel_trace("dead_letter_queue.in_memory.remove_entry")
    async def remove_entry(self, entry_id: str) -> bool:
        """Belirtilen kaydı bellekten kaldırır.

        Args:
            entry_id: Kaldırılacak kayıt kimliği.

        Returns:
            bool: Kayıt bulunup silindiyse True, aksi halde False.
        """
        with self._lock:
            return self._entries.pop(entry_id, None) is not None

    @otel_trace("dead_letter_queue.in_memory.clear")
    async def clear(self) -> int:
        """Tüm kayıtları siler.

        Returns:
            int: Silinen toplam kayıt adedi.
        """
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def export_to_polars(
        self,
        status: DLQStatus | str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """Bellek içi kayıtları katı şemalı Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

        Args:
            status: İsteğe bağlı durum filtresi.
            event_type: İsteğe bağlı olay tipi filtresi.
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Sıfır kopyalı analitik veri tablosu.
        """
        empty_schema = {
            "entry_id": pl.Utf8,
            "event_id": pl.Utf8,
            "event_type": pl.Utf8,
            "payload": pl.Utf8,
            "error": pl.Utf8,
            "retry_count": pl.Int64,
            "max_retries": pl.Int64,
            "status": pl.Utf8,
            "created_at": pl.Utf8,
            "last_retry_at": pl.Utf8,
            "next_retry_at": pl.Utf8,
            "resolved_at": pl.Utf8,
        }

        with self._lock:
            status_val = status.value if isinstance(status, DLQStatus) else (str(status) if status else None)
            matched: list[dict[str, Any]] = []
            for e in self._entries.values():
                if status_val and e.status.value != status_val:
                    continue
                if event_type and e.event_type != event_type:
                    continue
                matched.append(e.to_dict())
                if len(matched) >= max(1, limit):
                    break

            if not matched:
                return pl.DataFrame(schema=empty_schema)
            return pl.DataFrame(matched, schema=empty_schema)

    def __enter__(self) -> InMemoryDeadLetterQueue:
        """Context manager giriş protokolü."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkış protokolü."""
        return None

    def __repr__(self) -> str:
        """Nesne durum temsili."""
        with self._lock:
            return f"InMemoryDeadLetterQueue(entries={len(self._entries)}, max={self._max_entries})"


class DeadLetterQueue(PersistentDeadLetterQueue):
    """Kurumsal ve Kalıcı Dead Letter Queue Motoru.

    `PersistentDeadLetterQueue` sınıfını miras alarak DuckDB WAL garantisiyle
    tüm hata ve olay kuyruğu operasyonlarını yürütür; reentrant kilit (`RLock`) ile
    Windows DuckDB dosya paylaşım güvenliği sağlar ve çöküşlerde veri kaybını önler.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DLQ_DB_PATH,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        """DeadLetterQueue örneğini başlatır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            max_entries: Saklanabilecek maksimum kayıt sayısı.
        """
        # Sıfır baytlık bozuk dosya kontrolü (Windows dosya kilidi ve çökme koruması)
        db_file = Path(db_path)
        if db_file.exists() and db_file.stat().st_size == 0:
            with contextlib.suppress(OSError):
                db_file.unlink()

        super().__init__(db_path=db_path, max_entries=max_entries)
        self._lock = threading.RLock()

    @contextmanager
    def _connect(self) -> Any:
        """Güvenli DuckDB bağlantısı ve WAL yapılandırması sağlar."""
        conn = duckdb.connect(str(self.db_path))
        with contextlib.suppress(Exception):
            from services.core.duckdb_store import configure_duckdb_wal

            configure_duckdb_wal(conn)
        try:
            yield conn
        finally:
            conn.close()

    @otel_trace("dead_letter_queue.persistent.push")
    async def push(
        self,
        event_id: str,
        event_type: str,
        payload: Any,
        error: str,
        retry_count: int = 0,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        """Başarısız olan olayı kalıcı DuckDB DLQ deposuna thread-safe olarak yazar.

        Args:
            event_id: Orijinal olayın benzersiz kimliği.
            event_type: Olay türü.
            payload: Serileştirilmiş metin veya serileştirilebilir nesne.
            error: Oluşan hatanın açıklama metni.
            retry_count: Mevcut deneme sayısı.
            max_retries: Maksimum deneme adedi.

        Returns:
            str: Oluşturulan benzersiz kayıt kimliği.
        """
        return self.push_sync(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
        )

    def push_sync(
        self,
        event_id: str,
        event_type: str,
        payload: Any,
        error: str,
        retry_count: int = 0,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        """Başarısız olan olayı senkron olarak DuckDB deposuna kaydeder.

        Args:
            event_id: Orijinal olayın benzersiz kimliği.
            event_type: Olay türü.
            payload: Serileştirilmiş metin veya serileştirilebilir nesne.
            error: Oluşan hatanın açıklama metni.
            retry_count: Mevcut deneme sayısı.
            max_retries: Maksimum deneme adedi.

        Returns:
            str: Oluşturulan benzersiz kayıt kimliği.
        """
        # Payload güvenli serileştirme
        if not isinstance(payload, str):
            try:
                payload_str = orjson.dumps(payload, default=str).decode("utf-8")
            except Exception:
                payload_str = str(payload)
        else:
            payload_str = payload

        now_dt = datetime.now(UTC)
        entry_id = f"dlq_{event_id}_{int(now_dt.timestamp() * 1000)}"
        now_str = now_dt.isoformat()

        clamped_retries = min(20, max(0, retry_count))
        backoff_seconds = min(
            DEFAULT_MAX_BACKOFF_SECONDS,
            DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped_retries),
        )
        next_retry = (now_dt + timedelta(seconds=backoff_seconds)).isoformat()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO dlq_entries (
                        entry_id, event_id, event_type, payload, error,
                        retry_count, max_retries, status, created_at, next_retry_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                    """,
                    (
                        entry_id,
                        str(event_id),
                        str(event_type),
                        payload_str,
                        str(error),
                        max(0, retry_count),
                        max(1, max_retries),
                        now_str,
                        next_retry,
                    ),
                )

            self._total_pushed += 1
            self._evict_oldest()

        logger.warning(
            "Event kalıcı DLQ'ya kaydedildi",
            entry_id=entry_id,
            event_id=event_id,
            event_type=event_type,
            error=str(error)[:200],
        )
        return entry_id

    @otel_trace("dead_letter_queue.persistent.retry_failed")
    async def retry_failed(self, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
        """DLQ'daki yeniden denenebilir olayları geri çekilme sırasına göre işler.

        DuckDB bağlantısını uzun süre açık tutmadan satırları okur, işler ve sonuçları
        atomik olarak günceller (Windows file lock güvenliği).

        Args:
            batch_size: İşlenecek maksimum kayıt adedi.

        Returns:
            int: Başarıyla çözülen kayıt adedi.
        """
        now = datetime.now(UTC).isoformat()
        eff_batch = max(1, batch_size)

        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    SELECT * FROM dlq_entries
                    WHERE status = 'PENDING'
                    AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    AND retry_count < max_retries
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (now, eff_batch),
                )
                rows = self._cursor_to_dicts(cur)

                # Hemen durumları RETRYING yapıp bağlantıyı serbest bırak
                for entry in rows:
                    conn.execute(
                        "UPDATE dlq_entries SET status = 'RETRYING', last_retry_at = ? WHERE entry_id = ?",
                        (now, entry["entry_id"]),
                    )

        retried = 0
        for entry in rows:
            with self._lock:
                handler = self._retry_handlers.get(entry["event_type"])

            if not handler:
                with self._lock:
                    with self._connect() as conn:
                        conn.execute(
                            "UPDATE dlq_entries SET status = 'EXHAUSTED' WHERE entry_id = ?",
                            (entry["entry_id"],),
                        )
                        self._total_exhausted += 1
                continue

            try:
                if asyncio.iscoroutinefunction(handler):
                    success = await handler(entry["payload"])
                else:
                    success = handler(entry["payload"])

                now_ts = datetime.now(UTC).isoformat()
                with self._lock:
                    with self._connect() as conn:
                        if success:
                            conn.execute(
                                "UPDATE dlq_entries SET status = 'RESOLVED', resolved_at = ? WHERE entry_id = ?",
                                (now_ts, entry["entry_id"]),
                            )
                            self._total_resolved += 1
                            self._total_retried += 1
                            retried += 1
                        else:
                            new_count = entry["retry_count"] + 1
                            if new_count >= entry["max_retries"]:
                                conn.execute(
                                    """
                                    UPDATE dlq_entries SET status = 'EXHAUSTED',
                                    retry_count = ?, error = ?
                                    WHERE entry_id = ?
                                    """,
                                    (new_count, "Yeniden deneme başarısız oldu", entry["entry_id"]),
                                )
                                self._total_exhausted += 1
                            else:
                                clamped = min(20, new_count)
                                backoff = min(DEFAULT_MAX_BACKOFF_SECONDS, DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped))
                                next_retry = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()
                                conn.execute(
                                    """
                                    UPDATE dlq_entries SET status = 'PENDING',
                                    retry_count = ?, next_retry_at = ?
                                    WHERE entry_id = ?
                                    """,
                                    (new_count, next_retry, entry["entry_id"]),
                                )

            except Exception as exc:
                logger.error("dlq_retry_isleyici_hatasi", entry_id=entry["entry_id"], error=str(exc))
                new_count = entry["retry_count"] + 1
                with self._lock:
                    with self._connect() as conn:
                        if new_count >= entry["max_retries"]:
                            conn.execute(
                                """
                                UPDATE dlq_entries SET status = 'EXHAUSTED',
                                retry_count = ?, error = ?
                                WHERE entry_id = ?
                                """,
                                (new_count, str(exc), entry["entry_id"]),
                            )
                            self._total_exhausted += 1
                        else:
                            clamped = min(20, new_count)
                            backoff = min(DEFAULT_MAX_BACKOFF_SECONDS, DEFAULT_BASE_BACKOFF_SECONDS * (2**clamped))
                            next_retry = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()
                            conn.execute(
                                """
                                UPDATE dlq_entries SET status = 'PENDING',
                                retry_count = ?, error = ?, next_retry_at = ?
                                WHERE entry_id = ?
                                """,
                                (new_count, str(exc), next_retry, entry["entry_id"]),
                            )

        with self._lock:
            self._cleanup_resolved()
        return retried

    @otel_trace("dead_letter_queue.persistent.get_stats")
    async def get_stats(self) -> dict[str, Any]:
        """Kalıcı DLQ istatistiklerini döner; pending/resolved/exhausted alanları ile zenginleştirir.

        Returns:
            dict[str, Any]: Durum ve yaşam döngüsü istatistikleri sözlüğü.
        """
        with self._lock:
            stats = await super().get_stats()
            by_status = stats.get("by_status", {})
            stats["pending"] = by_status.get("PENDING", 0)
            stats["retrying"] = by_status.get("RETRYING", 0)
            stats["resolved"] = by_status.get("RESOLVED", 0)
            stats["exhausted"] = by_status.get("EXHAUSTED", 0)
            return stats

    @otel_trace("dead_letter_queue.persistent.get_entries")
    async def get_entries(
        self,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Kalıcı DLQ kayıtlarını thread-safe olarak filtreleyerek getirir.

        Args:
            status: Durum filtresi.
            event_type: Olay türü filtresi.
            limit: Maksimum satır limiti.

        Returns:
            list[dict[str, Any]]: Kayıt sözlükleri listesi.
        """
        with self._lock:
            return await super().get_entries(status=status, event_type=event_type, limit=max(1, limit))

    @otel_trace("dead_letter_queue.persistent.remove_entry")
    async def remove_entry(self, entry_id: str) -> bool:
        """Kalıcı DuckDB DLQ deposundan belirtilen kaydı siler.

        Args:
            entry_id: Silinecek kaydın benzersiz kimliği.

        Returns:
            bool: Kayıt bulunup silindiyse True, aksi halde False.
        """
        with self._lock:
            with self._connect() as conn:
                check = conn.execute(
                    "SELECT 1 FROM dlq_entries WHERE entry_id = ? LIMIT 1",
                    [entry_id],
                ).fetchone()
                if not check:
                    return False
                conn.execute("DELETE FROM dlq_entries WHERE entry_id = ?", [entry_id])
                return True

    @otel_trace("dead_letter_queue.persistent.clear")
    async def clear(self) -> int:
        """Tüm DLQ tablosunu temizler ve silinen kayıt sayısını döner.

        Returns:
            int: Silinen kayıt adedi.
        """
        with self._lock:
            return await super().clear()

    def export_to_polars(
        self,
        status: DLQStatus | str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """Kalıcı DuckDB DLQ kayıtlarını sıfır kopyalı Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

        DuckDB'nin yerel `.pl()` metodu kullanılarak sıfır satırda dahi şema garantisi sağlanır.

        Args:
            status: İsteğe bağlı durum filtresi.
            event_type: İsteğe bağlı olay türü filtresi.
            limit: Maksimum kayıt limiti.

        Returns:
            pl.DataFrame: Sıfır kopyalı analitik veri tablosu.
        """
        empty_schema = {
            "entry_id": pl.Utf8,
            "event_id": pl.Utf8,
            "event_type": pl.Utf8,
            "payload": pl.Utf8,
            "error": pl.Utf8,
            "retry_count": pl.Int64,
            "max_retries": pl.Int64,
            "status": pl.Utf8,
            "created_at": pl.Utf8,
            "last_retry_at": pl.Utf8,
            "next_retry_at": pl.Utf8,
            "resolved_at": pl.Utf8,
        }

        with self._lock:
            try:
                with self._connect() as conn:
                    query = """
                        SELECT entry_id, event_id, event_type, payload, error, retry_count,
                               max_retries, status, created_at, last_retry_at, next_retry_at, resolved_at
                        FROM dlq_entries
                    """
                    conditions: list[str] = []
                    params: list[Any] = []

                    if status is not None:
                        val = status.value if isinstance(status, DLQStatus) else str(status)
                        conditions.append("status = ?")
                        params.append(val)
                    if event_type:
                        conditions.append("event_type = ?")
                        params.append(str(event_type))

                    if conditions:
                        query += " WHERE " + " AND ".join(conditions)

                    query += " ORDER BY created_at DESC LIMIT ?"
                    params.append(max(1, limit))

                    return conn.execute(query, params).pl()
            except Exception as exc:
                logger.error("dlq_polars_aktarim_hatasi", error=str(exc))
                return pl.DataFrame(schema=empty_schema)

    def __enter__(self) -> DeadLetterQueue:
        """Context manager giriş protokolü."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkış protokolü."""
        return None

    def __repr__(self) -> str:
        """Kalıcı kuyruk durum temsili."""
        return f"DeadLetterQueue(db_path={self.db_path!r}, max_entries={self._max_entries})"


# Singleton Kuyruk Nesnesini Hazırla
def _create_dlq_instance() -> PersistentDeadLetterQueue | InMemoryDeadLetterQueue:
    """Kalıcı DuckDB motorunu başlatır; disk arızası halinde güvenli InMemory fallback'e geçer.

    Returns:
        PersistentDeadLetterQueue | InMemoryDeadLetterQueue: Aktif kuyruk motoru.
    """
    try:
        instance = DeadLetterQueue()
        logger.info("dead_letter_queue_persistent_aktif", db_path=instance.db_path)
        return instance
    except Exception as exc:
        logger.warning(
            "dead_letter_queue_persistent_baslatilamadi_in_memory_devrede",
            error=str(exc),
        )
        return InMemoryDeadLetterQueue()


# Global Singleton
dead_letter_queue: Final[PersistentDeadLetterQueue | InMemoryDeadLetterQueue] = _create_dlq_instance()


# ---------------------------------------------------------------------------
# Modül Seviyesi Kolaylık Fonksiyonları (GEMINI.md Kural 6)
# ---------------------------------------------------------------------------


async def push_to_dlq(
    event_id: str,
    event_type: str,
    payload: Any,
    error: str,
    retry_count: int = 0,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """Başarısız bir olayı aktif singleton DLQ motoruna asenkron olarak ekler.

    Args:
        event_id: Orijinal olayın benzersiz kimliği.
        event_type: Olay türü.
        payload: Veri yükü (metin veya nesne).
        error: Hata mesajı.
        retry_count: Deneme sayısı.
        max_retries: İzin verilen maksimum deneme adedi.

    Returns:
        str: Oluşturulan DLQ kayıt kimliği.
    """
    return await dead_letter_queue.push(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        error=error,
        retry_count=retry_count,
        max_retries=max_retries,
    )


def push_to_dlq_sync(
    event_id: str,
    event_type: str,
    payload: Any,
    error: str,
    retry_count: int = 0,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """Başarısız bir olayı aktif singleton DLQ motoruna senkron olarak ekler.

    Args:
        event_id: Orijinal olayın benzersiz kimliği.
        event_type: Olay türü.
        payload: Veri yükü (metin veya nesne).
        error: Hata mesajı.
        retry_count: Deneme sayısı.
        max_retries: İzin verilen maksimum deneme adedi.

    Returns:
        str: Oluşturulan DLQ kayıt kimliği.
    """
    if hasattr(dead_letter_queue, "push_sync"):
        return dead_letter_queue.push_sync(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
        )
    return asyncio.run(
        dead_letter_queue.push(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
        )
    )


async def retry_dlq_failed(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Zamanı gelen başarısız olayları yeniden dener.

    Args:
        batch_size: Maksimum işlenecek kayıt adedi.

    Returns:
        int: Başarıyla çözülen olay sayısı.
    """
    return await dead_letter_queue.retry_failed(batch_size=batch_size)


async def get_dlq_stats() -> dict[str, Any]:
    """Aktif DLQ kuyruğunun anlık istatistiklerini döner.

    Returns:
        dict[str, Any]: Kuyruk istatistikleri sözlüğü.
    """
    return await dead_letter_queue.get_stats()


async def get_dlq_entries(
    status: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Kuyruktaki olay kayıtlarını filtreleyerek getirir.

    Args:
        status: Durum filtresi.
        event_type: Olay tipi filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        list[dict[str, Any]]: Kayıt sözlükleri.
    """
    return await dead_letter_queue.get_entries(status=status, event_type=event_type, limit=limit)


def export_dlq_to_polars(
    status: DLQStatus | str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DLQ kayıtlarını sıfır kopyalı Polars DataFrame olarak döner.

    Args:
        status: Durum filtresi.
        event_type: Olay tipi filtresi.
        limit: Maksimum satır limiti.

    Returns:
        pl.DataFrame: Polars tablosu.
    """
    if hasattr(dead_letter_queue, "export_to_polars"):
        return dead_letter_queue.export_to_polars(status=status, event_type=event_type, limit=limit)
    return pl.DataFrame()


async def remove_dlq_entry(entry_id: str) -> bool:
    """Belirtilen kaydı DLQ'dan siler.

    Args:
        entry_id: Silinecek kayıt kimliği.

    Returns:
        bool: Başarıyla silindiyse True, aksi halde False.
    """
    if hasattr(dead_letter_queue, "remove_entry"):
        return await dead_letter_queue.remove_entry(entry_id)
    return False


async def clear_dlq() -> int:
    """Tüm DLQ tablosunu temizler.

    Returns:
        int: Silinen kayıt adedi.
    """
    return await dead_letter_queue.clear()


def register_dlq_retry_handler(event_type: str, handler: Callable[..., Any]) -> None:
    """Belirli bir olay türü için yeniden işleme işleyicisi kaydeder.

    Args:
        event_type: Olay türü.
        handler: İşleyici fonksiyon.
    """
    dead_letter_queue.register_retry_handler(event_type, handler)


# Geriye dönük uyumluluk takma adı
persistent_dlq: Final[PersistentDeadLetterQueue | InMemoryDeadLetterQueue] = dead_letter_queue


__all__: Final[list[str]] = [
    # Yapılandırma Sabitleri
    "DEFAULT_BASE_BACKOFF_SECONDS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DLQ_DB_PATH",
    "DEFAULT_MAX_BACKOFF_SECONDS",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_IN_MEMORY_ENTRIES",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_DLQ_MAX_RETRIES",
    # Modeller ve Enumlar
    "DLQEntry",
    "DLQStatus",
    "DeadLetterQueue",
    "InMemoryDeadLetterQueue",
    "PersistentDeadLetterQueue",
    "PersistentDLQEntry",
    "PersistentDLQStatus",
    # Singleton Nesne
    "dead_letter_queue",
    "persistent_dlq",
    # Kolaylık Fonksiyonları
    "clear_dlq",
    "export_dlq_to_polars",
    "get_dlq_entries",
    "get_dlq_stats",
    "push_to_dlq",
    "push_to_dlq_sync",
    "register_dlq_retry_handler",
    "remove_dlq_entry",
    "retry_dlq_failed",
]

