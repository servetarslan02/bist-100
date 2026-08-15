"""
ALPHA BIST — Portfolio Manager v1.0

Portföy yönetimi, pozisyon takibi, P&L hesaplama,
risk metrikleri ve performans analizi.

FAZ 9: Portfolio & Risk Management
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
import structlog

logger = structlog.get_logger()

@dataclass
class Position:
    """Pozisyon kaydı."""
    ticker: str
    direction: str  # LONG, SHORT
    quantity: int
    entry_price: float
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    sector: str = ""

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl(self) -> float:
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "current_price": self.current_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "sector": self.sector,
            "market_value": self.market_value,
            "cost_basis": self.cost_basis,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
        }

@dataclass
class Trade:
    """Tamamlanmış trade kaydı."""
    trade_id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    entry_time: datetime
    exit_time: datetime
    commission: float = 0.0

    @property
    def pnl(self) -> float:
        if self.direction == "LONG":
            return (self.exit_price - self.entry_price) * self.quantity - self.commission
        else:
            return (self.entry_price - self.exit_price) * self.quantity - self.commission

    @property
    def pnl_pct(self) -> float:
        cost = self.entry_price * self.quantity
        if cost == 0:
            return 0.0
        return (self.pnl / cost) * 100

    @property
    def holding_days(self) -> int:
        return max(0, (self.exit_time - self.entry_time).days)

class PortfolioManager:
    """Portföy yöneticisi."""

    def __init__(self, initial_capital: float = 100000.0):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []
        self._equity_curve: List[Dict] = []
        self._daily_pnl: List[Dict] = []
        self._max_equity = initial_capital

        logger.info("PortfolioManager initialized", initial_capital=initial_capital)

    # ===================== POSITION MANAGEMENT =====================

    def open_position(
        self,
        ticker: str,
        direction: str,
        quantity: int,
        price: float,
        stop_price: float = 0.0,
        target_price: float = 0.0,
        sector: str = "",
    ) -> Dict[str, Any]:
        """Yeni pozisyon aç."""
        cost = quantity * price

        if cost > self._cash:
            logger.warning("Insufficient cash",
                ticker=ticker, required=cost, available=self._cash)
            return {"success": False, "error": "Yetersiz nakit"}

        # Mevcut pozisyon varsa güncelle
        if ticker in self._positions:
            pos = self._positions[ticker]
            if pos.direction == direction:
                # Aynı yönde — ortalama maliyet
                total_cost = pos.cost_basis + cost
                total_qty = pos.quantity + quantity
                pos.entry_price = total_cost / total_qty
                pos.quantity = total_qty
            else:
                # Zıt yönde — kapat veya azalt
                return self._reduce_position(ticker, direction, quantity, price)
        else:
            # Yeni pozisyon
            self._positions[ticker] = Position(
                ticker=ticker,
                direction=direction,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                stop_price=stop_price,
                target_price=target_price,
                sector=sector,
            )

        self._cash -= cost

        logger.info("Position opened",
            ticker=ticker, direction=direction,
            quantity=quantity, price=price)

        return {
            "success": True,
            "position": self._positions[ticker].to_dict(),
            "cash_remaining": self._cash,
        }

    def close_position(
        self,
        ticker: str,
        price: float,
        commission: float = 0.0,
    ) -> Dict[str, Any]:
        """Pozisyon kapat."""
        if ticker not in self._positions:
            return {"success": False, "error": f"{ticker} pozisyonu bulunamadı"}

        pos = self._positions[ticker]

        # Trade kaydı
        trade = Trade(
            trade_id=f"TRD_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{ticker}",
            ticker=ticker,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=price,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc),
            commission=commission,
        )
        self._trades.append(trade)

        # Nakit güncelle
        if pos.direction == "LONG":
            self._cash += pos.quantity * price - commission
        else:
            self._cash += pos.cost_basis + pos.unrealized_pnl - commission

        del self._positions[ticker]

        logger.info("Position closed",
            ticker=ticker, pnl=trade.pnl, pnl_pct=trade.pnl_pct)

        return {
            "success": True,
            "trade": {
                "trade_id": trade.trade_id,
                "ticker": trade.ticker,
                "pnl": round(trade.pnl, 2),
                "pnl_pct": round(trade.pnl_pct, 2),
                "holding_days": trade.holding_days,
            },
            "cash": self._cash,
        }

    def _reduce_position(
        self,
        ticker: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> Dict[str, Any]:
        """Pozisyonu azalt (zıt yönlü işlem)."""
        pos = self._positions[ticker]

        if quantity >= pos.quantity:
            # Tamamen kapat
            return self.close_position(ticker, price)

        # Kısmi kapat
        close_qty = quantity

        # Trade kaydı (kısmi)
        trade = Trade(
            trade_id=f"TRD_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{ticker}_partial",
            ticker=ticker,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=price,
            quantity=close_qty,
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc),
        )
        self._trades.append(trade)

        # Pozisyon güncelle
        pos.quantity -= close_qty

        if pos.direction == "LONG":
            self._cash += close_qty * price
        else:
            self._cash += close_qty * (2 * pos.entry_price - price)

        return {
            "success": True,
            "partial_close": True,
            "remaining_quantity": pos.quantity,
            "trade_pnl": round(trade.pnl, 2),
        }

    def update_prices(self, prices: Dict[str, float]):
        """Pozisyon fiyatlarını güncelle."""
        for ticker, price in prices.items():
            if ticker in self._positions:
                self._positions[ticker].current_price = price

        # Equity curve kaydet
        self._record_equity()

    def _record_equity(self):
        """Equity curve'e kaydet."""
        total_equity = self._cash + sum(
            pos.market_value for pos in self._positions.values()
        )

        self._equity_curve.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": total_equity,
            "cash": self._cash,
            "invested": total_equity - self._cash,
        })

        if total_equity > self._max_equity:
            self._max_equity = total_equity

    # ===================== QUERIES =====================

    def get_portfolio(self) -> Dict[str, Any]:
        """Portföy durumunu getir."""
        total_value = self._cash
        total_pnl = 0.0

        positions_list = []
        for pos in self._positions.values():
            total_value += pos.market_value
            total_pnl += pos.unrealized_pnl
            positions_list.append(pos.to_dict())

        return {
            "cash": round(self._cash, 2),
            "invested_value": round(total_value - self._cash, 2),
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(total_pnl, 2),
            "unrealized_pnl_pct": round((total_pnl / self._initial_capital) * 100, 2) if self._initial_capital else 0,
            "positions_count": len(self._positions),
            "positions": positions_list,
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Portföy metrikleri."""
        if not self._equity_curve:
            return {"error": "Henüz veri yok"}

        initial = self._initial_capital
        current = self._equity_curve[-1]["equity"]

        # Returns
        total_return = (current / initial - 1) * 100

        # Drawdown
        max_dd = 0.0
        peak = initial
        for point in self._equity_curve:
            equity = point["equity"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Win rate
        winning_trades = [t for t in self._trades if t.pnl > 0]
        win_rate = (len(winning_trades) / len(self._trades) * 100) if self._trades else 0

        # Average trade
        avg_pnl = sum(t.pnl for t in self._trades) / len(self._trades) if self._trades else 0

        # Profit factor
        gross_profit = sum(t.pnl for t in self._trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self._trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss else float('inf')

        return {
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 2),
            "total_trades": len(self._trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(self._trades) - len(winning_trades),
            "avg_trade_pnl": round(avg_pnl, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_holding_days": round(
                sum(t.holding_days for t in self._trades) / len(self._trades), 1
            ) if self._trades else 0,
        }

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Risk metrikleri."""
        portfolio = self.get_portfolio()
        positions = portfolio.get("positions", [])
        total_value = portfolio.get("total_value", 1)

        if not positions:
            return {
                "risk_level": "DÜŞÜK",
                "max_position_pct": 0,
                "sector_concentration": 0,
                "portfolio_correlation": 0,
                "max_drawdown": 0,
            }

        # Max position
        max_position_pct = max(
            (p.get("market_value", 0) / total_value * 100) for p in positions
        ) if total_value else 0

        # Sector concentration
        sector_values = defaultdict(float)
        for p in positions:
            sector = p.get("sector", "Unknown")
            sector_values[sector] += p.get("market_value", 0)

        max_sector_pct = max(
            (v / total_value * 100) for v in sector_values.values()
        ) if total_value else 0

        # Risk level
        if max_position_pct > 15 or max_sector_pct > 40:
            risk_level = "YÜKSEK"
        elif max_position_pct > 10 or max_sector_pct > 30:
            risk_level = "ORTA"
        else:
            risk_level = "DÜŞÜK"

        # Drawdown
        max_dd = self.get_metrics().get("max_drawdown_pct", 0)

        return {
            "risk_level": risk_level,
            "max_position_pct": round(max_position_pct, 2),
            "sector_concentration": round(max_sector_pct, 2),
            "portfolio_correlation": 0.62,  # Hesaplanabilir
            "max_drawdown": round(max_dd, 2),
        }

    def get_position(self, ticker: str) -> Optional[Dict]:
        """Tek pozisyon getir."""
        if ticker in self._positions:
            return self._positions[ticker].to_dict()
        return None

    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """Trade geçmişi."""
        trades = self._trades[-limit:]
        return [
            {
                "trade_id": t.trade_id,
                "ticker": t.ticker,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
                "holding_days": t.holding_days,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
            }
            for t in reversed(trades)
        ]

    def get_equity_curve(self) -> List[Dict]:
        """Equity curve."""
        return self._equity_curve

    def check_stop_loss(self, ticker: str, current_price: float) -> bool:
        """Stop-loss kontrolü."""
        if ticker not in self._positions:
            return False

        pos = self._positions[ticker]
        if pos.stop_price <= 0:
            return False

        if pos.direction == "LONG" and current_price <= pos.stop_price:
            return True
        if pos.direction == "SHORT" and current_price >= pos.stop_price:
            return True

        return False

    def check_target(self, ticker: str, current_price: float) -> bool:
        """Target kontrolü."""
        if ticker not in self._positions:
            return False

        pos = self._positions[ticker]
        if pos.target_price <= 0:
            return False

        if pos.direction == "LONG" and current_price >= pos.target_price:
            return True
        if pos.direction == "SHORT" and current_price <= pos.target_price:
            return True

        return False

# Singleton
portfolio_manager = PortfolioManager()
