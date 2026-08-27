"""
ALPHA BIST — Adaptive Scan Scheduler v1.0

Piyasa koşullarına göre tarama sıklığını otomatik ayarlar:
- Volatilite artınca sık tarama
- Rejim değişince sıklık değişimi
- Event gelince acil tarama
- Piyasa kapalıyken duraklat

Kaynaklar: Mometic (2026), TradeAlgo (2026)
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from datetime import time as dt_time
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ScanMode(StrEnum):
    """Tarama modu."""
    CONTINUOUS = "CONTINUOUS"      # Sürekli tarama (piyasa açık)
    SCHEDULED = "SCHEDULED"        # Zamanlanmış tarama
    EVENT_DRIVEN = "EVENT_DRIVEN"  # Event tetikli
    PAUSED = "PAUSED"              # Duraklatılmış (piyasa kapalı)
    MANUAL = "MANUAL"              # Manuel tetikleme


@dataclass
class ScanInterval:
    """Tarama aralığı ayarları."""
    base_seconds: int = 60           # 1 dakika
    min_seconds: int = 10            # Minimum (event/acil)
    max_seconds: int = 300           # Maximum (düşük volatilite)
    volatility_scale: float = 1.0   # Volatilite çarpanı
    regime_scale: float = 1.0       # Rejim çarpanı


class AdaptiveScanScheduler:
    """Volatilite ve rejime göre adaptif tarama zamanlaması.

    Prensip: Piyasa hareketliyken sık, sakinken seyrek tarama.
    Bu sayede CPU verimli kullanılır, önemli hareketler kaçırılmaz.
    """

    # BIST piyasa saatleri (Türkiye, UTC+3)
    MARKET_OPEN = dt_time(10, 0)    # 10:00
    MARKET_CLOSE = dt_time(18, 0)   # 18:00
    PRE_MARKET = dt_time(9, 55)     # 09:55
    POST_MARKET = dt_time(18, 5)    # 18:05

    # Volatilite eşikleri ve çarpanları
    VOLATILITY_INTERVALS = {
        "very_low":  {"max_vol": 0.10, "scale": 2.0},   # Düşük vol → 2x yavaş
        "low":       {"max_vol": 0.15, "scale": 1.5},
        "normal":    {"max_vol": 0.20, "scale": 1.0},   # Normal
        "high":      {"max_vol": 0.30, "scale": 0.5},   # Yüksek vol → 2x hızlı
        "very_high": {"max_vol": 1.00, "scale": 0.25},  # Ekstrem → 4x hızlı
    }

    # Rejim bazlı çarpanlar
    REGIME_SCALES = {
        "PANIC":               0.2,   # 5x hızlı
        "RISK-OFF":            0.3,   # 3.3x hızlı
        "HIGH-VOLATILITY":     0.4,   # 2.5x hızlı
        "TRENDING-UP":         0.7,   # 1.4x hızlı
        "TRENDING-DOWN":       0.7,
        "MOMENTUM-EXPANSION":  0.6,   # 1.7x hızlı
        "RECOVERY":            0.8,
        "RANGE":               1.0,   # Normal
        "LOW-VOLATILITY":      1.5,   # 1.5x yavaş
    }

    def __init__(
        self,
        base_interval: int = 60,
        timezone_offset: int = 3,  # UTC+3 (Türkiye)
    ):
        self._base_interval = base_interval
        self._tz_offset = timezone_offset
        self._running = False
        self._current_mode = ScanMode.PAUSED
        self._current_interval = base_interval

        # State
        self._current_volatility = 0.20
        self._current_regime = "RANGE"
        self._has_recent_event = False
        self._event_cooldown_until: float = 0

        # Callbacks
        self._scan_callback: Callable[[], Awaitable[None]] | None = None

        # İstatistikler
        self._total_scans = 0
        self._total_events_triggered = 0
        self._last_scan_time: float = 0
        self._interval_history: list = []

    def set_scan_callback(self, callback: Callable[[], Awaitable[None]]):
        """Tarama callback'i ata.

        Args:
            callback: Async tarama fonksiyonu
        """
        self._scan_callback = callback

    def update_market_state(
        self,
        volatility: float = None,
        regime: str = None,
        has_event: bool = None,
    ):
        """Piyasa durumunu güncelle.

        Args:
            volatility: Yıllık volatilite (0.20 = %20)
            regime: Mevcut rejim
            has_event: Yakın zamanda event var mı?
        """
        if volatility is not None:
            self._current_volatility = volatility
        if regime is not None:
            self._current_regime = regime
        if has_event is not None:
            self._has_recent_event = has_event
            if has_event:
                self._event_cooldown_until = time.time() + 60  # 1 dakika event modu

        # Interval'ı yeniden hesapla
        self._current_interval = self._calculate_interval()

    def get_scan_interval(self) -> int:
        """Mevcut tarama aralığını al (saniye).

        Returns:
            Tarama aralığı (saniye)
        """
        return self._calculate_interval()

    def get_scan_mode(self) -> ScanMode:
        """Mevcut tarama modunu al.

        Returns:
            ScanMode
        """
        if not self._is_market_hours():
            return ScanMode.PAUSED
        if self._has_recent_event or time.time() < self._event_cooldown_until:
            return ScanMode.EVENT_DRIVEN
        return ScanMode.CONTINUOUS

    def is_market_open(self) -> bool:
        """Piyasa açık mı?

        Returns:
            True: Piyasa açık
        """
        return self._is_market_hours()

    async def start(self):
        """Scheduler'ı başlat."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        logger.info("Scan scheduler started",
                    base_interval=f"{self._base_interval}s")

        # Ana döngü
        while self._running:
            try:
                # Piyasa saatleri kontrolü
                if not self._is_market_hours():
                    self._current_mode = ScanMode.PAUSED
                    logger.debug("Market closed, scheduler paused")
                    await asyncio.sleep(60)  # 1 dakika bekle
                    continue

                # Tarama aralığını hesapla
                interval = self._calculate_interval()
                self._current_interval = interval
                self._current_mode = ScanMode.CONTINUOUS

                # Event-driven mod
                if self._has_recent_event or time.time() < self._event_cooldown_until:
                    interval = min(interval, 10)  # Event modu: max 10 saniye
                    self._current_mode = ScanMode.EVENT_DRIVEN

                # Tarama callback'i varsa çalıştır
                if self._scan_callback:
                    try:
                        await self._scan_callback()
                        self._total_scans += 1
                        self._last_scan_time = time.time()
                    except Exception as e:
                        logger.error("Scan callback error", error=str(e))

                # Interval geçmişine kaydet
                self._interval_history.append({
                    "timestamp": datetime.now(UTC).isoformat(),
                    "interval": interval,
                    "mode": self._current_mode.value,
                    "volatility": self._current_volatility,
                    "regime": self._current_regime,
                })
                if len(self._interval_history) > 1000:
                    self._interval_history = self._interval_history[-1000:]
                # Son 100 kaydı tut
                self._interval_history = self._interval_history[-100:]

                # Event cooldown kontrolü
                if time.time() >= self._event_cooldown_until:
                    self._has_recent_event = False

                # Bir sonraki taramaya kadar bekle
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler error", error=str(e))
                await asyncio.sleep(5)

    async def stop(self):
        """Scheduler'ı durdur."""
        self._running = False
        self._current_mode = ScanMode.PAUSED
        logger.info("Scan scheduler stopped",
                    total_scans=self._total_scans)

    def trigger_event_scan(self, tickers: list = None):
        """Event-driven tarama tetikle.

        Args:
            tickers: Etkilenen hisseler (opsiyonel)
        """
        self._has_recent_event = True
        self._event_cooldown_until = time.time() + 60
        self._total_events_triggered += 1

        logger.info("Event scan triggered",
                    tickers=tickers,
                    total_events=self._total_events_triggered)

    def trigger_manual_scan(self):
        """Manuel tarama tetikle."""
        self._current_mode = ScanMode.MANUAL
        logger.info("Manual scan triggered")

    def _calculate_interval(self) -> int:
        """Tarama aralığını hesapla.

        Returns:
            Aralık (saniye)
        """
        interval = self._base_interval

        # 1. Volatilite bazlı
        vol_scale = self._get_volatility_scale(self._current_volatility)
        interval = interval * vol_scale

        # 2. Rejim bazlı
        regime_scale = self.REGIME_SCALES.get(self._current_regime, 1.0)
        interval = interval * regime_scale

        # 3. Event varsa sık tarama
        if self._has_recent_event or time.time() < self._event_cooldown_until:
            interval = min(interval, 10)

        # Sınırla
        interval = max(10, min(300, interval))

        return int(interval)

    def _get_volatility_scale(self, volatility: float) -> float:
        """Volatilite bazlı çarpan.

        Args:
            volatility: Yıllık volatilite

        Returns:
            Çarpan (0.25 = 4x hızlı, 2.0 = 2x yavaş)
        """
        for _level, config in self.VOLATILITY_INTERVALS.items():
            if volatility <= config["max_vol"]:
                return config["scale"]
        return 1.0

    def _is_market_hours(self) -> bool:
        """BIST piyasa saatleri içinde mi?

        Returns:
            True: Piyasa açık
        """
        now = datetime.now(timezone(timedelta(hours=self._tz_offset)))
        current_time = now.time()

        # Hafta sonu kontrolü
        if now.weekday() >= 5:  # Cumartesi=5, Pazar=6
            return False

        # Piyasa saatleri (pre-market + market + post-market)
        return self.PRE_MARKET <= current_time <= self.POST_MARKET

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler.

        Returns:
            Scheduler istatistikleri
        """
        return {
            "running": self._running,
            "mode": self._current_mode.value,
            "current_interval_seconds": self._current_interval,
            "base_interval_seconds": self._base_interval,
            "volatility": round(self._current_volatility, 4),
            "regime": self._current_regime,
            "has_recent_event": self._has_recent_event,
            "market_open": self._is_market_hours(),
            "total_scans": self._total_scans,
            "total_events_triggered": self._total_events_triggered,
            "last_scan_time": datetime.fromtimestamp(
                self._last_scan_time, tz=UTC
            ).isoformat() if self._last_scan_time else None,
        }

    def get_interval_history(self, limit: int = 20) -> list:
        """Interval geçmişini al.

        Args:
            limit: Maksimum kayıt sayısı

        Returns:
            Interval geçmişi
        """
        return self._interval_history[-limit:]


# Singleton
scan_scheduler = AdaptiveScanScheduler()
