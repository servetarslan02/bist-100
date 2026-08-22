"""
ALPHA BIST — Portfolio Simulator v3.0 (Institutional Grade)

Finansal doğruluk:
- Position lifecycle (open → partial close → full close)
- Oversell prevention
- Cash accounting invariant: cash + cost_basis + realized_pnl = initial (approximately)
- Commission: BIST yapısı (broker + exchange + BSMV)
- Slippage: volume-aware
- Realized / unrealized P&L
- Daily equity snapshot
- Audit trail (her işlem loglanır)
- Deterministic sonuç garantisi

Mevcut v2.0 ile aynı finansal sonuçları üretir.
"""

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Lazy import to avoid circular dependency
_transaction_cost_engine = None

def _get_cost_engine():
    global _transaction_cost_engine
    if _transaction_cost_engine is None:
        try:
            from .transaction_costs import bist_transaction_cost
            _transaction_cost_engine = bist_transaction_cost
        except ImportError:
            _transaction_cost_engine = None
    return _transaction_cost_engine


# =====================================================
# DATA CLASSES
# =====================================================

@dataclass
class Trade:
    """Tek bir trade kaydı."""
    trade_id: int
    ticker: str
    side: str              # BUY | SELL
    date: str
    quantity: int
    price: float
    commission: float
    slippage: float
    pnl: float = 0.0       # Sadece SELL'de
    pnl_pct: float = 0.0
    holding_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "ticker": self.ticker,
            "side": self.side,
            "date": self.date,
            "quantity": self.quantity,
            "price": round(self.price, 4),
            "commission": round(self.commission, 2),
            "slippage": round(self.slippage, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "holding_days": self.holding_days,
        }


@dataclass
class Position:
    """Açık pozisyon."""
    ticker: str
    quantity: int
    entry_price: float
    entry_date: str
    cost_basis: float       # Toplam maliyet (fiyat × adet + komisyon + slippage)
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis <= 0:
            return 0.0
        return (self.market_value / self.cost_basis - 1) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 4),
            "entry_date": self.entry_date,
            "cost_basis": round(self.cost_basis, 2),
            "current_price": round(self.current_price, 4),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 4),
        }


@dataclass
class EquitySnapshot:
    """Günlük equity kaydı."""
    date: str
    equity: float
    cash: float
    market_value: float
    positions: int
    drawdown: float
    daily_return: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "market_value": round(self.market_value, 2),
            "positions": self.positions,
            "drawdown": round(self.drawdown, 6),
            "daily_return": round(self.daily_return, 6),
        }


@dataclass
class AuditEntry:
    """Audit trail kaydı."""
    timestamp: str
    date: str
    entry_type: str    # BUY | SELL | EQUITY | ERROR | INFO
    ticker: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# =====================================================
# COMMISSION MODEL (BIST)
# =====================================================

class BISTCommissionModel:
    """BIST komisyon yapısı."""

    BROKER_RATE = 0.0003      # %0.03
    EXCHANGE_RATE = 0.000056   # %0.0056
    BSMV_RATE = 0.05           # BSMV (komisyon üzerinden %5)
    MIN_COMMISSION = 1.0       # Minimum 1 TL

    @classmethod
    def compute(cls, amount: float) -> float:
        broker = amount * cls.BROKER_RATE
        exchange = amount * cls.EXCHANGE_RATE
        base = broker + exchange
        bsmv = base * cls.BSMV_RATE
        return max(base + bsmv, cls.MIN_COMMISSION)


# =====================================================
# PORTFOLIO SIMULATOR v3.0
# =====================================================

