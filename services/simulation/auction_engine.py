"""
ALPHA BIST — Call Auction (Tek Fiyat Açık Artırması) Eşleşme Motoru

Borsa İstanbul Pay Piyasası Prosedürü Açık Artırma Algoritması:
1. Kümülatif Alış ve Satış Eğrisi (Demand & Supply curves)
2. Maksimum İşlem Hacmi Üreten Fiyat (Max Executable Volume)
3. Minimum Dengesizlik (Min Surplus / Imbalance)
4. Referans Fiyata En Yakın Fiyat (Tie-breaker with Reference Price)
5. Tek Denge Fiyatından (Single Equilibrium Price) tüm eşleşen emirlerin gerçekleşmesi
"""

from dataclasses import dataclass
from typing import Any

import structlog

from services.core.bist_tick_size import round_to_bist_tick

logger = structlog.get_logger()


@dataclass
class AuctionOrder:
    """Açık artırma (Call Auction) seansı için verilen emir veri modeli.

    Args:
        order_id: Benzersiz emir kimliği.
        ticker: Hisse senedi sembolü.
        side: Emir yönü ('BUY' veya 'SELL').
        quantity: Talep edilen lot adedi.
        price: Limit fiyatı (piyasa emirleri için 0.0 veya sınırsız).
        is_market: Piyasa emri olup olmadığı göstergesi.
        timestamp: Emrin zaman damgası (öncelik sıralaması için).
    """

    order_id: str
    ticker: str
    side: str  # "BUY" | "SELL"
    quantity: int
    price: float  # 0.0 veya float('inf') for Market orders
    is_market: bool = False
    timestamp: float = 0.0

    def __repr__(self) -> str:
        return (
            f"AuctionOrder(id={self.order_id!r}, ticker={self.ticker!r}, side={self.side!r}, "
            f"qty={self.quantity}, price={self.price:.2f}, market={self.is_market})"
        )


@dataclass
class AuctionResult:
    """Açık artırma eşleşme algoritması neticesinde oluşan seans sonucu.

    Args:
        equilibrium_price: Seans denge/açılış fiyatı.
        matched_volume: Başarıyla eşleşen toplam lot adedi.
        matched_trades: Gerçekleşen karşılıklı işlemler listesi.
        unfilled_orders: Eşleşmeyen veya kısmi kalan emirler.
        imbalance_volume: Dengesizlik (karşılanamayan talep/arz) miktarı.
        imbalance_side: Dengesizliğin olduğu yön ('BUY', 'SELL' veya 'NONE').
    """

    equilibrium_price: float
    matched_volume: int
    matched_trades: list[dict[str, Any]]
    unfilled_orders: list[AuctionOrder]
    imbalance_volume: int
    imbalance_side: str  # "BUY", "SELL", "NONE"

    def __repr__(self) -> str:
        return (
            f"AuctionResult(eq_price={self.equilibrium_price:.2f}, matched_vol={self.matched_volume}, "
            f"imbalance={self.imbalance_volume} ({self.imbalance_side}), trades={len(self.matched_trades)})"
        )


class CallAuctionEngine:
    """BIST Tek Fiyat Açık Artırması Eşleşme Motoru."""

    def calculate_equilibrium(
        self,
        orders: list[AuctionOrder],
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
            cum_buy = sum(o.quantity for o in orders if o.side == "BUY" and (o.is_market or o.price >= p))
            # Satış hacmi: Fiyatı <= p olan limit satışlar + piyasa satışları
            cum_sell = sum(o.quantity for o in orders if o.side == "SELL" and (o.is_market or o.price <= p))

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
            key=lambda x: (0 if x.is_market else -x.price, x.timestamp),
        )
        sells = sorted(
            [o for o in orders if o.side == "SELL" and (o.is_market or o.price <= eq_price)],
            key=lambda x: (0 if x.is_market else x.price, x.timestamp),
        )

        matched_trades = []
        buy_idx, sell_idx = 0, 0
        rem_buy_qty = buys[0].quantity if buys else 0
        rem_sell_qty = sells[0].quantity if sells else 0

        while buy_idx < len(buys) and sell_idx < len(sells):
            fill_qty = min(rem_buy_qty, rem_sell_qty)
            if fill_qty > 0:
                matched_trades.append(
                    {
                        "buy_order_id": buys[buy_idx].order_id,
                        "sell_order_id": sells[sell_idx].order_id,
                        "ticker": buys[buy_idx].ticker,
                        "price": eq_price,
                        "quantity": fill_qty,
                    }
                )
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
        imb_side = (
            "BUY"
            if sum(b.quantity for b in buys) > sum(s.quantity for s in sells)
            else ("SELL" if sum(s.quantity for s in sells) > sum(b.quantity for b in buys) else "NONE")
        )

        unfilled_orders: list[AuctionOrder] = []
        if buy_idx < len(buys) and rem_buy_qty > 0:
            unfilled_orders.append(
                AuctionOrder(
                    order_id=buys[buy_idx].order_id,
                    ticker=buys[buy_idx].ticker,
                    side=buys[buy_idx].side,
                    quantity=rem_buy_qty,
                    price=buys[buy_idx].price,
                    is_market=buys[buy_idx].is_market,
                    timestamp=buys[buy_idx].timestamp,
                )
            )
            unfilled_orders.extend(buys[buy_idx + 1 :])
        elif buy_idx + 1 < len(buys):
            unfilled_orders.extend(buys[buy_idx + 1 :])

        if sell_idx < len(sells) and rem_sell_qty > 0:
            unfilled_orders.append(
                AuctionOrder(
                    order_id=sells[sell_idx].order_id,
                    ticker=sells[sell_idx].ticker,
                    side=sells[sell_idx].side,
                    quantity=rem_sell_qty,
                    price=sells[sell_idx].price,
                    is_market=sells[sell_idx].is_market,
                    timestamp=sells[sell_idx].timestamp,
                )
            )
            unfilled_orders.extend(sells[sell_idx + 1 :])
        elif sell_idx + 1 < len(sells):
            unfilled_orders.extend(sells[sell_idx + 1 :])

        ineligible_buys = [o for o in orders if o.side == "BUY" and not o.is_market and o.price < eq_price]
        ineligible_sells = [o for o in orders if o.side == "SELL" and not o.is_market and o.price > eq_price]
        unfilled_orders.extend(ineligible_buys)
        unfilled_orders.extend(ineligible_sells)

        return AuctionResult(
            equilibrium_price=eq_price,
            matched_volume=total_matched,
            matched_trades=matched_trades,
            unfilled_orders=unfilled_orders,
            imbalance_volume=imbalance_qty,
            imbalance_side=imb_side,
        )

    def __repr__(self) -> str:
        return "CallAuctionEngine(algorithm='BIST Single Price Call Auction (FIFO)')"


call_auction_engine = CallAuctionEngine()

