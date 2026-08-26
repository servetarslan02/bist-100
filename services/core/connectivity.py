"""
ALPHA BIST — İnternet Bağlantı İzleyici v1.0

Kişisel PC senaryosu için kritik:
- İnternet kesintisi tespiti
- Offline/Online durum yönetimi
- Offline süresi takibi
- Otomatik recovery tetikleme
- Birden fazla endpoint'e health check (tek nokta arızası önleme)

Kullanım:
    from services.core.connectivity import connectivity_monitor

    if connectivity_monitor.is_online:
        # Veri çek
    else:
        # Offline mod, bekle
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


class ConnectivityState(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"      # Bazı endpoint'ler erişilebilir
    OFFLINE = "OFFLINE"


@dataclass
class ConnectivityEvent:
    """Bağlantı olayı kaydı."""
    timestamp: float
    event_type: str  # "connected", "disconnected", "degraded"
    duration_seconds: float = 0.0
    details: str = ""


class ConnectivityMonitor:
    """İnternet bağlantısı izleyici.

    Özellikler:
    - Birden fazla endpoint'e paralel health check
    - Exponential backoff ile check aralığı artırma
    - Offline süresi takibi
    - Online/Offline callback'leri
    - Bağlantı olayları geçmişi
    """

    # Kontrol endpoint'leri — birden fazla, tek nokta arızası önleme
    CHECK_ENDPOINTS = [
        "https://finance.yahoo.com",
        "https://query1.finance.yahoo.com",
        "https://www.google.com",
        "https://httpbin.org/get",
    ]

    def __init__(
        self,
        check_interval_seconds: float = 30.0,
        timeout_seconds: float = 5.0,
        failure_threshold: int = 3,
        recovery_threshold: int = 1,
    ):
        self._check_interval = check_interval_seconds
        self._timeout = timeout_seconds
        self._failure_threshold = failure_threshold
        self._recovery_threshold = recovery_threshold

        self._state = ConnectivityState.ONLINE
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_check_time: float = 0
        self._last_online_time: float = time.time()
        self._offline_since: Optional[float] = None
        self._total_offline_seconds: float = 0

        self._event_log: List[ConnectivityEvent] = []
        self._max_event_log = 500

        # Callbacks
        self._on_offline: List[Callable[[], Awaitable[None]]] = []
        self._on_online: List[Callable[[float], Awaitable[None]]] = []  # arg: offline_duration
        self._on_degraded: List[Callable[[], Awaitable[None]]] = []

        # Background task
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def is_online(self) -> bool:
        return self._state == ConnectivityState.ONLINE

    @property
    def is_offline(self) -> bool:
        return self._state == ConnectivityState.OFFLINE

    @property
    def state(self) -> ConnectivityState:
        return self._state

    @property
    def offline_since(self) -> Optional[float]:
        return self._offline_since

    @property
    def offline_duration_seconds(self) -> float:
        if self._offline_since:
            return time.time() - self._offline_since
        return 0.0

    @property
    def total_offline_seconds(self) -> float:
        total = self._total_offline_seconds
        if self._offline_since:
            total += time.time() - self._offline_since
        return total

    def on_offline(self, callback: Callable[[], Awaitable[None]]):
        """Offline olduğunda çağrılacak callback kaydet."""
        self._on_offline.append(callback)

    def on_online(self, callback: Callable[[float], Awaitable[None]]):
        """Online olduğunda çağrılacak callback kaydet (arg: offline süresi)."""
        self._on_online.append(callback)

    def on_degraded(self, callback: Callable[[], Awaitable[None]]):
        """Degraded durumda çağrılacak callback kaydet."""
        self._on_degraded.append(callback)

    async def start(self):
        """Arka plan izleyiciyi başlat."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Connectivity monitor started",
                    check_interval=self._check_interval,
                    failure_threshold=self._failure_threshold)

    async def stop(self):
        """Arka plan izleyiciyi durdur."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                logger.warning("Timeout/cancellation in stop", exc_info=True)
        logger.info("Connectivity monitor stopped",
                    total_offline_seconds=round(self._total_offline_seconds, 1))

    async def check_now(self) -> ConnectivityState:
        """Şu an bağlantı kontrolü yap (anlık)."""
        return await self._do_check()

    async def wait_for_online(self, timeout: float = 300.0, poll_interval: float = 10.0):
        """Online olana kadar bekle."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_online:
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def _monitor_loop(self):
        """Arka plan izleme döngüsü."""
        while self._running:
            try:
                await self._do_check()

                # Duruma göre bekleme süresi
                if self._state == ConnectivityState.OFFLINE:
                    # Offline'da daha sık kontrol et (ama exponential backoff ile)
                    wait = min(self._check_interval * 2, 120)
                elif self._state == ConnectivityState.DEGRADED:
                    wait = self._check_interval * 0.5
                else:
                    wait = self._check_interval

                await asyncio.sleep(wait)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Connectivity monitor error", error=str(e))
                await asyncio.sleep(self._check_interval)

    async def _do_check(self) -> ConnectivityState:
        """Gerçek bağlantı kontrolü yap."""
        import aiohttp

        self._last_check_time = time.time()
        successful = 0
        total = len(self.CHECK_ENDPOINTS)

        # Paralel kontrol — timeout ile
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                tasks = [self._check_endpoint(session, url) for url in self.CHECK_ENDPOINTS]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                successful = sum(1 for r in results if r is True)
        except Exception:
            successful = 0

        # Durum belirle
        old_state = self._state

        if successful >= self._recovery_threshold:
            # Online veya degraded
            if successful == total:
                new_state = ConnectivityState.ONLINE
            else:
                new_state = ConnectivityState.DEGRADED

            self._consecutive_successes += 1
            self._consecutive_failures = 0

            if old_state == ConnectivityState.OFFLINE:
                # Offline'dan online'a geçiş
                offline_duration = self.offline_duration_seconds
                self._total_offline_seconds += offline_duration
                self._offline_since = None
                self._last_online_time = time.time()

                self._log_event("connected", offline_duration)
                logger.info("Internet restored",
                           offline_seconds=round(offline_duration, 1),
                           successful_endpoints=successful)

                # Online callback'leri çağır
                for cb in self._on_online:
                    try:
                        await cb(offline_duration)
                    except Exception as e:
                        logger.error("Online callback error", error=str(e))

            self._state = new_state

        else:
            # Offline
            self._consecutive_failures += 1
            self._consecutive_successes = 0

            if self._consecutive_failures >= self._failure_threshold:
                if old_state != ConnectivityState.OFFLINE:
                    self._offline_since = time.time()
                    self._state = ConnectivityState.OFFLINE
                    self._log_event("disconnected")
                    logger.warning("Internet lost",
                                  consecutive_failures=self._consecutive_failures)

                    # Offline callback'leri çağır
                    for cb in self._on_offline:
                        try:
                            await cb()
                        except Exception as e:
                            logger.error("Offline callback error", error=str(e))

        return self._state

    async def _check_endpoint(self, session, url: str) -> bool:
        """Tek endpoint kontrolü."""
        try:
            async with session.get(url) as resp:
                return resp.status < 500
        except Exception:
            return False

    def _log_event(self, event_type: str, duration: float = 0.0, details: str = ""):
        """Olay kaydet."""
        event = ConnectivityEvent(
            timestamp=time.time(),
            event_type=event_type,
            duration_seconds=duration,
            details=details,
        )
        self._event_log.append(event)
        if len(self._event_log) > self._max_event_log:
            self._event_log = self._event_log[-self._max_event_log:]

    def get_status(self) -> dict:
        """Durum bilgisi."""
        return {
            "state": self._state.value,
            "is_online": self.is_online,
            "offline_since": datetime.fromtimestamp(
                self._offline_since, tz=timezone.utc
            ).isoformat() if self._offline_since else None,
            "offline_duration_seconds": round(self.offline_duration_seconds, 1),
            "total_offline_seconds": round(self.total_offline_seconds, 1),
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "last_check": datetime.fromtimestamp(
                self._last_check_time, tz=timezone.utc
            ).isoformat() if self._last_check_time else None,
            "recent_events": [
                {
                    "type": e.event_type,
                    "time": datetime.fromtimestamp(e.timestamp, tz=timezone.utc).isoformat(),
                    "duration": round(e.duration_seconds, 1),
                }
                for e in self._event_log[-10:]
            ],
        }

    def get_offline_report(self) -> dict:
        """Offline raporu — kaçırılan süre ve etki."""
        return {
            "total_offline_seconds": round(self.total_offline_seconds, 1),
            "total_offline_minutes": round(self.total_offline_seconds / 60, 1),
            "total_offline_hours": round(self.total_offline_seconds / 3600, 2),
            "current_offline": self.is_offline,
            "current_offline_seconds": round(self.offline_duration_seconds, 1),
            "event_count": len([e for e in self._event_log if e.event_type == "disconnected"]),
        }


# Singleton
connectivity_monitor = ConnectivityMonitor()
