"""ALPHA BIST - Event Bus (Redpanda/Kafka)"""

import json
import asyncio
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum
import structlog

from confluent_kafka import Producer, Consumer, KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from .config import settings

logger = structlog.get_logger()


# =====================================================
# Event Schema
# =====================================================

class EventType(str, Enum):
    # Market data
    MARKET_TICK = "market.tick"
    MARKET_TRADE = "market.trade"
    MARKET_QUOTE = "market.quote"
    MARKET_ORDERBOOK = "market.orderbook"

    # Events
    NEWS_RAW = "news.raw"
    NEWS_EVENT = "news.event"
    KAP_EVENT = "kap.event"
    MACRO_EVENT = "macro.event"
    SOCIAL_EVENT = "social.event"

    # State updates
    FEATURE_UPDATED = "feature.updated"
    STATE_UPDATED = "state.updated"
    MARKET_STATE_CHANGED = "market_state.changed"
    WORLD_STATE_CHANGED = "world_state.changed"

    # Signals & Decisions
    SIGNAL_GENERATED = "signal.generated"
    ANOMALY_DETECTED = "anomaly.detected"
    REGIME_CHANGED = "regime.changed"

    # Simulation
    SIMULATION_REQUESTED = "simulation.requested"
    SIMULATION_COMPLETED = "simulation.completed"

    # Risk
    RISK_CHANGED = "risk.changed"
    RISK_ALERT = "risk.alert"
    KILL_SWITCH_TRIGGERED = "kill_switch.triggered"

    # Portfolio
    DECISION_CREATED = "decision.created"
    ORDER_PLACED = "order.placed"
    ORDER_FILLED = "order.filled"

    # Learning
    PREDICTION_CREATED = "prediction.created"
    OUTCOME_CREATED = "outcome.created"


@dataclass
class AlphaEvent:
    """Base event structure for the ALPHA event bus."""
    event_type: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "system"
    event_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v1"

    def __post_init__(self):
        if not self.event_id:
            import uuid
            self.event_id = str(uuid.uuid4())

    def to_json(self) -> str:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, json_str: str) -> "AlphaEvent":
        d = json.loads(json_str)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


# =====================================================
# Topic Definitions
# =====================================================

TOPICS = [
    "market.tick",
    "market.trade",
    "market.quote",
    "market.orderbook",
    "news.raw",
    "news.event",
    "kap.event",
    "macro.event",
    "social.event",
    "feature.updated",
    "state.updated",
    "market_state.changed",
    "world_state.changed",
    "signal.generated",
    "anomaly.detected",
    "regime.changed",
    "simulation.requested",
    "simulation.completed",
    "risk.changed",
    "risk.alert",
    "kill_switch.triggered",
    "decision.created",
    "order.placed",
    "order.filled",
    "prediction.created",
    "outcome.created",
]


# =====================================================
# Producer
# =====================================================

_producer: Optional[Producer] = None


def get_producer() -> Producer:
    """Get or create Kafka/Redpanda producer."""
    global _producer
    if _producer is None:
        _producer = Producer({
            "bootstrap.servers": settings.redpanda_brokers,
            "client.id": "alpha-producer",
            "acks": "all",
            "retries": 3,
            "linger.ms": 5,
            "batch.size": 16384,
        })
        logger.info("Event producer created", brokers=settings.redpanda_brokers)
    return _producer


def publish_event(event: AlphaEvent, key: Optional[str] = None):
    """Publish an event to the event bus."""
    producer = get_producer()
    topic = event.event_type

    def delivery_callback(err, msg):
        if err:
            logger.error("Event delivery failed", error=str(err), topic=topic)
        else:
            logger.debug("Event delivered", topic=topic, partition=msg.partition(), offset=msg.offset())

    try:
        producer.produce(
            topic=topic,
            key=key or event.event_id,
            value=event.to_json().encode("utf-8"),
            callback=delivery_callback,
        )
        producer.poll(0)
    except Exception as e:
        logger.error("Failed to publish event", error=str(e), event_type=event.event_type)
        raise


def flush_producer():
    """Flush all pending events."""
    global _producer
    if _producer:
        _producer.flush(timeout=10)


# =====================================================
# Consumer
# =====================================================

class EventConsumer:
    """Async event consumer for the ALPHA event bus."""

    def __init__(self, group_id: str, topics: List[str], auto_offset_reset: str = "latest"):
        self.group_id = group_id
        self.topics = topics
        self.auto_offset_reset = auto_offset_reset
        self._consumer: Optional[Consumer] = None
        self._handlers: Dict[str, Callable] = {}
        self._running = False

    def on(self, event_type: str, handler: Callable):
        """Register an event handler."""
        self._handlers[event_type] = handler
        return self

    def start(self):
        """Start consuming events."""
        self._consumer = Consumer({
            "bootstrap.servers": settings.redpanda_brokers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 1000,
        })
        self._consumer.subscribe(self.topics)
        self._running = True
        logger.info("Event consumer started", group_id=self.group_id, topics=self.topics)

    def stop(self):
        """Stop consuming events."""
        self._running = False
        if self._consumer:
            self._consumer.close()
            self._consumer = None
        logger.info("Event consumer stopped", group_id=self.group_id)

    def poll(self, timeout: float = 1.0) -> Optional[AlphaEvent]:
        """Poll for a single event."""
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
            event = AlphaEvent.from_json(msg.value().decode("utf-8"))
            return event
        except Exception as e:
            logger.error("Failed to deserialize event", error=str(e))
            return None

    async def consume_loop(self, poll_timeout: float = 0.1):
        """Async consume loop that dispatches events to handlers."""
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
                    except Exception as e:
                        logger.error(
                            "Handler error",
                            event_type=event.event_type,
                            error=str(e),
                        )
                else:
                    logger.debug("No handler for event", event_type=event.event_type)

        except Exception as e:
            logger.error("Consume loop error", error=str(e))
        finally:
            self.stop()


# =====================================================
# Topic Management
# =====================================================

def ensure_topics():
    """Create topics if they don't exist."""
    admin = AdminClient({"bootstrap.servers": settings.redpanda_brokers})

    existing = admin.list_topics(timeout=10).topics
    new_topics = []

    for topic in TOPICS:
        if topic not in existing:
            new_topics.append(NewTopic(
                topic,
                num_partitions=4,
                replication_factor=1,
            ))

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
