"""
ALPHA BIST — Paper Trading Performance Tracker v1.0

Gunluk performans metrikleri:
- CAGR
- Sharpe Ratio
- Sortino Ratio
- Max Drawdown
- Win Rate
- Profit Factor
- Turnover
- Transaction Cost
- Alpha vs XU100
- IC / ICIR
- Top-K spread

Mevcut services.backtest.engine.BacktestMetrics'i extend eder.
Gunluk incremental hesaplama yapar (tum veriyi her gun bastan hesaplamaz).
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class PerformanceTracker:
    """Paper trading performans motoru — incremental."""

    def __init__(self, state_store=None):
        self._state_store = state_store
        self._daily_perf_cache: List[Dict[str, Any]] = []

    def compute_daily_performance(
        self,
        date: str,
        portfolio_value: float,
        cash: float,
        initial_capital: float,
        trades_today: List[Dict[str, Any]],
        orders_today: List[Dict[str, Any]],
        num_positions: int,
        benchmark_return_pct: float = 0.0,
        prev_portfolio_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Gunluk performans hesapla."""

        # Daily return
        if prev_portfolio_value and prev_portfolio_value > 0:
            daily_return_pct = (portfolio_value / prev_portfolio_value - 1) * 100
        else:
            daily_return_pct = 0.0

        # Cumulative return
        cumulative_return_pct = (portfolio_value / initial_capital - 1) * 100

        # Max drawdown (equity curve'den)
        max_dd = self._compute_max_drawdown_from_history()

        # Alpha vs benchmark
        alpha_pct = daily_return_pct - benchmark_return_pct

        # Turnover (gunluk)
        turnover = self._compute_daily_turnover(orders_today, portfolio_value)

        # Transaction cost
        transaction_cost = sum(o.get("commission", 0) for o in orders_today if o.get("status") == "FILLED")

        # Num trades today
        num_trades = len(trades_today)

        perf = {
            "date": date,
            "portfolio_value": round(portfolio_value, 2),
            "cash": round(cash, 2),
            "invested_value": round(portfolio_value - cash, 2),
            "daily_pnl": round(portfolio_value - (prev_portfolio_value or portfolio_value), 2),
            "daily_return_pct": round(daily_return_pct, 4),
            "cumulative_return_pct": round(cumulative_return_pct, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "benchmark_return_pct": round(benchmark_return_pct, 4),
            "alpha_pct": round(alpha_pct, 4),
            "turnover": round(turnover, 4),
            "transaction_cost": round(transaction_cost, 2),
            "num_positions": num_positions,
            "num_trades": num_trades,
        }

        if self._state_store:
            self._state_store.save_daily_performance(perf)

        self._daily_perf_cache.append(perf)
        return perf

    def compute_full_metrics(self, equity_curve: List[Dict[str, Any]], trades: List[Dict[str, Any]], benchmark_returns: Optional[List[float]] = None) -> Dict[str, Any]:
        """Tum metrikleri hesapla."""
        if not equity_curve:
            return {"error": "No equity curve data"}

        equities = [p["equity"] for p in equity_curve]
        initial = equities[0]
        final = equities[-1]

        # Total return & CAGR
        total_return_pct = (final / initial - 1) * 100
        n_days = len(equities)
        years = n_days / 252
        cagr = ((final / initial) ** (1 / max(years, 0.001)) - 1) * 100 if initial > 0 else 0

        # Daily returns
        returns = []
        for i in range(1, len(equities)):
            if equities[i-1] > 0:
                returns.append(equities[i] / equities[i-1] - 1)

        returns_arr = np.array(returns) if returns else np.array([0])

        # Sharpe
        sharpe = self._sharpe(returns_arr)

        # Sortino
        sortino = self._sortino(returns_arr)

        # Max Drawdown
        max_dd = self._max_drawdown(equities)

        # Calmar
        calmar = cagr / max_dd if max_dd > 0 else 0

        # Win Rate (trades)
        if trades:
            wins = [t for t in trades if t.get("realized_pnl", 0) > 0]
            win_rate = len(wins) / len(trades)
            avg_win = np.mean([t["realized_pnl"] for t in wins]) if wins else 0
            losses = [t for t in trades if t.get("realized_pnl", 0) < 0]
            avg_loss = np.mean([abs(t["realized_pnl"]) for t in losses]) if losses else 0
            profit_factor = sum(t["realized_pnl"] for t in wins) / sum(abs(t["realized_pnl"]) for t in losses) if losses else float('inf')
            expectancy = np.mean([t["realized_pnl"] for t in trades])
            avg_holding = np.mean([t.get("holding_days", 0) for t in trades])
        else:
            win_rate = avg_win = avg_loss = profit_factor = expectancy = avg_holding = 0

        # Turnover (annualized)
        total_turnover = sum(t.get("quantity", 0) * t.get("exit_price", 0) for t in trades)
        avg_portfolio_value = np.mean(equities)
        turnover_annual = (total_turnover / max(avg_portfolio_value, 1)) * (252 / max(n_days, 1))

        # Transaction cost
        total_commission = sum(t.get("commission", 0) for t in trades)

        # Benchmark correlation & alpha
        alpha = beta = corr = 0
        if benchmark_returns and len(benchmark_returns) == len(returns):
            alpha, beta, corr = self._alpha_beta(returns_arr, np.array(benchmark_returns))

        # IC / ICIR
        ic = icir = 0

        return {
            "total_return_pct": round(total_return_pct, 2),
            "cagr_pct": round(cagr, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "calmar_ratio": round(calmar, 3),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "avg_win": round(float(avg_win), 2),
            "avg_loss": round(float(avg_loss), 2),
            "expectancy": round(float(expectancy), 2),
            "avg_holding_days": round(float(avg_holding), 1),
            "total_trades": len(trades),
            "turnover_annual": round(turnover_annual, 2),
            "total_commission": round(total_commission, 2),
            "alpha_pct": round(alpha * 100, 4),
            "beta": round(beta, 3),
            "benchmark_corr": round(corr, 3),
            "ic": round(ic, 4),
            "icir": round(icir, 4),
            "num_days": n_days,
        }

    def compute_ic(self, predictions: List[float], actuals: List[float]) -> float:
        """Information Coefficient (Spearman rank correlation)."""
        if len(predictions) < 2 or len(predictions) != len(actuals):
            return 0.0
        try:
            from scipy import stats
            corr, _ = stats.spearmanr(predictions, actuals)
            return float(corr) if not np.isnan(corr) else 0.0
        except Exception:
            return 0.0

    def compute_icir(self, ic_series: List[float]) -> float:
        """IC Information Ratio = mean(IC) / std(IC)."""
        if len(ic_series) < 2:
            return 0.0
        arr = np.array(ic_series)
        mean_ic = np.mean(arr)
        std_ic = np.std(arr, ddof=1)
        return float(mean_ic / std_ic) if std_ic > 0 else 0.0

    def compute_top_k_spread(self, returns: Dict[str, float], k: int = 5) -> float:
        """Top K - Bottom K getiri farki."""
        if len(returns) < k * 2:
            return 0.0
        sorted_rets = sorted(returns.items(), key=lambda x: x[1], reverse=True)
        top_k = [r for _, r in sorted_rets[:k]]
        bottom_k = [r for _, r in sorted_rets[-k:]]
        return np.mean(top_k) - np.mean(bottom_k)

    # ===================== INTERNAL =====================

    def _sharpe(self, returns: np.ndarray) -> float:
        if len(returns) < 2 or np.std(returns) == 0:
            return 0.0
        return float(np.mean(returns) / np.std(returns) * np.sqrt(252))

    def _sortino(self, returns: np.ndarray) -> float:
        downside = returns[returns < 0]
        if len(downside) < 1 or np.std(downside) == 0:
            return 0.0
        return float(np.mean(returns) / np.std(downside) * np.sqrt(252))

    def _max_drawdown(self, equities: List[float]) -> float:
        peak = equities[0]
        max_dd = 0.0
        for e in equities:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _compute_max_drawdown_from_history(self) -> float:
        if not self._daily_perf_cache:
            return 0.0
        return max((p["max_drawdown_pct"] for p in self._daily_perf_cache), default=0.0)

    def _compute_daily_turnover(self, orders: List[Dict[str, Any]], portfolio_value: float) -> float:
        if portfolio_value <= 0:
            return 0.0
        total_value = sum(o.get("quantity", 0) * o.get("execution_price", 0) for o in orders if o.get("execution_price", 0) > 0)
        return (total_value / portfolio_value) * 100

    def _alpha_beta(self, returns: np.ndarray, benchmark: np.ndarray) -> tuple:
        if len(returns) < 2 or len(returns) != len(benchmark):
            return 0, 0, 0
        cov = np.cov(returns, benchmark)[0, 1]
        var = np.var(benchmark)
        beta = cov / var if var > 0 else 0
        alpha = np.mean(returns) - beta * np.mean(benchmark)
        corr = np.corrcoef(returns, benchmark)[0, 1] if len(returns) > 1 else 0
        return alpha, beta, corr if not np.isnan(corr) else 0

    def load_history(self) -> List[Dict[str, Any]]:
        if self._state_store:
            return self._state_store.load_daily_performance()
        return []


# Singleton
performance_tracker = PerformanceTracker()
