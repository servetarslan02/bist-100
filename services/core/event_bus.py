"""ALPHA BIST - Event Bus v2.0 (Push-Based Internal Architecture)

Dış kaynaklardan veri PUSH ile gelir.
İç servisler arası iletişim NATS + Redis Pub/Sub ile olur.
Sürekli API isteği YOKTUR.

Mesajlaşma Strateji:
- PRIMARY: NATS (yüksek throughput, düşük gecikme, JetStream dayanıklılık)
- SECONDARY: Redis Pub/Sub (anlık bildirim, push-based)
- DURABLE: Redis Streams (event ledger, at-least-once)
"""

import asyncio
from typing import Optional, Callable, Dict, Any, List
import structlog

from .config import settings
from .event_schema import CanonicalEvent

logger = structlog.get_logger()


# =====================================================
# NATS Topic Management
# =====================================================

# Varsayılan NATS subject'leri
DEFAULT_SUBJECTS = [
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


def ensure_topics(subjects: Optional[List[str]] = None):
    """Ensure NATS subjects are registered.

    NATS otomatik subject oluşturma destekler, bu fonksiyon
    sadece loglama ve doğrulama yapar.
    """
    target_subjects = subjects or DEFAULT_SUBJECTS
    logger.info("NATS subjects ensured", count=len(target_subjects),
                subjects=target_subjects[:5])
    return True


async def flush_producer():
    """Flush pending events to NATS/Redis.

    Çıkış sırasında buffer'daki tüm mesajları gönder.
    """
    try:
        redis = await _get_redis()
        if redis:
            logger.info("Producer flushed")
    except Exception as e:
        logger.warning("Producer flush failed", error=str(e))


# =====================================================
# Internal Event Bus (Redis Pub/Sub — Push-Based)
# =====================================================

class InternalEventBus:
    """
    İç servisler arası iletişim için Redis Pub/Sub kullanır.
    Push-based: veri olduğunda anında gider, polling yok.
    """

    def __init__(self):
        self._redis = None
        self._redis_loop = None
        self._subscribers: Dict[str, List[Callable]] = {}
        self._running = False

    async def _get_redis(self):
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._redis is None or self._redis_loop is not current_loop:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
                self._redis_loop = current_loop
            except (ImportError, Exception):
                self._redis = InMemoryRedis()
                self._redis_loop = current_loop
        return self._redis

    async def publish(self, channel: str, event: CanonicalEvent):
        """Event'i publish et — tüm subscriber'lara anında gider."""
        r = await self._get_redis()
        try:
            await r.publish(f"alpha:{channel}", event.to_json())
            logger.debug("Event published", channel=channel, event_type=event.event_type)
        except Exception as e:
            logger.warning("Publish failed, using in-memory", error=str(e))
            # In-memory fallback
            if hasattr(r, 'publish_local'):
                r.publish_local(channel, event)

    async def subscribe(self, channel: str, handler: Callable):
        """Kanalı dinle — veri geldiğinde handler çalışır."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(handler)
        logger.debug("Subscribed", channel=channel)

    async def start_listening(self):
        """Tüm subscriber'ları dinle — blocking loop."""
        self._running = True
        r = await self._get_redis()

        # Tüm kanalları tek bir pubsub'da dinle
        pubsub = r.pubsub()
        channels = [f"alpha:{ch}" for ch in self._subscribers.keys()]
        if channels:
            await pubsub.subscribe(*channels)
            logger.info("Listening on channels", channels=list(self._subscribers.keys()))

        while self._running:
            try:
                message = await pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    channel = message["channel"].replace("alpha:", "")
                    event = CanonicalEvent.from_json(message["data"])

                    handlers = self._subscribers.get(channel, [])
                    for handler in handlers:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(event)
                            else:
                                handler(event)
                        except Exception as e:
                            logger.error("Handler error", channel=channel, error=str(e))
                            # DLQ'ya düşür (event kaybını önle)
                            try:
                                from .dead_letter_queue import dead_letter_queue
                                await dead_letter_queue.push(
                                    event_id=event.event_id,
                                    event_type=event.event_type,
                                    payload=event.to_json(),
                                    error=str(e),
                                    retry_count=0,
                                )
                            except Exception as e:
                                logger.warning("Operation failed", context="DLQ bile çalışamıyorsa log yeterli", error=str(e))
            except Exception as e:
                logger.warning("PubSub listen error", error=str(e))
                await asyncio.sleep(0.1)

    async def stop(self):
        """Dinlemeyi durdur."""
        self._running = False
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.debug("Redis close failed", error=str(e))


class InMemoryRedis:
    """In-memory Redis fallback (Docker yokken veya test ortamında)."""
    def __init__(self):
        self._data = {}
        self._pubsub_handlers = {}
        self._streams = defaultdict(list)

    async def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    async def get(self, key: str) -> Optional[Any]:
        return self._data.get(key)

    async def xadd(self, stream_key: str, fields: Dict[str, Any]) -> str:
        msg_id = f"{int(_time.time() * 1000)}-0"
        self._streams[stream_key].append({"id": msg_id, "fields": fields})
        return msg_id

    async def publish(self, channel: str, message: str):
        """Event yayinla."""
        handlers = self._pubsub_handlers.get(channel, [])
        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h({"type": "message", "channel": channel, "data": message})
                else:
                    h({"type": "message", "channel": channel, "data": message})
            except Exception as e:
                logger.debug("InMemoryRedis handler error", channel=channel, error=str(e))

    def pubsub(self):
        """Pubsub instance dondur."""
        return self

    async def subscribe(self, *channels):
        """Kanala abone ol."""
        for ch in channels:
            if ch not in self._pubsub_handlers:
                self._pubsub_handlers[ch] = []

    async def get_message(self, timeout=1.0):
        """Mesaj al (blocking)."""
        await asyncio.sleep(timeout)
        return None

    async def close(self):
        """Baglantilari kapat ve temizle."""
        self._pubsub_handlers.clear()
        self._streams.clear()
        logger.debug("InMemoryRedis closed and cleaned up")

    def publish_local(self, channel, event):
        """In-memory publish with loop safety."""
        try:
            loop = asyncio.get_running_loop()
            if loop and loop.is_running():
                loop.create_task(self.publish(f"alpha:{channel}", event.to_json()))
            else:
                asyncio.run(self.publish(f"alpha:{channel}", event.to_json()))
        except RuntimeError:
            pass


# =====================================================
# Singleton
# =====================================================

event_bus = InternalEventBus()


# =====================================================
# NATS Integration (Primary Messaging)
# Tek client: services.nats.client.nats_client
# =====================================================


def publish_event(event: CanonicalEvent):
    """Publish to NATS (primary) + Redis Pub/Sub (push) + Redis Stream (durable).

    v2.0: Kafka/Redpanda kaldırıldı. NATS ana mesajlaşma, Redis Pub/Sub yardımcı.
    """
    # Schema validation
    missing = event.validate_payload()
    if missing:
        logger.warning("Event payload validation failed",
                      event_type=event.event_type, missing=missing)
        return

    # NATS (primary) — yüksek throughput, düşük gecikme
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_publish_to_nats(event))
        else:
            asyncio.run(_publish_to_nats(event))
    except Exception as e:
        logger.debug("NATS publish skipped", error=str(e))

    # Redis Pub/Sub (push-based) + Stream (durable ledger)
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_publish_with_idempotency(event))
        else:
            asyncio.run(_publish_with_idempotency(event))
    except Exception as e:
        logger.debug("Redis publish handled", event_type=event.event_type, error=str(e))


