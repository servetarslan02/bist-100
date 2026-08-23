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
        signals: list[dict[str, any]],
        price_data: dict[str, list[dict[str, any]]],
        initial_capital: float = 100000,
        commission_rate: float | None = None,
        slippage_pct: float = 0.05,
        dump_ledger: bool = False,
        stop_loss_pct: float = 0.07,
        trailing_stop_pct: float = 0.15,
        market_regime: float = 1.0,
    ):
        import csv
        import os
        from collections import defaultdict
        
        """Backtest calistir (CANONICAL ENGINE)."""
        if not signals:
            return BacktestResult(strategy_name, "", "", initial_capital, initial_capital, self._compute_metrics([], [], initial_capital, []), [], [], [])
            
        if commission_rate is not None:
            _cm = CommissionModel(broker_rate=commission_rate/2, exchange_rate=commission_rate/2)
        else:
            _cm = CommissionModel()

        capital = initial_capital
        positions = {}
        trades = []
        equity_curve = []
        exposure_history = []
        trade_id = 0
        
        trades_writer = None
        daily_writer = None
        trades_file = None
        daily_file = None
        
        if dump_ledger:
            os.makedirs('data/ledgers', exist_ok=True)
            trades_csv_path = 'data/ledgers/continuous_oos_trades.csv'
            daily_csv_path = 'data/ledgers/continuous_oos_daily.csv'
            
            # For continuous OOS, we want to overwrite cleanly
            trades_file = open(trades_csv_path, 'w', newline='', encoding='utf-8')
            daily_file = open(daily_csv_path, 'w', newline='', encoding='utf-8')
            
            trades_writer = csv.writer(trades_file)
            daily_writer = csv.writer(daily_file)
            
            trades_writer.writerow(['trade_id', 'ticker', 'side', 'signal_timestamp', 'execution_timestamp', 'signal_price', 'execution_price', 'quantity', 'gross_value', 'slippage', 'commission', 'other_cost', 'cash_before', 'cash_after', 'equity_before', 'equity_after', 'fold_id', 'reason', 'exit_reason'])
            daily_writer.writerow(['date', 'cash', 'market_value', 'gross_exposure', 'net_exposure', 'equity', 'daily_return', 'drawdown', 'fold_id'])
        # Tarihleri normalize et (YYYY-MM-DD string)
        all_dates = set()
        price_lookup = {}
        
        for ticker, rows in price_data.items():
            for row in rows:
                d = str(row["date"])[:10]
                all_dates.add(d)
                if d not in price_lookup:
                    price_lookup[d] = {}
                price_lookup[d][ticker] = row
                
        all_dates = sorted(list(all_dates))
        if not all_dates:
            all_dates = sorted(list(set([str(s["date"])[:10] for s in signals])))
            
        signals_by_date = defaultdict(list)
        for sig in signals:
            sig_d = str(sig["date"])[:10]
            signals_by_date[sig_d].append(sig)
            if sig_d not in all_dates:
                all_dates.append(sig_d)
        all_dates = sorted(list(set(all_dates)))
        
        peak_equity = initial_capital
        prev_equity = initial_capital

        for current_date in all_dates:
            day_prices = price_lookup.get(current_date, {})
            
        pending_orders = []

        for current_date in all_dates:
            day_prices = price_lookup.get(current_date, {})
            
            # 1. T+1 Pending Orders Execution at Market OPEN
            if pending_orders:
                for order in pending_orders:
                    ticker = order["ticker"]
                    action = order["action"]
                    signal_price = order["signal_price"]
                    signal_date = order["signal_date"]
                    weight = order["weight"]
                    regime_mult = order["market_regime"]

                    if ticker in day_prices:
                        exec_price = day_prices[ticker].get("open", day_prices[ticker].get("close", signal_price))
                        signal_volume = day_prices[ticker].get("volume", 0)
                    else:
                        exec_price = signal_price
                        signal_volume = 0

                    if exec_price <= 0:
                        continue

                    effective_slippage = self._compute_dynamic_slippage(exec_price, signal_volume if signal_volume > 0 else 100000, 100, slippage_pct)

                    if action == "BUY" and ticker not in positions:
                        fill_price = exec_price * (1 + effective_slippage / 100)
                        adjusted_weight = weight * regime_mult
                        position_value = (capital + sum([p["qty"] * day_prices.get(t, {}).get("open", p["avg_cost"]) for t, p in positions.items()])) * adjusted_weight
                        shares = int(position_value / fill_price)
                        if signal_volume > 0:
                            shares = self._check_liquidity_constraint(fill_price, signal_volume, shares)[1]

                        if shares > 0:
                            cost = shares * fill_price
                            commission = _cm.calculate(cost)
                            if capital >= (cost + commission):
                                cash_before = capital
                                capital -= (cost + commission)
                                positions[ticker] = {
                                    "qty": shares,
                                    "avg_cost": fill_price,
                                    "entry_date": current_date,
                                    "peak_price": fill_price,
                                    "commission": commission,
                                }
                                if dump_ledger:
                                    trades_writer.writerow([
                                        trade_id, ticker, 'BUY', signal_date, current_date, signal_price, fill_price,
                                        shares, cost, effective_slippage, commission, 0.0, cash_before, capital,
                                        capital + cost, capital + cost, '0', 'T+1_OPEN_SIGNAL', ''
                                    ])

                    elif action == "SELL" and ticker in positions:
                        fill_price = exec_price * (1 - effective_slippage / 100)
                        pos = positions[ticker]
                        revenue = pos["qty"] * fill_price
                        commission = _cm.calculate(revenue)
                        capital += (revenue - commission)

                        pnl = (fill_price - pos["avg_cost"]) * pos["qty"] - pos["commission"] - commission
                        pnl_pct = (fill_price / pos["avg_cost"] - 1) * 100
                        trade_id += 1

                        try:
                            _d1 = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                            _d2 = datetime.strptime(current_date, "%Y-%m-%d")
                            _holding = max(1, (_d2 - _d1).days)
                        except Exception:
                            _holding = 1

                        trades.append(BacktestTrade(
                            trade_id=trade_id, ticker=ticker, side="BUY-SELL", entry_date=pos["entry_date"], exit_date=current_date,
                            entry_price=pos["avg_cost"], exit_price=fill_price, quantity=pos["qty"], pnl=round(pnl, 2),
                            pnl_pct=round(pnl_pct, 2), holding_days=_holding, commission=round(pos["commission"] + commission, 2),
                        ))
                        del positions[ticker]
                        if dump_ledger:
                            trades_writer.writerow([
                                trade_id, ticker, 'SELL', signal_date, current_date, signal_price, fill_price,
                                pos["qty"], revenue, effective_slippage, commission, 0.0, capital - revenue, capital,
                                capital, capital, '0', 'T+1_OPEN_SIGNAL', 'EXIT'
                            ])

                pending_orders = []

            # 2. Intraday Stop-Loss & Trailing Stop Checks (using intraday Low / High)
            total_market_value = 0.0
            to_sell_due_to_stop = []
            
            for t, p in positions.items():
                close_price = day_prices.get(t, {}).get("close", p["avg_cost"])
                low_price = day_prices.get(t, {}).get("low", close_price)
                high_price = day_prices.get(t, {}).get("high", close_price)
                
                # Update peak price with intraday High
                p["peak_price"] = max(p.get("peak_price", high_price), high_price)
                
                # Check stops using intraday Low
                is_stop_loss = low_price <= p["avg_cost"] * (1 - stop_loss_pct)
                is_trailing_stop = low_price <= p["peak_price"] * (1 - trailing_stop_pct)
                
                if is_stop_loss or is_trailing_stop:
                    # Executed at stop price (or low if gap down)
                    stop_level = min(close_price, p["avg_cost"] * (1 - stop_loss_pct) if is_stop_loss else p["peak_price"] * (1 - trailing_stop_pct))
                    to_sell_due_to_stop.append((t, stop_level))
                else:
                    total_market_value += p["qty"] * close_price
            
            # Execute stop sells
            for t, exit_price in to_sell_due_to_stop:
                p = positions[t]
                qty = p["qty"]
                gross = qty * exit_price
                comm = _cm.calculate(gross)
                capital += (gross - comm)
                
                trades.append(BacktestTrade(
                    trade_id=trade_id, ticker=t, side="STOP_SELL", entry_date=p["entry_date"],
                    exit_date=current_date, entry_price=p["avg_cost"], exit_price=exit_price,
                    quantity=qty, pnl=(gross - comm) - (qty * p["avg_cost"]),
                    pnl_pct=(exit_price / p["avg_cost"]) - 1.0,
                    holding_days=len([d for d in all_dates if p["entry_date"] <= d <= current_date]),
                    commission=comm
                ))
                trade_id += 1
                del positions[t]
                
            current_equity = capital + total_market_value
            
            # 3. Process Signals generated at current day close -> Queue for T+1 Open Execution
            if current_date in signals_by_date:
                day_sigs = sorted(signals_by_date[current_date], key=lambda x: 0 if x.get("action") == "SELL" else 1)
                for signal in day_sigs:
                    action = signal.get("action", "HOLD")
                    if action in ["BUY", "SELL"]:
                        pending_orders.append({
                            "ticker": signal.get("ticker", ""),
                            "action": action,
                            "signal_price": signal.get("price", day_prices.get(signal.get("ticker", ""), {}).get("close", 0.0)),
                            "signal_date": current_date,
                            "weight": signal.get("weight", 0.10),
                            "market_regime": market_regime,
                        })

            # End of Day Accounting
            total_market_value = 0.0
            for t, p in positions.items():
                current_price = day_prices.get(t, {}).get("close", p["avg_cost"])
                total_market_value += p["qty"] * current_price
            
            end_of_day_equity = capital + total_market_value
            if end_of_day_equity > peak_equity:
                peak_equity = end_of_day_equity
            
            drawdown = (peak_equity - end_of_day_equity) / peak_equity if peak_equity > 0 else 0.0
            daily_return = (end_of_day_equity / prev_equity - 1.0) if prev_equity > 0 else 0.0
            
            if dump_ledger:
                daily_writer.writerow([
                    current_date, capital, total_market_value, total_market_value, total_market_value, end_of_day_equity, daily_return, drawdown, '0'
                ])
            
            equity_curve.append(end_of_day_equity)
            exposure_history.append(total_market_value / end_of_day_equity if end_of_day_equity > 0 else 0)
            prev_equity = end_of_day_equity

        if dump_ledger:
            trades_file.close()
            daily_file.close()
        
        metrics = self._compute_metrics(trades, equity_curve, initial_capital, exposure_history)

        return BacktestResult(
            strategy_name=strategy_name, start_date=all_dates[0] if all_dates else "", end_date=all_dates[-1] if all_dates else "",
            initial_capital=initial_capital, final_capital=round(equity_curve[-1] if equity_curve else initial_capital, 2),
            metrics=metrics, trades=trades, equity_curve=equity_curve, drawdown_curve=self._compute_drawdown_curve(equity_curve),
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
            avg_holding_days=float(np.mean([t.holding_days for t in trades])) if trades else 0.0,
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
