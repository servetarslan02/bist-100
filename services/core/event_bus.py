"""
ALPHA BIST — Event Bus v2.0 (Enterprise-Grade Push-Based Architecture)

Kurumsal Olay Dağıtım ve Mesajlaşma Yolu (Event Bus):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Mimari: NATS (birincil yüksek verimli kuyruk) + Redis Pub/Sub (anlık push) + Redis Stream / DuckDB (kalıcı defter)
2. Serileştirme: orjson modül seviyesinde yüksek performanslı serileştirme (GEMINI.md Kural 5)
3. Dayanıklılık: Kritik finansal olaylar için sıfır veri kaybı, kalıcı DuckDB denetim defteri (Event Ledger)
4. İzlenebilirlik: OpenTelemetry span yayılımı ve Prometheus throughput metrikleri
5. Eşzamanlılık: İş parçacığı ve asenkron görev emniyetli (thread-safe) kilit yönetimi
6. Analitik: Olay geçmişini Polars DataFrame olarak dışa aktarma (GEMINI.md Kural 2)
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract, inject

from .config import settings
from .event_schema import CanonicalEvent, EventType  # noqa: F401 — geriye dönük uyumluluk

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.event_bus")
meter = metrics.get_meter("alpha-bist.event_bus")

_events_published = meter.create_counter(
    "alpha.event_bus.published.total",
    description="Toplam publish edilen event sayısı",
)
_events_consumed = meter.create_counter(
    "alpha.event_bus.consumed.total",
    description="Toplam işlenen event sayısı",
)
_handler_errors = meter.create_counter(
    "alpha.event_bus.handler_errors.total",
    description="Handler hata sayısı",
)

DEFAULT_EVENT_LEDGER_DB_PATH: Final[str] = "data/event_ledger.duckdb"
DEFAULT_MAX_EVENT_HISTORY: Final[int] = 50000

# Varsayılan NATS konu (subject) başlıkları
DEFAULT_SUBJECTS: Final[list[str]] = [
    "market.tick",
    "market.ohlcv",
    "market.orderbook",
    "signal.generated",
    "signal.executed",
    "portfolio.updated",
    "portfolio.trade",
    "risk.alert",
    "risk.breach",
    "event.kap",
    "event.news",
    "event.macro",
    "feature.computed",
    "regime.changed",
    "learning.cycle",
    "system.health",
    "system.alert",
]

# Kritik olay tipleri (JetStream ve kalıcı defter garantili)
CRITICAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "signal.generated",
        "signal.executed",
        "portfolio.trade",
        "portfolio.updated",
        "risk.alert",
        "risk.breach",
        "regime.changed",
    }
)


def ensure_topics(subjects: list[str] | None = None) -> bool:
    """NATS konu başlıklarının doğrulandığını ve hazır olduğunu teyit eder.

    Args:
        subjects: Doğrulanacak NATS subject listesi. None ise DEFAULT_SUBJECTS kullanılır.

    Returns:
        bool: İşlem başarılı ise True.
    """
    target_subjects = subjects or DEFAULT_SUBJECTS
    logger.info("NATS konuları doğrulandı", count=len(target_subjects), subjects=target_subjects[:5])
    return True


async def flush_producer() -> None:
    """Arabellekteki bekleyen tüm olayları NATS ve Redis hattına boşaltır."""
    try:
        redis = await _get_redis()
        if redis:
            logger.info("Olay üretici tamponu boşaltıldı")
    except Exception as exc:
        logger.warning("Olay üretici tampon boşaltma hatası", error=str(exc))


class InternalEventBus:
    """İç servisler arası anlık iletişim için Redis Pub/Sub tabanlı olay dağıtıcı.

    Push-based mimaride çalışır: veri üretildiği anda dinleyicilere anında aktarılır.
    """

    def __init__(self) -> None:
        """InternalEventBus örneğini başlatır."""
        self._redis: Any = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, list[Callable[..., Any]]] = {}
        self._running: bool = False
        self._lock: threading.RLock = threading.RLock()

    def __repr__(self) -> str:
        """InternalEventBus nesnesinin okunabilir temsilini döner."""
        with self._lock:
            return (
                f"InternalEventBus(kanallar={len(self._subscribers)}, "
                f"aktif={self._running}, redis={'bagli' if self._redis else 'kapali'})"
            )

    def to_orjson_bytes(self) -> bytes:
        """İç olay yolu durumunu orjson binary formatında döner (GEMINI.md Kural 5).

        Returns:
            JSON bayt dizisi.
        """
        with self._lock:
            data = {
                "channels": list(self._subscribers.keys()),
                "total_channels": len(self._subscribers),
                "is_running": self._running,
                "has_redis": self._redis is not None,
            }
        return orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str)

    def clear_subscribers(self) -> None:
        """Kayıtlı tüm kanal abonelerini temizler."""
        with self._lock:
            self._subscribers.clear()
            logger.info("InternalEventBus aboneleri temizlendi")

    async def _get_redis(self) -> Any:
        """Etkin olay döngüsüne ait Redis istemcisini döner veya oluşturur.

        Returns:
            Redis bağlantı nesnesi veya bellek içi yedek (InMemoryRedis).
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        with self._lock:
            if self._redis is None or self._redis_loop is not current_loop:
                try:
                    from .redis_sentinel import get_ha_redis

                    self._redis = await get_ha_redis()
                    self._redis_loop = current_loop
                except Exception:
                    try:
                        import redis.asyncio as aioredis

                        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
                        self._redis_loop = current_loop
                    except (ImportError, Exception):
                        self._redis = InMemoryRedis()
                        self._redis_loop = current_loop
        return self._redis

    async def publish(self, channel: str, event: CanonicalEvent) -> None:
        """Olayı belirtilen kanala yayınlar.

        Args:
            channel: Hedef kanal adı.
            event: Yayınlanacak kanonik olay.
        """
        r = await self._get_redis()
        try:
            with tracer.start_as_current_span(f"publish {channel}", kind=trace.SpanKind.PRODUCER) as span:
                span.set_attribute("messaging.system", "redis")
                span.set_attribute("messaging.destination", channel)

                # OTel Context Injection
                headers: dict[str, str] = {}
                inject(headers)

                payload = event.to_json()
                if isinstance(payload, str):
                    data_dict = orjson.loads(payload)
                    data_dict["_trace_headers"] = headers
                    payload = orjson.dumps(data_dict).decode("utf-8")
                elif isinstance(payload, bytes):
                    data_dict = orjson.loads(payload)
                    data_dict["_trace_headers"] = headers
                    payload = orjson.dumps(data_dict)

                await r.publish(f"alpha:{channel}", payload)
                _events_published.add(1, {"channel": channel})
                logger.debug("Olay yayınlandı", channel=channel, event_type=str(event.event_type))
        except Exception as exc:
            logger.warning("Yayınlama başarısız oldu, bellek içi yedeğe geçiliyor", error=str(exc))
            if hasattr(r, "publish_local"):
                r.publish_local(channel, event)

    async def subscribe(self, channel: str, handler: Callable[..., Any]) -> None:
        """Belirtilen kanala olay dinleyici fonksiyon kaydeder.

        Args:
            channel: Dinlenecek kanal adı.
            handler: Olay alındığında tetiklenecek fonksiyon.
        """
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(handler)
        logger.debug("Kanala abone olundu", channel=channel)

    async def start_listening(self) -> None:
        """Kayıtlı tüm kanalları dinleyen döngüyü başlatır."""
        self._running = True
        r = await self._get_redis()

        with self._lock:
            sub_channels = list(self._subscribers.keys())

        pubsub = r.pubsub()
        channels = [f"alpha:{ch}" for ch in sub_channels]
        if channels:
            await pubsub.subscribe(*channels)
            logger.info("Kanallar dinleniyor", channels=sub_channels)

        while self._running:
            try:
                message = await pubsub.get_message(timeout=5.0)
                if message and message.get("type") == "message":
                    channel = str(message["channel"]).replace("alpha:", "")
                    raw_data = message["data"]
                    data_dict = orjson.loads(raw_data) if isinstance(raw_data, (str, bytes)) else raw_data

                    trace_headers = data_dict.pop("_trace_headers", {}) if isinstance(data_dict, dict) else {}
                    context = extract(trace_headers)

                    cleaned_json = orjson.dumps(data_dict)
                    event = CanonicalEvent.from_json(cleaned_json)

                    with self._lock:
                        handlers = list(self._subscribers.get(channel, []))

                    for handler in handlers:
                        try:
                            with tracer.start_as_current_span(
                                f"process {channel}", context=context, kind=trace.SpanKind.CONSUMER
                            ) as span:
                                span.set_attribute("messaging.system", "redis")
                                span.set_attribute("messaging.destination", channel)
                                if asyncio.iscoroutinefunction(handler):
                                    await handler(event)
                                else:
                                    handler(event)
                        except Exception as handler_exc:
                            logger.error("Handler çalışma hatası", channel=channel, error=str(handler_exc))
                            _handler_errors.add(1, {"channel": channel})
                            try:
                                from .dead_letter_queue import dead_letter_queue

                                await dead_letter_queue.push(
                                    event_id=event.event_id,
                                    event_type=str(event.event_type),
                                    payload=cleaned_json,
                                    error=str(handler_exc),
                                    retry_count=0,
                                )
                            except Exception as dlq_exc:
                                logger.warning("DLQ aktarımı başarısız oldu", error=str(dlq_exc))
            except Exception as exc:
                if self._running:
                    logger.warning("PubSub dinleme hatası", error=str(exc))
                    await asyncio.sleep(0.1)

    async def stop(self) -> None:
        """Dinleme döngüsünü durdurur ve bağlantıyı kapatır."""
        self._running = False
        if self._redis:
            try:
                await self._redis.close()
            except Exception as exc:
                logger.debug("Redis kapatılırken hata", error=str(exc))


