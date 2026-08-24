"""
ALPHA BIST — NATS Client v1.0

Redis Pub/Sub'a alternatif: daha hızlı, daha dayanıklı.
10M+ msg/s throughput, JetStream ile kalıcılık.

Kullanım:
    from services.nats.client import NatsClient
    
    async with NatsClient() as nc:
        await nc.publish("market.ticks", data)
        async for msg in nc.subscribe("market.ticks"):
            print(msg)
"""

import asyncio
import json
from typing import Optional, Callable, Dict, Any, AsyncIterator
import structlog

try:
    import nats
    from nats.aio.client import Client as NATS
    HAS_NATS = True
except ImportError:
    HAS_NATS = False

logger = structlog.get_logger()


class NatsClient:
    """NATS istemcisi — Redis Pub/Sub'a alternatif."""

    def __init__(self, servers: str = "nats://localhost:4222"):
        self.servers = servers
        self._nc: Optional[NATS] = None
        self._subscriptions: Dict[str, Any] = {}

    async def connect(self):
        """NATS'a bağlan."""
        if not HAS_NATS:
            logger.warning("nats-py not installed, falling back to Redis")
            return False

        try:
            self._nc = await nats.connect(self.servers)
            logger.info("NATS connected", servers=self.servers)
            return True
        except Exception as e:
            logger.warning("NATS connection failed", error=str(e))
            return False

    async def close(self):
        """Bağlantıyı kapat."""
        if self._nc:
            await self._nc.close()
            self._nc = None

    async def publish(self, subject: str, data: Any):
        """Veri yayınla."""
        if not self._nc:
            # Fallback: Redis Pub/Sub
            await self._publish_redis(subject, data)
            return

        try:
            if isinstance(data, dict):
                payload = json.dumps(data).encode()
            elif isinstance(data, bytes):
                payload = data
            else:
                payload = str(data).encode()

            await self._nc.publish(subject, payload)
        except Exception as e:
            logger.error("NATS publish failed", subject=subject, error=str(e))

    async def subscribe(self, subject: str) -> AsyncIterator[Dict[str, Any]]:
        """Konuya abone ol."""
        if not self._nc:
            async for msg in self._subscribe_redis(subject):
                yield msg
            return

        try:
            sub = await self._nc.subscribe(subject)
            self._subscriptions[subject] = sub

            async for msg in sub.messages:
                try:
                    data = json.loads(msg.data.decode())
                    yield data
                except json.JSONDecodeError:
                    yield {"raw": msg.data.decode()}
        except Exception as e:
            logger.error("NATS subscribe failed", subject=subject, error=str(e))

    async def request(self, subject: str, data: Any, timeout: float = 5.0) -> Dict[str, Any]:
        """İstek-yanıt (request-reply pattern)."""
        if not self._nc:
            return {}

        try:
            if isinstance(data, dict):
                payload = json.dumps(data).encode()
            else:
                payload = str(data).encode()

            response = await self._nc.request(subject, payload, timeout=timeout)
            return json.loads(response.data.decode())
        except Exception as e:
            logger.error("NATS request failed", subject=subject, error=str(e))
            return {}

    async def _publish_redis(self, subject: str, data: Any):
        """Redis Pub/Sub fallback."""
        try:
            import redis.asyncio as aioredis
            from ..core.config import settings
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            await r.publish(subject, json.dumps(data, default=str))
            await r.close()
        except Exception as e:
            logger.error("Redis publish fallback failed", error=str(e))

    async def _subscribe_redis(self, subject: str) -> AsyncIterator[Dict[str, Any]]:
        """Redis Pub/Sub fallback."""
        try:
            import redis.asyncio as aioredis
            from ..core.config import settings
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(subject)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError:
                        yield {"raw": message["data"]}
        except Exception as e:
            logger.error("Redis subscribe fallback failed", error=str(e))

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()


# =====================================================
# Konu (Subject) Tanımları
# =====================================================

class Subjects:
    """NATS konu tanımları — organize mesajlaşma."""
    TICKS = "market.ticks"
    OHLCV = "market.ohlcv"
    SIGNALS = "signals.new"
    PORTFOLIO = "portfolio.update"
    RISK = "risk.alerts"
    EVENTS = "events.market"
    ALERTS = "alerts.all"
    REGIME = "market.regime"
    LEARNING = "learning.update"