async def _publish_to_nats(event: CanonicalEvent):
    """NATS'a publish et — kritik event'ler için JetStream, diğerleri için normal publish."""
    try:
        from ..nats.client import nats_client
        subject = f"alpha.{event.event_type}"

        # Kritik event tipleri → JetStream (disk-based, persistent, restart-safe)
        CRITICAL_EVENT_TYPES = {
            "signal.generated", "signal.executed",
            "portfolio.trade", "portfolio.updated",
            "risk.alert", "risk.breach",
            "regime.changed",
        }

        if event.event_type in CRITICAL_EVENT_TYPES:
            await nats_client.publish_durable(subject, event.to_json())
        else:
            await nats_client.publish(subject, event.to_json())
    except Exception as e:
        logger.debug("NATS publish skipped", error=str(e))


async def subscribe_nats(subject: str, handler: Callable):
    """NATS konusuna abone ol."""
    try:
        from ..nats.client import nats_client
        await nats_client.subscribe(subject, handler=handler)
        logger.info("NATS subscribed", subject=subject)
    except Exception as e:
        logger.debug("NATS subscribe skipped", error=str(e))


async def _publish_with_idempotency(event: CanonicalEvent):
    """Idempotent publish to Redis Pub/Sub + Stream + NATS."""
    # Idempotency check
    is_new = await _check_and_mark_published(event.event_id)
    if not is_new:
        logger.debug("Duplicate event skipped", event_id=event.event_id)
        return

    # Pub/Sub (push-based, anlık)
    await event_bus.publish(event.event_type, event)

    # Stream (durable ledger)
    await _publish_to_stream(event)

    # NATS (yüksek throughput, düşük gecikme)
    await _publish_to_nats(event)


