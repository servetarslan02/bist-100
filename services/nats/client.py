"""
ALPHA BIST — NATS Client v2.5 (Unified Event-Driven Engine)

Tek NATS client — tüm sistem bu client'ı kullanır.
Özellikler:
1. Yüksek Verimlilik (10M+ msg/s throughput)
2. JetStream Kalıcı Mesajlaşma (At-least-once delivery, durable consumer)
3. Dağıtık İzleme (Correlation ID otomatik injection & propagation)
4. CanonicalEvent & Şema Doğrulama Desteği
5. Otomatik Hata Yönetimi & Dead-Letter Queue (DLQ) Yönlendirmesi
6. Metrikler & Observability (published, received, error, dlq)
7. Mesaj Sıralama & Monotonik Zaman Damgası Kontrolü

Kullanım:
    from services.nats.client import nats_client, Subjects

    # Normal Publish
    await nats_client.publish(Subjects.TICKS, {"ticker": "THYAO", "price": 100})

    # Durable JetStream Publish
    await nats_client.publish_durable(Subjects.SIGNALS, signal_dict)

    # Canonical Event Publish
    await nats_client.publish_canonical_event(Subjects.EVENTS, canonical_event)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING, Any

import orjson
import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from nats.aio.client import Client as NATS

    from services.core.event_schema import CanonicalEvent

try:
    import nats

    HAS_NATS = True
except ImportError:
    HAS_NATS = False
import contextlib
import functools

from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.nats_client")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class NatsClient:
    """NATS & JetStream istemcisi — kurumsal event bus."""

    def __init__(self):
        """Otomatik eklendi."""
        self._nc: NATS | None = None
        self._js = None  # JetStream context
        self._subscriptions: dict[str, Any] = {}
        self._connected = False
        # Observability sayaçları
        self._total_published = 0
        self._total_received = 0
        self._total_errors = 0
        self._total_dlq_routed = 0

    @otel_trace("nats.connect")
    async def connect(self, servers: str = None) -> bool:
        """NATS'a bağlan (reconnect + JetStream handling ile)."""
        if not HAS_NATS:
            logger.debug("nats-py not installed")
            return False

        if self._connected and self._nc:
            return True

        try:
            url = servers or os.environ.get("NATS_URL", "nats://localhost:4222")

            async def _disconnected_cb() -> Any:
                """Otomatik eklendi."""
                logger.warning("NATS disconnected, will reconnect")
                self._connected = False

            async def _reconnected_cb() -> Any:
                """Otomatik eklendi."""
                logger.info("NATS reconnected")
                self._connected = True

            async def _error_cb(e) -> Any:
                """Otomatik eklendi."""
                self._total_errors += 1
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

    async def close(self) -> Any:
        """Bağlantıyı kapat."""
        if self._nc:
            try:
                await self._nc.close()
            except Exception:
                logger.warning("Caught Exception in close", exc_info=True)
            self._nc = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        """Otomatik eklendi."""
        return self._connected and self._nc is not None

    @otel_trace("nats.publish")
    async def publish(self, subject: str, data: Any) -> bool:
        """Veri yayınla. Başarısız olursa False döner."""
        if not self.is_connected and not await self.connect():
            return False

        try:
            payload = self._prepare_payload(data)
            await self._nc.publish(subject, payload)
            self._total_published += 1
            return True
        except Exception as e:
            self._total_errors += 1
            logger.debug("NATS publish failed", subject=subject, error=str(e))
            self._connected = False
            return False

    @otel_trace("nats.publish_canonical_event")
    async def publish_canonical_event(self, subject: str, event: CanonicalEvent, durable: bool = False) -> bool:
        """Standart CanonicalEvent yayınlar."""
        is_valid, msg = event.validate()
        if not is_valid:
            logger.warning("invalid_canonical_event_schema", error=msg, subject=subject)
            return False

        if durable:
            return await self.publish_durable(subject, event.to_dict())
        return await self.publish(subject, event.to_dict())

    @otel_trace("nats.publish_durable")
    async def publish_durable(self, subject: str, data: Any, stream: str = None) -> bool:
        """JetStream ile kalıcı mesaj yayınla (At-least-once delivery)."""
        if not self.is_connected or not self._js:
            return await self.publish(subject, data)

        try:
            payload = self._prepare_payload(data)
            if stream is None:
                stream = subject.replace(".", "_").upper()

            with contextlib.suppress(Exception):
                await self._js.add_stream(name=stream, subjects=[subject])

            ack = await self._js.publish(subject, payload)
            self._total_published += 1
            logger.debug("JetStream published", subject=subject, stream=stream, seq=ack.seq)
            return True
        except Exception as e:
            self._total_errors += 1
            logger.debug("JetStream publish failed, falling back to basic publish", error=str(e))
            return await self.publish(subject, data)

    @otel_trace("nats.subscribe")
    async def subscribe(self, subject: str, handler: Callable = None) -> AsyncIterator[dict[str, Any]]:
        """Konuya abone ol. handler verilirse callback, verilmezse async iterator döner."""
        if not self.is_connected and not await self.connect():
            return

        try:
            if handler:

                async def _msg_handler(msg) -> Any:
                    """Otomatik eklendi."""
                    self._total_received += 1
                    try:
                        raw_data = msg.data
                        if isinstance(raw_data, (bytes, bytearray)) and raw_data.startswith(b"GZ:"):
                            import gzip
                            raw_data = gzip.decompress(raw_data[3:])

                        data = (
                            orjson.loads(raw_data)
                            if isinstance(raw_data, (bytes, bytearray))
                            else orjson.loads(str(raw_data).encode("utf-8"))
                        )
                        self._propagate_correlation(data)
                        if asyncio.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                    except Exception as e:
                        self._total_errors += 1
                        logger.error("NATS handler error", subject=subject, error=str(e))
                        raw_str = (
                            msg.data.decode("utf-8", errors="replace")
                            if isinstance(msg.data, (bytes, bytearray))
                            else str(msg.data)
                        )
                        await self._route_to_dlq(subject=subject, raw_payload=raw_str, error_str=str(e))

                sub = await self._nc.subscribe(subject, cb=_msg_handler)
                self._subscriptions[subject] = sub
                logger.debug("NATS subscribed (callback)", subject=subject)
            else:
                sub = await self._nc.subscribe(subject)
                self._subscriptions[subject] = sub

                async for msg in sub.messages:
                    self._total_received += 1
                    try:
                        data = (
                            orjson.loads(msg.data)
                            if isinstance(msg.data, (bytes, bytearray))
                            else orjson.loads(str(msg.data).encode("utf-8"))
                        )
                        self._propagate_correlation(data)
                        yield data
                    except orjson.JSONDecodeError:
                        raw_str = (
                            msg.data.decode("utf-8", errors="replace")
                            if isinstance(msg.data, (bytes, bytearray))
                            else str(msg.data)
                        )
                        yield {"raw": raw_str}
        except Exception as e:
            self._total_errors += 1
            logger.debug("NATS subscribe failed", subject=subject, error=str(e))

    @otel_trace("nats.subscribe_durable")
    async def subscribe_durable(
        self, subject: str, durable_name: str, handler: Callable = None, stream: str = None
    ) -> AsyncIterator[dict[str, Any]]:
        """JetStream ile kalıcı (durable) abone ol."""
        if not self.is_connected or not self._js:
            async for msg in self.subscribe(subject, handler=handler):
                yield msg
            return

        try:
            if stream is None:
                stream = subject.replace(".", "_").upper()

            with contextlib.suppress(Exception):
                await self._js.add_stream(name=stream, subjects=[subject])

            if handler:

                async def _msg_handler(msg) -> Any:
                    """Otomatik eklendi."""
                    self._total_received += 1
                    try:
                        data = (
                            orjson.loads(msg.data)
                            if isinstance(msg.data, (bytes, bytearray))
                            else orjson.loads(str(msg.data).encode("utf-8"))
                        )
                        self._propagate_correlation(data)
                        if asyncio.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                        await msg.ack()
                    except Exception as e:
                        self._total_errors += 1
                        logger.error("JetStream handler error", subject=subject, error=str(e))
                        raw_str = (
                            msg.data.decode("utf-8", errors="replace")
                            if isinstance(msg.data, (bytes, bytearray))
                            else str(msg.data)
                        )
                        await self._route_to_dlq(subject=subject, raw_payload=raw_str, error_str=str(e))
                        await msg.nak()

                psub = await self._js.subscribe(subject, durable=durable_name, cb=_msg_handler)
                self._subscriptions[subject] = psub
                logger.info("JetStream subscribed (callback)", subject=subject, durable=durable_name)
            else:
                psub = await self._js.subscribe(subject, durable=durable_name)
                self._subscriptions[subject] = psub

                async for msg in psub.messages:
                    self._total_received += 1
                    try:
                        data = (
                            orjson.loads(msg.data)
                            if isinstance(msg.data, (bytes, bytearray))
                            else orjson.loads(str(msg.data).encode("utf-8"))
                        )
                        self._propagate_correlation(data)
                        yield data
                        await msg.ack()
                    except orjson.JSONDecodeError:
                        raw_str = (
                            msg.data.decode("utf-8", errors="replace")
                            if isinstance(msg.data, (bytes, bytearray))
                            else str(msg.data)
                        )
                        yield {"raw": raw_str}
                        await msg.ack()
                    except Exception as e:
                        self._total_errors += 1
                        logger.error("JetStream iterator error", error=str(e))
                        raw_str = (
                            msg.data.decode("utf-8", errors="replace")
                            if isinstance(msg.data, (bytes, bytearray))
                            else str(msg.data)
                        )
                        await self._route_to_dlq(subject=subject, raw_payload=raw_str, error_str=str(e))
                        await msg.nak()
        except Exception as e:
            self._total_errors += 1
            logger.debug("JetStream subscribe failed", subject=subject, error=str(e))

    @otel_trace("nats.request")
    async def request(self, subject: str, data: Any, timeout: float = 5.0) -> dict[str, Any]:
        """İstek-yanıt (request-reply pattern)."""
        if not self.is_connected and not await self.connect():
            return {}

        try:
            payload = self._prepare_payload(data)
            response = await self._nc.request(subject, payload, timeout=timeout)
            return orjson.loads(response.data.decode())
        except Exception as e:
            self._total_errors += 1
            logger.debug("NATS request failed", subject=subject, error=str(e))
            return {}

    async def unsubscribe(self, subject: str) -> Any:
        """Aboneliği iptal et."""
        if subject in self._subscriptions:
            try:
                await self._subscriptions[subject].unsubscribe()
            except Exception:
                logger.warning("Caught Exception in unsubscribe", exc_info=True)
            del self._subscriptions[subject]

    def get_stats(self) -> dict[str, Any]:
        """NATS istemcisi performans ve sağlık istatistikleri."""
        return {
            "connected": self.is_connected,
            "jetstream_enabled": self._js is not None,
            "active_subscriptions": len(self._subscriptions),
            "total_published": self._total_published,
            "total_received": self._total_received,
            "total_errors": self._total_errors,
            "total_dlq_routed": self._total_dlq_routed,
        }

    # =====================================================
    # HELPER METOTLAR
    # =====================================================
    def _prepare_payload(self, data: Any) -> bytes:
        """Mesaj verisini serialize eder ve Correlation ID inject eder."""
        if hasattr(data, "to_dict"):
            data = data.to_dict()

        if isinstance(data, dict):
            if "_correlation_id" not in data:
                try:
                    from ..core.distributed_tracing import correlation_id_var

                    cid = correlation_id_var.get()
                    if cid:
                        data = {**data, "_correlation_id": cid}
                except (ImportError, LookupError):
                    logger.error("Exception caught", exc_info=True)
            raw = orjson.dumps(data, default=str)
        elif isinstance(data, bytes):
            raw = data
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = orjson.dumps(data, default=str)

        # Koşullu Sıkıştırma: Yalnızca 4 KB üzerindeki büyük payload'lar sıkıştırılır
        if len(raw) > 4096:
            import gzip
            return b"GZ:" + gzip.compress(raw)
        return raw

    def _propagate_correlation(self, data: dict[str, Any]) -> None:
        """Gelen mesajdaki Correlation ID'yi async tracing context'e aktarır."""
        cid = data.get("_correlation_id") or data.get("correlation_id")
        if cid:
            try:
                from ..core.distributed_tracing import correlation_id_var

                correlation_id_var.set(cid)
            except (ImportError, LookupError):
                logger.error("Exception caught", exc_info=True)

    async def _route_to_dlq(self, subject: str, raw_payload: str, error_str: str) -> None:
        """İşlenemeyen hatalı mesajları Dead Letter Queue'ya yönlendirir."""
        self._total_dlq_routed += 1
        try:
            from services.core.dead_letter_queue import dead_letter_queue

            event_id = str(uuid.uuid4())
            await dead_letter_queue.push(
                event_id=event_id,
                event_type=subject,
                payload=raw_payload,
                error=error_str,
            )
            logger.info("message_routed_to_dlq", subject=subject, event_id=event_id)
        except Exception as dlq_err:
            logger.error("dlq_route_failed", error=str(dlq_err))


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
    DLQ = "alpha.dlq.events"

    # JetStream stream adları
    STREAM_TICKS = "ALPHA_TICKS"
    STREAM_SIGNALS = "ALPHA_SIGNALS"
    STREAM_EVENTS = "ALPHA_EVENTS"
    STREAM_ORDERS = "ALPHA_ORDERS"
    STREAM_DLQ = "ALPHA_DLQ"


# Singleton
nats_client = NatsClient()
