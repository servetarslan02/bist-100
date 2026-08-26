"""
ALPHA BIST — Market Player

Geçmiş piyasa verilerini "canlı gibi" oynatan motor.
"""

import pandas as pd
import polars as pl
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Generator, Callable
from dataclasses import dataclass
from enum import Enum
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class PlaybackSpeed(Enum):
    REALTIME = 1.0
    FAST_10X = 10.0
    FAST_100X = 100.0
    MAX = float("inf")


@dataclass
class TickData:
    timestamp: datetime
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    phase: str = "CONTINUOUS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "ticker": self.ticker,
            "open": round(self.open, 4), "high": round(self.high, 4),
            "low": round(self.low, 4), "close": round(self.close, 4),
            "volume": self.volume, "phase": self.phase,
        }


class MarketPlayer:
    """Geçmiş piyasa verisini oynatan motor."""

    def __init__(self):
        self._data: Optional[pl.DataFrame] = None
        self._tickers: List[str] = []
        self._is_playing: bool = False
        self._is_paused: bool = False
        self._current_index: int = 0
        self._total_ticks: int = 0
        self._speed: PlaybackSpeed = PlaybackSpeed.FAST_10X
        self._ticks_processed: int = 0
        self._on_tick_callbacks: List[Callable] = []

    def load_data(
        self,
        start_date: str,
        end_date: str,
        tickers: Optional[List[str]] = None,
        source: str = "yfinance",
    ) -> Dict[str, Any]:
        """Tarihsel veriyi yükle (BIST-100)."""
        result = {"start_date": start_date, "end_date": end_date, "source": source}

        try:
            if source == "yfinance":
                import yfinance as yf
                from services.ingestion.bist_universe import bist_universe

                if tickers is None:
                    tickers = bist_universe.BIST_100_TICKERS
                    if not tickers:
                        tickers = bist_universe.BIST_ALL_TICKERS[:100]

                self._tickers = tickers
                download_tickers = [f"{t}.IS" for t in tickers]

                raw = yf.download(
                    tickers=" ".join(download_tickers),
                    start=start_date, end=end_date,
                    group_by="ticker", auto_adjust=True, progress=False, threads=True,
                )

                if not raw.empty:
                    frames = []
                    for t in tickers:
                        tick_sym = f"{t}.IS"
                        try:
                            if isinstance(raw.columns, pd.MultiIndex) and tick_sym in raw.columns.levels[0]:
                                df_t = raw[tick_sym].dropna(how="all")
                                if not df_t.empty:
                                    df_t = df_t.copy()
                                    df_t = df_t.with_columns(pl.lit(t).alias('ticker'))
                                    frames.append(df_t)
                        except Exception:
                            continue

                    if frames:
                        self._data = pl.concat(frames).sort_index()
                        self._total_ticks = len(self._data)
                        result = result.with_columns(pl.lit("ok").alias('status'))
                        result = result.with_columns(pl.lit(len(frames)).alias('tickers_loaded'))
                        result = result.with_columns(pl.lit(self._total_ticks).alias('total_ticks'))
                    else:
                        result = result.with_columns(pl.lit("empty").alias('status'))
                else:
                    result = result.with_columns(pl.lit("empty").alias('status'))
        except Exception as e:
            result = result.with_columns(pl.lit("failed").alias('status'))
            result = result.with_columns(pl.lit(str(e)).alias('error'))

        return result

    def set_speed(self, speed: PlaybackSpeed):
        self._speed = speed

    def on_tick(self, callback: Callable):
        self._on_tick_callbacks.append(callback)

    def play(self, start_index: int = 0, max_ticks: Optional[int] = None) -> Generator[TickData, None, None]:
        """Veriyi oynat."""
        if self._data is None or self._data.empty:
            return

        self._is_playing = True
        self._current_index = start_index
        self._ticks_processed = 0
        end_index = min(len(self._data), start_index + max_ticks if max_ticks else len(self._data))

        try:
            for idx in range(start_index, end_index):
                if not self._is_playing:
                    break
                while self._is_paused:
                    import time; time.sleep(0.1)
                    if not self._is_playing:
                        break

                row = self._data[idx]
                ticker = row.get("ticker", "UNKNOWN")
                ts = self._data.index[idx]
                if hasattr(ts, 'to_pydatetime'):
                    ts = ts.to_pydatetime()

                from datetime import time as dt_time
                t = ts.time() if hasattr(ts, 'time') else ts
                if t < dt_time(9, 40): phase = "CLOSED"
                elif t < dt_time(10, 0): phase = "OPENING_AUCTION"
                elif t < dt_time(18, 0): phase = "CONTINUOUS"
                elif t < dt_time(18, 10): phase = "CLOSING_AUCTION"
                else: phase = "CLOSED"

                tick = TickData(
                    timestamp=ts, ticker=ticker,
                    open=float(row.get("Open", 0)), high=float(row.get("High", 0)),
                    low=float(row.get("Low", 0)), close=float(row.get("Close", 0)),
                    volume=int(row.get("Volume", 0)), phase=phase,
                )

                self._current_index = idx
                self._ticks_processed += 1

                for cb in self._on_tick_callbacks:
                    try:
                        cb(tick)
                    except Exception as e:
                        logger.debug("Tick callback error", error=str(e))

                yield tick

        except KeyboardInterrupt:
            logger.info("Playback interrupted by user")
        finally:
            self._is_playing = False

    def pause(self): self._is_paused = True
    def resume(self): self._is_paused = False
    def stop(self): self._is_playing = False; self._is_paused = False

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_playing": self._is_playing, "is_paused": self._is_paused,
            "current_index": self._current_index, "total_ticks": self._total_ticks,
            "ticks_processed": self._ticks_processed, "speed": self._speed.value,
            "data_loaded": self._data is not None, "tickers": len(self._tickers),
        }


market_player = MarketPlayer()
