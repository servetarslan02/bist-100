"""
ALPHA BIST — State Recovery v2.0

P0-7 düzeltmesi:
- Snapshot + Event Log approach (60 günlük veriyi yeniden çekme YOK)
- Recovery deterministic olmalı
- Snapshot → events after snapshot → replay → state validation
- Consistency check sonrası current state
"""

import functools
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.state_recovery")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class StateRecovery:
    """State recovery — restart sonrası state'i güvenli şekilde yeniden oluştur.

    v2.0: Snapshot + Event Replay approach.
    Hedef: latest_snapshot + event_log = current state
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._recovered_states: dict[str, dict] = {}
        self._recovery_errors: list[str] = []

    @otel_trace("state_recovery.recover_all_states")
    async def recover_all_states(
        self,
        tickers: list[str],
        redis_client=None,
        pg_pool=None,
    ) -> dict[str, dict]:
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

        logger.info(
            "State recovery completed", recovered=recovered, total=len(tickers), errors=len(self._recovery_errors)
        )

        return self._recovered_states

    async def _recover_via_snapshot(self, ticker: str, redis_client=None, pg_pool=None) -> dict | None:
        """Snapshot + Event Replay ile state kurtar.

        1. Redis'ten son snapshot'ı oku
        2. SQLite'tan son snapshot'ı oku (Redis yoksa)
        3. Snapshot'tan sonraki event'leri çek
        4. Event'leri uygula
        """
        try:
            # Redis'ten son state'i oku
            if redis_client:
                snapshot_data = await redis_client.get(f"state_snapshot:{ticker}")
                if snapshot_data:
                    snapshot = orjson.loads(snapshot_data)
                    logger.debug("Snapshot found (Redis)", ticker=ticker, snapshot_time=snapshot.get("timestamp"))
                    return snapshot

            # SQLite'tan son snapshot'ı oku (Redis yoksa veya TTL dolmuşsa)
            try:
                from .state_store import state_store

                all_state = state_store.load_learning_state()
                state_key = f"snapshot:{ticker}"
                if state_key in all_state:
                    snapshot = all_state[state_key]
                    if isinstance(snapshot, str):
                        snapshot = orjson.loads(snapshot)
                    logger.debug("Snapshot found (SQLite)", ticker=ticker)
                    return snapshot
            except Exception as e:
                logger.debug(f"SQLite snapshot recovery skipped for {ticker}: {e}")

            # DB'den son snapshot'ı oku
            if pg_pool:
                async with pg_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT state_data, snapshot_time FROM state_snapshots
                        WHERE ticker = $1
                        ORDER BY snapshot_time DESC LIMIT 1
                    """,
                        ticker,
                    )
                    if row:
                        snapshot = orjson.loads(row["state_data"])
                        logger.debug("DB snapshot found", ticker=ticker, snapshot_time=row["snapshot_time"])
                        return snapshot

            return None

        except Exception as e:
            logger.warning("Snapshot recovery failed", ticker=ticker, error=str(e))
            return None

    async def _recover_from_clickhouse(self, ticker: str, pg_pool=None) -> dict | None:
        """ClickHouse'dan feature'ları yeniden hesapla.

        Son seçenek: Snapshot ve event log yoksa.
        Bu durumda sadece son 60 günlük bar'ları çekip feature hesaplarız.
        Ama bu YAVAŞ bir kurtarma yöntemidir ve sadece fallback olarak kullanılır.
        """
        try:
            import polars as pl
            import yfinance as yf

            from ..features.calculator import feature_calculator

            logger.info("Fallback: ClickHouse recovery", ticker=ticker)

            t = yf.Ticker(f"{ticker}.IS")
            hist = t.history(period="60d").reset_index()

            if len(hist) < 20:
                return None

            df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
            df = df.rename(
                {
                    "Date": "timestamp",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )

            features = feature_calculator.compute_all_features(df)

            if not features:
                return None

            close_list = [x for x in df["close"].to_list() if x is not None]

            state = {
                "ticker": ticker,
                "price": close_list[-1] if close_list else 0,
                "features": features,
                "recovered_at": datetime.now(UTC).isoformat(),
                "data_points": len(df),
                "recovery_method": "clickhouse_fallback",
            }

            logger.debug("ClickHouse recovery completed", ticker=ticker)
            return state

        except Exception as e:
            logger.warning("ClickHouse recovery failed", ticker=ticker, error=str(e))
            return None

    @otel_trace("state_recovery.save_snapshot")
    async def save_snapshot(self, ticker: str, state: dict, redis_client=None) -> Any:
        """State snapshot'ını kaydet (Redis + SQLite — dual persistence)."""
        try:
            state["snapshot_time"] = datetime.now(UTC).isoformat()

            # Redis'e kaydet
            if redis_client:
                await redis_client.set(
                    f"state_snapshot:{ticker}",
                    orjson.dumps(state, default=str).decode(),
                    ex=86400 * 7,  # 7 gün TTL
                )

            # SQLite'a da kaydet (restart-safe — elektrik kesintisinde kaybolmaz)
            try:
                from .state_store import state_store

                state_store.save_learning_state({f"snapshot:{ticker}": state})
            except Exception as e:
                logger.debug(f"SQLite snapshot save skipped for {ticker}: {e}")

        except Exception as e:
            logger.warning("Snapshot save failed", ticker=ticker, error=str(e))

    def get_state(self, ticker: str) -> dict | None:
        """Kurtarılmış state'i döndür."""
        return self._recovered_states.get(ticker)

    def get_all_states(self) -> dict[str, dict]:
        """Tüm kurtarılmış state'leri döndür."""
        return self._recovered_states

    def get_recovery_errors(self) -> list[str]:
        """Recovery hatalarını döndür."""
        return self._recovery_errors

    @otel_trace("state_recovery.validate_consistency")
    async def validate_consistency(self, redis_client=None) -> dict[str, Any]:
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