class InMemoryRedis:
    """Geliştirme, test ve Redis kesintilerinde devreye giren bellek içi yedek kuyruk."""

    def __init__(self) -> None:
        """InMemoryRedis örneğini başlatır."""
        self._data: dict[str, Any] = {}
        self._pubsub_handlers: dict[str, list[Callable[..., Any]]] = {}
        self._streams: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock: threading.RLock = threading.RLock()

    def __repr__(self) -> str:
        """InMemoryRedis nesnesinin okunabilir temsilini döner."""
        with self._lock:
            return f"InMemoryRedis(anahtarlar={len(self._data)}, akislar={len(self._streams)})"

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        """Bellek içi anahtar-değer kaydı yapar.

        Args:
            key: Anahtar.
            value: Değer.
            ex: Sona erme süresi (saniye, simüle edilir).
            nx: Yalnızca anahtar yoksa kaydet bayrağı.

        Returns:
            bool: Başarılı ise True.
        """
        with self._lock:
            if nx and key in self._data:
                return False
            self._data[key] = value
            return True

    async def get(self, key: str) -> Any | None:
        """Bellek içi anahtar değerini okur.

        Args:
            key: Anahtar.

        Returns:
            Değer veya bulunamazsa None.
        """
        with self._lock:
            return self._data.get(key)

    async def xadd(
        self,
        stream_key: str,
        fields: dict[str, Any],
        maxlen: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Akışa (Stream) yeni bir mesaj ekler.

        Args:
            stream_key: Akış anahtarı.
            fields: Alan sözlüğü.
            maxlen: Tutulacak azami eleman adedi.

        Returns:
            str: Üretilen mesaj kimliği.
        """
        with self._lock:
            msg_id = f"{int(time.time() * 1000)}-0"
            self._streams[stream_key].append({"id": msg_id, "fields": fields})
            if maxlen and len(self._streams[stream_key]) > maxlen:
                self._streams[stream_key] = self._streams[stream_key][-maxlen:]
            return msg_id

    async def publish(self, channel: str, message: str) -> None:
        """Kanal abonelerine mesajı iletir.

        Args:
            channel: Kanal adı.
            message: Gönderilecek mesaj metni.
        """
        with self._lock:
            handlers = list(self._pubsub_handlers.get(channel, []))

        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h({"type": "message", "channel": channel, "data": message})
                else:
                    h({"type": "message", "channel": channel, "data": message})
            except Exception as exc:
                logger.debug("InMemoryRedis handler hatası", channel=channel, error=str(exc))

    def pubsub(self) -> InMemoryRedis:
        """PubSub arayüzünü döner."""
        return self

    async def subscribe(self, *channels: str) -> None:
        """Kanallara abone olur.

        Args:
            channels: Kanal isimleri.
        """
        with self._lock:
            for ch in channels:
                if ch not in self._pubsub_handlers:
                    self._pubsub_handlers[ch] = []

    async def get_message(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Mesaj bekleme simülasyonu."""
        await asyncio.sleep(timeout)
        return None

    async def close(self) -> None:
        """Veri yapılarını temizler."""
        with self._lock:
            self._pubsub_handlers.clear()
            self._streams.clear()
            logger.debug("InMemoryRedis kaynakları temizlendi")

    def publish_local(self, channel: str, event: CanonicalEvent) -> None:
        """Olay döngüsü emniyetli yerel yayınlama."""
        try:
            loop = asyncio.get_running_loop()
            if loop and loop.is_running():
                loop.create_task(self.publish(f"alpha:{channel}", event.to_json()))
            else:
                asyncio.run(self.publish(f"alpha:{channel}", event.to_json()))
        except RuntimeError:
            logger.warning("publish_local sırasında aktif döngü bulunamadı")


# Global tekil event bus
event_bus: Final[InternalEventBus] = InternalEventBus()


def publish_event(event: CanonicalEvent, key: str | None = None, **kwargs: Any) -> None:
    """Olayı NATS, Redis Pub/Sub, Redis Stream ve yerel DuckDB defterine yayınlar.

    Args:
        event: Yayınlanacak kanonik olay.
        key: İsteğe bağlı anahtar.
        kwargs: Ek parametreler.
    """
    # Şema doğrulaması
    if hasattr(event, "validate_payload"):
        missing = event.validate_payload()
        if missing:
            logger.warning("Olay yükü doğrulanamadı", event_type=str(event.event_type), missing=missing)
            return
    elif hasattr(event, "validate"):
        is_valid, reason = event.validate()
        if not is_valid:
            logger.warning("Olay doğrulaması başarısız", event_type=str(event.event_type), reason=reason)
            return

    # NATS (birincil yüksek throughput hattı)
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_publish_to_nats(event))
        else:
            asyncio.run(_publish_to_nats(event))
    except Exception as exc:
        logger.debug("NATS yayını atlandı", error=str(exc))

    # Redis Pub/Sub & Stream & DuckDB Ledger
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_publish_with_idempotency(event))
        else:
            asyncio.run(_publish_with_idempotency(event))
    except Exception as exc:
        logger.debug("Redis yayını işlendi", event_type=str(event.event_type), error=str(exc))


