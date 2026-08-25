"""
ALPHA BIST — Synthetic Liquidity & Order Book Engine

Bu modül, ücretsiz/açık veri ortamında Borsa İstanbul kurallarını aşırı iyimserlikten uzak,
bilimsel mikro-yapı ve maliyet modelleriyle simüle eder:
1. Corwin–Schultz (2012) High-Low Spread Vekili (Cost Proxy)
2. BIST Kuruş Adımı Tabanlı Spread Tabanı (Tick Size Floor)
3. 5-10 Kademeli Deterministik Sentetik Emir Defteri (Synthetic Depth Ladder)
4. Çok Senaryolu Likidite Rejimi (Kötümser / Normal / İyimser)
5. Walk-the-Book (Kademe Tüketme) & Almgren-Chriss Katılım Sınırı
"""

import math
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

from services.core.bist_tick_size import round_to_bist_tick, get_bist_tick_size
from services.simulation.order_book import OrderBookLevel, OrderBookSnapshot

logger = structlog.get_logger()


class LiquidityScenario(str, Enum):
    """3 Senaryolu Likidite Değerlendirmesi."""
    PESSIMISTIC = "PESSIMISTIC"  # Stres Senaryosu: Geniş spread, sığ derinlik, katı katılım sınırı (%2 ADV)
    NORMAL = "NORMAL"            # Baz Senaryo: Standart Corwin-Schultz, medyan derinlik (%5 ADV)
    OPTIMISTIC = "OPTIMISTIC"    # İyimser Senaryo: Dar spread, geniş derinlik (%10 ADV)


class LiquidityRegime(str, Enum):
    """Hisse Likidite Sınıflandırması."""
    HIGH_LIQUIDITY = "HIGH_LIQUIDITY"    # BIST 30 yüksek hacimli paylar
    NORMAL_LIQUIDITY = "NORMAL_LIQUIDITY" # BIST 100 standart paylar
    ILLIQUID = "ILLIQUID"                # Sığ / Düşük hacimli paylar


@dataclass
class LiquidityMetrics:
    """Hisse likidite ve mikro-yapı tahmin metrikleri."""
    ticker: str
    mid_price: float
    spread_pct: float             # Corwin-Schultz + BIST floor spread oranı (%)
    spread_amount: float          # TL cinsinden spread
    adv: float                    # Ortalama günlük hacim (lot)
    volatility: float             # Parkinson / Garman-Klass volatilite oranı
    regime: LiquidityRegime
    tick_size: float
    effective_spread_floor: float


