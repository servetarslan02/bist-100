"""
ALPHA BIST — Paper Execution Engine v1.0

Signal -> Order Simulation:
- Gercekci execution modeli (kapanis/ertesi seans)
- Commission (BIST yapisina uygun)
- Slippage (volatilite, hacim, spread, emir buyuklugu)
- Turnover takibi
- Likidite kisiti (gunluk hacmin %10'u)
- Ayni fiyat uzerinden signal uretip islem gerceklestirme; look-ahead bias YOK.

Mevcut services.backtest.engine.BacktestEngine'den farkli:
- O gunluk, ertesi seans execution
- Persistent order kaydi
- BIST komisyon yapisi
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog

logger = structlog.get_logger()


class PaperExecutionEngine:
    """Sanal execution motoru — gercek broker YOK."""

    def __init__(
        self,
        commission_rate: float = 0.0003,      # %0.03 broker
        exchange_fee_rate: float = 0.000056,  # %0.0056 BIST
        bsmv_rate: float = 0.05,              # BSMV
        min_commission: float = 1.0,
        slippage_base_pct: float = 0.05,      # %0.05 base
        slippage_max_pct: float = 0.5,        # %0.5 max
    ):
        self.commission_rate = commission_rate
        self.exchange_fee_rate = exchange_fee_rate
        self.bsmv_rate = bsmv_rate
        self.min_commission = min_commission
        self.slippage_base_pct = slippage_base_pct
        self.slippage_max_pct = slippage_max_pct
        self._daily_turnover_value: float = 0.0

    def execute_signal(
        self,
        date: str,
        ticker: str,
        side: str,  # "BUY" | "SELL"
        quantity: int,
        signal_price: float,
        market_price: float,
        avg_volume: int = 1_000_000,
        volatility: float = 0.25,
        spread_pct: float = 0.1,
        sector: str = "",
    ) -> Dict[str, Any]:
        """
        Sinyali sanal order'a cevir.

        ONEMLI: signal_price (sinyal uretildigi fiyat) ile market_price
        (islem fiyati) AYRI olabilir. Ertesi seans acilisinda islem
        gerceklesirse signal_price != execution_price olur.
        Bu look-ahead bias'i onler.
        """
        order_id = f"ORD_{date}_{ticker}_{side}_{uuid.uuid4().hex[:6]}"

        order = {
            "order_id": order_id,
            "date": date,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "signal_price": signal_price,
            "execution_price": 0.0,
            "commission": 0.0,
            "slippage_pct": 0.0,
            "status": "CREATED",
            "rejection_reason": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # === EXECUTION TIMING ===
        # Ertesi seans acilisinda islem (realistic)
        execution_price = market_price

        # === SLIPPAGE ===
        slippage = self._compute_slippage(
            quantity=quantity,
            avg_volume=avg_volume,
            volatility=volatility,
            spread_pct=spread_pct,
            side=side,
        )

        if side == "BUY":
            fill_price = execution_price * (1 + slippage)
        else:
            fill_price = execution_price * (1 - slippage)

        # === LIQUIDITY CONSTRAINT ===
        if avg_volume > 0:
            max_qty = int(avg_volume * 0.1)  # Gunluk hacmin %10'u
            if quantity > max_qty:
                order["status"] = "REJECTED"
                order["rejection_reason"] = f"LIQUIDITY: qty {quantity} > max {max_qty} (10% of daily volume)"
                logger.warning("Order rejected: liquidity", ticker=ticker, qty=quantity, max_qty=max_qty)
                return order

        # === COMMISSION ===
        amount = quantity * fill_price
        commission = self._compute_commission(amount)

        # === FILL ===
        order["execution_price"] = round(fill_price, 4)
        order["commission"] = round(commission, 2)
        order["slippage_pct"] = round(slippage * 100, 4)
        order["status"] = "FILLED"

        # Turnover guncelle
        self._daily_turnover_value += amount

        logger.info("Order executed",
                   order_id=order_id, ticker=ticker, side=side,
                   qty=quantity, signal_price=signal_price,
                   execution_price=order["execution_price"],
                   commission=order["commission"],
                   slippage=order["slippage_pct"])

        return order

    def _compute_slippage(
        self,
        quantity: int,
        avg_volume: int,
        volatility: float,
        spread_pct: float,
        side: str,
    ) -> float:
        """Slippage hesapla."""
        # Base slippage (spread'in yarisi)
        base_slippage = (spread_pct / 100) / 2

        # Volume impact
        if avg_volume > 0:
            participation_rate = quantity / avg_volume
            volume_impact = participation_rate * volatility * 0.5
        else:
            volume_impact = 0.001

        # Volatility premium
        vol_premium = volatility * 0.02

        total_slippage = base_slippage + volume_impact + vol_premium

        # Max slippage cap
        max_slippage = self.slippage_max_pct / 100
        return min(total_slippage, max_slippage)

    def _compute_commission(self, amount: float) -> float:
        """BIST komisyon yapisi."""
        broker_fee = amount * self.commission_rate
        exchange_fee = amount * self.exchange_fee_rate
        base = broker_fee + exchange_fee
        bsmv = base * self.bsmv_rate
        total = base + bsmv
        return max(total, self.min_commission)

    def get_daily_turnover(self) -> float:
        """Gunluk turnover degeri."""
        return self._daily_turnover_value

    def reset_daily_turnover(self):
        """Gunluk turnover'u sifirla."""
        self._daily_turnover_value = 0.0

    def compute_transaction_cost_summary(self, orders: List[Dict[str, Any]]) -> Dict[str, float]:
        """Islem maliyet ozeti."""
        filled = [o for o in orders if o.get("status") == "FILLED"]
        total_commission = sum(o.get("commission", 0) for o in filled)
        total_slippage_cost = sum(
            o["quantity"] * o["signal_price"] * (o.get("slippage_pct", 0) / 100)
            for o in filled
        )
        return {
            "total_commission": round(total_commission, 2),
            "total_slippage_cost": round(total_slippage_cost, 2),
            "total_transaction_cost": round(total_commission + total_slippage_cost, 2),
            "avg_commission_per_trade": round(total_commission / len(filled), 2) if filled else 0,
            "num_filled": len(filled),
            "num_rejected": len([o for o in orders if o.get("status") == "REJECTED"]),
        }


# Singleton
paper_execution = PaperExecutionEngine()