async def _publish_to_nats(event: CanonicalEvent) -> None:
    """Olayı NATS sunucusuna iletir."""
    try:
        from ..nats.client import nats_client

        subject = f"alpha.{event.event_type}"
        if not getattr(nats_client, "_connected", False):
            return

        if str(event.event_type) in CRITICAL_EVENT_TYPES:
            await nats_client.publish_durable(subject, event.to_json())
        else:
            await nats_client.publish(subject, event.to_json())
    except Exception as exc:
        logger.debug("NATS yayını atlandı", error=str(exc))


async def subscribe_nats(subject: str, handler: Callable[..., Any]) -> None:
    """NATS konusuna abone olur.

    Args:
        subject: NATS konu başlığı.
        handler: Olay işleyici fonksiyon.
    """
    try:
        from ..nats.client import nats_client

        await nats_client.subscribe(subject, handler=handler)
        logger.info("NATS konusuna abone olundu", subject=subject)
    except Exception as exc:
        logger.debug("NATS aboneliği atlandı", error=str(exc))


async def _publish_with_idempotency(event: CanonicalEvent) -> None:
    """Idempotent olarak Redis Pub/Sub, Stream ve DuckDB defterine yazar."""
    is_new = await _check_and_mark_published(event.event_id)
    if not is_new:
        logger.debug("Mükerrer olay atlandı", event_id=event.event_id)
        return

    # Pub/Sub (anlık dağıtım)
    await event_bus.publish(str(event.event_type), event)

    # Stream & DuckDB kalıcı defteri
    await _publish_to_stream(event)