class SyntheticLiquidityEstimator:
    """
    OHLCV verisinden Corwin-Schultz (2012) spread vekili ve likidite metrikleri tahmin motoru.
    """

    @staticmethod
    def estimate_corwin_schultz_spread(
        high_prev: float,
        low_prev: float,
        high_curr: float,
        low_curr: float,
        price: float,
    ) -> float:
        """
        Corwin-Schultz (2012) High-Low Spread Tahmincisi.
        S = 2(exp(alpha) - 1) / (1 + exp(alpha))
        
        Referans: Corwin & Schultz (2012), "A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices", Journal of Finance.
        """
        if high_prev <= 0 or low_prev <= 0 or high_curr <= 0 or low_curr <= 0 or price <= 0:
            return 0.001

        # 1. Günlük beta hesaplaması: beta = ln(H_t/L_t)^2 + ln(H_{t-1}/L_{t-1})^2
        try:
            log_hl_curr = math.log(max(high_curr / max(low_curr, 1e-6), 1.0))
            log_hl_prev = math.log(max(high_prev / max(low_prev, 1e-6), 1.0))
            beta = (log_hl_curr ** 2) + (log_hl_prev ** 2)

            # 2. İki günlük gama hesaplaması: gamma = ln(H_{t-1,t} / L_{t-1,t})^2
            high_2d = max(high_curr, high_prev)
            low_2d = min(low_curr, low_prev)
            log_hl_2d = math.log(max(high_2d / max(low_2d, 1e-6), 1.0))
            gamma = log_hl_2d ** 2

            # 3. Alpha hesaplaması: alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma / (3 - 2*sqrt(2)))
            k = 3.0 - 2.0 * math.sqrt(2.0)  # ~0.17157
            sqrt_2beta = math.sqrt(2.0 * beta)
            sqrt_beta = math.sqrt(beta)
            sqrt_gamma_k = math.sqrt(gamma / k) if gamma >= 0 else 0.0

            alpha = (sqrt_2beta - sqrt_beta) / k - sqrt_gamma_k

            # Negatif alpha durumunda spread 0'a yakınsar
            if alpha <= 0:
                raw_spread = 0.0
            else:
                exp_alpha = math.exp(alpha)
                raw_spread = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
        except Exception:
            raw_spread = 0.001

        # BIST Kuruş Adımı Tabanı (Floor): Spread asla 1 kademeden dar olamaz
        tick_size = get_bist_tick_size(price)
        min_spread_pct = (tick_size / price) * 100.0

        # Spread yüzdesi (0.01% - 5.0% arası sınırlandırma)
        spread_pct = max(raw_spread * 100.0, min_spread_pct)
        return min(spread_pct, 5.0)

    @staticmethod
    def estimate_parkinson_volatility(
        highs: List[float],
        lows: List[float],
        window: int = 20,
    ) -> float:
        """Parkinson High-Low Volatilite Tahmincisi."""
        if len(highs) < 2 or len(lows) < 2:
            return 0.25

        valid_pairs = [
            math.log(max(h / max(l, 1e-6), 1.0)) ** 2
            for h, l in zip(highs[-window:], lows[-window:])
            if h > 0 and l > 0
        ]
        if not valid_pairs:
            return 0.25

        factor = 1.0 / (4.0 * math.log(2.0))
        variance = factor * (sum(valid_pairs) / len(valid_pairs))
        daily_vol = math.sqrt(max(variance, 1e-6))
        annual_vol = daily_vol * math.sqrt(252)
        return min(max(annual_vol, 0.05), 1.5)

    @classmethod
    def compute_liquidity_metrics(
        cls,
        ticker: str,
        high_prev: float,
        low_prev: float,
        high_curr: float,
        low_curr: float,
        price: float,
        volumes: List[float],
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None,
    ) -> LiquidityMetrics:
        """Hisse için tam likidite metrik profilini hesaplar."""
        spread_pct = cls.estimate_corwin_schultz_spread(
            high_prev=high_prev,
            low_prev=low_prev,
            high_curr=high_curr,
            low_curr=low_curr,
            price=price,
        )
        tick_size = get_bist_tick_size(price)
        spread_amount = max(price * (spread_pct / 100.0), tick_size)

        # ADV (20 günlük medyan / ortalama)
        if volumes and len(volumes) > 0:
            recent_vols = [v for v in volumes[-20:] if v > 0]
            adv = sum(recent_vols) / len(recent_vols) if recent_vols else 1_000_000.0
        else:
            adv = 1_000_000.0

        # Volatilite
        if highs and lows and len(highs) >= 2:
            volatility = cls.estimate_parkinson_volatility(highs, lows)
        else:
            volatility = 0.25

        # Rejim sınıflandırması
        if adv >= 5_000_000 and spread_pct <= 0.2:
            regime = LiquidityRegime.HIGH_LIQUIDITY
        elif adv < 500_000 or spread_pct > 1.0:
            regime = LiquidityRegime.ILLIQUID
        else:
            regime = LiquidityRegime.NORMAL_LIQUIDITY

        return LiquidityMetrics(
            ticker=ticker,
            mid_price=price,
            spread_pct=spread_pct,
            spread_amount=spread_amount,
            adv=adv,
            volatility=volatility,
            regime=regime,
            tick_size=tick_size,
            effective_spread_floor=(tick_size / price) * 100.0,
        )


