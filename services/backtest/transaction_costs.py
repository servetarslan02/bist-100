"""
ALPHA BIST — Realistic Transaction Cost Model

BIST'e özgü gerçekçi işlem maliyeti modeli. Sadece komisyon değil,
spread, slippage, market impact ve vergileri içerir.

Maliyet Bileşenleri:
1. Komisyon: Broker + BIST + MKK + Takasbank
2. Spread: Bid/ask farkı (hacme göre değişken)
3. Slippage: Volatilite bazlı kayma
4. Market Impact: Emir boyutuna bağlı piyasa etkisi
5. BSMV: Banka ve Sigorta Muameleleri Vergisi

Referanslar:
- BIST işlem ücretleri tablosu (2025/2026)
- "Transaction Cost Analysis" (Kissell, 2013)
- "Trading and Exchanges" (Harris, 2003)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class MarketCapCategory(Enum):
    """Piyasa değeri kategorileri."""

    LARGE_CAP = "large"  # > 10B TL
    MID_CAP = "mid"  # 2-10B TL
    SMALL_CAP = "small"  # 500M-2B TL
    MICRO_CAP = "micro"  # < 500M TL


class LiquidityTier(Enum):
    """Likidite katmanları."""

    TIER_1 = "tier_1"  # En likit (THYAO, GARAN, AKBNK vb.)
    TIER_2 = "tier_2"  # Orta likit
    TIER_3 = "tier_3"  # Düşük likit
    TIER_4 = "tier_4"  # Çok düşük likit


@dataclass
class BISTFeeStructure:
    """BIST işlem ücretleri yapısı."""

    # Broker komisyonu (değişken, genel piyasa ortalaması)
    broker_commission_pct: float = 0.03  # %0.03

    # BIST pay piyasası işlem ücreti
    bist_fee_pct: float = 0.0056  # %0.0056

    # MKK (Merkezi Kayıt Kuruluşu) ücreti
    mkk_fee_pct: float = 0.00109  # %0.00109

    # Takasbank ücreti
    takasbank_fee_pct: float = 0.0001  # %0.0001

    # Minimum komisyon (TL)
    min_commission_tl: float = 1.0

    # BSMV (Banka ve Sigorta Muameleleri Vergisi)
    bsmv_rate: float = 0.05  # Komisyon üzerinden %5

    # Stopaj (vergi kesintisi) - hisse satışında
    stopaj_rate: float = 0.0  # Güncel oran (değişken)

    @property
    def total_exchange_fee_pct(self) -> float:
        """Toplam borsa ücreti (broker hariç)."""
        return self.bist_fee_pct + self.mkk_fee_pct + self.takasbank_fee_pct

    @property
    def total_base_fee_pct(self) -> float:
        """Toplam temel ücret (BSMV hariç)."""
        return self.broker_commission_pct + self.total_exchange_fee_pct


@dataclass
class SpreadModel:
    """
    Bid/ask spread modeli.

    Gerçek piyasa verisiyle kalibre edilmeli.
    Likidite katmanına göre spread tahmini.
    """

    # Spread baz değerleri (bps - basis points)
    tier_1_spread_bps: float = 5.0  # 5 bps = %0.05
    tier_2_spread_bps: float = 15.0  # 15 bps = %0.15
    tier_3_spread_bps: float = 30.0  # 30 bps = %0.30
    tier_4_spread_bps: float = 75.0  # 75 bps = %0.75

    # Volatilite çarpanı (yüksek vol → daha geniş spread)
    volatility_multiplier: float = 1.5

    # Hacim çarpanı (düşük hacim → daha geniş spread)
    volume_decay_factor: float = 0.5

    def estimate_spread(
        self,
        liquidity_tier: LiquidityTier,
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
    ) -> float:
        """
        Spread tahmini (ondalık).

        Args:
            liquidity_tier: Likidite katmanı
            volatility_ratio: Anlık volatilite / ortalama volatilite
            volume_ratio: Anlık hacim / ortalama hacim

        Returns:
            Tahmini spread (ondalık, ör: 0.001 = %0.1)
        """
        # Baz spread
        base_spread = {
            LiquidityTier.TIER_1: self.tier_1_spread_bps / 10000,
            LiquidityTier.TIER_2: self.tier_2_spread_bps / 10000,
            LiquidityTier.TIER_3: self.tier_3_spread_bps / 10000,
            LiquidityTier.TIER_4: self.tier_4_spread_bps / 10000,
        }[liquidity_tier]

        # Volatilite ayarlaması
        vol_adj = 1.0 + (volatility_ratio - 1.0) * (self.volatility_multiplier - 1.0)
        vol_adj = max(0.5, min(vol_adj, 3.0))  # Sınırlandır

        # Hacim ayarlaması
        if volume_ratio < 1.0:
            vol_adj *= 1.0 + (1.0 - volume_ratio) * self.volume_decay_factor

        return base_spread * vol_adj


@dataclass
class SlippageModel:
    """
    Slippage (kayma) modeli.

    Emrin gerçekleştiği fiyat ile karar anındaki fiyat arasındaki fark.
    Volatilite, hacim ve emir boyutuna bağlı.
    """

    # Baz slippage (bps)
    base_slippage_bps: float = 5.0  # 5 bps = %0.05

    # Volatilite etkisi
    volatility_impact: float = 2.0  # Her 1x volatilite için 2x slippage

    # Hacim etkisi (düşük hacim → daha fazla slippage)
    volume_impact: float = 1.5

    def estimate_slippage(
        self,
        side: str,  # BUY | SELL
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        order_size_pct: float = 0.01,  # Emir boyutu / günlük hacim
    ) -> float:
        """
        Slippage tahmini (ondalık).

        Args:
            side: ALIŞ veya SATIŞ
            volatility_ratio: Anlık vol / ortalama vol
            volume_ratio: Anlık hacim / ortalama hacim
            order_size_pct: Emrin günlük hacme oranı

        Returns:
            Tahmini slippage (ondalık, pozitif)
        """
        base = self.base_slippage_bps / 10000

        # Volatilite etkisi
        vol_effect = 1.0 + (volatility_ratio - 1.0) * self.volatility_impact
        vol_effect = max(0.5, min(vol_effect, 5.0))

        # Hacim etkisi (düşük hacim = fazla slippage)
        if volume_ratio > 0:
            volume_effect = 1.0 + (1.0 / volume_ratio - 1.0) * self.volume_impact
            volume_effect = max(1.0, min(volume_effect, 5.0))
        else:
            volume_effect = 3.0

        # Emir boyutu etkisi
        size_effect = 1.0 + order_size_pct * 10  # %1 hacim → 1.1x
        size_effect = max(1.0, min(size_effect, 3.0))

        slippage = base * vol_effect * volume_effect * size_effect

        # ALIŞ'ta pozitif slippage (yüksek fiyattan al), SATIŞ'ta negatif (düşük fiyattan sat)
        return abs(slippage)


@dataclass
class MarketImpactModel:
    """
    Market impact modeli.

    Büyük emirlerin piyasa fiyatını etkileme modeli.
    Square-root modeli kullanılır (standart literatür).

    Impact = sigma * sqrt(Q / V) * eta

    sigma: volatilite
    Q: emir boyutu (adet)
    V: günlük ortalama hacim
    eta: sabit (akışkanlık parametresi)
    """

    # Akışkanlık parametresi
    eta: float = 0.5  # Genel piyasa ortalaması

    # Kalıcı impact oranı (geçici vs kalıcı)
    permanent_ratio: float = 0.3  # %30 kalıcı, %70 geçici

    def estimate_impact(
        self,
        order_quantity: int,
        avg_daily_volume: int,
        volatility: float,
        price: float,
    ) -> tuple[float, float]:
        """
        Market impact tahmini.

        Args:
            order_quantity: Emir adedi
            avg_daily_volume: Günlük ortalama hacim
            volatility: Günlük volatilite (ondalık)
            price: Güncel fiyat

        Returns:
            (total_impact_pct, permanent_impact_pct): Toplam ve kalıcı impact
        """
        if avg_daily_volume <= 0 or price <= 0:
            return 0.0, 0.0

        # Participation rate
        participation = order_quantity / avg_daily_volume

        # Square-root model
        total_impact = volatility * np.sqrt(participation) * self.eta

        # Kalıcı impact
        permanent_impact = total_impact * self.permanent_ratio

        return abs(total_impact), abs(permanent_impact)


class TransactionCostEngine:
    """
    BIST transaction cost motoru.

    Tüm maliyet bileşenlerini birleştirerek gerçekçi toplam maliyet hesaplar.
    """

    def __init__(
        self,
        fee_structure: BISTFeeStructure | None = None,
        spread_model: SpreadModel | None = None,
        slippage_model: SlippageModel | None = None,
        impact_model: MarketImpactModel | None = None,
    ):
        """Otomatik eklendi."""
        self.fees = fee_structure or BISTFeeStructure()
        self.spread = spread_model or SpreadModel()
        self.slippage = slippage_model or SlippageModel()
        self.impact = impact_model or MarketImpactModel()

    def classify_liquidity(
        self,
        avg_daily_volume: float,
        market_cap: float | None = None,
    ) -> LiquidityTier:
        """
        Hisseyi likidite katmanına sınıflandır.

        Args:
            avg_daily_volume: Günlük ortalama hacim (TL)
            market_cap: Piyasa değeri (TL)

        Returns:
            Likidite katmanı
        """
        if avg_daily_volume > 500_000_000:  # 500M TL+
            return LiquidityTier.TIER_1
        elif avg_daily_volume > 100_000_000:  # 100-500M TL
            return LiquidityTier.TIER_2
        elif avg_daily_volume > 20_000_000:  # 20-100M TL
            return LiquidityTier.TIER_3
        else:
            return LiquidityTier.TIER_4

    def calculate_total_cost(
        self,
        side: str,  # BUY | SELL
        price: float,
        quantity: int,
        ticker: str,
        avg_daily_volume: float = 0,
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        market_cap: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Toplam işlem maliyeti hesapla.

        Args:
            side: ALIŞ veya SATIŞ
            price: Fiyat
            quantity: Adet
            ticker: Hisse kodu
            avg_daily_volume: Günlük ortalama hacim
            volatility_ratio: Volatilite oranı
            volume_ratio: Hacim oranı
            market_cap: Piyasa değeri

        Returns:
            Maliyet bileşenleri ve toplam
        """
        # Savunma: negatif veya sifir fiyat/adet
        if price <= 0 or quantity <= 0:
            return {
                "ticker": ticker,
                "side": side,
                "price": 0,
                "quantity": 0,
                "notional": 0,
                "liquidity_tier": "tier_4",
                "costs": {k: 0 for k in ["commission", "bsmv", "spread", "slippage", "market_impact", "stopaj"]},
                "cost_pcts": {k: 0 for k in ["commission_pct", "spread_pct", "slippage_pct", "impact_pct"]},
                "total_cost": 0,
                "total_cost_pct": 0,
                "execution_price": 0,
            }

        notional = price * quantity

        # 1. Komisyon (broker + BIST + MKK + Takasbank)
        base_commission = notional * self.fees.total_base_fee_pct / 100
        commission = max(base_commission, self.fees.min_commission_tl)

        # Broker komisyonu ayrı hesapla (BSMV sadece broker üzerinden)
        broker_commission = max(notional * self.fees.broker_commission_pct / 100, self.fees.min_commission_tl)

        # 2. BSMV (sadece broker komisyonu üzerinden — BIST/MKK/Takasbank üzerinden alınmaz)
        bsmv = broker_commission * self.fees.bsmv_rate

        # 3. Spread
        liquidity = self.classify_liquidity(avg_daily_volume, market_cap)
        spread_pct = self.spread.estimate_spread(liquidity, volatility_ratio, volume_ratio)

        # Devre kesici sonrası spread genişleme
        if kwargs.get("post_circuit_breaker", False):
            spread_pct *= 1.5  # Devre kesici sonrası spread %50 genişler

        # Brüt takaslı hisselerde spread genişleme
        if kwargs.get("is_gross_settlement", False):
            spread_pct *= 1.3  # Brüt takasta spread %30 genişler

        spread_cost = notional * spread_pct / 2  # Yarısı alış, yarısı satış

        # 4. Slippage
        order_size_pct = 0
        if avg_daily_volume > 0:
            order_size_pct = (quantity * price) / avg_daily_volume

        slippage_pct = self.slippage.estimate_slippage(side, volatility_ratio, volume_ratio, order_size_pct)
        slippage_cost = notional * slippage_pct

        # 5. Market Impact
        volatility = 0.02 * volatility_ratio  # Günlük volatilite tahmini
        impact_pct, permanent_impact_pct = self.impact.estimate_impact(
            quantity, int(avg_daily_volume) if avg_daily_volume > 0 else 1000000, volatility, price
        )
        impact_cost = notional * impact_pct

        # 6. Stopaj (sadece satışta)
        stopaj = 0.0
        if side == "SELL":
            # Stopaj gerçekleşmiş kar üzerinden hesaplanır
            # Basitleştirme: notional üzerinden
            stopaj = 0.0  # Gerçek hesaplama için maliyet bazlı olmalı

        # Toplam
        total_cost = commission + bsmv + spread_cost + slippage_cost + impact_cost + stopaj
        total_pct = (total_cost / notional * 100) if notional > 0 else 0

        result = {
            "ticker": ticker,
            "side": side,
            "price": round(price, 4),
            "quantity": quantity,
            "notional": round(notional, 2),
            "liquidity_tier": liquidity.value,
            "costs": {
                "commission": round(commission, 2),
                "bsmv": round(bsmv, 2),
                "spread": round(spread_cost, 2),
                "slippage": round(slippage_cost, 2),
                "market_impact": round(impact_cost, 2),
                "stopaj": round(stopaj, 2),
            },
            "cost_pcts": {
                "commission_pct": round(commission / notional * 100, 4) if notional > 0 else 0,
                "spread_pct": round(spread_pct * 100, 4),
                "slippage_pct": round(slippage_pct * 100, 4),
                "impact_pct": round(impact_pct * 100, 4),
            },
            "total_cost": round(total_cost, 2),
            "total_cost_pct": round(total_pct, 4),
            "execution_price": round(price * (1 + slippage_pct) if side == "BUY" else price * (1 - slippage_pct), 4),
        }

        logger.debug("Transaction cost calculated", ticker=ticker, side=side, total_pct=f"{total_pct:.4f}%")

        return result

    def estimate_round_trip_cost(
        self,
        ticker: str,
        entry_price: float,
        quantity: int,
        avg_daily_volume: float = 0,
        volatility_ratio: float = 1.0,
    ) -> dict[str, Any]:
        """
        Al-sat (round trip) maliyet tahmini.

        Returns:
            Giriş ve çıkış maliyetleri + toplam round-trip
        """
        buy_cost = self.calculate_total_cost("BUY", entry_price, quantity, ticker, avg_daily_volume, volatility_ratio)
        sell_cost = self.calculate_total_cost("SELL", entry_price, quantity, ticker, avg_daily_volume, volatility_ratio)

        total_round_trip = buy_cost["total_cost"] + sell_cost["total_cost"]
        total_rt_pct = total_round_trip / buy_cost["notional"] * 100 if buy_cost["notional"] > 0 else 0

        return {
            "buy": buy_cost,
            "sell": sell_cost,
            "round_trip_cost": round(total_round_trip, 2),
            "round_trip_cost_pct": round(total_rt_pct, 4),
            "break_even_return_pct": round(total_rt_pct, 4),
        }


# BIST'e özel varsayılan motor
bist_transaction_cost = TransactionCostEngine()
