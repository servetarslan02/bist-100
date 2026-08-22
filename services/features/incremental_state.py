"""ALPHA BIST - Incremental Feature State v1.3

v1.3: Bar aggregation artık bar_engine.py'den kullanılıyor (kod tekrarı kaldırıldı).
v1.2 Düzeltmeler:
- ATR: completed bar'dan güncellenir, tick'ten değil
- RSI: tek canonical Wilder implementation
- MACD signal: gerçek 9-period EMA
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import deque
import structlog

from .bar_engine import BarEngine, Bar

logger = structlog.get_logger()


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

    # Bar engine (bar_engine.py'den — kod tekrarı yok)
    _bar_engine: Any = field(default=None, repr=False)

    def __post_init__(self):
        if self._bar_engine is None:
            self._bar_engine = BarEngine(self.ticker)

    # Incremental RSI (Wilder's smoothing — tek canonical implementation)
    rsi_14: float = 50.0
    _avg_gain: float = 0.0
    _avg_loss: float = 0.0
    _rsi_initialized: bool = False
    _rsi_period: int = 14
    _last_bar_close: float = 0.0  # RSI için önceki bar'ın kapanışı

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
        Yeni tick → bar_engine ile bar'ları güncelle.
        Tamamlanan bar'lar → indicator güncelleme.
        """
        self.previous_price = self.price
        self.price = price
        self.last_update = timestamp

        # Bar engine ile tick'i işle → completed bar'ları al
        completed = self._bar_engine.process_tick(price, volume, timestamp)

        for tf_name, bar in completed:
            # 1m bar tamamlandı → RSI, EMA, ATR güncelle
            if tf_name == "1m":
                self._update_rsi(bar.close)
                self._last_bar_close = bar.close
                self._update_ema(bar.close)
                self._update_atr_from_bar(bar)

            # 1d bar tamamlandı → günlük referans fiyat güncelle
            if tf_name == "1d":
                self.previous_close_daily = bar.close

        # Volume history
        self._volume_history.append(volume)
        if len(self._volume_history) > 1000:
            self._volume_history = self._volume_history[-1000:]

        self.features_dirty = True

    # =====================================================
    # RSI — Wilder's Smoothing (tek canonical implementation)
    # =====================================================

    def _update_rsi(self, close: float):
        """Wilder's RSI — incremental.

        close: tamamlanmış bar'ın kapanış fiyatı.
        change: bu bar ile önceki bar arasındaki değişim.
        """
        if self._last_bar_close == 0:
            # İlk bar — RSI hesaplanamaz, referans fiyat kaydet
            self._last_bar_close = close
            return

        change = close - self._last_bar_close
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

    def _update_atr_from_bar(self, bar):
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

        # Momentum from completed bars (bar_engine'den)
        bars_1d = self._bar_engine.get_bars("1d")
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
        """State getir veya olustur."""
        if instrument_id not in self._states:
            self._states[instrument_id] = IncrementalAssetState(
                instrument_id=instrument_id, ticker=ticker,
            )
        return self._states[instrument_id]

    def process_tick(self, instrument_id: int, ticker: str,
                     price: float, volume: int, timestamp: datetime):
        """Tick verisini isle ve state guncelle."""
        state = self.get_or_create(instrument_id, ticker)
        state.process_tick(price, volume, timestamp)
        return state

    def get_state(self, instrument_id: int) -> Optional[IncrementalAssetState]:
        """Ticker icin state dondur."""
        return self._states.get(instrument_id)

    def get_all_states(self) -> Dict[int, IncrementalAssetState]:
        """Tum state'leri dondur."""
        return self._states

    def get_features(self, instrument_id: int) -> Dict[str, float]:
        """Ticker icin feature'lari dondur."""
        state = self._states.get(instrument_id)
        if state:
            return state.get_incremental_features()
        return {}


# Singleton
state_manager = IncrementalStateManager()