class SyntheticOrderBookBuilder:
    """
    Deterministik 5-10 Kademeli Sentetik Emir Defteri Üreticisi ve Walk-the-Book Eşleştiricisi.
    """

    # Senaryo Parametreleri (Spread Çarpanı, Katılım Tavanı, Derinlik Çarpanı)
    SCENARIO_CONFIGS = {
        LiquidityScenario.PESSIMISTIC: {
            "spread_multiplier": 1.5,
            "depth_multiplier": 0.5,
            "max_participation_pct": 0.02,  # ADV'nin en fazla %2'si tek seferde
            "decay_factor": 0.45,            # Kademeler hızla sığlaşır
        },
        LiquidityScenario.NORMAL: {
            "spread_multiplier": 1.0,
            "depth_multiplier": 1.0,
            "max_participation_pct": 0.05,  # ADV'nin en fazla %5'i tek seferde
            "decay_factor": 0.30,            # Standart derinlik sönümlenmesi
        },
        LiquidityScenario.OPTIMISTIC: {
            "spread_multiplier": 0.7,
            "depth_multiplier": 1.5,
            "max_participation_pct": 0.10,  # ADV'nin en fazla %10'u tek seferde
            "decay_factor": 0.18,            # Derin kademeler
        },
    }

    @classmethod
    def build_synthetic_book(
        cls,
        ticker: str,
        mid_price: float,
        adv: float,
        volatility: float,
        spread_pct: float,
        scenario: LiquidityScenario = LiquidityScenario.NORMAL,
        num_levels: int = 10,
        limit_up_price: float = float("inf"),
        limit_down_price: float = 0.0,
    ) -> OrderBookSnapshot:
        """
        Deterministik 5-10 Kademeli BIST uyumlu sentetik L2 derinlik defteri üretir.
        """
        cfg = cls.SCENARIO_CONFIGS.get(scenario, cls.SCENARIO_CONFIGS[LiquidityScenario.NORMAL])
        effective_spread_pct = max(spread_pct * cfg["spread_multiplier"], (get_bist_tick_size(mid_price) / mid_price) * 100.0)
        half_spread = (mid_price * (effective_spread_pct / 100.0)) / 2.0

        # BIST kuruş adımlarına uygun best bid / best ask
        best_bid = round_to_bist_tick(mid_price - half_spread, side="SELL")
        best_ask = round_to_bist_tick(mid_price + half_spread, side="BUY")

        # Tavan/Taban sınırları
        if limit_down_price > 0:
            best_bid = max(best_bid, limit_down_price)
        if limit_up_price < float("inf"):
            best_ask = min(best_ask, limit_up_price)

        # İlk kademe taban lot büyüklüğü (ADV ve volatiliteye göre ölçekli)
        base_level_qty = max(int((adv * 0.005) * cfg["depth_multiplier"] / (1.0 + volatility * 2.0)), 50)

        bids: List[OrderBookLevel] = []
        asks: List[OrderBookLevel] = []

        # 1. Kademe
        bids.append(OrderBookLevel(price=best_bid, quantity=base_level_qty, side="bid"))
        asks.append(OrderBookLevel(price=best_ask, quantity=base_level_qty, side="ask"))

        # 2..N Kademeleri (Deterministik üstel sönümlenme ve BIST fiyat adımları)
        current_bid_price = best_bid
        current_ask_price = best_ask

        for i in range(1, num_levels):
            decay = math.exp(-cfg["decay_factor"] * i)
            level_qty = max(int(base_level_qty * (1.0 + i * 0.4) * decay), 20)

            # Fiyat adımı kadar ötele
            tick_bid = get_bist_tick_size(current_bid_price)
            tick_ask = get_bist_tick_size(current_ask_price)

            current_bid_price = round_to_bist_tick(current_bid_price - tick_bid, side="SELL")
            current_ask_price = round_to_bist_tick(current_ask_price + tick_ask, side="BUY")

            if limit_down_price > 0 and current_bid_price < limit_down_price:
                current_bid_price = limit_down_price
            if limit_up_price < float("inf") and current_ask_price > limit_up_price:
                current_ask_price = limit_up_price

            bids.append(OrderBookLevel(price=current_bid_price, quantity=level_qty, side="bid"))
            asks.append(OrderBookLevel(price=current_ask_price, quantity=level_qty, side="ask"))

        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderBookSnapshot(
            ticker=ticker,
            timestamp=0.0,
            bids=bids,
            asks=asks,
        )

    @classmethod
    def execute_market_order_walk(
        cls,
        book: OrderBookSnapshot,
        side: str,                  # "BUY" | "SELL"
        requested_quantity: int,
        adv: float,
        scenario: LiquidityScenario = LiquidityScenario.NORMAL,
        limit_up_price: float = float("inf"),
        limit_down_price: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Sentetik defter üzerinde kademeleri tüketerek (Walk-the-Book) emri eşleştirir.
        Almgren-Chriss maksimum katılım sınırını uygular.
        """
        cfg = cls.SCENARIO_CONFIGS.get(scenario, cls.SCENARIO_CONFIGS[LiquidityScenario.NORMAL])
        max_allowed_qty = max(int(adv * cfg["max_participation_pct"]), 10)
        target_qty = min(requested_quantity, max_allowed_qty)

        levels = book.asks if side == "BUY" else book.bids
        remaining = target_qty
        total_cost = 0.0
        filled_qty = 0
        levels_consumed = 0

        best_price = book.best_ask if side == "BUY" else book.best_bid

        for lvl in levels:
            if remaining <= 0:
                break
            
            # Tavan/Taban kilidi kontrolü
            if side == "BUY" and limit_up_price < float("inf") and lvl.price >= limit_up_price:
                # Tavan seviyesinde alıcı sırasına takılır, likidite yoksa durur
                fill_at_level = min(remaining, max(int(lvl.quantity * 0.2), 0))
            elif side == "SELL" and limit_down_price > 0 and lvl.price <= limit_down_price:
                # Taban seviyesinde satıcı sırasına takılır
                fill_at_level = min(remaining, max(int(lvl.quantity * 0.2), 0))
            else:
                fill_at_level = min(remaining, lvl.quantity)

            if fill_at_level <= 0:
                continue

            total_cost += fill_at_level * lvl.price
            filled_qty += fill_at_level
            remaining -= fill_at_level
            levels_consumed += 1

        mid_price = book.mid_price
        if filled_qty > 0:
            vwap_price = total_cost / filled_qty
            # Kuruş adımına yuvarla
            vwap_price = round_to_bist_tick(vwap_price, side=side)
            if side == "BUY" and mid_price > 0:
                slippage_pct = ((vwap_price - mid_price) / mid_price) * 100.0
            elif side == "SELL" and mid_price > 0:
                slippage_pct = ((mid_price - vwap_price) / mid_price) * 100.0
            else:
                slippage_pct = 0.0
        else:
            vwap_price = best_price
            slippage_pct = 0.0

        is_partial = filled_qty < requested_quantity

        return {
            "filled_quantity": filled_qty,
            "requested_quantity": requested_quantity,
            "remaining_quantity": requested_quantity - filled_qty,
            "vwap_price": vwap_price,
            "best_price": best_price,
            "slippage_pct": max(slippage_pct, 0.0),
            "levels_consumed": levels_consumed,
            "is_partial": is_partial,
            "scenario": scenario.value,
        }
