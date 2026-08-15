"""ALPHA BIST - Incremental Feature State v1.2

v1.2 Düzeltmeler:
- ATR: completed bar'dan güncellenir, tick'ten değil
- 5m aggregation: zaman bazlı bucket (timestamp bucket)
- Daily bars: doğru aggregation
- return_1d: günlük return (tick-to-tick değil)
- momentum_5d/20d: timeframe bazlı
- MACD signal: gerçek 9-period EMA
- RSI: tek canonical Wilder implementation
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
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
class TimeframeState:
    """Belirli bir timeframe için state (1m, 5m, 15m, 1h, 1d)."""
    timeframe: str
    bar_duration: timedelta
    current_bar: Optional[OHLCBar] = None
    completed_bars: deque = field(default_factory=lambda: deque(maxlen=252))

    def process_tick(self, price: float, volume: int, timestamp: datetime) -> Optional[OHLCBar]:
        """Tick işle, gerekirse bar tamamla ve döndür."""
        # Bar bucket timestamp
        if self.bar_duration.total_seconds() >= 86400:
            # Daily: günün başı
            bar_ts = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self.bar_duration.total_seconds() >= 3600:
            # Hourly: saatin başı
            bar_ts = timestamp.replace(minute=0, second=0, microsecond=0)
        else:
            # Minute-based: dakika bucket
            total_seconds = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            bucket_seconds = int(self.bar_duration.total_seconds())
            bucketed = (total_seconds // bucket_seconds) * bucket_seconds
            bar_ts = timestamp.replace(
                hour=bucketed // 3600,
                minute=(bucketed % 3600) // 60,
                second=bucketed % 60,
                microsecond=0,
            )

        completed_bar = None

        if self.current_bar is None:
            # İlk bar
            self.current_bar = OHLCBar(
                timestamp=bar_ts, open=price, high=price, low=price,
                close=price, volume=volume, trade_count=1, vwap=price,
            )
        elif bar_ts > self.current_bar.timestamp:
            # Yeni bar zamanı → eski bar'ı tamamla
            self.current_bar.is_complete = True
            completed_bar = self.current_bar
            self.completed_bars.append(self.current_bar)

            # Yeni bar başlat
            self.current_bar = OHLCBar(
                timestamp=bar_ts, open=price, high=price, low=price,
                close=price, volume=volume, trade_count=1, vwap=price,
            )
        else:
            # Aynı bar içinde → güncelle
            self.current_bar.high = max(self.current_bar.high, price)
            self.current_bar.low = min(self.current_bar.low, price)
            self.current_bar.close = price
            self.current_bar.volume += volume
            self.current_bar.trade_count += 1
            total_val = self.current_bar.vwap * (self.current_bar.volume - volume) + price * volume
            self.current_bar.vwap = total_val / self.current_bar.volume if self.current_bar.volume > 0 else price

        return completed_bar

    def get_all_bars(self) -> List[OHLCBar]:
        """Tüm tamamlanmış bar'ları döndür."""
        return list(self.completed_bars)

    def get_last_n_bars(self, n: int) -> List[OHLCBar]:
        """Son n tamamlanmış bar'ı döndür."""
        bars = list(self.completed_bars)
        return bars[-n:] if len(bars) >= n else bars


