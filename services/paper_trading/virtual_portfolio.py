"""
ALPHA BIST — Virtual Portfolio v1.0

Sanal portfoy yonetimi:
- Cash, positions, average cost
- Realized / unrealized P&L
- Mark-to-market (gunluk fiyat guncelleme)
- Sektorel agirlik takibi
- Persistent state entegrasyonu

Mevcut modelleri kullanir:
- services.core.models.Portfolio
- services.portfolio.portfolio_manager.Position (dataclass)
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict
import structlog

from ..core.models import Portfolio, Position
from ..portfolio.portfolio_manager import Position as PortfolioPosition

logger = structlog.get_logger()


class VirtualPortfolio:
    """Sanal portfoy — gercek para YOK."""

    def __init__(self, initial_capital: float = 1_000_000.0, state_store=None):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._trades: List[Dict[str, Any]] = []
        self._orders: List[Dict[str, Any]] = []
        self._equity_curve: List[Dict[str, Any]] = []
        self._state_store = state_store
        self._max_equity = initial_capital
        self._current_date = ""

        logger.info("VirtualPortfolio initialized", initial_capital=initial_capital)

    # ===================== PERSISTENCE =====================

    def load_from_store(self):
        """State store'dan yukle."""
        if not self._state_store:
            return
        snapshot = self._state_store.load_portfolio_state()
        if snapshot:
            self.cash = snapshot.get("cash", self.initial_capital)
            self.initial_capital = snapshot.get("initial_capital", self.initial_capital)
            self._positions = {p["ticker"]: p for p in snapshot.get("positions", [])}
            self._trades = snapshot.get("trades", [])
            self._orders = snapshot.get("orders", [])
            self._equity_curve = snapshot.get("equity_curve", [])
            logger.info("VirtualPortfolio loaded from store",
                       positions=len(self._positions), trades=len(self._trades))

    def save_to_store(self, date: str):
        """State store'a kaydet."""
        if not self._state_store:
            return
        snapshot = {
            "date": date,
            "cash": self.cash,
            "initial_capital": self.initial_capital,
            "positions": list(self._positions.values()),
            "equity_curve": self._equity_curve,
            "trades": self._trades,
            "orders": self._orders,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self._state_store.save_portfolio_state(snapshot)
        self._state_store.save_positions(list(self._positions.values()))

    # ===================== POSITION MANAGEMENT =====================

    def open_position(
        self,
        ticker: str,
        quantity: int,
        price: float,
        sector: str = "",
        date: str = "",
        commission: float = 0.0,
    ) -> Dict[str, Any]:
        """Yeni pozisyon ac veya mevcut pozisyonu artir."""
        cost = quantity * price + commission

        if cost > self.cash:
            logger.warning("Insufficient cash for position",
                         ticker=ticker, required=cost, available=self.cash)
            return {"success": False, "error": "INSUFFICIENT_CASH", "required": cost, "available": self.cash}

        if ticker in self._positions:
            # Mevcut pozisyonu artir — weighted average cost
            pos = self._positions[ticker]
            old_cost = pos["quantity"] * pos["avg_cost"]
            new_cost = quantity * price + commission
            total_qty = pos["quantity"] + quantity
            pos["avg_cost"] = (old_cost + new_cost) / total_qty if total_qty > 0 else price
            pos["quantity"] = total_qty
            pos["current_price"] = price
            pos["market_value"] = total_qty * price
            pos["sector"] = sector or pos.get("sector", "")
            logger.info("Position increased", ticker=ticker, new_qty=total_qty, avg_cost=pos["avg_cost"])
        else:
            # Yeni pozisyon
            avg_with_commission = (quantity * price + commission) / quantity if quantity > 0 else price
            self._positions[ticker] = {
                "ticker": ticker,
                "quantity": quantity,
                "avg_cost": avg_with_commission,
                "current_price": price,
                "market_value": quantity * price,
                "sector": sector,
                "entry_date": date,
                "last_update": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("Position opened", ticker=ticker, quantity=quantity, price=price)

        self.cash -= cost
        self._current_date = date
        return {"success": True, "ticker": ticker, "quantity": quantity, "cash_remaining": self.cash}

    def close_position(
        self,
        ticker: str,
        price: float,
        date: str = "",
        commission: float = 0.0,
        reason: str = "EXIT_SIGNAL",
    ) -> Dict[str, Any]:
        """Pozisyon kapat."""
        if ticker not in self._positions:
            return {"success": False, "error": "NO_POSITION", "ticker": ticker}

        pos = self._positions[ticker]
        quantity = pos["quantity"]

        # Revenue
        revenue = quantity * price - commission
        self.cash += revenue

        # Realized P&L
        realized_pnl = (price - pos["avg_cost"]) * quantity - commission
        realized_pnl_pct = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0

        # Trade kaydi
        trade = {
            "trade_id": f"TRD_{date}_{ticker}_{uuid.uuid4().hex[:8]}",
            "ticker": ticker,
            "side": "SELL",
            "quantity": quantity,
            "entry_price": pos["avg_cost"],
            "exit_price": price,
            "entry_date": pos.get("entry_date", date),
            "exit_date": date,
            "commission": commission,
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl_pct, 2),
            "holding_days": self._holding_days(pos.get("entry_date"), date),
            "reason": reason,
        }
        self._trades.append(trade)

        if self._state_store:
            self._state_store.save_trade(trade)

        del self._positions[ticker]

        logger.info("Position closed", ticker=ticker, realized_pnl=realized_pnl, reason=reason)
        self._current_date = date
        return {
            "success": True,
            "ticker": ticker,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "cash": self.cash,
            "trade": trade,
        }

    def reduce_position(
        self,
        ticker: str,
        quantity: int,
        price: float,
        date: str = "",
        commission: float = 0.0,
        reason: str = "PARTIAL_EXIT",
    ) -> Dict[str, Any]:
        """Pozisyonu kismen kapat."""
        if ticker not in self._positions:
            return {"success": False, "error": "NO_POSITION"}

        pos = self._positions[ticker]
        if quantity >= pos["quantity"]:
            return self.close_position(ticker, price, date, commission, reason)

        # Kismen kapat
        revenue = quantity * price - commission
        self.cash += revenue

        realized_pnl = (price - pos["avg_cost"]) * quantity - commission

        trade = {
            "trade_id": f"TRD_{date}_{ticker}_partial_{uuid.uuid4().hex[:8]}",
            "ticker": ticker,
            "side": "SELL",
            "quantity": quantity,
            "entry_price": pos["avg_cost"],
            "exit_price": price,
            "entry_date": pos.get("entry_date", date),
            "exit_date": date,
            "commission": commission,
            "realized_pnl": round(realized_pnl, 2),
            "reason": reason,
        }
        self._trades.append(trade)
        if self._state_store:
            self._state_store.save_trade(trade)

        pos["quantity"] -= quantity
        pos["market_value"] = pos["quantity"] * price

        logger.info("Position reduced", ticker=ticker, remaining=pos["quantity"], realized_pnl=realized_pnl)
        return {"success": True, "ticker": ticker, "remaining": pos["quantity"], "realized_pnl": realized_pnl}

    def update_prices(self, prices: Dict[str, float], date: str):
        """Gunluk fiyatlari guncelle ve mark-to-market yap."""
        self._current_date = date
        for ticker, price in prices.items():
            if ticker in self._positions:
                self._positions[ticker]["current_price"] = price
                self._positions[ticker]["market_value"] = self._positions[ticker]["quantity"] * price

        total_value = self.get_total_value()
        if total_value > self._max_equity:
            self._max_equity = total_value

        self._equity_curve.append({
            "date": date,
            "equity": total_value,
            "cash": self.cash,
            "invested": total_value - self.cash,
        })

        if self._state_store:
            self._state_store.save_equity_point(date, total_value, self.cash, total_value - self.cash)

    # ===================== QUERIES =====================

    def get_total_value(self) -> float:
        """Toplam portfoy degeri (cash + positions)."""
        invested = sum(p["market_value"] for p in self._positions.values())
        return self.cash + invested

    def get_invested_value(self) -> float:
        return sum(p["market_value"] for p in self._positions.values())

    def get_unrealized_pnl(self) -> float:
        total = 0.0
        for pos in self._positions.values():
            if pos["avg_cost"] > 0:
                total += (pos["current_price"] - pos["avg_cost"]) * pos["quantity"]
        return total

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        return self._positions.get(ticker)

    def get_all_positions(self) -> List[Dict[str, Any]]:
        return list(self._positions.values())

    def get_sector_weights(self) -> Dict[str, float]:
        """Sektorel agirliklar."""
        total = self.get_total_value()
        if total <= 0:
            return {}
        sector_values = defaultdict(float)
        for pos in self._positions.values():
            sector_values[pos.get("sector", "UNKNOWN")] += pos["market_value"]
        return {s: v / total for s, v in sector_values.items()}

    def get_position_weights(self) -> Dict[str, float]:
        """Hisse bazli agirliklar."""
        total = self.get_total_value()
        if total <= 0:
            return {}
        return {t: p["market_value"] / total for t, p in self._positions.items()}

    def get_trades(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        trades = self._trades
        if limit:
            trades = trades[-limit:]
        return trades

    def get_equity_curve(self) -> List[Dict[str, Any]]:
        return self._equity_curve

    def get_max_drawdown(self) -> float:
        """Mevcut max drawdown (peak-to-trough)."""
        if not self._equity_curve:
            return 0.0
        peak = self.initial_capital
        max_dd = 0.0
        for point in self._equity_curve:
            equity = point["equity"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def get_current_drawdown(self) -> float:
        """Mevcut drawdown."""
        if not self._equity_curve or self._max_equity <= 0:
            return 0.0
        current = self._equity_curve[-1]["equity"]
        return (self._max_equity - current) / self._max_equity * 100

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Portfoy ozeti."""
        total = self.get_total_value()
        invested = self.get_invested_value()
        return {
            "cash": round(self.cash, 2),
            "invested_value": round(invested, 2),
            "total_value": round(total, 2),
            "total_return_pct": round((total / self.initial_capital - 1) * 100, 2) if self.initial_capital else 0,
            "unrealized_pnl": round(self.get_unrealized_pnl(), 2),
            "realized_pnl": round(sum(t.get("realized_pnl", 0) for t in self._trades), 2),
            "num_positions": len(self._positions),
            "num_trades": len(self._trades),
            "max_drawdown_pct": round(self.get_max_drawdown(), 2),
            "current_drawdown_pct": round(self.get_current_drawdown(), 2),
        }

    # ===================== UTILS =====================

    @staticmethod
    def _holding_days(entry_date: Optional[str], exit_date: str) -> int:
        if not entry_date:
            return 0
        try:
            from datetime import datetime as dt
            d1 = dt.strptime(entry_date, "%Y-%m-%d")
            d2 = dt.strptime(exit_date, "%Y-%m-%d")
            return max(0, (d2 - d1).days)
        except Exception:
            return 0

    def reset(self):
        """Portfoyu sifirla."""
        self.cash = self.initial_capital
        self._positions.clear()
        self._trades.clear()
        self._orders.clear()
        self._equity_curve.clear()
        self._max_equity = self.initial_capital
        if self._state_store:
            self._state_store.reset_all()
        logger.warning("VirtualPortfolio RESET")


# Singleton
virtual_portfolio = VirtualPortfolio()
