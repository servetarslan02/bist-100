"""
ALPHA BIST — QuestDB Tick Data Consumer

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
from typing import Any

import structlog

from ..core.event_bus import EventType, event_bus
from ..core.event_schema import CanonicalEvent
from ..core.questdb_client import questdb_client

logger = structlog.get_logger()


class QuestDBTickConsumer:
    """QuestDB tick veri tüketici — NATS'tan QuestDB'ye tick akışı.

    Buffer'lı toplu yazma ve retry mekanizması ile yüksek
    güvenilirlik sağlar.
    """

    def __init__(self) -> None:
        """QuestDBTickConsumer örneği oluşturur."""
        self._running = False
        self._buffer: list[dict[str, Any]] = []
        self._buffer_size = 100
        self._flush_interval = 5.0
        self._write_count = 0
        self._error_count = 0
        self._retry_count = 0
        self._dropped_count = 0
        self._max_retries = 3
        self._retry_buffer: list[dict[str, Any]] = []
        self._max_retry_buffer_size = 1000
        self._last_flush = datetime.now(UTC)
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Consumer'ı başlatır.

        QuestDB bağlantısını kurar, tabloları oluşturur ve
        NATS'tan tick olaylarını dinlemeye başlar.

        Raises:
            ConnectionError: QuestDB bağlantısı kurulamazsa (retry ile devam eder).
        """
        self._running = True

        connected = await questdb_client.connect()
        if not connected:
            logger.warning("QuestDB connection failed, will retry on first tick")

        await questdb_client.ensure_tables()

        await event_bus.subscribe(EventType.MARKET_TICK, self._on_tick)

        self._flush_task = asyncio.create_task(self._flush_loop())

        logger.info(
            "QuestDB tick consumer started",
            buffer_size=self._buffer_size,
            flush_interval=self._flush_interval,
        )

    async def stop(self) -> None:
        """Consumer'ı durdurur.

        Buffer'daki kalan verileri flush eder ve bağlantıyı kapatır.
        """
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()

        if self._buffer:
            await self._flush_buffer()

        questdb_client.close()
        logger.info(
            "QuestDB tick consumer stopped",
            total_writes=self._write_count,
            total_errors=self._error_count,
        )

    async def _on_tick(self, event: CanonicalEvent) -> None:
        """MARKET_TICK olayını işler.

        Args:
            event: CanonicalEvent MARKET_TICK olayı.
        """
        try:
            data = event.data

            if data.get("is_index"):
                return

            ticker = data.get("ticker")
            price = data.get("price")
            volume = data.get("volume", 0)
            bid = data.get("bid", 0.0)
            ask = data.get("ask", 0.0)

            if not ticker or not price:
                return

            self._buffer.append({
                "ticker": ticker,
                "price": float(price),
                "volume": int(volume) if volume else 0,
                "bid": float(bid) if bid else 0.0,
                "ask": float(ask) if ask else 0.0,
                "timestamp": datetime.now(UTC),
            })

            if len(self._buffer) >= self._buffer_size:
                await self._flush_buffer()

        except Exception as exc:
            logger.warning("QuestDB tick processing error", error=str(exc))
            self._error_count += 1

    async def _flush_loop(self) -> None:
        """Periyodik buffer flush döngüsü."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)

                if self._buffer:
                    await self._flush_buffer()

            except Exception as exc:
                logger.warning("QuestDB flush loop error", error=str(exc))
                await asyncio.sleep(1)

    async def _flush_buffer(self) -> None:
        """Buffer'ı QuestDB'ye yazar.

        Başarısız olursa retry mekanizması ile tekrar dener.
        Retry'lar da başarısız olursa retry buffer'a kaybeder.
        """
        if not self._buffer:
            return

        ticks_to_write = self._buffer.copy()
        self._buffer.clear()

        if self._retry_buffer:
            ticks_to_write = self._retry_buffer + ticks_to_write
            self._retry_buffer.clear()

        success = await self._write_with_retry(ticks_to_write)

        if not success:
            self._error_count += 1
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

    async def _write_with_retry(self, ticks: list[dict[str, Any]]) -> bool:
        """QuestDB'ye retry mekanizması ile yazar.

        Args:
            ticks: Yazılacak tick listesi.

        Returns:
            True: Başarılı, False: Tüm denemeler başarısız.
        """
        for attempt in range(self._max_retries):
            try:
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

            except Exception as exc:
                logger.warning(
                    "QuestDB write error",
                    attempt=attempt + 1,
                    error=str(exc),
                    count=len(ticks),
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                return False

        self._error_count += 1
        return False

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndürür.

        Returns:
            Consumer istatistik sözlüğü.
        """
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


__all__ = [
    "QuestDBTickConsumer",
    "questdb_tick_consumer",
]
