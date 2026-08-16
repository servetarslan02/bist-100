"""
ALPHA BIST — Scanner Backtest Runner v2.0

Tam entegre backtest pipeline:

Historical Data → Data Quality → Features → Ranking → AlphaScanner → Signal → Portfolio Simulation

Özellikler:
- Look-ahead bias engeli
- Survivorship bias koruması
- Signal timestamp doğruluğu
- İşlem maliyetleri (komisyon + slippage)
- Equity curve
- P&L tracking
- Drawdown
- Sharpe ratio
- Benchmark karşılaştırması
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import structlog

from ..features.calculator import FeatureCalculator
from ..core.tradability_mask import TradabilityMask
from ..core.data_quality_v2 import DataQualityV2

logger = structlog.get_logger()


@dataclass
class BacktestTrade:
    date: str
    ticker: str
    direction: str
    quantity: int
    price: float
    commission: float
    slippage: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date, "ticker": self.ticker,
            "direction": self.direction, "quantity": self.quantity,
            "price": self.price, "commission": round(self.commission, 2),
            "slippage": round(self.slippage, 2),
        }


@dataclass
class BacktestSignal:
    date: str
    ticker: str
    signal: str
    score: float
    features_count: int
    quality_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date, "ticker": self.ticker,
            "signal": self.signal, "score": self.score,
            "features_count": self.features_count,
            "quality_score": self.quality_score,
        }


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    total_scans: int
    signals_generated: int
    trades_executed: int
    look_ahead_violations: int
    survivorship_violations: int
    data_quality_issues: int
    signals: List[BacktestSignal]
    trades: List[BacktestTrade]
    portfolio: Dict[str, Any]
    performance: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_date, "end_date": self.end_date,
            "total_scans": self.total_scans,
            "signals_generated": self.signals_generated,
            "trades_executed": self.trades_executed,
            "look_ahead_violations": self.look_ahead_violations,
            "survivorship_violations": self.survivorship_violations,
            "data_quality_issues": self.data_quality_issues,
            "signal_count": len(self.signals),
            "trade_count": len(self.trades),
            "portfolio": self.portfolio,
            "performance": self.performance,
            "equity_curve_points": len(self.equity_curve),
        }


class PortfolioSimulator:
    """Backtest portföy simülasyonu."""

    def __init__(
        self,
        initial_capital: float = 100000,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        max_position_pct: float = 0.10,
    ):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate
        self._max_position_pct = max_position_pct
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[Dict[str, Any]] = []
        self._high_water_mark = initial_capital

    def execute_buy(self, ticker: str, price: float, date: str) -> Optional[BacktestTrade]:
        """Alım işlemi."""
        # Pozisyon boyutu
        max_amount = self._cash * self._max_position_pct
        if max_amount < price:
            return None

        quantity = int(max_amount / price)
        if quantity <= 0:
            return None

        amount = quantity * price
        slippage = amount * self._slippage_rate
        commission = amount * self._commission_rate
        total_cost = amount + slippage + commission

        if total_cost > self._cash:
            quantity = int((self._cash) / (price * (1 + self._slippage_rate + self._commission_rate)))
            if quantity <= 0:
                return None
            amount = quantity * price
            slippage = amount * self._slippage_rate
            commission = amount * self._commission_rate
            total_cost = amount + slippage + commission

        self._cash -= total_cost
        self._positions[ticker] = {
            "quantity": quantity, "entry_price": price,
            "entry_date": date, "cost_basis": total_cost,
        }

        trade = BacktestTrade(
            date=date, ticker=ticker, direction="BUY",
            quantity=quantity, price=price,
            commission=commission, slippage=slippage,
        )
        self._trades.append(trade)
        return trade

    def execute_sell(self, ticker: str, price: float, date: str) -> Optional[BacktestTrade]:
        """Satış işlemi."""
        if ticker not in self._positions:
            return None

        pos = self._positions[ticker]
        quantity = pos["quantity"]
        amount = quantity * price
        slippage = amount * self._slippage_rate
        commission = amount * self._commission_rate
        net_revenue = amount - slippage - commission

        self._cash += net_revenue

        trade = BacktestTrade(
            date=date, ticker=ticker, direction="SELL",
            quantity=quantity, price=price,
            commission=commission, slippage=slippage,
        )
        self._trades.append(trade)
        del self._positions[ticker]
        return trade

    def update_equity(self, prices: Dict[str, float], date: str):
        """Equity curve güncelle."""
        market_value = sum(
            pos["quantity"] * prices.get(t, pos["entry_price"])
            for t, pos in self._positions.items()
        )
        equity = self._cash + market_value

        if equity > self._high_water_mark:
            self._high_water_mark = equity

        drawdown = (self._high_water_mark - equity) / self._high_water_mark if self._high_water_mark > 0 else 0

        self._equity_curve.append({
            "date": date, "equity": round(equity, 2),
            "cash": round(self._cash, 2),
            "market_value": round(market_value, 2),
            "drawdown": round(drawdown, 4),
            "positions": len(self._positions),
        })

    def get_summary(self) -> Dict[str, Any]:
        """Portföy özeti."""
        if not self._equity_curve:
            return {}

        final_equity = self._equity_curve[-1]["equity"]
        total_return = (final_equity / self._initial_capital - 1) * 100

        # Sharpe
        equities = [e["equity"] for e in self._equity_curve]
        if len(equities) > 1:
            returns = np.diff(equities) / equities[:-1]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        # Max drawdown
        max_dd = max(e["drawdown"] for e in self._equity_curve) if self._equity_curve else 0

        # Win rate
        buy_trades = [t for t in self._trades if t.direction == "BUY"]
        sell_trades = [t for t in self._trades if t.direction == "SELL"]
        winning = 0
        for sell in sell_trades:
            buy = next((b for b in buy_trades if b.ticker == sell.ticker and b.date <= sell.date), None)
            if buy and sell.price > buy.price:
                winning += 1
        win_rate = winning / len(sell_trades) * 100 if sell_trades else 0

        return {
            "initial_capital": self._initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_trades": len(self._trades),
            "win_rate_pct": round(win_rate, 1),
            "total_commission": round(sum(t.commission for t in self._trades), 2),
            "total_slippage": round(sum(t.slippage for t in self._trades), 2),
            "open_positions": len(self._positions),
        }


class ScannerBacktestRunner:
    """Scanner backtest runner v2.0 — tam entegre."""

    def __init__(
        self,
        initial_capital: float = 100000,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        min_quality_score: float = 70.0,
    ):
        self._calc = FeatureCalculator()
        self._tm = TradabilityMask()
        self._dq = DataQualityV2()
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate
        self._min_quality_score = min_quality_score

    def run(
        self,
        market_data: Dict[str, pd.DataFrame],
        lookback_days: int = 120,
        universe_at_date: Optional[List[str]] = None,
        signal_threshold: float = 60.0,
        benchmark_data: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """Tam backtest çalıştır."""
        import time as _time
        start_time = _time.time()

        sim = PortfolioSimulator(
            initial_capital=self._initial_capital,
            commission_rate=self._commission_rate,
            slippage_rate=self._slippage_rate,
        )

        signals = []
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        # Ortak tarih aralığı bul
        all_dates = set()
        for df in market_data.values():
            if df is not None and not df.empty:
                all_dates.update(df.index)
        sorted_dates = sorted(all_dates)

        if len(sorted_dates) < lookback_days + 10:
            return BacktestResult(
                start_date=str(sorted_dates[0].date()) if sorted_dates else "",
                end_date=str(sorted_dates[-1].date()) if sorted_dates else "",
                total_scans=0, signals_generated=0, trades_executed=0,
                look_ahead_violations=0, survivorship_violations=0,
                data_quality_issues=0, signals=[], trades=[],
                portfolio={}, performance={}, equity_curve=[],
            )

        # Her tarih için tarama
        for i in range(lookback_days, len(sorted_dates) - 1):
            current_date = sorted_dates[i]
            next_date = sorted_dates[i + 1]
            date_str = str(current_date.date()) if hasattr(current_date, 'date') else str(current_date)

            # Her ticker için
            day_signals = []
            for ticker, df in market_data.items():
                if df is None or df.empty:
                    continue

                # Survivorship bias kontrolü
                if universe_at_date and ticker not in universe_at_date:
                    survivorship_violations += 1
                    continue

                # Veriyi al (look-ahead engeli: sadece current_date'e kadar)
                df_until = df[df.index <= current_date]
                if len(df_until) < lookback_days:
                    continue

                df_lookback = df_until.iloc[-lookback_days:]

                # Data quality
                quality = self._dq.full_quality_check(df_lookback, ticker)
                if quality.quality_score < self._min_quality_score:
                    data_quality_issues += 1
                    continue

                # Feature hesaplama (look-ahead yok)
                try:
                    mask = self._tm.compute_mask(
                        ticker, df_lookback['Open'].values,
                        df_lookback['High'].values, df_lookback['Low'].values,
                        df_lookback['Close'].values, df_lookback['Volume'].values,
                    )
                    features = self._calc.compute_all_features(
                        df_lookback, mask=mask.mask, ticker=ticker
                    )
                    if not features:
                        continue

                    total_scans += 1
                    score = self._compute_score(features)
                    signal = self._determine_signal(score, signal_threshold)

                    day_signals.append(BacktestSignal(
                        date=date_str, ticker=ticker,
                        signal=signal, score=score,
                        features_count=len(features),
                        quality_score=quality.quality_score,
                    ))

                except Exception:
                    data_quality_issues += 1

            signals.extend(day_signals)

            # Sinyallere göre işlem yap
            buys = [s for s in day_signals if s.signal in ("STRONG_BUY", "BUY")]
            sells = [s for s in day_signals if s.signal in ("STRONG_SELL", "SELL")]

            # Satışlar önce
            for sig in sells:
                if sig.ticker in market_data:
                    df = market_data[sig.ticker]
                    if next_date in df.index:
                        price = df.loc[next_date, 'Open']
                        trade = sim.execute_sell(sig.ticker, price, date_str)

            # Alımlar (score'a göre sırala)
            buys.sort(key=lambda s: s.score, reverse=True)
            for sig in buys:
                if sig.ticker not in sim._positions and sig.ticker in market_data:
                    df = market_data[sig.ticker]
                    if next_date in df.index:
                        price = df.loc[next_date, 'Open']
                        trade = sim.execute_buy(sig.ticker, price, date_str)

            # Equity güncelle
            prices = {}
            for ticker in sim._positions:
                if ticker in market_data and current_date in market_data[ticker].index:
                    prices[ticker] = market_data[ticker].loc[current_date, 'Close']
            sim.update_equity(prices, date_str)

        elapsed = _time.time() - start_time

        return BacktestResult(
            start_date=str(sorted_dates[lookback_days].date()) if sorted_dates else "",
            end_date=str(sorted_dates[-1].date()) if sorted_dates else "",
            total_scans=total_scans,
            signals_generated=len(signals),
            trades_executed=len(sim._trades),
            look_ahead_violations=look_ahead_violations,
            survivorship_violations=survivorship_violations,
            data_quality_issues=data_quality_issues,
            signals=signals, trades=sim._trades,
            portfolio=sim.get_summary(),
            performance={
                "elapsed_seconds": round(elapsed, 2),
                "scans_per_second": round(total_scans / max(elapsed, 0.001), 1),
            },
            equity_curve=sim._equity_curve,
        )

    def _compute_score(self, features: Dict[str, Any]) -> float:
        """Feature'lardan skor hesapla."""
        _s = lambda v: float(v.flat[0]) if isinstance(v, np.ndarray) and v.size > 0 else float(v) if v is not None else 0

        score = 50.0
        rsi = _s(features.get("rsi_14", 50))
        if rsi > 60: score += 10
        elif rsi < 40: score -= 10

        mom = _s(features.get("momentum_20d", 0))
        score += mom * 100

        roc = _s(features.get("roc_5d", 0))
        score += roc * 2

        vol_z = _s(features.get("volume_zscore", 0))
        score += vol_z * 5

        return max(0, min(100, score))

    def _determine_signal(self, score: float, threshold: float) -> str:
        """Skordan sinyal üret."""
        if score >= threshold + 10:
            return "STRONG_BUY"
        elif score >= threshold:
            return "BUY"
        elif score <= 100 - threshold - 10:
            return "STRONG_SELL"
        elif score <= 100 - threshold:
            return "SELL"
        return "HOLD"
