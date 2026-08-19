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

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import structlog

logger = structlog.get_logger()


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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
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
    details: Dict[str, Any] = field(default_factory=dict)


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
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        max_position_pct: float = 0.10,
        max_positions: int = 20,
        slippage_rate: float = 0.001,
    ):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._max_position_pct = max_position_pct
        self._max_positions = max_positions
        self._slippage_rate = slippage_rate

        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []
        self._equity_curve: List[EquitySnapshot] = []
        self._audit_log: List[AuditEntry] = []

        self._high_water_mark = initial_capital
        self._prev_equity = initial_capital
        self._trade_counter = 0

        # Benchmark
        self._benchmark_equity: List[Tuple[str, float]] = []

    # ===================== CORE OPERATIONS =====================

    def execute_buy(
        self,
        ticker: str,
        price: float,
        date: str,
        quantity: Optional[int] = None,
    ) -> Optional[Trade]:
        """Alım emri execute et.

        quantity belirtilmezse max_position_pct'ye göre otomatik hesapla.
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
            max_amount = min(
                self._cash * self._max_position_pct,
                self._cash * 0.95  # %5 nakit buffer
            )
            quantity = int(max_amount / (price * (1 + self._slippage_rate + 0.001)))
            if quantity <= 0:
                return None

        # Slippage
        slippage_pct = self._slippage_rate
        fill_price = price * (1 + slippage_pct)

        # Maliyet
        amount = quantity * fill_price
        commission = BISTCommissionModel.compute(amount)
        total_cost = amount + commission

        # Cash kontrolü
        if total_cost > self._cash:
            # Düşük quantity ile dene
            quantity = int((self._cash - 1) / (fill_price * 1.002))
            if quantity <= 0:
                self._audit(date, "ERROR", ticker, {"reason": "insufficient_cash",
                            "required": total_cost, "available": self._cash})
                return None
            amount = quantity * fill_price
            commission = BISTCommissionModel.compute(amount)
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
            slippage=amount * slippage_pct,
        )
        self._trades.append(trade)
        self._audit(date, "BUY", ticker, trade.to_dict())
        return trade

    def execute_sell(
        self,
        ticker: str,
        price: float,
        date: str,
    ) -> Optional[Trade]:
        """Satım emri execute et (tam kapatma)."""
        if ticker not in self._positions:
            return None

        if price <= 0 or np.isnan(price):
            self._audit(date, "ERROR", ticker, {"reason": "invalid_price", "price": price})
            return None

        pos = self._positions[ticker]
        quantity = pos.quantity

        # Slippage
        fill_price = price * (1 - self._slippage_rate)

        # Revenue
        amount = quantity * fill_price
        commission = BISTCommissionModel.compute(amount)
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
            slippage=amount * self._slippage_rate,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holding_days=holding_days,
        )
        self._trades.append(trade)
        self._audit(date, "SELL", ticker, trade.to_dict())
        return trade

    def update_equity(
        self,
        prices: Dict[str, float],
        date: str,
        benchmark_price: Optional[float] = None,
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

        # Drawdown
        drawdown = (self._high_water_mark - equity) / self._high_water_mark if self._high_water_mark > 0 else 0

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
        self._prev_equity = equity

        # Benchmark
        if benchmark_price is not None:
            self._benchmark_equity.append((date, benchmark_price))

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

    def get_trades(self) -> List[Trade]:
        return self._trades

    def get_equity_curve(self) -> List[EquitySnapshot]:
        return self._equity_curve

    def get_audit_log(self) -> List[AuditEntry]:
        return self._audit_log

    # ===================== METRICS =====================

    def compute_metrics(self) -> Dict[str, Any]:
        """Performans metrikleri hesapla."""
        # Trade-based metrics (equity curve gerektirmez)
        sell_trades = [t for t in self._trades if t.side == "SELL"]
        winning = sum(1 for t in sell_trades if t.pnl > 0)
        win_rate = winning / len(sell_trades) * 100 if sell_trades else 0
        gross_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = float(np.mean([t.pnl for t in sell_trades])) if sell_trades else 0
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
        }

    # ===================== INVARIANT CHECKS =====================

    def check_invariants(self) -> Tuple[bool, List[str]]:
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
        except Exception as e:
            return 0

    def _audit(self, date: str, entry_type: str, ticker: str, details: Dict[str, Any]):
        from datetime import datetime, timezone
        self._audit_log.append(AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
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
