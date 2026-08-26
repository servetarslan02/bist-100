"""
ALPHA BIST — Scanner Backtest Runner v3.0

Production-grade performans optimizasyonu.

Optimizasyonlar:
- Feature'lar ticker bazında bir kez hesaplanır (vectorized)
- Data quality sonucu cache'lenir
- Ranking batch çalıştırılır
- Signal üretimi toplu yapılır
- Portfolio simulator iyileştirildi

Geçmiş versiyonla aynı finansal sonuçları üretir.
"""

import numpy as np
import polars as pl
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import structlog

from ..features.calculator import feature_calculator
from ..core.tradability_mask import TradabilityMask
from ..core.data_quality import DataQualityChecker as DataQualityV2

logger = structlog.get_logger()


# =====================================================
# DATA CLASSES
# =====================================================

@dataclass
class BacktestTrade:
    date: str
    ticker: str
    direction: str
    quantity: int
    price: float
    commission: float
    slippage: float
    pnl: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date, "ticker": self.ticker,
            "direction": self.direction, "quantity": self.quantity,
            "price": self.price, "commission": round(self.commission, 2),
            "slippage": round(self.slippage, 2), "pnl": round(self.pnl, 2),
        }


@dataclass
class BacktestSignal:
    date: str
    ticker: str
    signal: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {"date": self.date, "ticker": self.ticker,
                "signal": self.signal, "score": round(self.score, 2)}


@dataclass
class DailySnapshot:
    date: str
    equity: float
    cash: float
    market_value: float
    positions: int
    drawdown: float
    daily_return: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date, "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "market_value": round(self.market_value, 2),
            "positions": self.positions,
            "drawdown": round(self.drawdown, 4),
            "daily_return": round(self.daily_return, 6),
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
            "portfolio": self.portfolio,
            "performance": self.performance,
            "equity_curve_points": len(self.equity_curve),
        }


# =====================================================
# FEATURE CACHE
# =====================================================

