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
            except Exception as e:
                logger.warning("PubSub listen error", error=str(e))
                await asyncio.sleep(0.1)

    async def stop(self):
        self._running = False
        if self._redis:
            try:
                await self._redis.close()
            except:
                pass


class InMemoryRedis:
    """In-memory Redis fallback (Docker yokken)."""
    def __init__(self):
        self._data = {}
        self._pubsub_handlers = {}

    async def publish(self, channel: str, message: str):
        handlers = self._pubsub_handlers.get(channel, [])
        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h({"type": "message", "channel": channel, "data": message})
                else:
                    h({"type": "message", "channel": channel, "data": message})
            except:
                pass

    def pubsub(self):
        return self

    async def subscribe(self, *channels):
        for ch in channels:
            if ch not in self._pubsub_handlers:
                self._pubsub_handlers[ch] = []

    async def get_message(self, timeout=1.0):
        await asyncio.sleep(timeout)
        return None

    async def close(self):
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
    "bar.1m", "bar.5m", "bar.15m", "bar.1h", "bar.1d",
]

_producer: Optional[Producer] = None


def get_producer():
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
        except Exception:
            return None
    return _producer


def publish_event(event: CanonicalEvent, key: Optional[str] = None):
    """Publish to Kafka (if available) + Redis Pub/Sub (always)."""
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
        except Exception:
            pass

    # Redis Pub/Sub (push-based, her zaman çalışır)
    try:
        asyncio.create_task(event_bus.publish(event.event_type, event))
    except:
        pass


def flush_producer():
    global _producer
    if _producer:
        _producer.flush(timeout=10)


def ensure_topics():
    if AdminClient is None:
        return
    try:
        admin = AdminClient({"bootstrap.servers": settings.redpanda_brokers})
        existing = admin.list_topics(timeout=10).topics
        new_topics = [NewTopic(t, num_partitions=4, replication_factor=1) for t in TOPICS if t not in existing]
        if new_topics:
            admin.create_topics(new_topics)
    except Exception:
        pass


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
                if len(self._processed_ids) > 10000:
                    self._processed_ids = set(list(self._processed_ids)[-5000:])
            except Exception as e:
                logger.error("Handler error", event_type=event.event_type, error=str(e))

    async def consume_loop(self):
        """Start listening — push-based, blocking."""
        await self.start()
        await event_bus.start_listening()

    def stop(self):
        self._running = False
