"""
ALPHA BIST — NATS Client v2.0 (Unified)

Tek NATS client — tüm sistem bu client'ı kullanır.
Redis Pub/Sub'a alternatif: daha hızlı, daha dayanıklı.
10M+ msg/s throughput, JetStream ile kalıcılık.

Kullanım:
    from services.nats.client import nats_client, Subjects

    # Publish
    await nats_client.publish(Subjects.TICKS, {"ticker": "THYAO", "price": 100})

    # Subscribe
    async for msg in nats_client.subscribe(Subjects.TICKS):
        print(msg)
"""

import asyncio
import json
import os
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
    """NATS istemcisi — tek instance, tüm sistem kullanır."""

    def __init__(self):
        self._nc: Optional[NATS] = None
        self._subscriptions: Dict[str, Any] = {}
        self._connected = False

    async def connect(self, servers: str = None) -> bool:
        """NATS'a bağlan."""
        if not HAS_NATS:
            logger.debug("nats-py not installed")
            return False

        if self._connected and self._nc:
            return True

        try:
            url = servers or os.environ.get("NATS_URL", "nats://localhost:4222")
            self._nc = await nats.connect(url)
            self._connected = True
            logger.info("NATS connected", url=url)
            return True
        except Exception as e:
            logger.debug("NATS connection failed", error=str(e))
            self._connected = False
            return False

    async def close(self):
        """Bağlantıyı kapat."""
        if self._nc:
            try:
                await self._nc.close()
            except Exception:
                pass
            self._nc = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._nc is not None

    async def publish(self, subject: str, data: Any) -> bool:
        """Veri yayınla. Başarısız olursa False döner."""
        if not self.is_connected:
            if not await self.connect():
                return False

        try:
            if isinstance(data, dict):
                payload = json.dumps(data, default=str).encode()
            elif isinstance(data, bytes):
                payload = data
            elif isinstance(data, str):
                payload = data.encode()
            else:
                payload = json.dumps(data, default=str).encode()

            await self._nc.publish(subject, payload)
            return True
        except Exception as e:
            logger.debug("NATS publish failed", subject=subject, error=str(e))
            self._connected = False
            return False

    async def subscribe(self, subject: str, handler: Callable = None) -> AsyncIterator[Dict[str, Any]]:
        """Konuya abone ol. handler verilirse callback, verilmezse async iterator döner."""
        if not self.is_connected:
            if not await self.connect():
                return

        try:
            if handler:
                # Callback mode
                async def _msg_handler(msg):
                    try:
                        data = json.loads(msg.data.decode())
                        if asyncio.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                    except Exception as e:
                        logger.error("NATS handler error", subject=subject, error=str(e))

                sub = await self._nc.subscribe(subject, cb=_msg_handler)
                self._subscriptions[subject] = sub
                logger.debug("NATS subscribed (callback)", subject=subject)
            else:
                # Iterator mode
                sub = await self._nc.subscribe(subject)
                self._subscriptions[subject] = sub

                async for msg in sub.messages:
                    try:
                        data = json.loads(msg.data.decode())
                        yield data
                    except json.JSONDecodeError:
                        yield {"raw": msg.data.decode()}
        except Exception as e:
            logger.debug("NATS subscribe failed", subject=subject, error=str(e))

    async def request(self, subject: str, data: Any, timeout: float = 5.0) -> Dict[str, Any]:
        """İstek-yanıt (request-reply pattern)."""
        if not self.is_connected:
            if not await self.connect():
                return {}

        try:
            if isinstance(data, dict):
                payload = json.dumps(data, default=str).encode()
            else:
                payload = str(data).encode()

            response = await self._nc.request(subject, payload, timeout=timeout)
            return json.loads(response.data.decode())
        except Exception as e:
            logger.debug("NATS request failed", subject=subject, error=str(e))
            return {}

    async def unsubscribe(self, subject: str):
        """Aboneliği iptal et."""
        if subject in self._subscriptions:
            try:
                await self._subscriptions[subject].unsubscribe()
            except Exception:
                pass
            del self._subscriptions[subject]


# =====================================================
# Konu (Subject) Tanımları
# =====================================================

class Subjects:
    """NATS konu tanımları — organize mesajlaşma."""
    TICKS = "alpha.market.ticks"
    OHLCV = "alpha.market.ohlcv"
    SIGNALS = "alpha.signals.new"
    PORTFOLIO = "alpha.portfolio.update"
    RISK = "alpha.risk.alerts"
    EVENTS = "alpha.events.market"
    ALERTS = "alpha.alerts.all"
    REGIME = "alpha.market.regime"
    LEARNING = "alpha.learning.update"
    DECISIONS = "alpha.decisions.created"
    ORDERS = "alpha.orders.placed"


# =====================================================
# Singleton
# =====================================================

nats_client = NatsClient()