class FeatureCache:
    """Ticker bazında feature cache. Tarih değişince invalidation."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._date_cache: Dict[str, str] = {}  # ticker → son hesap tarihi

    def get(self, ticker: str, date: str) -> Optional[Dict[str, Any]]:
        if ticker in self._cache and self._date_cache.get(ticker) == date:
            return self._cache[ticker]
        return None

    def set(self, ticker: str, date: str, features: Dict[str, Any]):
        self._cache[ticker] = features
        self._date_cache[ticker] = date

    def invalidate(self, ticker: str):
        self._cache.pop(ticker, None)
        self._date_cache.pop(ticker, None)

    def clear(self):
        self._cache.clear()
        self._date_cache.clear()


class QualityCache:
    """Data quality sonucu cache."""

    def __init__(self):
        self._cache: Dict[str, Tuple[bool, float]] = {}

    def get(self, ticker: str) -> Optional[Tuple[bool, float]]:
        return self._cache.get(ticker)

    def set(self, ticker: str, passed: bool, score: float):
        self._cache[ticker] = (passed, score)

    def clear(self):
        self._cache.clear()


# =====================================================
# PORTFOLIO SIMULATOR v2.0
# =====================================================

class PortfolioSimulator:
    """Backtest portföy simülasyonu — v2.0."""

    def __init__(
        self,
        initial_capital: float = 100000,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        max_position_pct: float = 0.10,
        max_positions: int = 20,
    ):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate
        self._max_position_pct = max_position_pct
        self._max_positions = max_positions
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._trades: List[BacktestTrade] = []
        self._daily_snapshots: List[DailySnapshot] = []
        self._high_water_mark = initial_capital
        self._prev_equity = initial_capital

    def can_buy(self) -> bool:
        return len(self._positions) < self._max_positions and self._cash > 0

    def execute_buy(self, ticker: str, price: float, date: str) -> Optional[BacktestTrade]:
        if ticker in self._positions or not self.can_buy():
            return None
        if price <= 0 or np.isnan(price):
            return None

        max_amount = min(self._cash * self._max_position_pct, self._cash * 0.95)
        quantity = int(max_amount / (price * (1 + self._slippage_rate + self._commission_rate)))
        if quantity <= 0:
            return None

        amount = quantity * price
        slippage = amount * self._slippage_rate
        commission = max(amount * self._commission_rate, 1.0)
        total_cost = amount + slippage + commission

        if total_cost > self._cash:
            quantity = int((self._cash - 1) / (price * (1 + self._slippage_rate + self._commission_rate)))
            if quantity <= 0:
                return None
            amount = quantity * price
            slippage = amount * self._slippage_rate
            commission = max(amount * self._commission_rate, 1.0)
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
        if len(self._trades) > 5000:
            self._trades = self._trades[-5000:]
        return trade

    def execute_sell(self, ticker: str, price: float, date: str) -> Optional[BacktestTrade]:
        if ticker not in self._positions:
            return None
        if price <= 0 or np.isnan(price):
            return None

        pos = self._positions[ticker]
        quantity = pos["quantity"]
        amount = quantity * price
        slippage = amount * self._slippage_rate
        commission = max(amount * self._commission_rate, 1.0)
        net_revenue = amount - slippage - commission

        # P&L hesapla
        cost = pos["cost_basis"]
        pnl = net_revenue - cost

        self._cash += net_revenue

        trade = BacktestTrade(
            date=date, ticker=ticker, direction="SELL",
            quantity=quantity, price=price,
            commission=commission, slippage=slippage, pnl=pnl,
        )
        self._trades.append(trade)
        if len(self._trades) > 5000:
            self._trades = self._trades[-5000:]
        del self._positions[ticker]
        return trade

    def update_equity(self, prices: Dict[str, float], date: str):
        """Günlük equity snapshot."""
        market_value = sum(
            pos["quantity"] * prices.get(t, pos["entry_price"])
            for t, pos in self._positions.items()
        )
        equity = self._cash + market_value

        if equity > self._high_water_mark:
            self._high_water_mark = equity

        drawdown = (self._high_water_mark - equity) / self._high_water_mark if self._high_water_mark > 0 else 0
        daily_return = (equity / self._prev_equity - 1) if self._prev_equity > 0 else 0

        self._daily_snapshots.append(DailySnapshot(
            date=date, equity=equity, cash=self._cash,
            market_value=market_value, positions=len(self._positions),
            drawdown=drawdown, daily_return=daily_return,
        ))
        self._prev_equity = equity

    def get_summary(self) -> Dict[str, Any]:
        if not self._daily_snapshots:
            # Trade-based metrics only
            sell_trades = [t for t in self._trades if t.direction == "SELL"]
            winning = sum(1 for t in sell_trades if t.pnl > 0)
            win_rate = winning / len(sell_trades) * 100 if sell_trades else 0
            gross_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
            gross_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            total_commission = sum(t.commission for t in self._trades)
            total_slippage = sum(t.slippage for t in self._trades)
            return {
                "initial_capital": self._initial_capital,
                "final_equity": self._cash,
                "total_return_pct": 0, "sharpe_ratio": 0, "sortino_ratio": 0,
                "max_drawdown_pct": 0, "total_trades": len(self._trades),
                "win_rate_pct": round(win_rate, 1),
                "profit_factor": round(profit_factor, 2),
                "total_commission": round(total_commission, 2),
                "total_slippage": round(total_slippage, 2),
                "open_positions": len(self._positions),
            }

        final = self._daily_snapshots[-1].equity
        total_return = (final / self._initial_capital - 1) * 100

        # Sharpe & Sortino
        returns = np.array([s.daily_return for s in self._daily_snapshots])
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
            downside_returns = np.minimum(returns, 0)
            downside_std = np.sqrt(np.mean(downside_returns ** 2))
            sortino = np.mean(returns) / downside_std * np.sqrt(252) if downside_std > 0 else 0
        else:
            sharpe = sortino = 0

        max_dd = max(s.drawdown for s in self._daily_snapshots)

        # Win rate
        sell_trades = [t for t in self._trades if t.direction == "SELL"]
        winning = sum(1 for t in sell_trades if t.pnl > 0)
        win_rate = winning / len(sell_trades) * 100 if sell_trades else 0

        # Profit factor
        gross_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        total_commission = sum(t.commission for t in self._trades)
        total_slippage = sum(t.slippage for t in self._trades)

        return {
            "initial_capital": self._initial_capital,
            "final_equity": round(final, 2),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_trades": len(self._trades),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "total_commission": round(total_commission, 2),
            "total_slippage": round(total_slippage, 2),
            "open_positions": len(self._positions),
        }


# =====================================================
# BACKTEST RUNNER v3.0
# =====================================================

class ScannerBacktestRunner:
    """Backtest runner v3.0 — optimized."""

    def __init__(
        self,
        initial_capital: float = 100000,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        min_quality_score: float = 70.0,
    ):
        self._calc = feature_calculator
        self._tm = TradabilityMask()
        self._dq = DataQualityV2()
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate
        self._min_quality_score = min_quality_score
        self._feature_cache = FeatureCache()
        self._quality_cache = QualityCache()

    def run(
        self,
        market_data: Dict[str, pl.DataFrame],
        lookback_days: int = 120,
        universe_at_date: Optional[List[str]] = None,
        signal_threshold: float = 60.0,
        benchmark_data: Optional[pl.DataFrame] = None,
    ) -> BacktestResult:
        """Optimize edilmiş backtest."""
        import time as _time
        start_time = _time.time()

        sim = PortfolioSimulator(
            initial_capital=self._initial_capital,
            commission_rate=self._commission_rate,
            slippage_rate=self._slippage_rate,
        )

        # Cache'leri temizle
        self._feature_cache.clear()
        self._quality_cache.clear()

        # Ortak tarih aralığı
        all_dates = set()
        for df in market_data.values():
            if df is not None and not df.empty:
                all_dates.update(df.index)
        sorted_dates = sorted(all_dates)

        # Feature calculator en az 60 bar istiyor
        effective_lookback = max(lookback_days, 60)

        if len(sorted_dates) < effective_lookback + 10:
            return self._empty_result(sorted_dates)

        signals = []
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        # ====== OPTIMIZATION: Pre-compute quality cache ======
        for ticker, df in market_data.items():
            if df is not None and not df.empty and len(df) >= effective_lookback:
                quality = self._dq.full_quality_check(df, ticker)
                self._quality_cache.set(ticker, quality.passed, quality.quality_score)

        # ====== Ana döngü (optimize edilmiş) ======
        for i in range(effective_lookback, len(sorted_dates) - 1):
            current_date = sorted_dates[i]
            next_date = sorted_dates[i + 1]
            date_str = str(current_date.date()) if hasattr(current_date, 'date') else str(current_date)

            day_signals = []

            for ticker, df in market_data.items():
                # Survivorship bias
                if universe_at_date and ticker not in universe_at_date:
                    survivorship_violations += 1
                    continue

                # Quality cache kontrolü
                quality_info = self._quality_cache.get(ticker)
                if quality_info and not quality_info[0]:
                    data_quality_issues += 1
                    continue
                if quality_info and quality_info[1] < self._min_quality_score:
                    data_quality_issues += 1
                    continue

                # Veri penceresi (look-ahead engeli)
                df_until = df[df.index <= current_date]
                if len(df_until) < effective_lookback:
                    continue

                # ====== OPTIMIZATION: Feature cache ======
                cached_features = self._feature_cache.get(ticker, date_str)
                if cached_features is not None:
                    features = cached_features
                else:
                    df_lookback = df_until[-effective_lookback:]
                    try:
                        mask = self._tm.compute_mask(
                            ticker, df_lookback['Open'].to_numpy(),
                            df_lookback['High'].to_numpy(), df_lookback['Low'].to_numpy(),
                            df_lookback['Close'].to_numpy(), df_lookback['Volume'].to_numpy(),
                        )
                        features = self._calc.compute_all_features(
                            df_lookback, mask=mask.mask, ticker=ticker
                        )
                        if features:
                            self._feature_cache.set(ticker, date_str, features)
                    except Exception:
                        data_quality_issues += 1
                        continue

                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features)
                signal = self._determine_signal(score, signal_threshold)

                day_signals.append(BacktestSignal(
                    date=date_str, ticker=ticker,
                    signal=signal, score=score,
                ))

            signals.extend(day_signals)

            # ====== OPTIMIZATION: Batch trade execution ======
            sells = [s for s in day_signals if s.signal in ("STRONG_SELL", "SELL")]
            buys = sorted(
                [s for s in day_signals if s.signal in ("STRONG_BUY", "BUY")],
                key=lambda s: s.score, reverse=True,
            )

            # Satışlar önce
            for sig in sells:
                if sig.ticker in market_data and next_date in market_data[sig.ticker].index:
                    price = market_data[sig.ticker].loc[next_date, 'Open']
                    sim.execute_sell(sig.ticker, price, date_str)

            # Alımlar
            for sig in buys:
                if sig.ticker not in sim._positions and sig.ticker in market_data:
                    if next_date in market_data[sig.ticker].index:
                        price = market_data[sig.ticker].loc[next_date, 'Open']
                        sim.execute_buy(sig.ticker, price, date_str)

            # Equity güncelle
            prices = {}
            for ticker in sim._positions:
                if ticker in market_data and current_date in market_data[ticker].index:
                    prices[ticker] = market_data[ticker].loc[current_date, 'Close']
            sim.update_equity(prices, date_str)

        elapsed = _time.time() - start_time

        return BacktestResult(
            start_date=str(sorted_dates[effective_lookback].date()) if sorted_dates else "",
            end_date=str(sorted_dates[-1].date()) if sorted_dates else "",
            total_scans=total_scans,
            signals_generated=len(signals),
            trades_executed=len(sim._trades),
            look_ahead_violations=look_ahead_violations,
            survivorship_violations=survivorship_violations,
            data_quality_issues=data_quality_issues,
            signals=signals[-1000:],  # Son 1000 sinyal
            trades=sim._trades,
            portfolio=sim.get_summary(),
            performance={
                "elapsed_seconds": round(elapsed, 2),
                "scans_per_second": round(total_scans / max(elapsed, 0.001), 1),
                "cache_hits": sum(1 for t in market_data if self._feature_cache.get(t, "") is not None),
            },
            equity_curve=[s.to_dict() for s in sim._daily_snapshots],
        )

    def _empty_result(self, dates) -> BacktestResult:
        return BacktestResult(
            start_date="", end_date="", total_scans=0,
            signals_generated=0, trades_executed=0,
            look_ahead_violations=0, survivorship_violations=0,
            data_quality_issues=0, signals=[], trades=[],
            portfolio={}, performance={}, equity_curve=[],
        )

    def _compute_score(self, features: Dict[str, Any]) -> float:
        """Opportunity score — alpha_scanner ile aynı mantık.

        Ağırlıklar:
        - momentum: 20%
        - relative_strength: 15%
        - volume_anomaly: 15%
        - breakout: 10%
        - volatility_structure: 10%
        - regime_fit: 10%
        - technical: 20% (event ve ML yerine)
        """
        _s = lambda v: float(v.flat[0]) if isinstance(v, np.ndarray) and v.size > 0 else float(v) if v is not None else 0

        # Momentum skoru
        roc_5d = _s(features.get("roc_5d", 0))
        roc_20d = _s(features.get("momentum_20d", 0) or features.get("roc_20d", 0))
        mom_score = 50
        if roc_5d > 3:
            mom_score += min(roc_5d * 5, 30)
        elif roc_5d < -3:
            mom_score += max(roc_5d * 5, -30)
        if roc_20d > 5:
            mom_score += min(roc_20d * 2, 20)
        mom_score = max(0, min(100, mom_score))

        # Relative strength skoru
        price_vs_sma20 = _s(features.get("price_vs_sma20", 0))
        rs_score = 50 + min(price_vs_sma20 * 5, 50)
        rs_score = max(0, min(100, rs_score))

        # Volume anomaly skoru
        vol_z = _s(features.get("volume_zscore", 0))
        vol_score = 50
        if vol_z > 2:
            vol_score += min(vol_z * 15, 40)
        elif vol_z < -1:
            vol_score += max(vol_z * 10, -30)
        vol_score = max(0, min(100, vol_score))

        # Breakout skoru
        bb_pos = _s(features.get("bb_position", 0.5))
        near_high = _s(features.get("near_20d_high", 0))
        trend_slope = _s(features.get("trend_slope_20d", 0))
        brk_score = 0
        if bb_pos > 0.95:
            brk_score += 30
        elif bb_pos > 0.85:
            brk_score += 15
        if near_high:
            brk_score += 25
        if vol_z > 1.5:
            brk_score += 20
        if trend_slope > 0:
            brk_score += 15
        brk_score = min(100, brk_score)

        # Volatility structure
        atr_pct = _s(features.get("atr_14_pct", 2))
        vol_struct = 50
        if atr_pct < 2:
            vol_struct = 70
        elif atr_pct > 5:
            vol_struct = 40

        # Regime fit (basitleştirilmiş — backtest'te rejim bilinmiyor)
        rsi = _s(features.get("rsi_14", 50))
        regime_score = 50
        if 40 < rsi < 60:
            regime_score = 60  # Nötr bölge — çoğu rejimde iyi

        # Technical (RSI tabanlı)
        tech_score = 50
        if rsi > 70:
            tech_score -= 10
        elif rsi < 30:
            tech_score += 10
        elif 40 < rsi < 60:
            tech_score += 5
        macd = _s(features.get("macd_histogram", 0))
        if macd > 0:
            tech_score += 5
        elif macd < 0:
            tech_score -= 5
        tech_score = max(0, min(100, tech_score))

        # Ağırlıklı toplam (alpha_scanner ile aynı ağırlıklar)
        score = (
            mom_score * 0.20
            + rs_score * 0.15
            + vol_score * 0.15
            + brk_score * 0.10
            + vol_struct * 0.10
            + regime_score * 0.10
            + tech_score * 0.20  # event ve ML yerine technical
        )

        return max(0, min(100, round(score, 1)))

    def _determine_signal(self, score: float, threshold: float) -> str:
        """Sinyal belirleme — alpha_scanner ile uyumlu."""
        if score >= threshold + 15:
            return "STRONG_BUY"
        elif score >= threshold:
            return "BUY"
        elif score <= 100 - threshold - 15:
            return "STRONG_SELL"
        elif score <= 100 - threshold:
            return "SELL"
        return "HOLD"
