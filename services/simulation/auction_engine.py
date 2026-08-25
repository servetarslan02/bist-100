"""
ALPHA BIST — Call Auction (Tek Fiyat Açık Artırması) Eşleşme Motoru

Borsa İstanbul Pay Piyasası Prosedürü Açık Artırma Algoritması:
1. Kümülatif Alış ve Satış Eğrisi (Demand & Supply curves)
2. Maksimum İşlem Hacmi Üreten Fiyat (Max Executable Volume)
3. Minimum Dengesizlik (Min Surplus / Imbalance)
4. Referans Fiyata En Yakın Fiyat (Tie-breaker with Reference Price)
5. Tek Denge Fiyatından (Single Equilibrium Price) tüm eşleşen emirlerin gerçekleşmesi
"""

from typing import List, Dict, Any
from dataclasses import dataclass
import structlog
from services.core.bist_tick_size import round_to_bist_tick

logger = structlog.get_logger()


@dataclass
class AuctionOrder:
    order_id: str
    ticker: str
    side: str          # "BUY" | "SELL"
    quantity: int
    price: float       # 0.0 veya float('inf') for Market orders
    is_market: bool = False
    timestamp: float = 0.0


@dataclass
class AuctionResult:
    equilibrium_price: float
    matched_volume: int
    matched_trades: List[Dict[str, Any]]
    unfilled_orders: List[AuctionOrder]
    imbalance_volume: int
    imbalance_side: str  # "BUY", "SELL", "NONE"


class CallAuctionEngine:
    """BIST Tek Fiyat Açık Artırması Eşleşme Motoru."""

    def calculate_equilibrium(
        self,
        orders: List[AuctionOrder],
        reference_price: float,
    ) -> AuctionResult:
        """Emir havuzundan BIST kuralına göre tek fiyat ve eşleşmeleri hesaplar."""
        if not orders:
            return AuctionResult(
                equilibrium_price=reference_price,
                matched_volume=0,
                matched_trades=[],
                unfilled_orders=[],
                imbalance_volume=0,
                imbalance_side="NONE",
            )

        # 1. Tüm geçerli fiyat adaylarını topla
        candidate_prices = set()
        for o in orders:
            if not o.is_market and o.price > 0:
                candidate_prices.add(o.price)
        if reference_price > 0:
            candidate_prices.add(reference_price)

        sorted_prices = sorted(list(candidate_prices))
        if not sorted_prices:
            sorted_prices = [reference_price]

        # 2. Her fiyat seviyesi için Kümülatif Alış (Demand) ve Kümülatif Satış (Supply) hesapla
        best_price = reference_price
        max_volume = 0
        min_imbalance = float("inf")
        best_distance_to_ref = float("inf")

        for p in sorted_prices:
            # Alış hacmi: Fiyatı >= p olan limit alışlar + piyasa alışları
            cum_buy = sum(
                o.quantity for o in orders
                if o.side == "BUY" and (o.is_market or o.price >= p)
            )
            # Satış hacmi: Fiyatı <= p olan limit satışlar + piyasa satışları
            cum_sell = sum(
                o.quantity for o in orders
                if o.side == "SELL" and (o.is_market or o.price <= p)
            )

            executable = min(cum_buy, cum_sell)
            imbalance = abs(cum_buy - cum_sell)
            dist_to_ref = abs(p - reference_price)

            # BIST Öncelik Kuralları:
            # 1. En yüksek işlem hacmi
            if executable > max_volume:
                max_volume = executable
                min_imbalance = imbalance
                best_distance_to_ref = dist_to_ref
                best_price = p
            elif executable == max_volume and executable > 0:
                # 2. En düşük dengesizlik (imbalance)
                if imbalance < min_imbalance:
                    min_imbalance = imbalance
                    best_distance_to_ref = dist_to_ref
                    best_price = p
                elif imbalance == min_imbalance:
                    # 3. Referans fiyata en yakınlık
                    if dist_to_ref < best_distance_to_ref:
                        best_distance_to_ref = dist_to_ref
                        best_price = p

        eq_price = round_to_bist_tick(best_price) if best_price > 0 else reference_price

        # 3. Eşleşmeleri Tek Fiyat Üzerinden Gerçekleştir (FIFO / Zaman Önceliği)
        buys = sorted(
            [o for o in orders if o.side == "BUY" and (o.is_market or o.price >= eq_price)],
            key=lambda x: (0 if x.is_market else -x.price, x.timestamp)
        )
        sells = sorted(
            [o for o in orders if o.side == "SELL" and (o.is_market or o.price <= eq_price)],
            key=lambda x: (0 if x.is_market else x.price, x.timestamp)
        )

        matched_trades = []
        buy_idx, sell_idx = 0, 0
        rem_buy_qty = buys[0].quantity if buys else 0
        rem_sell_qty = sells[0].quantity if sells else 0

        while buy_idx < len(buys) and sell_idx < len(sells):
            fill_qty = min(rem_buy_qty, rem_sell_qty)
            if fill_qty > 0:
                matched_trades.append({
                    "buy_order_id": buys[buy_idx].order_id,
                    "sell_order_id": sells[sell_idx].order_id,
                    "ticker": buys[buy_idx].ticker,
                    "price": eq_price,
                    "quantity": fill_qty,
                })
                rem_buy_qty -= fill_qty
                rem_sell_qty -= fill_qty

            if rem_buy_qty == 0:
                buy_idx += 1
                if buy_idx < len(buys):
                    rem_buy_qty = buys[buy_idx].quantity
            if rem_sell_qty == 0:
                sell_idx += 1
                if sell_idx < len(sells):
                    rem_sell_qty = sells[sell_idx].quantity

        total_matched = sum(t["quantity"] for t in matched_trades)
        imbalance_qty = abs(sum(b.quantity for b in buys) - sum(s.quantity for s in sells))
        imb_side = "BUY" if sum(b.quantity for b in buys) > sum(s.quantity for s in sells) else ("SELL" if sum(s.quantity for s in sells) > sum(b.quantity for b in buys) else "NONE")

        return AuctionResult(
            equilibrium_price=eq_price,
            matched_volume=total_matched,
            matched_trades=matched_trades,
            unfilled_orders=[],
            imbalance_volume=imbalance_qty,
            imbalance_side=imb_side,
        )


call_auction_engine = CallAuctionEngine()
