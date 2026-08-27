"""ALPHA BIST — QuestDB Tick Data Consumer

NATS event bus'tan MARKET_TICK olaylarını dinler ve QuestDB'ye yazar.
Yüksek frekanslı tick verisi için optimize edilmiş.

Kullanım:
    from services.ingestion.questdb_consumer import questdb_tick_consumer

    await questdb_tick_consumer.start()
    # veya
    await questdb_tick_consumer.stop()
"""

import asyncio
from datetime import UTC, datetime

import structlog

from ..core.config import settings
from ..core.event_bus import EventType, subscribe
from ..core.questdb_client import questdb_client

logger = structlog.get_logger()


class QuestDBTickConsumer:
    """QuestDB tick veri tüketici — NATS'tan QuestDB'ye tick akışı."""

    def __init__(self):
        self._running = False
        self._buffer: list[dict] = []
        self._buffer_size = 100  # Toplu yazma için buffer boyutu
        self._flush_interval = 5.0  # Saniye
        self._write_count = 0
        self._error_count = 0
        self._last_flush = datetime.now(UTC)

    async def start(self):
        """Consumer'ı başlat."""
        self._running = True

        # QuestDB bağlantısı
        connected = await questdb_client.connect()
        if not connected:
            logger.warning("QuestDB connection failed, will retry on first tick")

        # Tabloları oluştur
        await questdb_client.ensure_tables()

        # NATS'tan tick olaylarını dinle
        subscribe(EventType.MARKET_TICK, self._on_tick)

        # Buffer flush döngüsü
        asyncio.create_task(self._flush_loop())

        logger.info(
            "QuestDB tick consumer started",
            buffer_size=self._buffer_size,
            flush_interval=self._flush_interval,
        )

    async def stop(self):
        """Consumer'ı durdur."""
        self._running = False

        # Buffer'ı temizle
        if self._buffer:
            await self._flush_buffer()

        questdb_client.close()
        logger.info(
            "QuestDB tick consumer stopped",
            total_writes=self._write_count,
            total_errors=self._error_count,
        )

    async def _on_tick(self, event):
        """MARKET_TICK olayını işle."""
        try:
            data = event.data

            # Index verilerini atla (sadece hisse tick'leri)
            if data.get("is_index"):
                return

            ticker = data.get("ticker")
            price = data.get("price")
            volume = data.get("volume", 0)
            bid = data.get("bid", 0.0)
            ask = data.get("ask", 0.0)

            if not ticker or not price:
                return

            # Buffer'a ekle
            self._buffer.append(
                {
                    "ticker": ticker,
                    "price": float(price),
                    "volume": int(volume) if volume else 0,
                    "bid": float(bid) if bid else 0.0,
                    "ask": float(ask) if ask else 0.0,
                    "timestamp": datetime.now(UTC),
                }
            )

            # Buffer dolmuşsa flush et
            if len(self._buffer) >= self._buffer_size:
                await self._flush_buffer()

        except Exception as e:
            logger.warning("QuestDB tick processing error", error=str(e))
            self._error_count += 1

    async def _flush_loop(self):
        """Periyodik buffer flush."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)

                if self._buffer:
                    await self._flush_buffer()

            except Exception as e:
                logger.warning("QuestDB flush loop error", error=str(e))
                await asyncio.sleep(1)

    async def _flush_buffer(self):
        """Buffer'ı QuestDB'ye yaz."""
        if not self._buffer:
            return

        ticks_to_write = self._buffer.copy()
        self._buffer.clear()

        try:
            # QuestDB bağlantısı yoksa yeniden bağlan
            if not questdb_client._connected:
                connected = await questdb_client.connect()
                if not connected:
                    logger.warning("QuestDB reconnect failed, dropping ticks", count=len(ticks_to_write))
                    self._error_count += 1
                    return

            # Toplu yazma
            success = questdb_client.insert_ticks_batch(ticks_to_write)

            if success:
                self._write_count += len(ticks_to_write)
                logger.debug(
                    "QuestDB ticks written",
                    count=len(ticks_to_write),
                    total=self._write_count,
                )
            else:
                self._error_count += 1
                logger.warning("QuestDB batch write failed", count=len(ticks_to_write))

        except Exception as e:
            self._error_count += 1
            logger.error("QuestDB flush error", error=str(e), count=len(ticks_to_write))

        self._last_flush = datetime.now(UTC)

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "running": self._running,
            "buffer_size": len(self._buffer),
            "total_writes": self._write_count,
            "total_errors": self._error_count,
            "last_flush": self._last_flush.isoformat(),
            "connected": questdb_client._connected,
        }


# Singleton
questdb_tick_consumer = QuestDBTickConsumer()
