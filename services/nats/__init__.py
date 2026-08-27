"""
ALPHA BIST — NATS Entegrasyonu v1.0

Redis Pub/Sub'a alternatif: daha hızlı, daha dayanıklı.
10M+ msg/s throughput, JetStream ile kalıcılık.

Kullanım:
    from services.nats.client import NatsClient

    async with NatsClient() as nc:
        await nc.publish("market.ticks", data)
        async for msg in nc.subscribe("market.ticks"):
            print(msg)
"""
