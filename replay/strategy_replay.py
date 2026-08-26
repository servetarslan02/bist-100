"""
ALPHA BIST — Strategy Replay

Strateji replay motoru.
Paper trading ile entegre çalışarak stratejiyi geçmiş veri üzerinde test eder.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Protocol
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


@dataclass
class ReplayResult:
    """Replay sonucu."""
    start_date: str
    end_date: str
    total_ticks: int = 0
    total_orders: int = 0
    filled_orders: int = 0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "period": f"{self.start_date} → {self.end_date}",
            "total_ticks": self.total_ticks,
            "total_orders": self.total_orders,
            "filled_orders": self.filled_orders,
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "num_trades": len(self.trades),
        }


class StrategyReplay:
    """Strateji replay motoru — multi-index destekli."""

    def __init__(self):
        self._strategy = None

    def load_strategy(self, strategy):
        self._strategy = strategy

    def run(
        self,
        start_date: str,
        end_date: str,
        tickers: Optional[List[str]] = None,
        universe: str = "bist100",
        initial_capital: float = 1_000_000.0,
    ) -> ReplayResult:
        """Replay'i çalıştır.

        Args:
            universe: "bist30", "bist50", "bist100"
        """
        from replay.market_player import MarketPlayer

        result = ReplayResult(start_date=start_date, end_date=end_date)

        player = MarketPlayer()
        load_result = player.load_data(start_date, end_date, tickers, universe=universe)

        if load_result.get("status") != "ok":
            logger.error("Failed to load data for replay", result=load_result)
            return result

        from services.paper_trading.paper_execution import PaperExecutionEngine
        paper = PaperExecutionEngine()

        equity = initial_capital

        for tick in player.play():
            result.total_ticks += 1

            if self._strategy:
                try:
                    signal = self._strategy.on_tick(tick.to_dict())
                except Exception:
                    signal = None

                if signal and signal.get("action") in ("BUY", "SELL"):
                    result.total_orders += 1

                    order = paper.execute_signal(
                        date=tick.timestamp.strftime("%Y-%m-%d"),
                        ticker=tick.ticker,
                        side=signal["action"],
                        quantity=signal.get("quantity", 100),
                        signal_price=tick.close,
                        market_price=tick.close,
                    )

                    if order.get("status") in ("FILLED", "PARTIAL_FILL"):
                        result.filled_orders += 1
                        result.trades.append({
                            "timestamp": tick.timestamp.isoformat(),
                            "ticker": tick.ticker,
                            "side": signal["action"],
                            "price": order.get("execution_price", tick.close),
                        })

            if result.total_ticks % 100 == 0:
                result.equity_curve.append(equity)

        if result.equity_curve:
            returns = pd.Series(result.equity_curve).pct_change().dropna()
            if len(returns) > 1:
                result.sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
                cumulative = (1 + returns).cumprod()
                drawdown = (cumulative / cumulative.cummax() - 1)
                result.max_drawdown_pct = float(drawdown.min()) * 100

        result.total_pnl = equity - initial_capital
        result.total_return_pct = (result.total_pnl / initial_capital) * 100

        logger.info("Strategy replay completed", **result.summary())
        return result


strategy_replay = StrategyReplay()
