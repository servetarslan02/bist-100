"""ALPHA BIST - Event Bus v1.3 (Push-Based Internal Architecture)

Dış kaynaklardan veri PUSH ile gelir.
İç servisler arası iletişim REDIS PUB/SUB ile olur.
Sürekli API isteği YOKTUR.
"""

import json
import asyncio
from typing import Optional, Callable, Dict, Any, List
import structlog

try:
    from confluent_kafka import Producer, Consumer, KafkaError
    from confluent_kafka.admin import AdminClient, NewTopic
except ImportError:
    Producer = None
    Consumer = None
    KafkaError = None
    AdminClient = None
    NewTopic = None

from .config import settings
from .event_schema import CanonicalEvent, EventType

logger = structlog.get_logger()


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
        self._subscribers: Dict[str, List[Callable]] = {}
        self._running = False

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            except ImportError:
                logger.warning("Redis not available, using in-memory fallback")
                self._redis = InMemoryRedis()
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
                pass  # Intentional: silent error handling


class InMemoryRedis:
    """In-memory Redis fallback (Docker yokken)."""
    def __init__(self):
        self._data = {}
        self._pubsub_handlers = {}

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
                pass  # Intentional: silent error handling

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
        """Baglantilari kapat."""
        pass

    def publish_local(self, channel, event):
        """In-memory publish."""
        asyncio.create_task(self.publish(f"alpha:{channel}", event.to_json()))


# =====================================================
# Singleton
# =====================================================

event_bus = InternalEventBus()


# =====================================================
# Legacy Kafka support (Redpanda varsa)
# =====================================================

TOPICS = [
    "market.tick", "market.trade", "market.quote", "market.orderbook",
    "news.raw", "news.event", "kap.event", "macro.event", "social.event",
    "feature.updated", "state.updated", "market_state.changed", "world_state.changed",
    "signal.generated", "anomaly.detected", "regime.changed",
    "simulation.requested", "simulation.completed",
    "risk.changed", "risk.alert", "kill_switch.triggered",
    "decision.created", "order.placed", "order.filled",
    "prediction.created", "outcome.created",
    "breadth.alert", "liquidity.alert", "regime.transition",
    "anomaly.cluster", "sentiment.shift", "multi_tf.divergence",
    "bar.1m", "bar.5m", "bar.15m", "bar.1h", "bar.1d",
]

_producer: Optional[Producer] = None


def get_producer():
    """Kafka producer getir veya olustur."""
    global _producer
    if Producer is None:
        return None
    if _producer is None:
        try:
            _producer = Producer({
                "bootstrap.servers": settings.redpanda_brokers,
                "client.id": "alpha-producer",
                "acks": "all",
                "retries": 5,
                "linger.ms": 5,
                "batch.size": 16384,
                "enable.idempotence": True,
            })
        except Exception as e:
            return None
    return _producer


def publish_event(event: CanonicalEvent, key: Optional[str] = None):
    """Publish to Kafka (if available) + Redis Pub/Sub (always) + Event Ledger.

    v2.0 düzeltmeleri:
    - Schema validation — yanlış payload publish edilemez
    - Event ledger (Redis Stream) — subscriber kapalıyken event kaybolmamalı
    - Idempotency — aynı event_id tekrar publish edilmemeli
    """
    # Schema validation
    missing = event.validate_payload()
    if missing:
        logger.warning("Event payload validation failed",
                      event_type=event.event_type, missing=missing)
        return

    # Kafka
    producer = get_producer()
    if producer:
        try:
            producer.produce(
                topic=event.event_type,
                key=key or event.event_id,
                value=event.to_json().encode("utf-8"),
            )
            producer.poll(0)
        except Exception as e:
            pass  # Intentional: silent error handling

    # Redis Pub/Sub (push-based) + Stream (durable ledger)
    try:
        asyncio.create_task(_publish_with_idempotency(event))
    except Exception as e:
        pass  # Intentional: silent error handling


async def _publish_with_idempotency(event: CanonicalEvent):
    """Idempotent publish to Redis Pub/Sub + Stream."""
    # Idempotency check
    is_new = await _check_and_mark_published(event.event_id)
    if not is_new:
        logger.debug("Duplicate event skipped", event_id=event.event_id)
        return

    # Pub/Sub (push-based, anlık)
    await event_bus.publish(event.event_type, event)

    # Stream (durable ledger)
    await _publish_to_stream(event)


async def _get_redis():
    """Reuse module-level Redis connection."""
    global _redis_conn
    if _redis_conn is None:
        try:
            import redis.asyncio as aioredis
            _redis_conn = aioredis.from_url(settings.redis_url, decode_responses=True)
        except ImportError:
            _redis_conn = InMemoryRedis()
    return _redis_conn


_redis_conn = None


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
        logger.debug("Handled exception", error=str(e), context="event_bus.py:271")

    # 2. PostgreSQL dene
    try:
        from services.core.database_dev import dev_db
        existing = await dev_db.pg_fetchrow(
            "SELECT event_id FROM event_ledger WHERE event_id = ?", event_id
        )
        if existing:
            return False
        await dev_db.pg_execute(
            "INSERT OR IGNORE INTO event_ledger (event_id, published_at) VALUES (?, CURRENT_TIMESTAMP)",
            event_id
        )
        return True
    except Exception as e:
        logger.debug("Handled exception", error=str(e), context="event_bus.py:287")

    # 3. Fail-open
    return True


async def _publish_to_stream(event: CanonicalEvent):
    """Durable event ledger'a yaz.
    Öncelik: Redis Stream > PostgreSQL > Log
    """
    # 1. Redis Stream dene
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        stream_key = f"alpha:events:{event.event_type}"
        await r.xadd(stream_key, {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "data": event.to_json(),
            "timestamp": event.timestamp.isoformat(),
        }, maxlen=10000)
        await r.close()
        return
    except Exception as e:
        logger.debug("Handled exception", error=str(e), context="event_bus.py:311")

    # 2. PostgreSQL dene
    try:
        from services.core.database_dev import dev_db
        await dev_db.pg_execute(
            "INSERT OR IGNORE INTO event_ledger (event_id, event_type, payload, published_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            event.event_id, event.event_type, event.to_json()
        )
        return
    except Exception as e:
        logger.debug("PG event ledger write failed", error=str(e))


def flush_producer():
    """Kafka producer buffer'ini bosalt."""
    global _producer
    if _producer:
        _producer.flush(timeout=10)


def ensure_topics():
    """Kafka topic'lerinin var oldugundan emin ol."""
    if AdminClient is None:
        return
    try:
        admin = AdminClient({"bootstrap.servers": settings.redpanda_brokers})
        existing = admin.list_topics(timeout=10).topics
        new_topics = [NewTopic(t, num_partitions=4, replication_factor=1) for t in TOPICS if t not in existing]
        if new_topics:
            admin.create_topics(new_topics)
    except Exception as e:
        pass  # Intentional: silent error handling


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