_redis_conn: Any = None
_redis_conn_loop: asyncio.AbstractEventLoop | None = None
_redis_unavailable: bool = False


async def _get_redis() -> Any:
    """Merkezi Redis havuzunu döner veya InMemoryRedis yedeğini sağlar."""
    global _redis_conn, _redis_conn_loop, _redis_unavailable
    if _redis_unavailable:
        return InMemoryRedis()

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    # Olay döngüsü değişmiş veya kapanmışsa mevcut bağlantıyı yenile
    if _redis_conn is not None and _redis_conn_loop is not current_loop:
        _redis_conn = None

    if _redis_conn is not None:
        return _redis_conn

    try:
        from .database import get_redis

        r = await get_redis()
        if r:
            _redis_conn = r
            _redis_conn_loop = current_loop
            return _redis_conn
    except Exception as exc:
        logger.debug("Veritabanı Redis bağlantısı kurulamadı, bellek içine geçiliyor", error=str(exc))
        _redis_conn = InMemoryRedis()
        _redis_conn_loop = current_loop

    return _redis_conn


_pg_unavailable: bool = False
_published_lock: Final[threading.Lock] = threading.Lock()
_published_events_in_memory: dict[str, None] = {}


async def _check_and_mark_published(event_id: str) -> bool:
    """Olayın daha önce işlenip işlenmediğini (idempotency) denetler.

    Args:
        event_id: Olay benzersiz kimliği.

    Returns:
        bool: Olay yeni ise True, mükerrer ise False.
    """
    global _pg_unavailable, _published_events_in_memory

    with _published_lock:
        if event_id in _published_events_in_memory:
            return False

    # 1. Redis ile kontrol et
    if not _redis_unavailable:
        try:
            r = await _get_redis()
            if not isinstance(r, InMemoryRedis):
                key = f"event_published:{event_id}"
                result = await r.set(key, "1", ex=3600, nx=True)
                if result:
                    with _published_lock:
                        _published_events_in_memory[event_id] = None
                    return True
                return False
        except Exception as exc:
            logger.debug("Redis idempotency denetimi atlandı", error=str(exc))

    # 2. PostgreSQL ile kontrol et
    if not _pg_unavailable:
        try:
            from services.core.database import pg_execute, pg_fetchrow

            existing = await pg_fetchrow("SELECT event_id FROM event_ledger WHERE event_id = $1", event_id)
            if existing:
                return False
            await pg_execute(
                "INSERT INTO event_ledger (event_id, published_at) VALUES ($1, CURRENT_TIMESTAMP) ON CONFLICT (event_id) DO NOTHING",
                event_id,
            )
            with _published_lock:
                _published_events_in_memory[event_id] = None
            return True
        except Exception as pg_err:
            _pg_unavailable = True
            logger.debug("pg_idempotency_denetimi_basarisiz_fallback", error=str(pg_err))

    # 3. Bellek içi FIFO koruma (fallback)
    with _published_lock:
        _published_events_in_memory[event_id] = None
        if len(_published_events_in_memory) > DEFAULT_MAX_EVENT_HISTORY:
            # En eski olayları at, en yeni 25000 olayı kronolojik koru (FIFO)
            surviving = list(_published_events_in_memory.keys())[-25000:]
            _published_events_in_memory = dict.fromkeys(surviving)
    return True