@dataclass
class IncrementalAssetState:
    """Her hissenin incremental state'i — v1.2 düzeltmeler."""

    instrument_id: int
    ticker: str
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Current price
    price: float = 0.0
    previous_price: float = 0.0
    previous_close_daily: float = 0.0  # Önceki günün kapanış fiyatı

    # Timeframe states (zaman bazlı bar aggregation)
    tf_1m: TimeframeState = field(default_factory=lambda: TimeframeState("1m", timedelta(minutes=1)))
    tf_5m: TimeframeState = field(default_factory=lambda: TimeframeState("5m", timedelta(minutes=5)))
    tf_15m: TimeframeState = field(default_factory=lambda: TimeframeState("15m", timedelta(minutes=15)))
    tf_1h: TimeframeState = field(default_factory=lambda: TimeframeState("1h", timedelta(hours=1)))
    tf_1d: TimeframeState = field(default_factory=lambda: TimeframeState("1d", timedelta(days=1)))

    # Incremental RSI (Wilder's smoothing — tek canonical implementation)
    rsi_14: float = 50.0
    _avg_gain: float = 0.0
    _avg_loss: float = 0.0
    _rsi_initialized: bool = False
    _rsi_period: int = 14

    # Incremental EMA
    ema_12: float = 0.0
    ema_26: float = 0.0
    ema_9_signal: float = 0.0  # MACD signal line
    _ema_initialized: bool = False

    # Incremental ATR (tamamlanmış bar'lardan güncellenir)
    atr_14: float = 0.0
    _atr_initialized: bool = False
    _atr_multiplier: float = 13.0 / 14.0  # Wilder's smoothing

    # Volume stats (rolling window)
    _volume_history: deque = field(default_factory=lambda: deque(maxlen=20))

    # Computed features cache
    features_cache: Dict[str, float] = field(default_factory=dict)
    features_dirty: bool = True

    def process_tick(self, price: float, volume: int, timestamp: datetime):
        """
        Yeni tick → tüm timeframe'leri güncelle.
        Tamamlanan bar'lar → indicator güncelleme.
        """
        self.previous_price = self.price
        self.price = price
        self.last_update = timestamp

        # Her timeframe için tick'i işle
        for tf in [self.tf_1m, self.tf_5m, self.tf_15m, self.tf_1h, self.tf_1d]:
            completed_bar = tf.process_tick(price, volume, timestamp)

            # 1m bar tamamlandı → RSI, EMA güncelle
            if tf == self.tf_1m and completed_bar:
                self._update_rsi(completed_bar.close)
                self._update_ema(completed_bar.close)

            # 1m bar tamamlandı → ATR güncelle (completed bar'dan)
            if tf == self.tf_1m and completed_bar:
                self._update_atr_from_bar(completed_bar)

            # 1d bar tamamlandı → günlük referans fiyat güncelle
            if tf == self.tf_1d and completed_bar:
                self.previous_close_daily = completed_bar.close

        # Volume history
        self._volume_history.append(volume)

        self.features_dirty = True

    # =====================================================
    # RSI — Wilder's Smoothing (tek canonical implementation)
    # =====================================================

    def _update_rsi(self, close: float):
        """Wilder's RSI — incremental."""
        if self.previous_price == 0:
            return

        change = close - self.previous_price
        gain = max(change, 0)
        loss = max(-change, 0)

        if not self._rsi_initialized:
            self._avg_gain = gain
            self._avg_loss = loss
            self._rsi_initialized = True
        else:
            # Wilder's smoothing: (prev * (period-1) + current) / period
            self._avg_gain = (self._avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
            self._avg_loss = (self._avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period

        if self._avg_loss == 0:
            self.rsi_14 = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.rsi_14 = 100 - (100 / (1 + rs))

    # =====================================================
    # EMA — Incremental (MACD signal dahil)
    # =====================================================

    def _update_ema(self, close: float):
        """Incremental EMA + MACD signal line."""
        if not self._ema_initialized:
            self.ema_12 = close
            self.ema_26 = close
            self.ema_9_signal = close - close  # MACD = 0
            self._ema_initialized = True
        else:
            alpha_12 = 2.0 / 13
            alpha_26 = 2.0 / 27
            alpha_9 = 2.0 / 10

            self.ema_12 = alpha_12 * close + (1 - alpha_12) * self.ema_12
            self.ema_26 = alpha_26 * close + (1 - alpha_26) * self.ema_26

            macd_line = self.ema_12 - self.ema_26
            self.ema_9_signal = alpha_9 * macd_line + (1 - alpha_9) * self.ema_9_signal

    # =====================================================
    # ATR — Tamamlanmış Bar'lardan (Wilder's)
    # =====================================================

    def _update_atr_from_bar(self, bar: OHLCBar):
        """ATR güncelle — completed bar'dan, tick'ten değil."""
        if self.previous_price == 0:
            # İlk bar, TR hesaplanamaz
            return

        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        prev_close = self.previous_price
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )

        if not self._atr_initialized:
            self.atr_14 = tr
            self._atr_initialized = True
        else:
            # Wilder's ATR smoothing
            self.atr_14 = (self.atr_14 * self._atr_multiplier + tr * (1 - self._atr_multiplier))

    # =====================================================
    # Feature Output
    # =====================================================

    def get_incremental_features(self) -> Dict[str, float]:
        """Incremental feature'ları döndür."""
        if not self.features_dirty:
            return self.features_cache

        features = {}

        # Price
        features["price"] = self.price

        # Return 1d (önceki güne göre)
        if self.previous_close_daily > 0:
            features["return_1d"] = (self.price / self.previous_close_daily - 1) * 100

        # RSI
        features["rsi_14"] = self.rsi_14

        # EMA
        features["ema_12"] = self.ema_12
        features["ema_26"] = self.ema_26

        # MACD (gerçek signal line ile)
        macd_line = self.ema_12 - self.ema_26
        features["macd"] = macd_line
        features["macd_signal"] = self.ema_9_signal
        features["macd_histogram"] = macd_line - self.ema_9_signal

        # ATR
        features["atr_14"] = self.atr_14
        if self.price > 0:
            features["atr_14_pct"] = self.atr_14 / self.price * 100

        # Volume stats
        if len(self._volume_history) >= 5:
            vol_arr = np.array(list(self._volume_history))
            features["volume_avg"] = float(np.mean(vol_arr))
            vol_std = float(np.std(vol_arr))
            if vol_std > 0:
                features["volume_zscore"] = (vol_arr[-1] - features["volume_avg"]) / vol_std

        # Momentum from completed bars
        bars_1d = self.tf_1d.get_all_bars()
        if len(bars_1d) >= 5:
            features["momentum_5d"] = (bars_1d[-1].close / bars_1d[-5].close - 1) * 100
        if len(bars_1d) >= 20:
            features["momentum_20d"] = (bars_1d[-1].close / bars_1d[-20].close - 1) * 100

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
                instrument_id=instrument_id, ticker=ticker,
            )
        return self._states[instrument_id]

    def process_tick(self, instrument_id: int, ticker: str,
                     price: float, volume: int, timestamp: datetime):
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
