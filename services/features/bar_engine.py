"""
ALPHA BIST — Canonical Bar Engine v1.0

Tick → 1m → 5m → 15m → 1h → 1d

Live ve replay aynı engine'i kullanır.
Tek canonical OHLC kaynağı.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class Bar:
    """Canonical OHLC bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int = 0
    vwap: float = 0.0
    is_complete: bool = False

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close,
            "volume": self.volume, "vwap": self.vwap,
        }


@dataclass
class TimeframeConfig:
    """Zaman dilimi konfigürasyonu."""
    name: str
    duration_seconds: int
    max_bars: int = 500


TIMEFRAMES = {
    "1m": TimeframeConfig("1m", 60, 500),
    "5m": TimeframeConfig("5m", 300, 500),
    "15m": TimeframeConfig("15m", 900, 500),
    "1h": TimeframeConfig("1h", 3600, 500),
    "1d": TimeframeConfig("1d", 86400, 2520),  # 10 yıl
}


class BarEngine:
    """
    Canonical bar engine.
    Tick'ten OHLC bar üretir.
    Live ve replay aynı engine'i kullanır.
    """

    def __init__(self, ticker: str):
        self.ticker = ticker
        self._bars: Dict[str, deque] = {
            tf: deque(maxlen=TIMEFRAMES[tf].max_bars) for tf in TIMEFRAMES
        }
        self._current_bars: Dict[str, Optional[Bar]] = {tf: None for tf in TIMEFRAMES}
        self._last_price: float = 0.0
        self._last_volume: int = 0

    def process_tick(self, price: float, volume: int, timestamp: datetime) -> List[Tuple[str, Bar]]:
        """
        Tick işle → tamamlanan bar'ları döndür.

        Returns: [(timeframe, completed_bar), ...]
        """
        self._last_price = price
        self._last_volume = volume

        completed = []

        for tf_name, tf_config in TIMEFRAMES.items():
            bar_ts = self._get_bar_timestamp(timestamp, tf_config.duration_seconds)
            current = self._current_bars[tf_name]

            if current is None:
                # İlk bar
                self._current_bars[tf_name] = Bar(
                    timestamp=bar_ts, open=price, high=price,
                    low=price, close=price, volume=volume,
                    trade_count=1, vwap=price,
                )
            elif bar_ts > current.timestamp:
                # Yeni bar zamanı → eski bar'ı tamamla
                current.is_complete = True
                self._bars[tf_name].append(current)
                completed.append((tf_name, current))

                # Yeni bar başlat
                self._current_bars[tf_name] = Bar(
                    timestamp=bar_ts, open=price, high=price,
                    low=price, close=price, volume=volume,
                    trade_count=1, vwap=price,
                )
            else:
                # Aynı bar içinde → güncelle
                current.high = max(current.high, price)
                current.low = min(current.low, price)
                current.close = price
                current.volume += volume
                current.trade_count += 1
                total_val = current.vwap * (current.volume - volume) + price * volume
                current.vwap = total_val / current.volume if current.volume > 0 else price

        return completed

    def _get_bar_timestamp(self, timestamp: datetime, duration_seconds: int) -> datetime:
        """Bar bucket timestamp hesapla."""
        if duration_seconds >= 86400:
            return timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        elif duration_seconds >= 3600:
            return timestamp.replace(minute=0, second=0, microsecond=0)
        else:
            total_seconds = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            bucketed = (total_seconds // duration_seconds) * duration_seconds
            return timestamp.replace(
                hour=bucketed // 3600,
                minute=(bucketed % 3600) // 60,
                second=bucketed % 60,
                microsecond=0,
            )

    def get_bars(self, timeframe: str, count: int = 100) -> List[Bar]:
        """Tamamlanmış bar'ları döndür."""
        bars = list(self._bars.get(timeframe, []))
        return bars[-count:] if len(bars) >= count else bars

    def get_current_bar(self, timeframe: str) -> Optional[Bar]:
        """Mevcut (tamamlanmamış) bar'ı döndür."""
        return self._current_bars.get(timeframe)

    def get_all_bars_numpy(self, timeframe: str) -> Dict[str, list]:
        """Bar'ları numpy array olarak döndür."""
        bars = self.get_bars(timeframe, 1000)
        if not bars:
            return {}

        return {
            "timestamp": [b.timestamp for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "vwap": [b.vwap for b in bars],
        }

    def get_latest_complete(self, timeframe: str) -> Optional[Bar]:
        """Son tamamlanmış bar'ı döndür."""
        bars = list(self._bars.get(timeframe, []))
        return bars[-1] if bars else None

    def warmup_from_history(self, bars_1d: List[Dict]):
        """
        Geçmiş verilerden state ısıt.
        Restart recovery için kullanılır.

        bars_1d: [{"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
        """
        for bar_data in bars_1d:
            bar = Bar(
                timestamp=bar_data["timestamp"],
                open=bar_data["open"],
                high=bar_data["high"],
                low=bar_data["low"],
                close=bar_data["close"],
                volume=bar_data["volume"],
                is_complete=True,
            )
            self._bars["1d"].append(bar)

        logger.info("Bar engine warmed up", ticker=self.ticker, bars=len(bars_1d))


class BarEngineManager:
    """Tüm hisselerin bar engine'lerini yönetir."""

    def __init__(self):
        self._engines: Dict[str, BarEngine] = {}

    def get_engine(self, ticker: str) -> BarEngine:
        if ticker not in self._engines:
            self._engines[ticker] = BarEngine(ticker)
        return self._engines[ticker]

    def process_tick(self, ticker: str, price: float, volume: int,
                     timestamp: datetime) -> List[Tuple[str, Bar]]:
        engine = self.get_engine(ticker)
        return engine.process_tick(price, volume, timestamp)

    def get_all_tickers(self) -> List[str]:
        return list(self._engines.keys())


# Singleton
bar_engine_manager = BarEngineManager()
