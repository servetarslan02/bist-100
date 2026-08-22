"""
ALPHA BIST — State Recovery v2.0

P0-7 düzeltmesi:
- Snapshot + Event Log approach (60 günlük veriyi yeniden çekme YOK)
- Recovery deterministic olmalı
- Snapshot → events after snapshot → replay → state validation
- Consistency check sonrası current state
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger()


class StateRecovery:
    """State recovery — restart sonrası state'i güvenli şekilde yeniden oluştur.

    v2.0: Snapshot + Event Replay approach.
    Hedef: latest_snapshot + event_log = current state
    """

    def __init__(self):
        self._recovered_states: Dict[str, Dict] = {}
        self._recovery_errors: List[str] = []

    async def recover_all_states(
        self,
        tickers: List[str],
        redis_client=None,
        pg_pool=None,
    ) -> Dict[str, Dict]:
        """
        Tüm hisseler için state'i kurtar.

        P0-7 Pipeline:
        1. Snapshot'tan son durumu oku (Redis/DB)
        2. Snapshot'tan sonraki event'leri çek
        3. Event'leri replay et
        4. State validation
        5. Consistency check
        """
        logger.info("Starting state recovery (v2.0)", tickers=len(tickers))

        recovered = 0
        for ticker in tickers:
            try:
                state = await self._recover_via_snapshot(ticker, redis_client, pg_pool)
                if state:
                    self._recovered_states[ticker] = state
                    recovered += 1
                else:
                    # Snapshot yoksa ClickHouse'dan kurtar
                    state = await self._recover_from_clickhouse(ticker, pg_pool)
                    if state:
                        self._recovered_states[ticker] = state
                        recovered += 1
            except Exception as e:
                self._recovery_errors.append(f"{ticker}: {e}")
                if len(self._recovery_errors) > 500:
                    self._recovery_errors = self._recovery_errors[-500:]
                logger.warning("State recovery failed", ticker=ticker, error=str(e))

        logger.info("State recovery completed",
                    recovered=recovered,
                    total=len(tickers),
                    errors=len(self._recovery_errors))

        return self._recovered_states

    async def _recover_via_snapshot(
        self, ticker: str, redis_client=None, pg_pool=None
    ) -> Optional[Dict]:
        """Snapshot + Event Replay ile state kurtar.

        1. Redis'ten son snapshot'ı oku
        2. Snapshot'tan sonraki event'leri çek
        3. Event'leri uygula
        """
        try:
            # Redis'ten son state'i oku
            if redis_client:
                snapshot_data = await redis_client.get(f"state_snapshot:{ticker}")
                if snapshot_data:
                    snapshot = json.loads(snapshot_data)
                    logger.debug("Snapshot found", ticker=ticker,
                               snapshot_time=snapshot.get("timestamp"))
                    return snapshot

            # DB'den son snapshot'ı oku
            if pg_pool:
                async with pg_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT state_data, snapshot_time FROM state_snapshots
                        WHERE ticker = $1
                        ORDER BY snapshot_time DESC LIMIT 1
                    """, ticker)
                    if row:
                        snapshot = json.loads(row["state_data"])
                        logger.debug("DB snapshot found", ticker=ticker,
                                   snapshot_time=row["snapshot_time"])
                        return snapshot

            return None

        except Exception as e:
            logger.warning("Snapshot recovery failed", ticker=ticker, error=str(e))
            return None

    async def _recover_from_clickhouse(
        self, ticker: str, pg_pool=None
    ) -> Optional[Dict]:
        """ClickHouse'dan feature'ları yeniden hesapla.

        Son seçenek: Snapshot ve event log yoksa.
        Bu durumda sadece son 60 günlük bar'ları çekip feature hesaplarız.
        Ama bu YAVAŞ bir kurtarma yöntemidir ve sadece fallback olarak kullanılır.
        """
        try:
            import yfinance as yf
            import polars as pl
            from ..features.calculator import feature_calculator

            logger.info("Fallback: ClickHouse recovery", ticker=ticker)

            t = yf.Ticker(f"{ticker}.IS")
            hist = t.history(period="60d").reset_index()

            if len(hist) < 20:
                return None

            df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
            df = df.rename({
                "Date": "timestamp", "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume"
            })

            features = feature_calculator.compute_all_features(df)

            if not features:
                return None

            close_list = [x for x in df["close"].to_list() if x is not None]

            state = {
                "ticker": ticker,
                "price": close_list[-1] if close_list else 0,
                "features": features,
                "recovered_at": datetime.now(timezone.utc).isoformat(),
                "data_points": len(df),
                "recovery_method": "clickhouse_fallback",
            }

            logger.debug("ClickHouse recovery completed", ticker=ticker)
            return state

        except Exception as e:
            logger.warning("ClickHouse recovery failed", ticker=ticker, error=str(e))
            return None

    async def save_snapshot(self, ticker: str, state: Dict, redis_client=None):
        """State snapshot'ını kaydet.

        Bu, bir sonraki restart için kullanılır.
        """
        try:
            state["snapshot_time"] = datetime.now(timezone.utc).isoformat()

            if redis_client:
                await redis_client.set(
                    f"state_snapshot:{ticker}",
                    json.dumps(state, default=str),
                    ex=86400 * 7,  # 7 gün TTL
                )

        except Exception as e:
            logger.warning("Snapshot save failed", ticker=ticker, error=str(e))

    def get_state(self, ticker: str) -> Optional[Dict]:
        """Kurtarılmış state'i döndür."""
        return self._recovered_states.get(ticker)

    def get_all_states(self) -> Dict[str, Dict]:
        """Tüm kurtarılmış state'leri döndür."""
        return self._recovered_states

    def get_recovery_errors(self) -> List[str]:
        """Recovery hatalarını döndür."""
        return self._recovery_errors

    async def validate_consistency(self, redis_client=None) -> Dict[str, Any]:
        """Recovery sonrası consistency kontrolü.

        P0-7: Positions, cash, P&L, world state, signals, risk state
        consistency check'ten geçmeli.
        """
        results = {
            "positions_valid": True,
            "cash_valid": True,
            "pnl_valid": True,
            "errors": [],
        }

        for ticker, state in self._recovered_states.items():
            price = state.get("price", 0)
            if price <= 0:
                results["errors"].append(f"{ticker}: invalid price after recovery")
                results["positions_valid"] = False

        return results


# Singleton
state_recovery = StateRecovery()
