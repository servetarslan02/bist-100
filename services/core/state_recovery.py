"""
ALPHA BIST — State Recovery v1.0

Laptop kapanırsa ne olur?
→ ClickHouse'dan son N bar'ı çek
→ State'i yeniden oluştur
→ Canlı devam et

Bu modül restart/warm start için.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


class StateRecovery:
    """State recovery — restart sonrası incremental state'i yeniden oluştur."""

    def __init__(self):
        self._recovered_states: Dict[str, Dict] = {}

    async def recover_all_states(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Tüm hisseler için state'i kurtar.
        ClickHouse'dan son 60 günlük bar'ları çek → feature'ları hesapla → state oluştur.
        """
        logger.info("Starting state recovery", tickers=len(tickers))

        for ticker in tickers:
            try:
                state = await self._recover_single_state(ticker)
                if state:
                    self._recovered_states[ticker] = state
            except Exception as e:
                logger.warning("State recovery failed", ticker=ticker, error=str(e))

        logger.info("State recovery completed",
                    recovered=len(self._recovered_states),
                    total=len(tickers))

        return self._recovered_states

    async def _recover_single_state(self, ticker: str) -> Optional[Dict]:
        """Tek bir hisse için state kurtar."""
        try:
            # ClickHouse'dan son 60 günlük bar'ları çek
            # (Gerçek implementasyonda ClickHouse'dan okunacak)
            # Şimdilik yfinance ile
            import yfinance as yf
            import polars as pl
            from ..features.calculator import FeatureCalculator

            t = yf.Ticker(f"{ticker}.IS")
            hist = t.history(period="60d").reset_index()

            if len(hist) < 20:
                return None

            df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
            df = df.rename({
                "Date": "timestamp", "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume"
            })

            # Feature'ları hesapla
            fc = FeatureCalculator()
            features = fc.compute_all_features(df)

            if not features:
                return None

            close_list = [x for x in df["close"].to_list() if x is not None]

            state = {
                "ticker": ticker,
                "price": close_list[-1] if close_list else 0,
                "features": features,
                "recovered_at": datetime.utcnow().isoformat(),
                "data_points": len(df),
            }

            logger.debug("State recovered", ticker=ticker, features=len(features))
            return state

        except Exception as e:
            logger.warning("Single state recovery failed", ticker=ticker, error=str(e))
            return None

    def get_state(self, ticker: str) -> Optional[Dict]:
        """Kurtarılmış state'i döndür."""
        return self._recovered_states.get(ticker)

    def get_all_states(self) -> Dict[str, Dict]:
        """Tüm kurtarılmış state'leri döndür."""
        return self._recovered_states


# Singleton
state_recovery = StateRecovery()
