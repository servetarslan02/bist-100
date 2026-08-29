"""ALPHA BIST - Replay Engine v1.1

Geçmişi canlıymış gibi oynatır.
"13 Mart 2025 10:37'de ne biliyorsam sadece onu kullanarak karar ver."
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()


@dataclass
class ReplayConfig:
    """Replay konfigürasyonu."""

    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000
    commission_rate: float = 0.001  # %0.1
    slippage_rate: float = 0.0005  # %0.05
    max_position_pct: float = 0.10  # %10
    tick_interval_seconds: int = 60  # 1 dakika


@dataclass
class ReplayEvent:
    """Replay sırasında oluşan olay."""

    timestamp: datetime
    event_type: str
    data: dict[str, Any]


@dataclass
class ReplayTrade:
    """Replay sırasında yapılan işlem."""

    timestamp: datetime
    ticker: str
    side: str  # BUY / SELL
    quantity: int
    price: float
    commission: float
    slippage: float
    signal_score: float
    signal_type: str


@dataclass
class ReplayResult:
    """Replay sonucu."""

    config: ReplayConfig
    trades: list[ReplayTrade]
    equity_curve: list[tuple[datetime, float]]
    metrics: dict[str, float]
    predictions: list[dict[str, Any]]


class ReplayEngine:
    """
    Historical event replay engine.
    Geçmiş veriyi zaman sırasıyla oynatır, sistem o anda geleceği bilmez.
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._handlers: dict[str, Callable] = {}
        self._state: dict[str, Any] = {}

    def on(self, event_type: str, handler: Callable) -> Any:
        """Event handler kaydet."""
        self._handlers[event_type] = handler
        return self

    def run(
        self, config: ReplayConfig, historical_data: pl.DataFrame, events: list[ReplayEvent] | None = None
    ) -> ReplayResult:
        """
        Replay çalıştır.

        Args:
            config: Replay konfigürasyonu
            historical_data: OHLCV verisi (timestamp, ticker, open, high, low, close, volume)
            events: Opsiyonel historical events (KAP, haber vb.)
        """
        logger.info("Starting replay", start=config.start_date, end=config.end_date, data_points=len(historical_data))

        # Initialize
        capital = config.initial_capital
        cash = capital
        positions: dict[str, dict] = {}
        trades: list[ReplayTrade] = []
        equity_curve: list[tuple[datetime, float]] = []
        predictions: list[dict[str, Any]] = []

        # Sort data by timestamp
        data = historical_data.sort("timestamp")

        # Filter to replay window
        data = data.filter((pl.col("timestamp") >= config.start_date) & (pl.col("timestamp") <= config.end_date))

        # Merge events if provided
        event_queue = sorted(events or [], key=lambda e: e.timestamp)

        # Get unique timestamps
        timestamps = data["timestamp"].unique().sort()

        logger.info("Replay window", timestamps=len(timestamps), data_points=len(data))

        # Process each timestamp
        for ts in timestamps:
            # Get data up to this point (no look-ahead!)
            available_data = data.filter(pl.col("timestamp") <= ts)

            # Get current prices
            current_prices = {}
            ts_data = data.filter(pl.col("timestamp") == ts)
            for row in ts_data.iter_rows(named=True):
                current_prices[row["ticker"]] = row["close"]

            # Process events at this timestamp
            while event_queue and event_queue[0].timestamp <= ts:
                event = event_queue.pop(0)
                handler = self._handlers.get(event.event_type)
                if handler:
                    try:
                        handler(
                            event,
                            {
                                "available_data": available_data,
                                "current_prices": current_prices,
                                "positions": positions,
                                "cash": cash,
                                "timestamp": ts,
                            },
                        )
                    except Exception as e:
                        logger.warning("Event handler error", event_type=event.event_type, error=str(e))

            # Process market data handlers
            handler = self._handlers.get("market.tick")
            if handler:
                try:
                    result = handler(
                        None,
                        {
                            "available_data": available_data,
                            "current_prices": current_prices,
                            "positions": positions,
                            "cash": cash,
                            "timestamp": ts,
                        },
                    )

                    # Handle trades
                    if result and "trades" in result:
                        for trade_data in result["trades"]:
                            trade = self._execute_trade(trade_data, current_prices, config, ts)
                            if trade:
                                trades.append(trade)
                                if trade.side == "BUY":
                                    cash -= trade.quantity * trade.price + trade.commission
                                    positions[trade.ticker] = {
                                        "quantity": trade.quantity,
                                        "avg_cost": trade.price,
                                    }
                                elif trade.side == "SELL":
                                    cash += trade.quantity * trade.price - trade.commission
                                    if trade.ticker in positions:
                                        del positions[trade.ticker]

                    # Handle predictions
                    if result and "predictions" in result:
                        predictions.extend(result["predictions"])

                except Exception as e:
                    logger.warning("Tick handler error", error=str(e))

            # Calculate equity
            portfolio_value = cash
            for ticker, pos in positions.items():
                price = current_prices.get(ticker, pos["avg_cost"])
                portfolio_value += pos["quantity"] * price

            equity_curve.append((ts, portfolio_value))

        # Calculate metrics
        metrics = self._calculate_metrics(equity_curve, trades, config)

        logger.info(
            "Replay complete",
            trades=len(trades),
            final_equity=equity_curve[-1][1] if equity_curve else 0,
            return_pct=metrics.get("total_return_pct", 0),
        )

        return ReplayResult(
            config=config,
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
            predictions=predictions,
        )

    def _execute_trade(
        self, trade_data: dict, prices: dict[str, float], config: ReplayConfig, timestamp: datetime
    ) -> ReplayTrade | None:
        """İşlemi simüle et (slippage + commission)."""
        ticker = trade_data.get("ticker")
        side = trade_data.get("side")
        quantity = trade_data.get("quantity", 0)
        signal_score = trade_data.get("signal_score", 0)
        signal_type = trade_data.get("signal_type", "")

        if not ticker or ticker not in prices:
            return None

        price = prices[ticker]

        # Apply slippage
        exec_price = price * (1 + config.slippage_rate) if side == "BUY" else price * (1 - config.slippage_rate)

        # Commission
        commission = quantity * exec_price * config.commission_rate

        return ReplayTrade(
            timestamp=timestamp,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=exec_price,
            commission=commission,
            slippage=abs(exec_price - price),
            signal_score=signal_score,
            signal_type=signal_type,
        )

    def _calculate_metrics(
        self, equity_curve: list[tuple[datetime, float]], trades: list[ReplayTrade], config: ReplayConfig
    ) -> dict[str, float]:
        """Performans metrikleri hesapla."""
        if not equity_curve:
            return {}

        equities = [e[1] for e in equity_curve]
        returns = np.diff(equities) / equities[:-1]

        # Total return
        total_return = (equities[-1] / config.initial_capital - 1) * 100

        # Annualized return
        days = (equity_curve[-1][0] - equity_curve[0][0]).days
        ann_return = ((equities[-1] / config.initial_capital) ** (365 / max(days, 1)) - 1) * 100

        # Sharpe ratio (annualized)
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if len(returns) > 1 and np.std(returns) > 0 else 0

        # Max drawdown
        peak = equities[0]
        max_dd = 0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Win rate
        if trades:
            buy_trades = [t for t in trades if t.side == "BUY"]
            sell_trades = [t for t in trades if t.side == "SELL"]

            # Match buy/sell pairs
            wins = 0
            losses = 0
            for sell in sell_trades:
                # Find matching buy
                matching_buys = [b for b in buy_trades if b.ticker == sell.ticker and b.timestamp < sell.timestamp]
                if matching_buys:
                    buy = matching_buys[-1]
                    if sell.price > buy.price:
                        wins += 1
                    else:
                        losses += 1

            win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        else:
            win_rate = 0

        # Profit factor
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "total_return_pct": round(total_return, 2),
            "annualized_return_pct": round(ann_return, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 3),
            "total_trades": len(trades),
            "trading_days": days,
        }