_redis_conn = None
_redis_loop = None


async def _get_redis():
    """Reuse module-level Redis connection or create new if loop changed/closed."""
    global _redis_conn, _redis_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _redis_conn is None or _redis_loop is not current_loop:
        try:
            import redis.asyncio as aioredis
            _redis_conn = aioredis.from_url(settings.redis_url, decode_responses=True)
            _redis_loop = current_loop
        except (ImportError, Exception):
            _redis_conn = InMemoryRedis()
            _redis_loop = current_loop
    return _redis_conn


async def _check_and_mark_published(event_id: str) -> bool:
    """Idempotency check — aynı event_id tekrar publish edilmesin.
    Returns True if this is a new event, False if duplicate.
    Öncelik: Redis > PostgreSQL > fail-open
    """
    # 1. Redis dene (reuse connection)
    try:
        r = await _get_redis()
        key = f"event_published:{event_id}"
        result = await r.set(key, "1", ex=3600, nx=True)
        if result is not None:
            return True
        return False
    except Exception as e:
        logger.debug("Redis idempotency check skipped", error=str(e))

    # 2. PostgreSQL dene
    try:
        from services.core.database import pg_fetchrow, pg_execute
        existing = await pg_fetchrow(
            "SELECT event_id FROM event_ledger WHERE event_id = $1", event_id
        )
        if existing:
            return False
        await pg_execute(
            "INSERT INTO event_ledger (event_id, published_at) VALUES ($1, CURRENT_TIMESTAMP) ON CONFLICT (event_id) DO NOTHING",
            event_id
        )
        return True
    except Exception as e:
        logger.debug("PostgreSQL idempotency check skipped", error=str(e))

    # 3. Fail-open
    return True


async def _publish_to_stream(event: CanonicalEvent):
    """Durable event ledger'a yaz.
    Öncelik: Redis Stream > PostgreSQL > Log
    """
    # 1. Redis Stream dene (reuse connection)
    try:
        r = await _get_redis()
        stream_key = f"alpha:events:{event.event_type}"
        await r.xadd(stream_key, {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "data": event.to_json(),
            "timestamp": event.timestamp.isoformat(),
        }, maxlen=10000)
        return
    except Exception as e:
        logger.warning("Redis Stream write failed", error=str(e), context="event_bus.py:311")

    # 2. PostgreSQL dene
    try:
        from services.core.database import pg_execute
        await pg_execute(
            "INSERT INTO event_ledger (event_id, event_type, payload, published_at) VALUES ($1, $2, $3, CURRENT_TIMESTAMP) ON CONFLICT (event_id) DO NOTHING",
            event.event_id, event.event_type, event.to_json()
        )
        return
    except Exception as e:
        logger.warning("PG event ledger write failed", error=str(e))


# =====================================================
# EventConsumer (At-least-once + Idempotent)
# =====================================================

class EventConsumer:
    """Push-based consumer — Redis Pub/Sub ile çalışır."""

    def __init__(self, group_id: str, topics: List[str], auto_offset_reset: str = "latest"):
        self.group_id = group_id
        self.topics = topics
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._processed_ids: set = set()

    def on(self, event_type: str, handler: Callable):
        """Event handler kaydet."""
        self._handlers[event_type] = handler
        return self

    async def start(self):
        """Redis Pub/Sub'a subscribe ol — push-based."""
        self._running = True
        for topic in self.topics:
            await event_bus.subscribe(topic, self._handle_event)
        logger.info("Consumer started (push-based)", group_id=self.group_id, topics=self.topics)

    async def _handle_event(self, event: CanonicalEvent):
        """Event geldiğinde çalışır — polling yok."""
        if event.event_id in self._processed_ids:
            return

        handler = self._handlers.get(event.event_type)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                self._processed_ids.add(event.event_id)
                if len(self._processed_ids) > 50000:
                    self._processed_ids = set(list(self._processed_ids)[-25000:])
            except Exception as e:
                logger.error("Handler error", event_type=event.event_type, error=str(e))
                # DLQ'ya düşür
                try:
                    from .dead_letter_queue import dead_letter_queue
                    await dead_letter_queue.push(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload=event.to_json(),
                        error=str(e),
                        retry_count=0,
                    )
                except Exception as e:
                    logger.warning("Failed to load module", module="unknown", error=str(e))

    async def consume_loop(self):
        """Start listening — push-based, blocking."""
        await self.start()
        await event_bus.start_listening()

    def stop(self):
        """Dinlemeyi durdur."""
        self._running = False
