"""
ALPHA BIST — Gerçekçi İşlem Maliyeti (Transaction Cost) Modeli

Borsa İstanbul'a (BIST) özgü gerçekçi ve çok bileşenli işlem maliyeti motoru.
Sadece aracı kurum komisyonunu değil; BIST pay piyasası işlem ücreti, MKK ücreti,
Takasbank payı, BSMV vergisi, bid/ask spread (makas), volatilite ve hacim bazlı
kayma (slippage) ile büyük emir piyasa etkisini (market impact) modeler.

Maliyet Bileşenleri:
1. Broker Komisyonu: Aracı kurum işlem komisyonu.
2. Borsa Ücretleri: BIST Pay Piyasası + MKK + Takasbank tescil/takas ücretleri.
3. BSMV Vergisi: Sadece aracı kurum komisyonu üzerinden alınan %5 Banka ve Sigorta Muameleleri Vergisi.
4. Bid/Ask Spread: Likidite katmanına ve oynaklığa göre açılan alış-satış kotasyon makası.
5. Slippage (Kayma): Karar fiyatı ile gerçekleşme fiyatı arasındaki sapma.
6. Market Impact: Büyük emirlerin piyasa derinliğini tüketerek fiyatı aleyhe itme etkisi (Square-root modeli).

Referanslar:
- Borsa İstanbul Pay Piyasası İşlem ve Tescil Ücret Tarifesi (2025/2026)
- Kissell, R. (2013). "The Science of Algorithmic Trading and Portfolio Management"
- Harris, L. (2003). "Trading and Exchanges: Market Microstructure for Practitioners"
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
BPS_DIVISOR: float = 10_000.0  # 1 bps = 0.0001 (ondalık)
PERCENT_DIVISOR: float = 100.0  # %1 = 0.01

TIER_1_MIN_VOLUME_TL: float = 500_000_000.0  # 500M+ TL (THYAO, GARAN, EREGL vb.)
TIER_2_MIN_VOLUME_TL: float = 100_000_000.0  # 100M - 500M TL
TIER_3_MIN_VOLUME_TL: float = 20_000_000.0   # 20M - 100M TL

DEFAULT_DAILY_VOLATILITY: float = 0.02  # BIST için tipik günlük volatilite (%2.0)
CIRCUIT_BREAKER_SPREAD_MULTIPLIER: float = 1.5  # Devre kesici sonrası spread %50 genişler
GROSS_SETTLEMENT_SPREAD_MULTIPLIER: float = 1.3  # Brüt takaslı hisselerde spread %30 genişler


# =====================================================================
# ENUM SINIFLARI
# =====================================================================
class MarketCapCategory(Enum):
    """
    Şirket piyasa değeri büyüklük kategorileri.
    """

    LARGE_CAP = "large"    # > 10 Milyar TL (BIST 30 omurgası)
    MID_CAP = "mid"        # 2 - 10 Milyar TL
    SMALL_CAP = "small"    # 500 Milyon - 2 Milyar TL
    MICRO_CAP = "micro"    # < 500 Milyon TL

    def __repr__(self) -> str:
        return f"MarketCapCategory.{self.name}"


class LiquidityTier(Enum):
    """
    Günlük ortalama işlem hacmine göre likidite katmanları.
    """

    TIER_1 = "tier_1"  # En likit (günlük hacim > 500M TL)
    TIER_2 = "tier_2"  # Orta-yüksek likit (100M - 500M TL)
    TIER_3 = "tier_3"  # Orta-düşük likit (20M - 100M TL)
    TIER_4 = "tier_4"  # Sığ / düşük likit (< 20M TL)

    def __repr__(self) -> str:
        return f"LiquidityTier.{self.name}"


# =====================================================================
# BIST KOMİSYON VE ÜCRET YAPISI
# =====================================================================
@dataclass
class BISTFeeStructure:
    """
    Borsa İstanbul resmi yasal ücret ve aracı kurum komisyon tarifesi.

    Attributes:
        broker_commission_pct: Aracı kurum komisyon oranı (yüzde, örn: 0.03 = onbinde 3).
        bist_fee_pct: BIST Pay Piyasası işlem tescil ücreti (yüzde, örn: 0.0056).
        mkk_fee_pct: Merkezi Kayıt Kuruluşu payı (yüzde, örn: 0.00109).
        takasbank_fee_pct: Takasbank saklama ve takas payı (yüzde, örn: 0.0001).
        min_commission_tl: İşlem başına asgari komisyon tutarı (TL).
        bsmv_rate: Broker komisyonu üzerinden alınan BSMV oranı (örn: 0.05 = %5).
        stopaj_rate: Pay senedi satış kazancı stopaj oranı (hisse senetlerinde genel olarak %0).
    """

    broker_commission_pct: float = 0.03  # %0.03 = on binde 3
    bist_fee_pct: float = 0.0056         # %0.0056 = yüz binde 5.6
    mkk_fee_pct: float = 0.00109         # %0.00109
    takasbank_fee_pct: float = 0.0001    # %0.0001
    min_commission_tl: float = 1.0       # Asgari 1.00 TL
    bsmv_rate: float = 0.05              # Komisyon üzerinden %5 BSMV
    stopaj_rate: float = 0.0             # Hisse satış stopajı

    def __post_init__(self) -> None:
        """Komisyon ve oran parametre doğrulaması."""
        if self.broker_commission_pct < 0.0 or self.bist_fee_pct < 0.0 or self.mkk_fee_pct < 0.0 or self.takasbank_fee_pct < 0.0:
            raise ValueError("Komisyon ve borsa ücret oranları negatif olamaz.")
        if self.min_commission_tl < 0.0:
            raise ValueError("Asgari komisyon tutarı negatif olamaz.")
        if not (0.0 <= self.bsmv_rate <= 1.0):
            raise ValueError(f"BSMV oranı [0.0, 1.0] aralığında olmalıdır: {self.bsmv_rate}")
        if not (0.0 <= self.stopaj_rate <= 1.0):
            raise ValueError(f"Stopaj oranı [0.0, 1.0] aralığında olmalıdır: {self.stopaj_rate}")

    @property
    def total_exchange_fee_pct(self) -> float:
        """Toplam resmi borsa ve takas ücretleri oranı (yüzde cinsinden)."""
        return self.bist_fee_pct + self.mkk_fee_pct + self.takasbank_fee_pct

    @property
    def total_base_fee_pct(self) -> float:
        """Aracı kurum ve borsa ücretlerinin toplam temel oranı (BSMV hariç, yüzde)."""
        return self.broker_commission_pct + self.total_exchange_fee_pct

    def __repr__(self) -> str:
        return (
            f"BISTFeeStructure(broker={self.broker_commission_pct}%, exchange={self.total_exchange_fee_pct:.5f}%, "
            f"bsmv={self.bsmv_rate * 100}%, min_tl={self.min_commission_tl})"
        )


# =====================================================================
# BID/ASK SPREAD (MAKAS) MODELİ
# =====================================================================
@dataclass
class SpreadModel:
    """
    Likidite katmanına, volatiliteye ve anlık hacme dayalı alış-satış makas modeli.

    Attributes:
        tier_1_spread_bps: 1. katman baz spread (bps, örn: 5 bps = %0.05).
        tier_2_spread_bps: 2. katman baz spread (bps, örn: 15 bps = %0.15).
        tier_3_spread_bps: 3. katman baz spread (bps, örn: 30 bps = %0.30).
        tier_4_spread_bps: 4. katman baz spread (bps, örn: 75 bps = %0.75).
        volatility_multiplier: Oynaklık artışının makası açma katsayısı.
        volume_decay_factor: Hacim düşüşünün makası açma katsayısı.
    """

    tier_1_spread_bps: float = 5.0
    tier_2_spread_bps: float = 15.0
    tier_3_spread_bps: float = 30.0
    tier_4_spread_bps: float = 75.0
    volatility_multiplier: float = 1.5
    volume_decay_factor: float = 0.5

    def estimate_spread(
        self,
        liquidity_tier: LiquidityTier | str,
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
    ) -> float:
        """
        Piyasa koşullarına göre tahmini bid/ask spread oranını (ondalık) hesaplar.

        Args:
            liquidity_tier: Hisse senedinin likidite katmanı (Enum veya 'tier_1' string).
            volatility_ratio: Anlık volatilite / ortalama volatilite oranı.
            volume_ratio: Anlık işlem hacmi / ortalama işlem hacmi oranı.

        Returns:
            float: Tahmini spread (ondalık, örn: 0.0015 = %0.15).
        """
        # String veya Enum esnek dönüşümü
        if isinstance(liquidity_tier, str):
            try:
                tier_enum = LiquidityTier(liquidity_tier.strip().lower())
            except ValueError:
                tier_enum = LiquidityTier.TIER_4
        else:
            tier_enum = liquidity_tier

        # Güvenli sayısal kısıtlar
        vol_r = 1.0 if math.isnan(volatility_ratio) or volatility_ratio <= 0.0 else volatility_ratio
        vol_r = max(0.2, min(vol_r, 5.0))

        volm_r = 1.0 if math.isnan(volume_ratio) or volume_ratio <= 0.0 else volume_ratio
        volm_r = max(0.1, min(volm_r, 10.0))

        # Katmana göre baz spread (bps)
        tier_bps_map = {
            LiquidityTier.TIER_1: self.tier_1_spread_bps,
            LiquidityTier.TIER_2: self.tier_2_spread_bps,
            LiquidityTier.TIER_3: self.tier_3_spread_bps,
            LiquidityTier.TIER_4: self.tier_4_spread_bps,
        }
        base_bps = tier_bps_map.get(tier_enum, self.tier_4_spread_bps)
        base_spread = base_bps / BPS_DIVISOR

        # Volatilite çarpanı
        vol_adj = 1.0 + (vol_r - 1.0) * (self.volatility_multiplier - 1.0)
        vol_adj = max(0.5, min(vol_adj, 3.0))

        # Hacim çarpanı (düşük hacimde spread genişler)
        if volm_r < 1.0:
            vol_adj *= (1.0 + (1.0 - volm_r) * self.volume_decay_factor)

        return float(base_spread * vol_adj)

    def __repr__(self) -> str:
        return (
            f"SpreadModel(tier_1={self.tier_1_spread_bps}bps, tier_2={self.tier_2_spread_bps}bps, "
            f"tier_3={self.tier_3_spread_bps}bps, tier_4={self.tier_4_spread_bps}bps)"
        )


# =====================================================================
# SLIPPAGE (FİYAT KAYMASI) MODELİ
# =====================================================================
@dataclass
class SlippageModel:
    """
    İşlem anındaki emir boyutu, volatilite ve piyasa likiditesine bağlı kayma modeli.

    Attributes:
        base_slippage_bps: Baz kayma oranı (bps, örn: 5 bps = %0.05).
        volatility_impact: Volatiliteye duyarlılık katsayısı.
        volume_impact: Düşük hacme duyarlılık katsayısı.
    """

    base_slippage_bps: float = 5.0
    volatility_impact: float = 2.0
    volume_impact: float = 1.5

    def estimate_slippage(
        self,
        side: str,
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        order_size_pct: float = 0.01,
    ) -> float:
        """
        Emir yönü ve piyasa şartlarına göre gerçekleşme fiyatı kaymasını (ondalık) hesaplar.

        Args:
            side: Emir yönü ('BUY' veya 'SELL').
            volatility_ratio: Anlık volatilite / ortalama volatilite oranı.
            volume_ratio: Anlık hacim / ortalama hacim oranı.
            order_size_pct: Emir büyüklüğünün günlük toplam hacme oranı.

        Returns:
            float: Mutlak tahmini kayma oranı (ondalık, pozitif).
        """
        base = self.base_slippage_bps / BPS_DIVISOR

        vol_r = 1.0 if math.isnan(volatility_ratio) or volatility_ratio <= 0.0 else volatility_ratio
        vol_effect = 1.0 + (vol_r - 1.0) * self.volatility_impact
        vol_effect = max(0.5, min(vol_effect, 5.0))

        volm_r = 1.0 if math.isnan(volume_ratio) or volume_ratio <= 0.0 else volume_ratio
        if volm_r > 0.0:
            volume_effect = 1.0 + (1.0 / volm_r - 1.0) * self.volume_impact
            volume_effect = max(1.0, min(volume_effect, 5.0))
        else:
            volume_effect = 3.0

        size_pct = 0.0 if math.isnan(order_size_pct) or order_size_pct < 0.0 else order_size_pct
        size_pct = min(size_pct, 1.0)
        size_effect = 1.0 + size_pct * 10.0
        size_effect = max(1.0, min(size_effect, 3.0))

        slippage = base * vol_effect * volume_effect * size_effect
        return abs(float(slippage))

    def __repr__(self) -> str:
        return f"SlippageModel(base={self.base_slippage_bps}bps, vol_impact={self.volatility_impact})"


# =====================================================================
# MARKET IMPACT (PİYASA ETKİSİ) MODELİ
# =====================================================================
@dataclass
class MarketImpactModel:
    """
    Büyük emirlerin piyasa tahtasında fiyatı itme etkisini hesaplayan Square-Root modeli.

    Formül: Impact = sigma * sqrt(Q / V) * eta
    Q: Emir boyutu (lot adedi)
    V: Günlük işlem hacmi (lot adedi)
    sigma: Günlük volatilite
    eta: Akışkanlık parametresi

    Attributes:
        eta: Piyasa akışkanlık / derinlik parametresi (tipik BIST ortalaması 0.5).
        permanent_ratio: Toplam etkinin kalıcı fiyata dönüşme oranı (örn: %30).
    """

    eta: float = 0.5
    permanent_ratio: float = 0.3

    def estimate_impact(
        self,
        order_quantity: int,
        avg_daily_volume: int | float,
        volatility: float,
        price: float,
    ) -> tuple[float, float]:
        """
        Birim uyumlu (lot / lot) square-root modeliyle toplam ve kalıcı piyasa etkisini hesaplar.

        Args:
            order_quantity: Emir adedi (lot).
            avg_daily_volume: Günlük ortalama işlem adedi (lot cinsinden).
            volatility: Günlük volatilite (ondalık, örn: 0.02).
            price: Hisse işlem fiyatı.

        Returns:
            tuple[float, float]: (Toplam etki oranı, Kalıcı etki oranı).
        """
        if order_quantity <= 0 or avg_daily_volume <= 0 or price <= 0 or volatility <= 0.0:
            return 0.0, 0.0

        if math.isnan(volatility):
            return 0.0, 0.0

        # Katılım oranı (participation rate) lot / lot cinsinden hesaplanır (cap: 1.0)
        participation = min(1.0, float(order_quantity) / float(avg_daily_volume))

        # Square-root piyasa etkisi formülü
        total_impact = volatility * math.sqrt(participation) * self.eta
        permanent_impact = total_impact * self.permanent_ratio

        return abs(float(total_impact)), abs(float(permanent_impact))

    def __repr__(self) -> str:
        return f"MarketImpactModel(eta={self.eta}, permanent_ratio={self.permanent_ratio})"


# =====================================================================
# İŞLEM MALİYETİ ANA MOTORU
# =====================================================================
class TransactionCostEngine:
    """
    BIST Gerçekçi İşlem Maliyeti Hesaplama Motoru.

    Komisyon, borsa ücretleri, BSMV vergisi, spread, slippage ve market impact
    bileşenlerini birleştirerek tekil işlem veya getiri serisi için toplam maliyet üretir.
    Thread-safe olarak çalışır.
    """

    def __init__(
        self,
        fee_structure: BISTFeeStructure | None = None,
        spread_model: SpreadModel | None = None,
        slippage_model: SlippageModel | None = None,
        impact_model: MarketImpactModel | None = None,
    ) -> None:
        """
        İşlem maliyeti motorunu bileşenleriyle ilklendirir.

        Args:
            fee_structure: BIST komisyon ve vergi yapısı (varsayılan: BISTFeeStructure).
            spread_model: Alış-satış makas modeli (varsayılan: SpreadModel).
            slippage_model: Fiyat kayması modeli (varsayılan: SlippageModel).
            impact_model: Piyasa etkisi modeli (varsayılan: MarketImpactModel).
        """
        self.fees: BISTFeeStructure = fee_structure or BISTFeeStructure()
        self.spread: SpreadModel = spread_model or SpreadModel()
        self.slippage: SlippageModel = slippage_model or SlippageModel()
        self.impact: MarketImpactModel = impact_model or MarketImpactModel()
        self._lock: threading.Lock = threading.Lock()

    def classify_liquidity(
        self,
        avg_daily_volume: float,
        market_cap: float | None = None,
    ) -> LiquidityTier:
        """
        Günlük ortalama işlem hacmine ve piyasa değerine göre hisseyi likidite katmanına sınıflandırır.

        Args:
            avg_daily_volume: Günlük ortalama işlem hacmi (TL cinsinden).
            market_cap: İsteğe bağlı piyasa değeri (TL cinsinden).

        Returns:
            LiquidityTier: TIER_1, TIER_2, TIER_3 veya TIER_4.
        """
        vol = 0.0 if math.isnan(avg_daily_volume) or avg_daily_volume <= 0.0 else avg_daily_volume

        if vol >= TIER_1_MIN_VOLUME_TL:
            return LiquidityTier.TIER_1
        elif vol >= TIER_2_MIN_VOLUME_TL:
            return LiquidityTier.TIER_2
        elif vol >= TIER_3_MIN_VOLUME_TL:
            return LiquidityTier.TIER_3
        else:
            return LiquidityTier.TIER_4

    def calculate_total_cost(
        self,
        side: str,
        price: float,
        quantity: int,
        ticker: str,
        avg_daily_volume: float = 0.0,
        volatility_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        market_cap: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Tek bir işlem emri için tüm maliyet kalemlerini ve net gerçekleşme fiyatını hesaplar.

        Args:
            side: Emir yönü ('BUY', 'ALIS' veya 'SELL', 'SATIS').
            price: Hisse birim fiyatı (TL).
            quantity: Emir adedi (lot).
            ticker: Hisse sembolü (örn: 'THYAO').
            avg_daily_volume: Günlük ortalama işlem hacmi (TL cinsinden).
            volatility_ratio: Oynaklık çarpanı.
            volume_ratio: Hacim çarpanı.
            market_cap: Şirket piyasa değeri (TL).
            **kwargs: Ek BIST özel durum parametreleri (post_circuit_breaker, is_gross_settlement vb.).

        Returns:
            dict[str, Any]: Detaylı maliyet dökümü, oranlar ve execution_price içeren sözlük.

        Raises:
            ValueError: Geçersiz emir yönü girildiğinde.
        """
        clean_side = side.strip().upper()
        if clean_side in ("BUY", "ALIS", "AL"):
            clean_side = "BUY"
        elif clean_side in ("SELL", "SATIS", "SAT"):
            clean_side = "SELL"
        else:
            raise ValueError(f"Geçersiz emir yönü: '{side}'. 'BUY' veya 'SELL' bekleniyordu.")

        clean_ticker = ticker.strip().upper()

        # Negatif veya sıfır fiyat/adet durumlarında güvenli sıfır maliyet dönüşü
        if price <= 0.0 or quantity <= 0:
            return {
                "ticker": clean_ticker,
                "side": clean_side,
                "price": 0.0,
                "quantity": 0,
                "notional": 0.0,
                "liquidity_tier": LiquidityTier.TIER_4.value,
                "costs": {k: 0.0 for k in ["commission", "bsmv", "spread", "slippage", "market_impact", "stopaj"]},
                "cost_pcts": {k: 0.0 for k in ["commission_pct", "spread_pct", "slippage_pct", "impact_pct"]},
                "total_cost": 0.0,
                "total_cost_pct": 0.0,
                "execution_price": 0.0,
            }

        notional = float(price * quantity)

        with self._lock:
            fees = self.fees
            spread_model = self.spread
            slippage_model = self.slippage
            impact_model = self.impact

        # 1. Komisyon (Broker + BIST Pay Piyasası + MKK + Takasbank)
        base_commission = notional * (fees.total_base_fee_pct / PERCENT_DIVISOR)
        commission = max(base_commission, fees.min_commission_tl)

        # BSMV sadece aracı kurum komisyonu üzerinden alınır
        broker_commission = max(notional * (fees.broker_commission_pct / PERCENT_DIVISOR), fees.min_commission_tl)
        bsmv = broker_commission * fees.bsmv_rate

        # 2. Bid/Ask Spread Maliyeti
        liquidity = self.classify_liquidity(avg_daily_volume, market_cap)
        spread_pct = spread_model.estimate_spread(liquidity, volatility_ratio, volume_ratio)

        # Devre kesici sonrası spread genişlemesi
        if kwargs.get("post_circuit_breaker", False):
            spread_pct *= CIRCUIT_BREAKER_SPREAD_MULTIPLIER

        # Brüt takaslı hisselerde spread genişlemesi
        if kwargs.get("is_gross_settlement", False):
            spread_pct *= GROSS_SETTLEMENT_SPREAD_MULTIPLIER

        # Tek yönlü işlem maliyeti = Spread'in yarısı
        spread_cost = notional * (spread_pct / 2.0)

        # 3. Slippage (Fiyat Kayması)
        order_size_pct = 0.0
        if avg_daily_volume > 0.0:
            order_size_pct = notional / avg_daily_volume

        slippage_pct = slippage_model.estimate_slippage(clean_side, volatility_ratio, volume_ratio, order_size_pct)
        slippage_cost = notional * slippage_pct

        # 4. Market Impact (Birim uyumlu: adet / adet katılım oranı)
        # avg_daily_volume TL hacim ise, günlük hisse adedi = TL Hacim / Fiyat
        daily_shares = max(1, int(avg_daily_volume / price)) if (avg_daily_volume > 0.0 and price > 0.0) else 1_000_000
        volatility = DEFAULT_DAILY_VOLATILITY * max(0.2, volatility_ratio)

        impact_pct, _ = impact_model.estimate_impact(quantity, daily_shares, volatility, price)
        impact_cost = notional * impact_pct

        # 5. Stopaj
        stopaj = 0.0

        # Toplam Maliyet Hesabı
        total_cost = commission + bsmv + spread_cost + slippage_cost + impact_cost + stopaj
        total_pct = (total_cost / notional * PERCENT_DIVISOR) if notional > 0.0 else 0.0

        # Gerçekleşme Fiyatı (Execution Price)
        # Alışta kayma, spread ve impact yukarı iter; satışta aşağı çeker
        half_spread = spread_pct / 2.0
        if clean_side == "BUY":
            exec_price = price * (1.0 + slippage_pct + half_spread + impact_pct)
        else:
            exec_price = price * max(0.0, 1.0 - slippage_pct - half_spread - impact_pct)

        result = {
            "ticker": clean_ticker,
            "side": clean_side,
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
                "commission_pct": round(commission / notional * PERCENT_DIVISOR, 4) if notional > 0.0 else 0.0,
                "spread_pct": round(spread_pct * PERCENT_DIVISOR, 4),
                "slippage_pct": round(slippage_pct * PERCENT_DIVISOR, 4),
                "impact_pct": round(impact_pct * PERCENT_DIVISOR, 4),
            },
            "total_cost": round(total_cost, 2),
            "total_cost_pct": round(total_pct, 4),
            "execution_price": round(exec_price, 4),
        }

        logger.debug(
            "İşlem maliyeti hesaplandı: hisse=%s, yön=%s, notional=%.2f TL, toplam_maliyet=%.2f TL (%%%.4f)",
            clean_ticker,
            clean_side,
            notional,
            total_cost,
            total_pct,
        )

        return result

    def estimate_round_trip_cost(
        self,
        ticker: str,
        entry_price: float,
        quantity: int,
        avg_daily_volume: float = 0.0,
        volatility_ratio: float = 1.0,
        exit_price: float | None = None,
    ) -> dict[str, Any]:
        """
        Pozisyon açma ve kapama (Al-Sat / Round-Trip) toplam maliyet ve başabaş getiri oranını hesaplar.

        Args:
            ticker: Hisse senedi sembolü.
            entry_price: Pozisyon giriş fiyatı.
            quantity: İşlem adedi (lot).
            avg_daily_volume: Günlük ortalama işlem hacmi (TL).
            volatility_ratio: Oynaklık çarpanı.
            exit_price: İsteğe bağlı çıkış fiyatı (belirtilmezse giriş fiyatı kullanılır).

        Returns:
            dict[str, Any]: Alış, satış ve toplam tur maliyetleri özeti.
        """
        eff_exit_price = exit_price if (exit_price is not None and exit_price > 0.0) else entry_price

        buy_cost = self.calculate_total_cost("BUY", entry_price, quantity, ticker, avg_daily_volume, volatility_ratio)
        sell_cost = self.calculate_total_cost("SELL", eff_exit_price, quantity, ticker, avg_daily_volume, volatility_ratio)

        total_round_trip = buy_cost["total_cost"] + sell_cost["total_cost"]
        notional = buy_cost["notional"]
        total_rt_pct = (total_round_trip / notional * PERCENT_DIVISOR) if notional > 0.0 else 0.0

        return {
            "buy": buy_cost,
            "sell": sell_cost,
            "round_trip_cost": round(total_round_trip, 2),
            "round_trip_cost_pct": round(total_rt_pct, 4),
            "break_even_return_pct": round(total_rt_pct, 4),
        }

    def compute_costs_df(
        self,
        trades_df: pl.DataFrame,
        price_col: str = "price",
        quantity_col: str = "quantity",
        side_col: str = "side",
        ticker_col: str = "ticker",
        volume_col: str | None = None,
    ) -> pl.DataFrame:
        """
        Polars DataFrame içindeki tüm işlemlere vektörel olarak detaylı maliyet sütunları ekler.

        Args:
            trades_df: İşlem listesi içeren Polars DataFrame.
            price_col: Fiyat sütun adı.
            quantity_col: Adet sütun adı.
            side_col: Yön sütun adı.
            ticker_col: Hisse kodu sütun adı.
            volume_col: İsteğe bağlı günlük hacim sütun adı.

        Returns:
            pl.DataFrame: Maliyet ve net icra fiyatı eklenmiş yeni Polars DataFrame.

        Raises:
            TypeError: trades_df Polars DataFrame değilse.
            ValueError: Zorunlu sütunlar DataFrame içinde bulunamazsa.
        """
        if not isinstance(trades_df, pl.DataFrame):
            raise TypeError(f"trades_df bir Polars DataFrame olmalıdır, {type(trades_df)} alındı.")

        if trades_df.is_empty():
            return trades_df.clone()

        required = {price_col, quantity_col, side_col, ticker_col}
        missing = required - set(trades_df.columns)
        if missing:
            raise ValueError(f"trades_df içinde zorunlu sütunlar eksik: {missing}")

        results: list[dict[str, Any]] = []
        for row in trades_df.iter_rows(named=True):
            raw_price = row[price_col]
            raw_qty = row[quantity_col]
            raw_side = row[side_col]
            raw_tck = row[ticker_col]

            if raw_price is None or raw_qty is None or raw_side is None or raw_tck is None:
                results.append({
                    "calculated_total_cost": 0.0,
                    "calculated_cost_pct": 0.0,
                    "calculated_exec_price": 0.0,
                })
                continue

            price = float(raw_price)
            qty = int(raw_qty)
            side = str(raw_side)
            tck = str(raw_tck)
            vol = float(row[volume_col]) if (volume_col and row.get(volume_col) is not None) else 0.0

            cost_dict = self.calculate_total_cost(side, price, qty, tck, avg_daily_volume=vol)
            results.append({
                "calculated_total_cost": cost_dict["total_cost"],
                "calculated_cost_pct": cost_dict["total_cost_pct"],
                "calculated_exec_price": cost_dict["execution_price"],
            })

        costs_df = pl.DataFrame(results)
        return pl.concat([trades_df, costs_df], how="horizontal")

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"TransactionCostEngine(fees={self.fees}, spread={self.spread}, "
                f"slippage={self.slippage}, impact={self.impact})"
            )


# =====================================================================
# GERİYE DÖNÜK UYUMLULUK ALIAS'I VE SINGLETON
# =====================================================================
BISTCostParams = BISTFeeStructure
bist_transaction_cost = TransactionCostEngine()

__all__ = [
    "BPS_DIVISOR",
    "CIRCUIT_BREAKER_SPREAD_MULTIPLIER",
    "DEFAULT_DAILY_VOLATILITY",
    "GROSS_SETTLEMENT_SPREAD_MULTIPLIER",
    "PERCENT_DIVISOR",
    "TIER_1_MIN_VOLUME_TL",
    "TIER_2_MIN_VOLUME_TL",
    "TIER_3_MIN_VOLUME_TL",
    "BISTCostParams",
    "BISTFeeStructure",
    "LiquidityTier",
    "MarketCapCategory",
    "MarketImpactModel",
    "SlippageModel",
    "SpreadModel",
    "TransactionCostEngine",
    "bist_transaction_cost",
]
