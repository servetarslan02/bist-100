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
import orjson
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
        self._js = None  # JetStream context
        self._subscriptions: Dict[str, Any] = {}
        self._connected = False

    async def connect(self, servers: str = None) -> bool:
        """NATS'a bağlan (reconnect + JetStream handling ile)."""
        if not HAS_NATS:
            logger.debug("nats-py not installed")
            return False

        if self._connected and self._nc:
            return True

        try:
            url = servers or os.environ.get("NATS_URL", "nats://localhost:4222")

            # Reconnect handling: bağlantı koparsa otomatik yeniden bağlan
            async def _disconnected_cb():
                logger.warning("NATS disconnected, will reconnect")
                self._connected = False

            async def _reconnected_cb():
                logger.info("NATS reconnected")
                self._connected = True

            async def _error_cb(e):
                logger.warning("NATS error", error=str(e))

            self._nc = await nats.connect(
                url,
                disconnected_cb=_disconnected_cb,
                reconnected_cb=_reconnected_cb,
                error_cb=_error_cb,
                max_reconnect_attempts=10,
                reconnect_time_wait=2,
            )
            self._connected = True

            # JetStream context — persistent messaging
            try:
                self._js = self._nc.jetstream()
                logger.info("NATS JetStream enabled")
            except Exception as e:
                logger.warning("JetStream not available", error=str(e))
                self._js = None

            logger.info("NATS connected", url=url, jetstream=self._js is not None)
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
                payload = orjson.dumps(data, default=str).decode()
            elif isinstance(data, bytes):
                payload = data
            elif isinstance(data, str):
                payload = data.encode()
            else:
                payload = orjson.dumps(data, default=str).decode()

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
                        data = orjson.loads(msg.data.decode())
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
                        data = orjson.loads(msg.data.decode())
                        yield data
                    except orjson.JSONDecodeError:
                        yield {"raw": msg.data.decode()}
        except Exception as e:
            logger.debug("NATS subscribe failed", subject=subject, error=str(e))

    async def publish_durable(self, subject: str, data: Any, stream: str = None) -> bool:
        """JetStream ile kalıcı mesaj yayınla.

        At-least-once delivery garantisi. Mesaj disk'e yazılır.
        Normal publish'den farkı: mesaj kaybolmaz, consumer group desteği.
        """
        if not self.is_connected or not self._js:
            # Fallback: normal publish
            return await self.publish(subject, data)

        try:
            if isinstance(data, dict):
                payload = orjson.dumps(data, default=str).decode()
            elif isinstance(data, bytes):
                payload = data
            elif isinstance(data, str):
                payload = data.encode()
            else:
                payload = orjson.dumps(data, default=str).decode()

            # Stream adı belirtilmemişse subject'ten türet
            if stream is None:
                stream = subject.replace(".", "_").upper()

            # Stream yoksa otomatik oluştur
            try:
                await self._js.add_stream(name=stream, subjects=[subject])
            except Exception:
                pass  # Zaten varsa devam et

            ack = await self._js.publish(subject, payload)
            logger.debug("JetStream published", subject=subject, stream=stream,
                        seq=ack.seq)
            return True
        except Exception as e:
            logger.debug("JetStream publish failed, falling back", error=str(e))
            return await self.publish(subject, data)

    async def subscribe_durable(self, subject: str, durable_name: str,
                                handler: Callable = None,
                                stream: str = None) -> AsyncIterator[Dict[str, Any]]:
        """JetStream ile kalıcı abone ol.

        Durable consumer: mesajlar kaybolmaz, restart sonrası kaldığı yerden devam.
        At-least-once: mesaj en az bir kez işlenir.
        """
        if not self.is_connected or not self._js:
            # Fallback: normal subscribe
            async for msg in self.subscribe(subject, handler=handler):
                yield msg
            return

        try:
            if stream is None:
                stream = subject.replace(".", "_").upper()

            # Stream yoksa otomatik oluştur
            try:
                await self._js.add_stream(name=stream, subjects=[subject])
            except Exception:
                pass

            if handler:
                # Callback mode
                async def _msg_handler(msg):
                    try:
                        data = orjson.loads(msg.data.decode())
                        if asyncio.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                        await msg.ack()
                    except Exception as e:
                        logger.error("JetStream handler error", subject=subject, error=str(e))
                        await msg.nak()

                psub = await self._js.subscribe(subject, durable=durable_name,
                                                cb=_msg_handler)
                self._subscriptions[subject] = psub
                logger.info("JetStream subscribed (callback)", subject=subject,
                           durable=durable_name)
            else:
                # Iterator mode
                psub = await self._js.subscribe(subject, durable=durable_name)
                self._subscriptions[subject] = psub

                async for msg in psub.messages:
                    try:
                        data = orjson.loads(msg.data.decode())
                        yield data
                        await msg.ack()
                    except orjson.JSONDecodeError:
                        yield {"raw": msg.data.decode()}
                        await msg.ack()
                    except Exception as e:
                        logger.error("JetStream iterator error", error=str(e))
                        await msg.nak()
        except Exception as e:
            logger.debug("JetStream subscribe failed", subject=subject, error=str(e))

    async def request(self, subject: str, data: Any, timeout: float = 5.0) -> Dict[str, Any]:
        """İstek-yanıt (request-reply pattern)."""
        if not self.is_connected:
            if not await self.connect():
                return {}

        try:
            if isinstance(data, dict):
                payload = orjson.dumps(data, default=str).decode()
            else:
                payload = str(data).encode()

            response = await self._nc.request(subject, payload, timeout=timeout)
            return orjson.loads(response.data.decode())
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
    """NATS konu tanımları — organize mesajlaşma.

    JetStream stream'leri: kalıcı mesajlaşma için.
    Normal publish: anlık (fire-and-forget)
    Durable publish: disk'e yazılır, restart sonrası devam eder.
    """
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

    # JetStream stream adları (kalıcı mesajlaşma)
    STREAM_TICKS = "ALPHA_TICKS"
    STREAM_SIGNALS = "ALPHA_SIGNALS"
    STREAM_EVENTS = "ALPHA_EVENTS"
    STREAM_ORDERS = "ALPHA_ORDERS"


# =====================================================
# Singleton
# =====================================================

nats_client = NatsClient()