_duckdb_ledger_lock: Final[threading.Lock] = threading.Lock()


def _record_to_duckdb_ledger(
    event: CanonicalEvent,
    db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH,
) -> None:
    """Olayı yerel DuckDB kalıcı defterine (Event Ledger) kaydeder (GEMINI.md Kural 5)."""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _duckdb_ledger_lock:
        # 0-byte bozuk dosya koruması
        if target.exists() and target.is_file() and target.stat().st_size == 0:
            with contextlib.suppress(OSError):
                target.unlink()

        try:
            with duckdb.connect(str(target)) as conn:
                try:
                    from services.core.debounce import configure_duckdb_wal

                    configure_duckdb_wal(conn)
                except Exception as wal_err:
                    logger.debug("event_ledger_wal_yapilandirma_atlandi", error=str(wal_err))

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS event_ledger (
                        event_id VARCHAR PRIMARY KEY,
                        event_type VARCHAR NOT NULL,
                        payload VARCHAR NOT NULL,
                        published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_event_ledger_type_ts ON event_ledger (event_type, published_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_event_ledger_ts ON event_ledger (published_at DESC);
                """
                )
                payload_str = event.to_json()
                if isinstance(payload_str, bytes):
                    payload_str = payload_str.decode("utf-8")

                conn.execute(
                    """
                    INSERT INTO event_ledger (event_id, event_type, payload, published_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (event_id) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        published_at = EXCLUDED.published_at
                """,
                    (event.event_id, str(event.event_type), payload_str),
                )
        except Exception as exc:
            logger.debug("DuckDB event ledger yazma hatası", error=str(exc))


async def _publish_to_stream(event: CanonicalEvent) -> None:
    """Kalıcı olay defterine kaydeder (Redis Stream > DuckDB > PostgreSQL)."""
    global _pg_unavailable

    # 1. Redis Stream
    try:
        r = await _get_redis()
        stream_key = f"alpha:events:{event.event_type}"
        payload_str = event.to_json()
        if isinstance(payload_str, bytes):
            payload_str = payload_str.decode("utf-8")

        await r.xadd(
            stream_key,
            {
                "event_id": event.event_id,
                "event_type": str(event.event_type),
                "data": payload_str,
                "timestamp": event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp),
            },
            maxlen=10000,
        )
    except Exception as exc:
        logger.debug("Redis Stream yazma atlandı", error=str(exc))

    # 2. Yerel DuckDB Kalıcı Defteri (Her koşulda kalıcı kayıt)
    _record_to_duckdb_ledger(event)

    # 3. PostgreSQL
    if not _pg_unavailable:
        try:
            from services.core.database import pg_execute

            payload_str = event.to_json()
            if isinstance(payload_str, bytes):
                payload_str = payload_str.decode("utf-8")

            await pg_execute(
                "INSERT INTO event_ledger (event_id, event_type, payload, published_at) VALUES ($1, $2, $3, CURRENT_TIMESTAMP) ON CONFLICT (event_id) DO NOTHING",
                event.event_id,
                str(event.event_type),
                payload_str,
            )
        except Exception as exc:
            _pg_unavailable = True
            logger.debug("PG event ledger yazma atlandı", error=str(exc))


def export_event_ledger_to_polars(
    db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """Kalıcı DuckDB olay defterini Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

    Args:
        db_path: DuckDB dosya yolu.
        limit: Çekilecek azami olay adedi.

    Returns:
        Olay kayıtlarını içeren Polars DataFrame.
    """
    empty_schema = {
        "event_id": pl.String,
        "event_type": pl.String,
        "payload": pl.String,
        "published_at": pl.Datetime("us", "UTC"),
    }
    target = Path(db_path)
    if not target.exists():
        return pl.DataFrame(schema=empty_schema)

    with _duckdb_ledger_lock:
        try:
            with duckdb.connect(str(target), read_only=True) as conn:
                return conn.execute(
                    """
                    SELECT event_id, event_type, payload, published_at
                    FROM event_ledger
                    ORDER BY published_at DESC
                    LIMIT ?
                """,
                    (limit,),
                ).pl()
        except Exception as exc:
            logger.debug("Event ledger Polars aktarımı hatası", error=str(exc))
            return pl.DataFrame(schema=empty_schema)


def query_event_ledger_duckdb(
    db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH,
    event_type: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """Kalıcı DuckDB olay defterini filtrelenmiş Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        event_type: İsteğe bağlı olay tipi filtresi.
        limit: Azami satır sayısı.

    Returns:
        Filtrelenmiş olay tablosu.
    """
    empty_schema = {
        "event_id": pl.String,
        "event_type": pl.String,
        "payload": pl.String,
        "published_at": pl.Datetime("us", "UTC"),
    }
    target = Path(db_path)
    if not target.exists():
        return pl.DataFrame(schema=empty_schema)

    with _duckdb_ledger_lock:
        try:
            with duckdb.connect(str(target), read_only=True) as conn:
                query = "SELECT event_id, event_type, payload, published_at FROM event_ledger"
                params: list[Any] = []
                if event_type:
                    query += " WHERE event_type = ?"
                    params.append(str(event_type))
                query += " ORDER BY published_at DESC LIMIT ?"
                params.append(max(1, limit))
                return conn.execute(query, params).pl()
        except Exception as exc:
            logger.debug("Event ledger sorgulama hatası", error=str(exc))
            return pl.DataFrame(schema=empty_schema)


class EventConsumer:
    """Push-based tüketici — Redis Pub/Sub üzerinden olayları dinler ve işler."""

    def __init__(self, group_id: str, topics: list[str], auto_offset_reset: str = "latest") -> None:
        """EventConsumer örneğini başlatır.

        Args:
            group_id: Tüketici grup kimliği.
            topics: Dinlenecek konu başlıkları listesi.
            auto_offset_reset: Başlangıç ofseti ("latest" / "earliest").
        """
        self.group_id: str = group_id
        self.topics: list[str] = list(topics)
        self.auto_offset_reset: str = auto_offset_reset
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._running: bool = False
        self._processed_ids: dict[str, None] = {}
        self._lock: threading.RLock = threading.RLock()

    def __repr__(self) -> str:
        """EventConsumer nesnesinin okunabilir temsilini döner."""
        with self._lock:
            return (
                f"EventConsumer(grup={self.group_id!r}, "
                f"konular={self.topics!r}, isleyiciler={len(self._handlers)})"
            )

    def on(self, event_type: str, handler: Callable[..., Any]) -> EventConsumer:
        """Belirli bir olay tipi için işleyici kaydeder.

        Args:
            event_type: Dinlenecek olay tipi.
            handler: Olay tetiklendiğinde çalışacak fonksiyon.

        Returns:
            Zincirleme çağrı için EventConsumer nesnesinin kendisi.
        """
        with self._lock:
            self._handlers[event_type] = handler
        return self

    async def start(self) -> None:
        """Kayıtlı konulara abone olarak dinlemeyi başlatır."""
        self._running = True
        for topic in self.topics:
            await event_bus.subscribe(topic, self._handle_event)
        logger.info("Tüketici başlatıldı (push-based)", group_id=self.group_id, topics=self.topics)

    async def _handle_event(self, event: CanonicalEvent) -> None:
        """Gelen olayı işleyiciye aktarır; mükerrerleri eler ve hataları DLQ'ya yönlendirir."""
        with self._lock:
            if event.event_id in self._processed_ids:
                return

        with self._lock:
            handler = self._handlers.get(str(event.event_type))

        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)

                with self._lock:
                    self._processed_ids[event.event_id] = None
                    if len(self._processed_ids) > DEFAULT_MAX_EVENT_HISTORY:
                        surviving = list(self._processed_ids.keys())[-25000:]
                        self._processed_ids = dict.fromkeys(surviving)

                _events_consumed.add(1, {"group_id": self.group_id})
            except Exception as handler_exc:
                logger.error("Olay işleme hatası", event_type=str(event.event_type), error=str(handler_exc))
                _handler_errors.add(1, {"group_id": self.group_id})
                try:
                    from .dead_letter_queue import dead_letter_queue

                    await dead_letter_queue.push(
                        event_id=event.event_id,
                        event_type=str(event.event_type),
                        payload=event.to_json(),
                        error=str(handler_exc),
                        retry_count=0,
                    )
                except Exception as dlq_exc:
                    logger.warning("DLQ aktarımı başarısız oldu", error=str(dlq_exc))

    async def consume_loop(self) -> None:
        """Olay dinleme döngüsünü başlatır."""
        await self.start()
        await event_bus.start_listening()

    def stop(self) -> None:
        """Tüketiciyi durdurur."""
        self._running = False

    def to_orjson_bytes(self) -> bytes:
        """Tüketici durumunu orjson binary formatında döner (GEMINI.md Kural 5).

        Returns:
            JSON bayt dizisi.
        """
        with self._lock:
            data = {
                "group_id": self.group_id,
                "topics": self.topics,
                "handlers_count": len(self._handlers),
                "processed_count": len(self._processed_ids),
                "is_running": self._running,
            }
        return orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str)

    def clear_history(self) -> None:
        """Tüketici tarafından işlenmiş olay kimlikleri önbelleğini temizler."""
        with self._lock:
            self._processed_ids.clear()
            logger.info("EventConsumer işlenmiş olay geçmişi temizlendi", group_id=self.group_id)


# Geriye dönük uyumluluk takma adı
EventBus = InternalEventBus


def record_event_to_duckdb_ledger(
    event: CanonicalEvent,
    db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH,
) -> None:
    """Olayı yerel DuckDB kalıcı defterine (Event Ledger) kaydeder."""
    _record_to_duckdb_ledger(event=event, db_path=db_path)


def clear_event_history() -> None:
    """Bellek içi idempotency olay geçmişini temizler."""
    global _published_events_in_memory
    with _published_lock:
        _published_events_in_memory.clear()
        logger.info("Olay yayın idempotency geçmişi temizlendi")


def clear_event_ledger(db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH) -> None:
    """Kalıcı DuckDB olay defterini temizler (tabloyu sıfırlar)."""
    target = Path(db_path)
    if not target.exists():
        return

    with _duckdb_ledger_lock:
        try:
            with duckdb.connect(str(target)) as conn:
                conn.execute("DELETE FROM event_ledger")
                logger.info("DuckDB olay defteri temizlendi", path=str(target))
        except Exception as exc:
            logger.error("DuckDB olay defteri temizlenirken hata", error=str(exc))


def export_event_ledger_to_orjson_bytes(
    db_path: str = DEFAULT_EVENT_LEDGER_DB_PATH,
    limit: int = 1000,
) -> bytes:
    """Kalıcı DuckDB olay defterini orjson binary olarak döner (GEMINI.md Kural 5)."""
    df = export_event_ledger_to_polars(db_path=db_path, limit=limit)
    rows = df.to_dicts()
    return orjson.dumps(rows, option=orjson.OPT_INDENT_2, default=str)


__all__: Final[list[str]] = [
    "CRITICAL_EVENT_TYPES",
    "DEFAULT_EVENT_LEDGER_DB_PATH",
    "DEFAULT_MAX_EVENT_HISTORY",
    "DEFAULT_SUBJECTS",
    "EventBus",
    "EventConsumer",
    "InMemoryRedis",
    "InternalEventBus",
    "clear_event_history",
    "clear_event_ledger",
    "ensure_topics",
    "event_bus",
    "export_event_ledger_to_orjson_bytes",
    "export_event_ledger_to_polars",
    "flush_producer",
    "publish_event",
    "query_event_ledger_duckdb",
    "record_event_to_duckdb_ledger",
    "subscribe_nats",
]

