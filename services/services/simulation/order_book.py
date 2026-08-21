"""
ALPHA BIST — Order Book Simulation v1.0

Basit order book simülasyonu:
- Bid/Ask depth
- Spread dynamics
- Likidite profili
- Fill simülasyonu (limit emirler için)

Kaynak: mbrenndoerfer Market Microstructure (2026)
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class OrderBookLevel:
    """Tek bir order book seviyesi."""
    price: float
    quantity: int
    side: str  # "bid" / "ask"


@dataclass
class OrderBookSnapshot:
    """Order book anlık görüntüsü."""
    ticker: str
    timestamp: float
    bids: List[OrderBookLevel]  # En yüksekten en düşüğe
    asks: List[OrderBookLevel]  # En düşükten en yükseğe

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2
        return 0.0

    @property
    def spread(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return self.best_ask - self.best_bid
        return 0.0

    @property
    def spread_pct(self) -> float:
        mid = self.mid_price
        if mid > 0:
            return self.spread / mid * 100
        return 0.0

    @property
    def bid_depth(self) -> int:
        """Toplam bid derinliği (adet)."""
        return sum(level.quantity for level in self.bids)

    @property
    def ask_depth(self) -> int:
        """Toplam ask derinliği (adet)."""
        return sum(level.quantity for level in self.asks)

    @property
    def total_depth(self) -> int:
        return self.bid_depth + self.ask_depth

    @property
    def imbalance(self) -> float:
        """Order book imbalance: pozitif = alıcı baskın, negatif = satıcı baskın."""
        total = self.total_depth
        if total == 0:
            return 0.0
        return (self.bid_depth - self.ask_depth) / total


class OrderBookSimulator:
    """Order book simülasyonu.

    Gerçekçi bid/ask depth ve spread dynamics üretir.
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        base_spread_pct: float = 0.1,
        depth_levels: int = 5,
    ):
        self.tick_size = tick_size
        self.base_spread_pct = base_spread_pct
        self.depth_levels = depth_levels

    def generate_book(
        self,
        mid_price: float,
        avg_volume: int = 1000000,
        volatility: float = 0.25,
        regime: str = "RANGE",
    ) -> OrderBookSnapshot:
        """Sentetik order book üret.

        Args:
            mid_price: Orta fiyat
            avg_volume: Günlük ortalama hacim
            volatility: Volatilite
            regime: Piyasa rejimi

        Returns:
            OrderBookSnapshot
        """
        # Spread: volatilite ve rejime göre
        regime_mult = {
            "BULL": 0.8, "BEAR": 1.3, "PANIC": 2.0, "CRISIS": 2.5,
            "HIGH-VOLATILITY": 1.5, "LOW-VOLATILITY": 0.7, "RANGE": 1.0,
        }.get(regime, 1.0)

        # base_spread_pct zaten temel spread, volatilite ile ayarla
        # Yüksek vol → geniş spread
        spread_pct = self.base_spread_pct * regime_mult * (1 + volatility * 5)
        spread_pct = min(spread_pct, 2.0)  # Max %2 spread
        spread = mid_price * spread_pct / 100

        best_bid = round(mid_price - spread / 2, 2)
        best_ask = round(mid_price + spread / 2, 2)

        # Depth: her seviyede azalan likidite
        bids = []
        asks = []

        # Günlük hacmin bir kısmı order book'da
        base_qty = max(int(avg_volume * 0.01), 100)  # ADV'nin %1'i

        # İlk seviye: best_bid ve best_ask
        decay0 = np.exp(0)  # = 1.0
        noise0 = np.random.uniform(0.5, 1.5)
        bids.append(OrderBookLevel(price=best_bid, quantity=max(int(base_qty * decay0 * noise0), 100), side="bid"))
        asks.append(OrderBookLevel(price=best_ask, quantity=max(int(base_qty * decay0 * noise0), 100), side="ask"))

        # Sonraki seviyeler
        for i in range(1, self.depth_levels):
            # Her seviyede fiyat ve miktar
            level_pct = 0.001 * (i + 1)  # Her seviye %0.1 uzaklıkta

            bid_price = round(best_bid - mid_price * level_pct, 2)
            ask_price = round(best_ask + mid_price * level_pct, 2)

            # Miktar: seviye uzaklaştıkça azalır (ama rastgele varyasyonla)
            decay = np.exp(-0.3 * i)  # üstel azalma
            noise = np.random.uniform(0.5, 1.5)

            bid_qty = max(int(base_qty * decay * noise), 100)
            ask_qty = max(int(base_qty * decay * noise), 100)

            bids.append(OrderBookLevel(price=bid_price, quantity=bid_qty, side="bid"))
            asks.append(OrderBookLevel(price=ask_price, quantity=ask_qty, side="ask"))

        # Bid'leri yüksekten düşüğe sırala
        bids.sort(key=lambda x: x.price, reverse=True)
        # Ask'leri düşükten yükseğe sırala
        asks.sort(key=lambda x: x.price)

        return OrderBookSnapshot(
            ticker="",
            timestamp=0,
            bids=bids,
            asks=asks,
        )

    def simulate_market_order(
        self,
        book: OrderBookSnapshot,
        side: str,
        quantity: int,
    ) -> Dict[str, Any]:
        """Market emrini order book üzerinde simüle et.

        Emir book'daki seviyeleri tüketir (walk the book).
        VWAP fiyatını hesaplar.

        Args:
            book: Order book snapshot
            side: "BUY" veya "SELL"
            quantity: Emir adedi

        Returns:
            {"fill_quantity", "avg_price", "vwap", "slippage_pct", "partial_fill",
             "levels_consumed", "remaining_quantity"}
        """
        if side == "BUY":
            levels = book.asks  # Ask'lerden al
        else:
            levels = book.bids  # Bid'lere sat

        remaining = quantity
        total_cost = 0.0
        filled_qty = 0
        levels_consumed = 0

        for level in levels:
            if remaining <= 0:
                break

            fill_at_level = min(remaining, level.quantity)
            total_cost += fill_at_level * level.price
            filled_qty += fill_at_level
            remaining -= fill_at_level
            levels_consumed += 1

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0

        # Slippage: best price vs VWAP
        if side == "BUY":
            best_price = book.best_ask
            slippage = (avg_price - best_price) / best_price if best_price > 0 else 0
        else:
            best_price = book.best_bid
            slippage = (best_price - avg_price) / best_price if best_price > 0 else 0

        return {
            "fill_quantity": filled_qty,
            "remaining_quantity": remaining,
            "avg_price": round(avg_price, 4),
            "vwap": round(avg_price, 4),
            "slippage_pct": round(slippage * 100, 4),
            "partial_fill": remaining > 0,
            "fill_ratio": round(filled_qty / quantity, 4) if quantity > 0 else 0,
            "levels_consumed": levels_consumed,
            "cost": round(total_cost, 2),
        }

    def estimate_spread_from_volume(
        self,
        avg_volume: int,
        volatility: float,
    ) -> float:
        """Hacim ve volatiliteden spread tahmini.

        Spread ≈ a × σ / √(V)  (microstructure modeli)
        """
        if avg_volume <= 0:
            return 1.0  # %1 default

        # Microstructure spread modeli
        spread_pct = 0.1 * volatility / np.sqrt(avg_volume / 1000000)
        return min(max(spread_pct, 0.01), 2.0)  # %0.01 - %2 arası

    def calculate_liquidity_score(
        self,
        book: OrderBookSnapshot,
        order_value: float = 0,
    ) -> Dict[str, Any]:
        """Likidite skoru hesapla.

        0-100 arası skor:
        - 100: Çok likit (dar spread, derin book)
        - 0: Likit değil (geniş spread, sığ book)
        """
        spread_score = max(0, 100 - book.spread_pct * 100)  # Spread dar → yüksek skor
        depth_score = min(100, book.total_depth / 100)  # Derinlik yüksek → yüksek skor
        imbalance_penalty = abs(book.imbalance) * 20  # Dengesizlik ceza

        score = (spread_score * 0.4 + depth_score * 0.4 + (100 - imbalance_penalty) * 0.2)
        score = max(0, min(100, score))

        return {
            "liquidity_score": round(score, 1),
            "spread_score": round(spread_score, 1),
            "depth_score": round(depth_score, 1),
            "imbalance": round(book.imbalance, 4),
            "spread_pct": round(book.spread_pct, 4),
            "bid_depth": book.bid_depth,
            "ask_depth": book.ask_depth,
        }


# Singleton
order_book_sim = OrderBookSimulator()
