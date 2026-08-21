"""
ALPHA BIST — Backtest Engine v1.0

Geçmiş veriler üzerinde strateji testi:
- Historical market data
- Decision simulation
- Risk simulation
- Execution simulation
- Portfolio tracking
- Performance metrics

FAZ 12: Backtest Engine
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import structlog
from services.portfolio.portfolio_manager import CommissionModel

logger = structlog.get_logger()


@dataclass
class BacktestTrade:
    """Backtest işlem kaydı."""
    trade_id: int
    ticker: str
    side: str          # BUY | SELL
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    holding_days: int
    commission: float


@dataclass
class BacktestMetrics:
    """Backtest performans metrikleri."""
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    expectancy: float
    total_trades: int
    total_fees: float
    avg_holding_days: float
    exposure_pct: float


@dataclass
class BacktestResult:
    """Backtest sonucu."""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    metrics: BacktestMetrics
    trades: List[BacktestTrade]
    equity_curve: List[float]
    drawdown_curve: List[float]


class BacktestEngine:
    """Backtest motoru."""

    def _compute_dynamic_slippage(
        self,
        price: float,
        volume: float,
        quantity: int,
        base_slippage_pct: float = 0.05,
    ) -> float:
        """F-010: Dinamik slippage modeli.

        Sabit slippage yerine hacim ve pozisyon büyüklüğüne göre slippage hesaplar.
        Likidite düşükse slippage artar.
        """
        if volume <= 0:
            return base_slippage_pct * 3  # Hacim yoksa yüksek slippage

        # Participation rate: pozisyon hacme oranı
        trade_value = quantity * price
        avg_daily_value = volume * price
        participation = trade_value / max(avg_daily_value, 1)

        # Square-root impact model: slippage ~ sqrt(participation)
        impact = base_slippage_pct * (1 + np.sqrt(participation) * 10)

        # Minimum slippage
        return max(impact, base_slippage_pct * 0.5)

    def _check_liquidity_constraint(
        self,
        price: float,
        volume: float,
        quantity: int,
        max_participation: float = 0.10,
    ) -> Tuple[bool, int]:
        """F-011: Likidite kısıtı kontrolü.

        Günlük hacmin %10'undan fazlasını almamaya çalış.
        Gerekirse miktarı azalt.

        Returns:
            (is_feasible, adjusted_quantity)
        """
        if volume <= 0:
            return False, 0

        max_shares = int(volume * max_participation)
        if quantity > max_shares:
            return True, max_shares  # Kısmi execution
        return True, quantity

    def run_backtest(
        self,
        strategy_name: str,
        signals: List[Dict[str, Any]],
        price_data: Dict[str, List[Dict[str, Any]]],
        initial_capital: float = 100000,
        commission_rate: Optional[float] = None,
        slippage_pct: float = 0.05,
    ) -> BacktestResult:
        """Backtest çalıştır.

        Args:
            signals: [{"date": "2024-01-15", "ticker": "THYAO", "action": "BUY", "price": 300, "confidence": 0.8}, ...]
            price_data: {"THYAO": [{"date": "2024-01-15", "close": 300, "volume": 1000000}, ...], ...}
        """
        if commission_rate is not None:
            _cm = CommissionModel(broker_rate=commission_rate/2, exchange_rate=commission_rate/2)
        else:
            _cm = CommissionModel()

        capital = initial_capital
        positions: Dict[str, Dict] = {}  # ticker -> {qty, avg_cost, entry_date}
        trades: List[BacktestTrade] = []
        equity_curve = [initial_capital]
        exposure_history = [0.0]  # Her gün için invested/total oranı
        trade_id = 0

        for signal in signals:
            date = signal.get("date", "")
            ticker = signal.get("ticker", "")
            action = signal.get("action", "HOLD")
            price = signal.get("price", 0)
            confidence = signal.get("confidence", 0.5)

            if action == "HOLD" or price <= 0:
                continue

            # Hacim bilgisi (price_data'dan)
            signal_volume = 0
            if price_data and ticker in price_data:
                pd_entries = price_data[ticker]
                if isinstance(pd_entries, list) and pd_entries:
                    signal_volume = pd_entries[-1].get("volume", 0)

            # F-010: Dinamik slippage
            effective_slippage = self._compute_dynamic_slippage(price, signal_volume, 100, slippage_pct)

            # Slippage
            if action == "BUY":
                fill_price = price * (1 + effective_slippage / 100)
            else:
                fill_price = price * (1 - effective_slippage / 100)

            if action == "BUY" and ticker not in positions:
                # Pozisyon büyüklüğü (basitleştirilmiş)
                risk_pct = 2.0 * confidence
                position_value = capital * (risk_pct / 100)
                shares = int(position_value / fill_price)

                # F-011: Likidite kısıtı
                if signal_volume > 0:
                    shares = self._check_liquidity_constraint(fill_price, signal_volume, shares)[1]

                if shares > 0 and capital >= shares * fill_price:
                    cost = shares * fill_price
                    commission = _cm.calculate(cost)
                    capital -= (cost + commission)

                    positions[ticker] = {
                        "qty": shares,
                        "avg_cost": fill_price,
                        "entry_date": date,
                        "commission": commission,
                    }

            elif action == "SELL" and ticker in positions:
                pos = positions[ticker]
                revenue = pos["qty"] * fill_price
                commission = _cm.calculate(revenue)
                capital += (revenue - commission)

                pnl = (fill_price - pos["avg_cost"]) * pos["qty"] - pos["commission"] - commission
                pnl_pct = (fill_price / pos["avg_cost"] - 1) * 100

                trade_id += 1
                # Holding days hesapla
                try:
                    _d1 = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                    _d2 = datetime.strptime(date, "%Y-%m-%d")
                    _holding = max(1, (_d2 - _d1).days)
                except Exception:
                    _holding = 1

                trades.append(BacktestTrade(
                    trade_id=trade_id,
                    ticker=ticker,
                    side="BUY→SELL",
                    entry_date=pos["entry_date"],
                    exit_date=date,
                    entry_price=pos["avg_cost"],
                    exit_price=fill_price,
                    quantity=pos["qty"],
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    holding_days=_holding,
                    commission=round(pos["commission"] + commission, 2),
                ))

                del positions[ticker]

            # Equity güncelle — tüm pozisyonlar için güncel fiyat
            total_value = capital
            invested_value = 0
            for t, p in positions.items():
                if price_data and t in price_data:
                    # price_data'dan güncel fiyat bul
                    pd_entries = price_data[t]
                    if isinstance(pd_entries, list) and pd_entries:
                        # Son entry'nin close'u
                        current_price = pd_entries[-1].get("close", p["avg_cost"])
                    else:
                        current_price = p["avg_cost"]
                elif t == ticker:
                    current_price = price
                else:
                    current_price = p["avg_cost"]
                pos_value = p["qty"] * current_price
                total_value += pos_value
                invested_value += pos_value
            equity_curve.append(total_value)
            exposure_history.append(invested_value / total_value if total_value > 0 else 0)

        # Metrikler hesapla
        metrics = self._compute_metrics(trades, equity_curve, initial_capital, exposure_history)

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=signals[0]["date"] if signals else "",
            end_date=signals[-1]["date"] if signals else "",
            initial_capital=initial_capital,
            final_capital=round(equity_curve[-1] if equity_curve else initial_capital, 2),
            metrics=metrics,
            trades=trades,
            equity_curve=equity_curve,
            drawdown_curve=self._compute_drawdown_curve(equity_curve),
        )

    def _compute_metrics(self, trades: List[BacktestTrade], equity_curve: List[float], initial_capital: float, exposure_history: Optional[List[float]] = None) -> BacktestMetrics:
        """Performans metrikleri hesapla."""
        if not trades:
            return BacktestMetrics(
                total_return_pct=0, cagr_pct=0, sharpe_ratio=0, sortino_ratio=0,
                calmar_ratio=0, max_drawdown_pct=0, max_drawdown_duration_days=0,
                win_rate=0, profit_factor=0, avg_win=0, avg_loss=0, expectancy=0,
                total_trades=0, total_fees=0, avg_holding_days=0, exposure_pct=0,
            )

        final = equity_curve[-1] if equity_curve else initial_capital
        total_return = (final / initial_capital - 1) * 100

        # Win/loss
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        win_rate = len(wins) / len(trades) if trades else 0
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t.pnl) for t in losses]) if losses else 0
        profit_factor = sum(t.pnl for t in wins) / sum(abs(t.pnl) for t in losses) if losses else float('inf')
        expectancy = np.mean([t.pnl for t in trades]) if trades else 0

        # Drawdown
        dd_curve = self._compute_drawdown_curve(equity_curve)
        max_dd = max(dd_curve) if dd_curve else 0

        # Returns
        if len(equity_curve) > 1:
            returns = np.diff(equity_curve) / equity_curve[:-1]
            sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0

            # Sortino: downside deviation sadece negatif getirilerden hesaplanır
            negative_returns = returns[returns < 0]
            downside_std = np.sqrt(np.mean(negative_returns ** 2)) if len(negative_returns) > 0 else 0
            sortino = (np.mean(returns) / downside_std * np.sqrt(252)) if downside_std > 0 else 0
        else:
            sharpe = 0
            sortino = 0

        # Fees
        total_fees = sum(t.commission for t in trades)

        # CAGR — gerçek tarih aralığı kullanarak
        try:
            _start = datetime.strptime(trades[0].entry_date, "%Y-%m-%d")
            _end = datetime.strptime(trades[-1].exit_date, "%Y-%m-%d")
            _years = max((_end - _start).days / 365.25, 0.01)
            _cagr = round(((final / initial_capital) ** (1 / _years) - 1) * 100, 2) if final > 0 else 0
        except Exception:
            _cagr = round(((final / initial_capital) ** (1 / max((len(equity_curve) - 1) / 252, 0.01)) - 1) * 100, 2) if final > 0 else 0

        # Max drawdown duration hesapla
        _max_dd_dur = 0
        if dd_curve:
            _in_dd = False
            _dd_start = 0
            for _i, _dd in enumerate(dd_curve):
                if _dd > 0 and not _in_dd:
                    _in_dd = True
                    _dd_start = _i
                elif _dd == 0 and _in_dd:
                    _in_dd = False
                    _max_dd_dur = max(_max_dd_dur, _i - _dd_start)
            if _in_dd:
                _max_dd_dur = max(_max_dd_dur, len(dd_curve) - _dd_start)

        return BacktestMetrics(
            total_return_pct=round(total_return, 2),
            cagr_pct=_cagr,
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(total_return / max_dd, 2) if max_dd > 0 else 0,
            max_drawdown_pct=round(max_dd, 2),
            max_drawdown_duration_days=_max_dd_dur,
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 2),
            avg_win=round(float(avg_win), 2),
            avg_loss=round(float(avg_loss), 2),
            expectancy=round(float(expectancy), 2),
            total_trades=len(trades),
            total_fees=round(total_fees, 2),
            avg_holding_days=float(np.mean([t.holding_days for t in trades])),
            exposure_pct=round(float(np.mean(exposure_history)) * 100, 2) if exposure_history else 0.0,
        )

    def _compute_drawdown_curve(self, equity_curve: List[float]) -> List[float]:
        """Drawdown eğrisi hesapla."""
        if not equity_curve:
            return []

        dd = []
        peak = equity_curve[0]
        for e in equity_curve:
            if e > peak:
                peak = e
            dd.append((peak - e) / peak * 100 if peak > 0 else 0)
        return dd


# Singleton
backtest_engine = BacktestEngine()


# =====================================================
# Backtest Modül Bağlantıları
# =====================================================
def get_backtest_systems() -> Dict[str, Any]:
    """Tüm backtest modüllerini getir."""
    systems = {}
    try:
        from .engine_v4 import BacktestEngineV4
        systems["engine_v4"] = BacktestEngineV4
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="BacktestEngineV4", error=str(e))
    try:
        from .enhanced_walk_forward import PurgeEmbargoWalkForward
        systems["enhanced_wf"] = PurgeEmbargoWalkForward
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="PurgeEmbargoWalkForward", error=str(e))
    try:
        from .portfolio_sim import PortfolioSimulator
        systems["portfolio_sim"] = PortfolioSimulator
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="PortfolioSimulator", error=str(e))
    try:
        from .walk_forward import WalkForwardEngine
        systems["walk_forward"] = WalkForwardEngine
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="WalkForwardEngine", error=str(e))
    try:
        from .walk_forward_runner import WalkForwardRunner
        systems["wf_runner"] = WalkForwardRunner
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="WalkForwardRunner", error=str(e))
    try:
        from .canonical_adapter import CanonicalBacktestAdapter
        systems["canonical_adapter"] = CanonicalBacktestAdapter
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="CanonicalBacktestAdapter", error=str(e))
    try:
        from .persistence import BacktestPersistence
        systems["persistence"] = BacktestPersistence
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to load module", module="BacktestPersistence", error=str(e))
    return systems