# =====================================================
# Walk-Forward Validation
# =====================================================


class WalkForwardValidator:
    """
    Purged Walk-Forward Validation.
    Train/test split'leri zaman bazlı, purge ve embargo ile.
    """

    def __init__(self, train_months: int = 12, test_months: int = 1, purge_days: int = 5, embargo_days: int = 5):
        """Otomatik eklendi."""
        self.train_months = train_months
        self.test_months = test_months
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(
        self, data: pl.DataFrame, date_column: str = "timestamp"
    ) -> list[tuple[pl.DataFrame, pl.DataFrame, datetime, datetime]]:
        """
        Walk-forward split'leri üret.

        Returns: List of (train_data, test_data, test_start, test_end)
        """
        data = data.sort(date_column)
        min_date = data[date_column].min()
        max_date = data[date_column].max()

        splits = []
        current_test_start = min_date + timedelta(days=self.train_months * 30)

        while current_test_start < max_date:
            test_end = current_test_start + timedelta(days=self.test_months * 30)
            train_end = current_test_start - timedelta(days=self.purge_days)
            train_start = train_end - timedelta(days=self.train_months * 30)
            embargo_start = current_test_start - timedelta(days=self.embargo_days)

            # Train: train_start'tan train_end'e kadar
            train = data.filter((pl.col(date_column) >= train_start) & (pl.col(date_column) <= train_end))

            # Test: current_test_start'tan test_end'e kadar
            test = data.filter((pl.col(date_column) >= current_test_start) & (pl.col(date_column) <= test_end))

            # Purge: train_end ile current_test_start arasındaki veriyi çıkar
            # (zaten filtrelenmiş)

            # Embargo: train sonuna yakın veriyi çıkar
            if self.embargo_days > 0:
                train = train.filter(pl.col(date_column) < embargo_start)

            if len(train) > 100 and len(test) > 20:
                splits.append((train, test, current_test_start, test_end))

            current_test_start = test_end

        logger.info("Walk-forward splits generated", count=len(splits))
        return splits

    def validate(
        self, data: pl.DataFrame, feature_names: list[str], target_column: str, date_column: str = "timestamp"
    ) -> dict[str, Any]:
        """
        Walk-forward validation çalıştır.

        Returns: Her split için metrikler + ortalama metrikler.
        """
        import lightgbm as lgb
        from sklearn.metrics import mean_squared_error, r2_score

        splits = self.split(data, date_column)
        results = []

        for i, (train, test, test_start, test_end) in enumerate(splits):
            # Prepare features
            available_features = [f for f in feature_names if f in train.columns]
            X_train = train.select(available_features).to_numpy()
            y_train = train.select(target_column).to_numpy().ravel()
            X_test = test.select(available_features).to_numpy()
            y_test = test.select(target_column).to_numpy().ravel()

            # Clean NaN
            train_mask = ~(np.isnan(X_train).any(axis=1) | np.isnan(y_train))
            X_train, y_train = X_train[train_mask], y_train[train_mask]
            test_mask = ~(np.isnan(X_test).any(axis=1) | np.isnan(y_test))
            X_test, y_test = X_test[test_mask], y_test[test_mask]

            if len(X_train) < 50 or len(X_test) < 10:
                continue

            # Train
            model = lgb.LGBMRegressor(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1,
            )
            model.fit(X_train, y_train)

            # Predict
            y_pred = model.predict(X_test)

            # Metrics
            rmse = np.sqrt(mean_squared_error(y_test, y_pred))
            r2 = r2_score(y_test, y_pred)
            dir_acc = np.sum(np.sign(y_pred) == np.sign(y_test)) / len(y_test) * 100

            # Sharpe (if trading on predictions)
            pred_returns = y_test[np.sign(y_pred) == np.sign(y_test)]
            if len(pred_returns) > 0 and np.std(pred_returns) > 0:
                sharpe = np.mean(pred_returns) / np.std(pred_returns) * np.sqrt(252)
            else:
                sharpe = 0

            results.append(
                {
                    "split": i,
                    "test_start": test_start.isoformat(),
                    "test_end": test_end.isoformat(),
                    "train_samples": len(X_train),
                    "test_samples": len(X_test),
                    "rmse": round(rmse, 4),
                    "r2": round(r2, 4),
                    "direction_accuracy": round(dir_acc, 1),
                    "sharpe": round(sharpe, 3),
                }
            )

        # Aggregate
        if results:
            avg_metrics = {
                "avg_rmse": round(np.mean([r["rmse"] for r in results]), 4),
                "avg_r2": round(np.mean([r["r2"] for r in results]), 4),
                "avg_direction_accuracy": round(np.mean([r["direction_accuracy"] for r in results]), 1),
                "avg_sharpe": round(np.mean([r["sharpe"] for r in results]), 3),
                "splits": len(results),
            }
        else:
            avg_metrics = {"error": "No valid splits"}

        return {"splits": results, "aggregate": avg_metrics}


# Singleton
replay_engine = ReplayEngine()
walk_forward = WalkForwardValidator()
