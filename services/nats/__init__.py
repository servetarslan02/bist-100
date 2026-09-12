"""
ALPHA BIST — NATS Entegrasyonu v1.0
===================================
Redis Pub/Sub'a alternatif: daha hızlı, daha dayanıklı.
10M+ msg/s throughput, JetStream ile kalıcılık.

Kullanım:
    from services.nats import NatsClient, Subjects, nats_client

    async with NatsClient() as nc:
        await nc.publish(Subjects.TICKS, data)
        async for msg in nc.subscribe(Subjects.TICKS):
            print(msg)
"""

from .client import HAS_NATS, NatsClient, Subjects, nats_client, otel_trace

__all__ = [
    "HAS_NATS",
    "NatsClient",
    "Subjects",
    "nats_client",
    "otel_trace",
]
