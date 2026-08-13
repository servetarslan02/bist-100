"""ALPHA BIST - Event Bus v1.1 (Redpanda/Kafka)

v1.1: AlphaEvent kaldırıldı, sadece CanonicalEvent kullanılıyor.
At-least-once delivery + idempotent consumers.
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
# Topic Definitions
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


# =====================================================
# Producer
# =====================================================

_producer: Optional[Producer] = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer({
            "bootstrap.servers": settings.redpanda_brokers,
            "client.id": "alpha-producer",
            "acks": "all",
            "retries": 5,
            "linger.ms": 5,
            "batch.size": 16384,
            "enable.idempotence": True,
        })
        logger.info("Event producer created", brokers=settings.redpanda_brokers)
    return _producer


def publish_event(event: CanonicalEvent, key: Optional[str] = None):
    """Publish a canonical event to the event bus."""
    producer = get_producer()
    topic = event.event_type

    def delivery_callback(err, msg):
        if err:
            logger.error("Event delivery failed", error=str(err), topic=topic,
                        event_id=event.event_id)
        else:
            logger.debug("Event delivered", topic=topic,
                        partition=msg.partition(), offset=msg.offset())

    try:
        producer.produce(
            topic=topic,
            key=key or event.event_id,
            value=event.to_json().encode("utf-8"),
            callback=delivery_callback,
        )
        producer.poll(0)
    except Exception as e:
        logger.error("Failed to publish event", error=str(e),
                    event_type=event.event_type, event_id=event.event_id)
        raise


def flush_producer():
    global _producer
    if _producer:
        _producer.flush(timeout=10)


# =====================================================
# Consumer (At-least-once + Idempotent)
# =====================================================

class EventConsumer:
    """
    At-least-once consumer with idempotent processing.

    - enable.auto.commit = False (manual commit after processing)
    - Idempotency: handler must be idempotent (check event_id in DB/Redis)
    """

    def __init__(self, group_id: str, topics: List[str],
                 auto_offset_reset: str = "latest"):
        self.group_id = group_id
        self.topics = topics
        self.auto_offset_reset = auto_offset_reset
        self._consumer: Optional[Consumer] = None
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._processed_ids: set = set()  # In-memory dedup (use Redis in production)

    def on(self, event_type: str, handler: Callable):
        self._handlers[event_type] = handler
        return self

    def start(self):
        self._consumer = Consumer({
            "bootstrap.servers": settings.redpanda_brokers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": False,  # Manual commit!
            "max.poll.interval.ms": 300000,
            "session.timeout.ms": 30000,
        })
        self._consumer.subscribe(self.topics)
        self._running = True
        logger.info("Event consumer started", group_id=self.group_id, topics=self.topics)

    def stop(self):
        self._running = False
        if self._consumer:
            try:
                self._consumer.commit(asynchronous=False)
            except Exception:
                pass
            self._consumer.close()
            self._consumer = None
        logger.info("Event consumer stopped", group_id=self.group_id)

    def poll(self, timeout: float = 1.0) -> Optional[CanonicalEvent]:
        if not self._consumer:
            return None

        msg = self._consumer.poll(timeout=timeout)
        if msg is None:
            return None

        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                return None
            logger.error("Consumer error", error=str(msg.error()))
            return None

        try:
            event = CanonicalEvent.from_json(msg.value().decode("utf-8"))

            # Idempotency check
            if event.event_id in self._processed_ids:
                logger.debug("Duplicate event skipped", event_id=event.event_id)
                self._consumer.commit(asynchronous=False)
                return None

            return event
        except Exception as e:
            logger.error("Failed to deserialize event", error=str(e))
            self._consumer.commit(asynchronous=False)
            return None

    async def consume_loop(self, poll_timeout: float = 0.1):
        self.start()
        logger.info("Starting consume loop", group_id=self.group_id)

        try:
            while self._running:
                event = self.poll(timeout=poll_timeout)
                if event is None:
                    await asyncio.sleep(0.01)
                    continue

                handler = self._handlers.get(event.event_type)
                if handler:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)

                        # Mark as processed (idempotency)
                        self._processed_ids.add(event.event_id)

                        # Limit memory
                        if len(self._processed_ids) > 10000:
                            self._processed_ids = set(list(self._processed_ids)[-5000:])

                        # Commit after successful processing
                        self._consumer.commit(asynchronous=False)

                    except Exception as e:
                        logger.error("Handler error", event_type=event.event_type,
                                   event_id=event.event_id, error=str(e))
                        # Don't commit on error — message will be reprocessed
                else:
                    # No handler, commit and skip
                    self._consumer.commit(asynchronous=False)

        except Exception as e:
            logger.error("Consume loop error", error=str(e))
        finally:
            self.stop()


# =====================================================
# Topic Management
# =====================================================

def ensure_topics():
    try:
        admin = AdminClient({"bootstrap.servers": settings.redpanda_brokers})
        existing = admin.list_topics(timeout=10).topics
        new_topics = []

        for topic in TOPICS:
            if topic not in existing:
                new_topics.append(NewTopic(topic, num_partitions=4, replication_factor=1))

        if new_topics:
            futures = admin.create_topics(new_topics)
            for topic, future in futures.items():
                try:
                    future.result()
                    logger.info("Topic created", topic=topic)
                except Exception as e:
                    logger.warning("Topic creation failed", topic=topic, error=str(e))
        else:
            logger.info("All topics already exist")
    except Exception as e:
        logger.warning("Topic management skipped (Redpanda not available)", error=str(e))
