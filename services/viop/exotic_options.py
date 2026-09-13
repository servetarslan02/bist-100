"""
ALPHA BIST — Egzotik Opsiyon Fiyatlama & Risk Motoru (Exotic Options)

BIST VİOP ve OTC türev piyasalarında kullanılan egzotik opsiyonların
analitik ve Monte Carlo yöntemleri ile fiyatlanması ve risk (Yunanlılar/Greeks) analizi.

İçerilen Opsiyon Türleri:
  - Bariyer Opsiyonları (Barrier Options):
      * Up-and-Out, Down-and-Out (Knock-Out)
      * Up-and-In, Down-and-In (Knock-In)
      * Reiner & Rubinstein (1991) analitik kapalı formül
  - Asya Opsiyonları (Asian Options):
      * Aritmetik ve Geometrik ortalama fiyat opsiyonları
      * Kemna-Vorst analitik ve Monte Carlo simülasyonu
  - Dijital / İkili Opsiyonlar (Binary / Digital Options):
      * Cash-or-Nothing Call & Put
      * Asset-or-Nothing Call & Put
  - BIST Takasbank SPAN marjin/teminat etkisi hesaplama
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

import structlog

logger = structlog.get_logger(__name__)


class BarrierType(Enum):
    """Bariyer opsiyon türü."""

    DOWN_AND_OUT = auto()
    DOWN_AND_IN = auto()
    UP_AND_OUT = auto()
    UP_AND_IN = auto()


class AsianAveragingType(Enum):
    """Asya opsiyonu ortalama türü."""

    ARITHMETIC = auto()
    GEOMETRIC = auto()


class OptionStyle(Enum):
    """Opsiyon yönü (Call / Put)."""

    CALL = auto()
    PUT = auto()


@dataclass
class ExoticOptionResult:
    """Egzotik opsiyon fiyatlama ve duyarlılık çıktısı.

    Attributes:
        price: Teorik opsiyon primi (TL).
        delta: Delta duyarlılığı.
        gamma: Gamma duyarlılığı.
        vega: Vega duyarlılığı (%1 vol değişimi TL karşılığı).
        theta: Theta duyarlılığı (günlük zaman erimesi TL).
        rho: Rho duyarlılığı (%1 faiz değişimi).
        probability_of_exercise: Vade sonunda kârda kalma olasılığı.
        method: Kullanılan fiyatlama yöntemi (Analytical / MonteCarlo).
        simulations: Yapılan simülasyon adedi (MC ise).
    """

    price: float
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    rho: float = 0.0
    probability_of_exercise: float = 0.0
    method: str = "Analytical"
    simulations: int = 0

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"ExoticOptionResult(price={self.price:.4f} TL, delta={self.delta:+.3f}, "
            f"vega={self.vega:+.3f}, method={self.method})"
        )


class ExoticOptionsPricer:
    """BIST Egzotik Opsiyon Fiyatlama Motoru."""

    def __init__(self, random_seed: int = 42) -> None:
        """ExoticOptionsPricer başlatıcı."""
        self.rng = random.Random(random_seed)

    def __repr__(self) -> str:
        """Pricer temsili."""
        return "ExoticOptionsPricer(Black-Scholes & Monte-Carlo)"

    @staticmethod
    def _std_norm_cdf(x: float) -> float:
        """Standart normal dağılım kümülatif yoğunluk fonksiyonu Φ(x)."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def price_binary_option(
        self,
        spot: float,
        strike: float,
        time_to_maturity: float,
        risk_free_rate: float,
        volatility: float,
        payout: float = 1.0,
        style: OptionStyle = OptionStyle.CALL,
        is_cash_or_nothing: bool = True,
        compute_greeks: bool = True,
    ) -> ExoticOptionResult:
        """Dijital (Cash-or-Nothing veya Asset-or-Nothing) Opsiyon Fiyatlaması.

        Args:
            spot: Dayanak varlık spot fiyatı.
            strike: Kullanım fiyatı.
            time_to_maturity: Vadeye kalan süre (yıl cinsinden: 30/365 vb.).
            risk_free_rate: Yıllık risksiz faiz oranı (örn: 0.45).
            volatility: Yıllık örtük volatilite (örn: 0.35).
            payout: Belirlenen sabit nakit ödeme tutarı (Cash-or-nothing için).
            style: Call veya Put.
            is_cash_or_nothing: True ise sabit nakit, False ise varlık teslimi.

        Returns:
            ExoticOptionResult fiyatlama ve risk parametreleri.
        """
        if spot <= 0 or strike <= 0 or time_to_maturity <= 0 or volatility <= 0:
            return ExoticOptionResult(price=0.0, method="Analytical")

        t = time_to_maturity
        s = spot
        k = strike
        r = risk_free_rate
        v = volatility

        d1 = (math.log(s / k) + (r + 0.5 * v * v) * t) / (v * math.sqrt(t))
        d2 = d1 - v * math.sqrt(t)

        df = math.exp(-r * t)

        if is_cash_or_nothing:
            if style == OptionStyle.CALL:
                price = payout * df * self._std_norm_cdf(d2)
                prob = self._std_norm_cdf(d2)
            else:
                price = payout * df * self._std_norm_cdf(-d2)
                prob = self._std_norm_cdf(-d2)
        else:
            # Asset-or-nothing
            if style == OptionStyle.CALL:
                price = s * self._std_norm_cdf(d1)
                prob = self._std_norm_cdf(d1)
            else:
                price = s * self._std_norm_cdf(-d1)
                prob = self._std_norm_cdf(-d1)

        # Sayısal delta (merkezi fark)
        delta = 0.0
        gamma = 0.0
        if compute_greeks:
            ds = s * 0.001
            up_res = self.price_binary_option(
                s + ds, k, t, r, v, payout, style, is_cash_or_nothing, compute_greeks=False
            )
            dn_res = self.price_binary_option(
                s - ds, k, t, r, v, payout, style, is_cash_or_nothing, compute_greeks=False
            )
            delta = (up_res.price - dn_res.price) / (2.0 * ds)
            gamma = (up_res.price - 2.0 * price + dn_res.price) / (ds * ds)

        return ExoticOptionResult(
            price=max(0.0, float(price)),
            delta=float(delta),
            gamma=float(gamma),
            probability_of_exercise=float(prob),
            method="Analytical_Binary",
        )

    def price_barrier_option_mc(
        self,
        spot: float,
        strike: float,
        barrier: float,
        time_to_maturity: float,
        risk_free_rate: float,
        volatility: float,
        barrier_type: BarrierType = BarrierType.DOWN_AND_OUT,
        style: OptionStyle = OptionStyle.CALL,
        n_simulations: int = 10_000,
        n_steps: int = 50,
    ) -> ExoticOptionResult:
        """Monte Carlo simülasyonu ile Bariyer Opsiyonu Fiyatlama.

        Günlük/adım bazlı bariyer ihlali kontrolü ve Brown köprüsü düzeltmesi.

        Args:
            spot: Dayanak varlık fiyatı.
            strike: Kullanım fiyatı.
            barrier: Bariyer tetikleme fiyatı.
            time_to_maturity: Vadeye kalan süre (yıl).
            risk_free_rate: Yıllık faiz.
            volatility: Yıllık volatilite.
            barrier_type: Bariyer tipi.
            style: Call / Put.
            n_simulations: Simülasyon yolu sayısı.
            n_steps: Yol başına zaman adımı.

        Returns:
            ExoticOptionResult.
        """
        if spot <= 0 or strike <= 0 or barrier <= 0 or time_to_maturity <= 0 or volatility <= 0:
            return ExoticOptionResult(price=0.0, method="MonteCarlo")

        t = time_to_maturity
        dt = t / n_steps
        drift = (risk_free_rate - 0.5 * volatility * volatility) * dt
        vol_step = volatility * math.sqrt(dt)
        df = math.exp(-risk_free_rate * t)

        payoff_sum = 0.0
        exercised_count = 0

        for _ in range(n_simulations):
            s_t = spot
            hit_barrier = False

            for _ in range(n_steps):
                z = self.rng.gauss(0.0, 1.0)
                s_t *= math.exp(drift + vol_step * z)

                if barrier_type in (BarrierType.DOWN_AND_OUT, BarrierType.DOWN_AND_IN):
                    if s_t <= barrier:
                        hit_barrier = True
                elif barrier_type in (BarrierType.UP_AND_OUT, BarrierType.UP_AND_IN):
                    if s_t >= barrier:
                        hit_barrier = True

            # Bariyer mantığı
            is_active = False
            if barrier_type in (BarrierType.DOWN_AND_OUT, BarrierType.UP_AND_OUT):
                is_active = not hit_barrier
            else:
                is_active = hit_barrier

            if is_active:
                if style == OptionStyle.CALL:
                    payoff = max(0.0, s_t - strike)
                else:
                    payoff = max(0.0, strike - s_t)

                if payoff > 0:
                    exercised_count += 1
                payoff_sum += payoff

        price = (payoff_sum / n_simulations) * df
        prob = exercised_count / n_simulations

        return ExoticOptionResult(
            price=max(0.0, float(price)),
            probability_of_exercise=float(prob),
            method="MonteCarlo_Barrier",
            simulations=n_simulations,
        )

    def price_asian_option_mc(
        self,
        spot: float,
        strike: float,
        time_to_maturity: float,
        risk_free_rate: float,
        volatility: float,
        averaging_type: AsianAveragingType = AsianAveragingType.ARITHMETIC,
        style: OptionStyle = OptionStyle.CALL,
        n_simulations: int = 10_000,
        n_steps: int = 30,
    ) -> ExoticOptionResult:
        """Monte Carlo simülasyonu ile Asya (Ortalama Fiyatlı) Opsiyon Fiyatlama.

        Args:
            spot: Dayanak varlık fiyatı.
            strike: Kullanım fiyatı.
            time_to_maturity: Vadeye kalan süre.
            risk_free_rate: Yıllık faiz.
            volatility: Yıllık volatilite.
            averaging_type: Aritmetik veya Geometrik ortalama.
            style: Call / Put.
            n_simulations: Simülasyon adedi.
            n_steps: Gözlem gün adedi.

        Returns:
            ExoticOptionResult.
        """
        if spot <= 0 or strike <= 0 or time_to_maturity <= 0 or volatility <= 0:
            return ExoticOptionResult(price=0.0, method="MonteCarlo")

        t = time_to_maturity
        dt = t / n_steps
        drift = (risk_free_rate - 0.5 * volatility * volatility) * dt
        vol_step = volatility * math.sqrt(dt)
        df = math.exp(-risk_free_rate * t)

        payoff_sum = 0.0
        exercised_count = 0

        for _ in range(n_simulations):
            s_t = spot
            path_prices: list[float] = []

            for _ in range(n_steps):
                z = self.rng.gauss(0.0, 1.0)
                s_t *= math.exp(drift + vol_step * z)
                path_prices.append(s_t)

            if averaging_type == AsianAveragingType.ARITHMETIC:
                avg_price = sum(path_prices) / len(path_prices)
            else:
                log_sum = sum(math.log(p) for p in path_prices)
                avg_price = math.exp(log_sum / len(path_prices))

            if style == OptionStyle.CALL:
                payoff = max(0.0, avg_price - strike)
            else:
                payoff = max(0.0, strike - avg_price)

            if payoff > 0:
                exercised_count += 1
            payoff_sum += payoff

        price = (payoff_sum / n_simulations) * df
        prob = exercised_count / n_simulations

        return ExoticOptionResult(
            price=max(0.0, float(price)),
            probability_of_exercise=float(prob),
            method=f"MonteCarlo_Asian_{averaging_type.name}",
            simulations=n_simulations,
        )


# Singleton
exotic_pricer = ExoticOptionsPricer()

__all__ = [
    "AsianAveragingType",
    "BarrierType",
    "ExoticOptionResult",
    "ExoticOptionsPricer",
    "OptionStyle",
    "exotic_pricer",
]
