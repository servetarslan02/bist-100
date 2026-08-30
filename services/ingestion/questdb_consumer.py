from typing import Any

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

from ..core.event_bus import EventType, event_bus
from ..core.questdb_client import questdb_client

logger = structlog.get_logger()


class QuestDBTickConsumer:
    """QuestDB tick veri tüketici — NATS'tan QuestDB'ye tick akışı."""

    def __init__(self):
        """Otomatik eklendi."""
        self._running = False
        self._buffer: list[dict] = []
        self._buffer_size = 100  # Toplu yazma için buffer boyutu
        self._flush_interval = 5.0  # Saniye
        self._write_count = 0
        self._error_count = 0
        self._retry_count = 0
        self._dropped_count = 0
        self._max_retries = 3  # Flush retry sayısı
        self._retry_buffer: list[dict] = []  # Başarısız flush'lardan kalan tick'ler
        self._max_retry_buffer_size = 1000  # Retry buffer üst sınırı
        self._last_flush = datetime.now(UTC)

    async def start(self) -> Any:
        """Consumer'ı başlat."""
        self._running = True

        # QuestDB bağlantısı
        connected = await questdb_client.connect()
        if not connected:
            logger.warning("QuestDB connection failed, will retry on first tick")

        # Tabloları oluştur
        await questdb_client.ensure_tables()

        # NATS'tan tick olaylarını dinle
        await event_bus.subscribe(EventType.MARKET_TICK, self._on_tick)

        # Buffer flush döngüsü
        self._flush_task = asyncio.create_task(self._flush_loop())

        logger.info(
            "QuestDB tick consumer started",
            buffer_size=self._buffer_size,
            flush_interval=self._flush_interval,
        )

    async def stop(self) -> Any:
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

    async def _on_tick(self, event) -> Any:
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

    async def _flush_loop(self) -> Any:
        """Periyodik buffer flush."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)

                if self._buffer:
                    await self._flush_buffer()

            except Exception as e:
                logger.warning("QuestDB flush loop error", error=str(e))
                await asyncio.sleep(1)

    async def _flush_buffer(self) -> Any:
        """Buffer'ı QuestDB'ye yaz. Başarısız olursa retry yapar."""
        if not self._buffer:
            return

        ticks_to_write = self._buffer.copy()
        self._buffer.clear()

        # Retry buffer'dan önceki başarısız tick'leri de ekle
        if self._retry_buffer:
            ticks_to_write = self._retry_buffer + ticks_to_write
            self._retry_buffer.clear()

        success = await self._write_with_retry(ticks_to_write)

        if not success:
            self._error_count += 1
            # Retry'lar da başarısız olduysa retry buffer'a kaydet (üst sınır ile)
            if len(self._retry_buffer) + len(ticks_to_write) <= self._max_retry_buffer_size:
                self._retry_buffer.extend(ticks_to_write)
                logger.warning(
                    "Ticks moved to retry buffer",
                    count=len(ticks_to_write),
                    retry_buffer_size=len(self._retry_buffer),
                )
            else:
                self._dropped_count += len(ticks_to_write)
                logger.error(
                    "Ticks DROPPED — retry buffer full",
                    count=len(ticks_to_write),
                    total_dropped=self._dropped_count,
                )

        self._last_flush = datetime.now(UTC)

    async def _write_with_retry(self, ticks: list[dict]) -> bool:
        """QuestDB'ye yaz, retry mekanizması ile. Başarılı ise True döner."""
        for attempt in range(self._max_retries):
            try:
                # QuestDB bağlantısı yoksa yeniden bağlan
                if not questdb_client._connected:
                    connected = await questdb_client.connect()
                    if not connected:
                        logger.warning(
                            "QuestDB reconnect failed",
                            attempt=attempt + 1,
                            count=len(ticks),
                        )
                        if attempt < self._max_retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        return False

                # Toplu yazma
                success = questdb_client.insert_ticks_batch(ticks)

                if success:
                    self._write_count += len(ticks)
                    self._retry_count = 0
                    logger.debug(
                        "QuestDB ticks written",
                        count=len(ticks),
                        total=self._write_count,
                    )
                    return True
                else:
                    logger.warning(
                        "QuestDB batch write failed",
                        attempt=attempt + 1,
                        count=len(ticks),
                    )
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    return False

            except Exception as e:
                logger.warning(
                    "QuestDB write error",
                    attempt=attempt + 1,
                    error=str(e),
                    count=len(ticks),
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                return False

        self._error_count += 1
        return False

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "running": self._running,
            "buffer_size": len(self._buffer),
            "retry_buffer_size": len(self._retry_buffer),
            "total_writes": self._write_count,
            "total_errors": self._error_count,
            "total_dropped": self._dropped_count,
            "last_flush": self._last_flush.isoformat(),
            "connected": questdb_client._connected,
        }


# Singleton
questdb_tick_consumer = QuestDBTickConsumer()
