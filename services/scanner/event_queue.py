"""
ALPHA BIST — Event Priority Queue v1.0

4. Event'leri priority queue/worker yapısına taşı.
50 hisseyi etkileyen makro olay bloklamaz.
"""

import asyncio
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class EventTask:
    """Event görevi."""
    event_type: str
    event_data: Dict
    ticker: str
    importance: float
    priority: int  # 1=en yüksek, 5=en düşük
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventPriorityQueue:
    """
    Event'leri öncelik sırasıyla işler.
    Yüksek önem → önce işlenir.
    Paralel worker ile bloklama olmaz.
    """

    def __init__(self, max_workers: int = 5):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._max_workers = max_workers
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._handler: Optional[Callable] = None
        self._processed_count = 0

    def set_handler(self, handler: Callable):
        """Event handler ata."""
        self._handler = handler

    async def start(self):
        """Worker'ları başlat."""
        self._running = True
        for i in range(self._max_workers):
            task = asyncio.create_task(self._worker(f"worker-{i}"))
            self._workers.append(task)
            if len(self._workers) > 1000:
                self._workers = self._workers[-1000:]
        logger.info("Event queue started", workers=self._max_workers)

    async def stop(self):
        """Worker'ları durdur."""
        self._running = False
        for task in self._workers:
            task.cancel()
        self._workers.clear()
        logger.info("Event queue stopped", processed=self._processed_count)

    async def submit(self, event_type: str, event_data: Dict,
                     affected_tickers: List[str]):
        """
        Event'i kuyruğa ekle.
        Her etkilenen hisse için ayrı task oluşturulur.
        """
        importance = event_data.get("importance", 0.5)

        # Öncelik belirle
        priority = self._calculate_priority(event_type, importance)

        for ticker in affected_tickers:
            task = EventTask(
                event_type=event_type,
                event_data=event_data,
                ticker=ticker,
                importance=importance,
                priority=priority,
            )
            await self._queue.put((priority, task))

        logger.info("Events queued", event_type=event_type,
                    tickers=len(affected_tickers), priority=priority)

    def _calculate_priority(self, event_type: str, importance: float) -> int:
        """Öncelik hesapla (1=en yüksek)."""
        if importance > 0.9:
            return 1  # Kritik
        elif importance > 0.7:
            return 2  # Yüksek
        elif importance > 0.5:
            return 3  # Orta
        elif event_type == "kap.event":
            return 2  # KAP her zaman yüksek
        else:
            return 4  # Düşük

    async def _worker(self, name: str):
        """Worker — kuyruktan task alıp işler."""
        while self._running:
            try:
                priority, task = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )

                if self._handler:
                    try:
                        if asyncio.iscoroutinefunction(self._handler):
                            await self._handler(task)
                        else:
                            self._handler(task)
                        self._processed_count += 1
                    except Exception as e:
                        logger.error("Event handler error",
                                   worker=name, ticker=task.ticker,
                                   error=str(e))

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Worker error", worker=name, error=str(e))
                await asyncio.sleep(0.1)

    def get_stats(self) -> Dict:
        """İstatistikler."""
        return {
            "queue_size": self._queue.qsize(),
            "workers": len(self._workers),
            "processed": self._processed_count,
            "running": self._running,
        }


# Singleton
event_queue = EventPriorityQueue(max_workers=5)