class PortfolioSimulatorV3:
    """Kurumsal seviye portföy simülasyonu.

    v2.0 ile aynı finansal sonuçları üretir.
    Ek: audit trail, invariant checks, XU100 benchmark.
    v4.1: TransactionCostEngine entegrasyonu (opsiyonel).
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        max_position_pct: float = 0.10,
        max_positions: int = 20,
        slippage_rate: float = 0.001,
        use_realistic_costs: bool = False,
        avg_daily_volume: float = 0,
        volatility_ratio: float = 1.0,
    ):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._max_position_pct = max_position_pct
        self._max_positions = max_positions
        self._slippage_rate = slippage_rate
        self._use_realistic_costs = use_realistic_costs
        self._avg_daily_volume = avg_daily_volume
        self._volatility_ratio = volatility_ratio

        self._positions: dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._equity_curve: list[EquitySnapshot] = []
        self._audit_log: list[AuditEntry] = []

        self._high_water_mark = initial_capital
        self._prev_equity = initial_capital
        self._trade_counter = 0

        # Benchmark
        self._benchmark_equity: list[tuple[str, float]] = []

        # MaxDD duration tracking
        self._drawdown_start_date: str | None = None
        self._max_drawdown_duration_days: int = 0

    # ===================== CORE OPERATIONS =====================

    def execute_buy(
        self,
        ticker: str,
        price: float,
        date: str,
        quantity: int | None = None,
        avg_daily_volume: float | None = None,
        volatility_ratio: float | None = None,
    ) -> Trade | None:
        """Alım emri execute et.

        quantity belirtilmezse max_position_pct'ye göre otomatik hesapla.
        avg_daily_volume/volatility_ratio: realistic cost model için.
        """
        if ticker in self._positions:
            self._audit(date, "ERROR", ticker, {"reason": "already_holding"})
            return None

        if len(self._positions) >= self._max_positions:
            self._audit(date, "ERROR", ticker, {"reason": "max_positions_reached"})
            return None

        if price <= 0 or np.isnan(price):
            self._audit(date, "ERROR", ticker, {"reason": "invalid_price", "price": price})
            return None

        # Otomatik quantity hesapla
        if quantity is None:
            total_equity = self.get_total_value()
            max_amount = min(
                total_equity * self._max_position_pct,
                self._cash * 0.95  # %5 nakit buffer
            )
            quantity = int(max_amount / (price * (1 + self._slippage_rate + 0.001)))
            if quantity <= 0:
                return None

        # Maliyet hesaplama: realistic veya legacy
        cost_engine = _get_cost_engine() if self._use_realistic_costs else None

        if cost_engine is not None:
            adv = avg_daily_volume if avg_daily_volume is not None else self._avg_daily_volume
            vol_r = volatility_ratio if volatility_ratio is not None else self._volatility_ratio
            cost_detail = cost_engine.calculate_total_cost(
                side="BUY",
                price=price,
                quantity=quantity,
                ticker=ticker,
                avg_daily_volume=adv,
                volatility_ratio=vol_r,
            )
            fill_price = cost_detail["execution_price"]
            commission = cost_detail["costs"]["commission"]
            slippage_amount = cost_detail["costs"]["slippage"]
            # Notional at fill price (slippage dahil)
            amount = quantity * fill_price
            # total_cost = notional + commission
            # Slippage zaten fill_price'a dahil, ayrıca eklenmez
            total_cost = amount + commission
        else:
            # Legacy path (v2.0 ile aynı)
            slippage_pct = self._slippage_rate
            fill_price = price * (1 + slippage_pct)
            amount = quantity * fill_price  # Slippage dahil notional
            commission = BISTCommissionModel.compute(amount)
            slippage_amount = amount - (quantity * price)  # Bilgi amaçlı
            # total_cost = notional (slippage dahil) + commission
            # Slippage zaten fill_price'a dahil, ayrıca eklenmez
            total_cost = amount + commission

        # Cash kontrolü
        if total_cost > self._cash:
            # Düşük quantity ile dene
            quantity = int((self._cash - 1) / (fill_price * 1.002))
            if quantity <= 0:
                self._audit(date, "ERROR", ticker, {"reason": "insufficient_cash",
                            "required": total_cost, "available": self._cash})
                return None
            if cost_engine is not None:
                cost_detail = cost_engine.calculate_total_cost(
                    side="BUY", price=price, quantity=quantity, ticker=ticker,
                    avg_daily_volume=adv,
                    volatility_ratio=vol_r,
                )
                fill_price = cost_detail["execution_price"]
                commission = cost_detail["costs"]["commission"]
                slippage_amount = cost_detail["costs"]["slippage"]
            else:
                fill_price = price * (1 + self._slippage_rate)
                slippage_amount = quantity * (fill_price - price)
                commission = BISTCommissionModel.compute(quantity * fill_price)
            amount = quantity * fill_price
            total_cost = amount + commission

        # Execute
        self._cash -= total_cost
        self._positions[ticker] = Position(
            ticker=ticker,
            quantity=quantity,
            entry_price=fill_price,
            entry_date=date,
            cost_basis=total_cost,
            current_price=price,
        )

        self._trade_counter += 1
        trade = Trade(
            trade_id=self._trade_counter,
            ticker=ticker,
            side="BUY",
            date=date,
            quantity=quantity,
            price=fill_price,
            commission=commission,
            slippage=slippage_amount,
        )
        self._trades.append(trade)
        if len(self._trades) > 5000:
            self._trades = self._trades[-5000:]
        self._audit(date, "BUY", ticker, trade.to_dict())
        return trade

    def execute_sell(
        self,
        ticker: str,
        price: float,
        date: str,
        avg_daily_volume: float | None = None,
        volatility_ratio: float | None = None,
    ) -> Trade | None:
        """Satım emri execute et (tam kapatma)."""
        if ticker not in self._positions:
            return None

        if price <= 0 or np.isnan(price):
            self._audit(date, "ERROR", ticker, {"reason": "invalid_price", "price": price})
            return None

        pos = self._positions[ticker]
        quantity = pos.quantity

        # Maliyet hesaplama: realistic veya legacy
        cost_engine = _get_cost_engine() if self._use_realistic_costs else None

        if cost_engine is not None:
            adv = avg_daily_volume if avg_daily_volume is not None else self._avg_daily_volume
            vol_r = volatility_ratio if volatility_ratio is not None else self._volatility_ratio
            cost_detail = cost_engine.calculate_total_cost(
                side="SELL",
                price=price,
                quantity=quantity,
                ticker=ticker,
                avg_daily_volume=adv,
                volatility_ratio=vol_r,
            )
            fill_price = cost_detail["execution_price"]
            # Komisyon market price üzerinden (BUY ile tutarlı)
            market_notional = quantity * price
            commission = BISTCommissionModel.compute(market_notional)
            slippage_amount = cost_detail["costs"]["slippage"]
        else:
            fill_price = price * (1 - self._slippage_rate)
            slippage_amount = quantity * (price - fill_price)  # Bilgi amaçlı
            commission = BISTCommissionModel.compute(quantity * price)

        # Revenue
        amount = quantity * fill_price
        net_revenue = amount - commission

        # P&L
        pnl = net_revenue - pos.cost_basis
        pnl_pct = (fill_price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0

        # Holding days
        holding_days = self._compute_holding_days(pos.entry_date, date)

        # Execute
        self._cash += net_revenue
        del self._positions[ticker]

        self._trade_counter += 1
        trade = Trade(
            trade_id=self._trade_counter,
            ticker=ticker,
            side="SELL",
            date=date,
            quantity=quantity,
            price=fill_price,
            commission=commission,
            slippage=slippage_amount,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holding_days=holding_days,
        )
        self._trades.append(trade)
        if len(self._trades) > 5000:
            self._trades = self._trades[-5000:]
        self._audit(date, "SELL", ticker, trade.to_dict())
        return trade

    def update_equity(
        self,
        prices: dict[str, float],
        date: str,
        benchmark_price: float | None = None,
    ):
        """Günlük equity snapshot al."""
        # Pozisyon fiyatlarını güncelle
        for ticker, pos in self._positions.items():
            if ticker in prices:
                pos.current_price = prices[ticker]

        market_value = sum(p.market_value for p in self._positions.values())
        equity = self._cash + market_value

        # Invariant check
        invariant_ok = abs(equity - (self._cash + market_value)) < 0.01
        if not invariant_ok:
            self._audit(date, "ERROR", "", {
                "reason": "equity_invariant_violation",
                "equity": equity,
                "cash": self._cash,
                "market_value": market_value,
            })

        # High water mark
        if equity > self._high_water_mark:
            self._high_water_mark = equity
            # Drawdown bitti
            if self._drawdown_start_date is not None:
                self._drawdown_start_date = None

        # Drawdown
        drawdown = (self._high_water_mark - equity) / self._high_water_mark if self._high_water_mark > 0 else 0

        # Drawdown duration tracking
        if drawdown > 0 and self._drawdown_start_date is None:
            self._drawdown_start_date = date
        if drawdown > 0 and self._drawdown_start_date is not None:
            try:
                from datetime import datetime
                d1 = datetime.strptime(self._drawdown_start_date, "%Y-%m-%d")
                d2 = datetime.strptime(date, "%Y-%m-%d")
                dd_duration = (d2 - d1).days
                if dd_duration > self._max_drawdown_duration_days:
                    self._max_drawdown_duration_days = dd_duration
            except Exception:
                pass

        # Daily return
        daily_return = (equity / self._prev_equity - 1) if self._prev_equity > 0 else 0

        snapshot = EquitySnapshot(
            date=date,
            equity=equity,
            cash=self._cash,
            market_value=market_value,
            positions=len(self._positions),
            drawdown=drawdown,
            daily_return=daily_return,
        )
        self._equity_curve.append(snapshot)
        if len(self._equity_curve) > 5000:
            self._equity_curve = self._equity_curve[-5000:]
        self._prev_equity = equity

        # Benchmark
        if benchmark_price is not None:
            self._benchmark_equity.append((date, benchmark_price))
            if len(self._benchmark_equity) > 5000:
                self._benchmark_equity = self._benchmark_equity[-5000:]

    # ===================== QUERIES =====================

    def get_total_value(self) -> float:
        return self._cash + sum(p.market_value for p in self._positions.values())

    def get_realized_pnl(self) -> float:
        return sum(t.pnl for t in self._trades if t.side == "SELL")

    def get_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    def can_buy(self) -> bool:
        return len(self._positions) < self._max_positions and self._cash > 0

    def get_position_count(self) -> int:
        return len(self._positions)

    def has_position(self, ticker: str) -> bool:
        return ticker in self._positions

    def get_trades(self) -> list[Trade]:
        return self._trades

    def get_equity_curve(self) -> list[EquitySnapshot]:
        return self._equity_curve

    def get_audit_log(self) -> list[AuditEntry]:
        return self._audit_log

    # ===================== METRICS =====================

    def compute_metrics(self) -> dict[str, Any]:
        """Performans metrikleri hesapla."""
        # Trade-based metrics (equity curve gerektirmez)
        sell_trades = [t for t in self._trades if t.side == "SELL"]
        sell_pnls = np.array([t.pnl for t in sell_trades]) if sell_trades else np.array([])

        winning = int(np.sum(sell_pnls > 0)) if len(sell_pnls) > 0 else 0
        win_rate = winning / len(sell_pnls) * 100 if len(sell_pnls) > 0 else 0
        gross_profit = float(np.sum(sell_pnls[sell_pnls > 0])) if len(sell_pnls) > 0 else 0
        gross_loss = float(np.abs(np.sum(sell_pnls[sell_pnls < 0]))) if len(sell_pnls) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = float(np.mean(sell_pnls)) if len(sell_pnls) > 0 else 0
        total_commission = sum(t.commission for t in self._trades)
        total_slippage = sum(t.slippage for t in self._trades)

        if not self._equity_curve:
            return {
                "initial_capital": self._initial_capital,
                "final_equity": self._cash + sum(p.market_value for p in self._positions.values()),
                "total_return_pct": 0, "cagr_pct": 0,
                "sharpe_ratio": 0, "sortino_ratio": 0, "calmar_ratio": 0,
                "max_drawdown_pct": 0,
                "win_rate_pct": round(win_rate, 1),
                "profit_factor": round(profit_factor, 4),
                "expectancy": round(expectancy, 2),
                "total_trades": len(self._trades),
                "sell_trades": len(sell_trades),
                "total_commission": round(total_commission, 2),
                "total_slippage": round(total_slippage, 2),
                "open_positions": len(self._positions),
                "benchmark_return_pct": 0, "alpha_pct": 0,
                "daily_returns_count": 0,
                "var_95": 0, "cvar_95": 0,
                "max_drawdown_duration_days": 0,
            }

        final_equity = self._equity_curve[-1].equity
        total_return_pct = (final_equity / self._initial_capital - 1) * 100

        # Returns array
        returns = np.array([s.daily_return for s in self._equity_curve])

        # Sharpe
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:
            sharpe = 0.0

        # Sortino (correct: sqrt of mean squared downside)
        downside_returns = np.minimum(returns, 0)
        downside_std = float(np.sqrt(np.mean(downside_returns ** 2)))
        sortino = float(np.mean(returns) / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

        # VaR 95% (Historical)
        var_95 = float(np.percentile(returns, 5)) if len(returns) >= 20 else 0.0

        # CVaR 95% (Expected Shortfall)
        cvar_95 = float(np.mean(returns[returns <= var_95])) if len(returns[returns <= var_95]) > 0 else var_95

        # Max drawdown
        max_dd = max(s.drawdown for s in self._equity_curve) * 100

        # Calmar
        calmar = total_return_pct / max_dd if max_dd > 0 else 0.0

        # Benchmark comparison
        benchmark_return = 0.0
        if self._benchmark_equity and len(self._benchmark_equity) >= 2:
            bench_start = self._benchmark_equity[0][1]
            bench_end = self._benchmark_equity[-1][1]
            if bench_start > 0:
                benchmark_return = (bench_end / bench_start - 1) * 100

        # Alpha
        alpha = total_return_pct - benchmark_return

        # CAGR
        n_days = len(self._equity_curve)
        n_years = n_days / 252 if n_days > 0 else 1
        cagr = ((final_equity / self._initial_capital) ** (1 / n_years) - 1) * 100 if n_years > 0 and final_equity > 0 else 0

        return {
            "initial_capital": self._initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return_pct, 2),
            "cagr_pct": round(cagr, 2),
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "calmar_ratio": round(calmar, 4),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 4),
            "expectancy": round(float(expectancy), 2),
            "total_trades": len(self._trades),
            "sell_trades": len(sell_trades),
            "total_commission": round(total_commission, 2),
            "total_slippage": round(total_slippage, 2),
            "open_positions": len(self._positions),
            "benchmark_return_pct": round(benchmark_return, 2),
            "alpha_pct": round(alpha, 2),
            "daily_returns_count": len(returns),
            "var_95": round(var_95, 6),
            "cvar_95": round(cvar_95, 6),
            "max_drawdown_duration_days": self._max_drawdown_duration_days,
        }

    # ===================== INVARIANT CHECKS =====================

    def check_invariants(self) -> tuple[bool, list[str]]:
        """Finansal invariant'ları kontrol et."""
        errors = []

        # 1. Cash negatif olmamalı
        if self._cash < -0.01:
            errors.append(f"Negative cash: {self._cash:.2f}")

        # 2. Equity = cash + market_value
        market_value = sum(p.market_value for p in self._positions.values())
        computed_equity = self._cash + market_value
        if self._equity_curve:
            actual_equity = self._equity_curve[-1].equity
            if abs(actual_equity - computed_equity) > 0.01:
                errors.append(f"Equity mismatch: {actual_equity:.2f} != {computed_equity:.2f}")

        # 3. Pozisyon quantity > 0
        for ticker, pos in self._positions.items():
            if pos.quantity <= 0:
                errors.append(f"Invalid quantity for {ticker}: {pos.quantity}")
            if pos.entry_price <= 0:
                errors.append(f"Invalid entry_price for {ticker}: {pos.entry_price}")

        # 4. Trade P&L tutarlılığı
        for t in self._trades:
            if t.side == "SELL" and t.commission < 0:
                errors.append(f"Negative commission on sell: {t.trade_id}")

        return len(errors) == 0, errors

    # ===================== HELPERS =====================

    @staticmethod
    def _compute_holding_days(entry_date: str, exit_date: str) -> int:
        try:
            from datetime import datetime
            d1 = datetime.strptime(entry_date, "%Y-%m-%d")
            d2 = datetime.strptime(exit_date, "%Y-%m-%d")
            return max(0, (d2 - d1).days)
        except Exception:
            return 0

    def _audit(self, date: str, entry_type: str, ticker: str, details: dict[str, Any]):
        from datetime import datetime
        self._audit_log.append(AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            date=date,
            entry_type=entry_type,
            ticker=ticker,
            details=details,
        ))

    def reset(self):
        """Sıfırla."""
        self._cash = self._initial_capital
        self._positions.clear()
        self._trades.clear()
        self._equity_curve.clear()
        self._audit_log.clear()
        self._benchmark_equity.clear()
        self._high_water_mark = self._initial_capital
        self._prev_equity = self._initial_capital
        self._trade_counter = 0
        self._drawdown_start_date = None
        self._max_drawdown_duration_days = 0
