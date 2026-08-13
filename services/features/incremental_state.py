"""ALPHA BIST - Incremental Feature State v1.1

Gerçek incremental state: tick geldiğinde tüm geçmişi yeniden hesaplamaz.
Rolling window'lar bellekte tutulur, yeni veri geldikçe güncellenir.
Ayrıca tick'lerden gerçek OHLC bar'ları üretir.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import structlog

logger = structlog.get_logger()


@dataclass
class OHLCBar:
    """Tek bir OHLC bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int = 0
    vwap: float = 0.0
    is_complete: bool = False


@dataclass
class RollingWindow:
    """Rolling window — sabit boyutlu deque."""
    size: int
    values: deque = field(default_factory=deque)

    def append(self, value: float):
        self.values.append(value)
        if len(self.values) > self.size:
            self.values.popleft()

    def mean(self) -> float:
        return np.mean(self.values) if self.values else 0.0

    def std(self) -> float:
        return np.std(self.values) if len(self.values) > 1 else 0.0

    def last(self) -> float:
        return self.values[-1] if self.values else 0.0

    def __len__(self):
        return len(self.values)


@dataclass
class IncrementalAssetState:
    """
    Her hissenin incremental state'i.
    Tick geldiğinde sadece değişen değerler güncellenir.
    """

    instrument_id: int
    ticker: str
    last_update: datetime = field(default_factory=datetime.utcnow)

    # Current price
    price: float = 0.0
    previous_price: float = 0.0

    # OHLC bars (tick'ten üretilen gerçek bar'lar)
    current_bar: Optional[OHLCBar] = None
    bars_1m: deque = field(default_factory=lambda: deque(maxlen=100))
    bars_5m: deque = field(default_factory=lambda: deque(maxlen=100))
    bars_1d: deque = field(default_factory=lambda: deque(maxlen=252))

    # Rolling windows (incremental)
    returns_1d: RollingWindow = field(default_factory=lambda: RollingWindow(60))
    volume_history: RollingWindow = field(default_factory=lambda: RollingWindow(20))

    # Incremental EMA values
    ema_12: float = 0.0
    ema_26: float = 0.0
    ema_initialized: bool = False

    # Incremental ATR
    atr_14: float = 0.0
    true_range_history: RollingWindow = field(default_factory=lambda: RollingWindow(14))
    previous_high: float = 0.0
    previous_low: float = 0.0
    previous_close: float = 0.0

    # Incremental RSI
    rsi_14: float = 50.0
    avg_gain: float = 0.0
    avg_loss: float = 0.0
    rsi_initialized: bool = False

    # Volume stats
    volume_avg_20d: float = 0.0
    volume_std_20d: float = 0.0
    volume_zscore: float = 0.0

    # Computed features cache
    features_cache: Dict[str, float] = field(default_factory=dict)
    features_dirty: bool = True

    def process_tick(self, price: float, volume: int, timestamp: datetime):
        """
        Yeni tick geldiğinde state'i incremental güncelle.
        Tüm geçmişi yeniden okumaz.
        """
        self.previous_price = self.price
        self.price = price
        self.last_update = timestamp

        # Update current OHLC bar
        self._update_current_bar(price, volume, timestamp)

        # Update rolling windows
        if self.previous_price > 0:
            ret = (price / self.previous_price - 1) * 100
            self.returns_1d.append(ret)

        self.volume_history.append(volume)

        # Update incremental indicators
        self._update_ema(price)
        self._update_rsi(price)
        self._update_atr(price, 0, 0)  # High/Low bilgisi yoksa close kullan

        # Update volume stats
        if len(self.volume_history) >= 5:
            self.volume_avg_20d = self.volume_history.mean()
            self.volume_std_20d = self.volume_history.std()
            if self.volume_std_20d > 0:
                self.volume_zscore = (volume - self.volume_avg_20d) / self.volume_std_20d

        self.features_dirty = True

    def _update_current_bar(self, price: float, volume: int, timestamp: datetime):
        """Mevcut OHLC bar'ını güncelle veya yeni bar başlat."""
        # 1 dakikalık bar
        bar_minute = timestamp.replace(second=0, microsecond=0)

        if self.current_bar is None or self.current_bar.timestamp < bar_minute:
            # Önceki bar'ı kapat
            if self.current_bar is not None:
                self.current_bar.is_complete = True
                self.bars_1m.append(self.current_bar)
                self._aggregate_bars()

            # Yeni bar başlat
            self.current_bar = OHLCBar(
                timestamp=bar_minute,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                trade_count=1,
                vwap=price,
            )
        else:
            # Mevcut bar'ı güncelle
            self.current_bar.high = max(self.current_bar.high, price)
            self.current_bar.low = min(self.current_bar.low, price)
            self.current_bar.close = price
            self.current_bar.volume += volume
            self.current_bar.trade_count += 1
            total_value = self.current_bar.vwap * (self.current_bar.volume - volume) + price * volume
            self.current_bar.vwap = total_value / self.current_bar.volume if self.current_bar.volume > 0 else price

    def _aggregate_bars(self):
        """1dk bar'lardan 5dk ve günlük bar'ları聚合le."""
        # 5 dakikalık bar
        if len(self.bars_1m) >= 5 and len(self.bars_1m) % 5 == 0:
            last_5 = list(self.bars_1m)[-5:]
            bar_5m = OHLCBar(
                timestamp=last_5[0].timestamp,
                open=last_5[0].open,
                high=max(b.high for b in last_5),
                low=min(b.low for b in last_5),
                close=last_5[-1].close,
                volume=sum(b.volume for b in last_5),
                trade_count=sum(b.trade_count for b in last_5),
                is_complete=True,
            )
            self.bars_5m.append(bar_5m)

    def _update_ema(self, price: float):
        """Incremental EMA güncelleme."""
        if not self.ema_initialized:
            self.ema_12 = price
            self.ema_26 = price
            self.ema_initialized = True
        else:
            alpha_12 = 2.0 / 13
            alpha_26 = 2.0 / 27
            self.ema_12 = alpha_12 * price + (1 - alpha_12) * self.ema_12
            self.ema_26 = alpha_26 * price + (1 - alpha_26) * self.ema_26

    def _update_rsi(self, price: float):
        """Incremental RSI güncelleme (Wilder's smoothing)."""
        if self.previous_price == 0:
            return

        change = price - self.previous_price
        gain = max(change, 0)
        loss = max(-change, 0)

        if not self.rsi_initialized:
            self.avg_gain = gain
            self.avg_loss = loss
            self.rsi_initialized = True
        else:
            # Wilder's smoothing
            self.avg_gain = (self.avg_gain * 13 + gain) / 14
            self.avg_loss = (self.avg_loss * 13 + loss) / 14

        if self.avg_loss == 0:
            self.rsi_14 = 100.0
        else:
            rs = self.avg_gain / self.avg_loss
            self.rsi_14 = 100 - (100 / (1 + rs))

    def _update_atr(self, high: float, low: float, close: float):
        """Incremental ATR güncelleme."""
        # Tick'ten geldiğinde high/low yok, sadece close
        if high == 0:
            high = self.price
            low = self.price

        if self.previous_close > 0:
            tr = max(
                high - low,
                abs(high - self.previous_close),
                abs(low - self.previous_close)
            )
            self.true_range_history.append(tr)

            if len(self.true_range_history) >= 14:
                # Wilder's ATR
                if self.atr_14 == 0:
                    self.atr_14 = self.true_range_history.mean()
                else:
                    self.atr_14 = (self.atr_14 * 13 + self.true_range_history.last()) / 14

        self.previous_high = high
        self.previous_low = low
        self.previous_close = self.price

    def get_daily_bars_numpy(self) -> Dict[str, np.ndarray]:
        """Günlük bar'ları numpy array olarak döndür (feature calculation için)."""
        bars = list(self.bars_1d)
        if not bars:
            # Fallback: son 60 1dk bar'ından günlük bar üret
            bars = list(self.bars_1m)[-60:]

        if not bars:
            return {}

        return {
            "open": np.array([b.open for b in bars]),
            "high": np.array([b.high for b in bars]),
            "low": np.array([b.low for b in bars]),
            "close": np.array([b.close for b in bars]),
            "volume": np.array([b.volume for b in bars]),
        }

    def get_incremental_features(self) -> Dict[str, float]:
        """
        Incremental olarak hesaplanmış feature'ları döndür.
        Tüm geçmişi yeniden hesaplamaz.
        """
        if not self.features_dirty:
            return self.features_cache

        features = {}

        # Price
        features["price"] = self.price
        if self.previous_price > 0:
            features["return_1d"] = (self.price / self.previous_price - 1) * 100

        # RSI (incremental)
        features["rsi_14"] = self.rsi_14

        # EMA (incremental)
        features["ema_12"] = self.ema_12
        features["ema_26"] = self.ema_26
        features["macd"] = self.ema_12 - self.ema_26

        # ATR (incremental)
        features["atr_14"] = self.atr_14
        if self.price > 0:
            features["atr_14_pct"] = self.atr_14 / self.price * 100

        # Volume (incremental)
        features["volume_zscore"] = self.volume_zscore
        features["volume_avg_20d"] = self.volume_avg_20d

        # Rolling returns
        if len(self.returns_1d) >= 5:
            features["momentum_5d"] = sum(list(self.returns_1d.values)[-5:])
        if len(self.returns_1d) >= 20:
            features["momentum_20d"] = sum(list(self.returns_1d.values)[-20:])

        self.features_cache = features
        self.features_dirty = False

        return features


class IncrementalStateManager:
    """Tüm hisselerin incremental state'lerini yönetir."""

    def __init__(self):
        self._states: Dict[int, IncrementalAssetState] = {}

    def get_or_create(self, instrument_id: int, ticker: str) -> IncrementalAssetState:
        if instrument_id not in self._states:
            self._states[instrument_id] = IncrementalAssetState(
                instrument_id=instrument_id,
                ticker=ticker,
            )
        return self._states[instrument_id]

    def process_tick(self, instrument_id: int, ticker: str,
                     price: float, volume: int, timestamp: datetime):
        """Tick işle — incremental state güncelle."""
        state = self.get_or_create(instrument_id, ticker)
        state.process_tick(price, volume, timestamp)
        return state

    def get_state(self, instrument_id: int) -> Optional[IncrementalAssetState]:
        return self._states.get(instrument_id)

    def get_all_states(self) -> Dict[int, IncrementalAssetState]:
        return self._states

    def get_features(self, instrument_id: int) -> Dict[str, float]:
        state = self._states.get(instrument_id)
        if state:
            return state.get_incremental_features()
        return {}


# Singleton
state_manager = IncrementalStateManager()
