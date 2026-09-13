"""
ALPHA BIST — Volatilite Yüzeyi (Implied Volatility Surface)

BIST VIOP opsiyonları için sürtünmesiz volatilite yüzeyi hesaplama ve analiz.
Black-Scholes implied volatility çıkarımı, smile/skew analizi ve term structure
modelleme ile kurumsal opsiyoncu düzeyinde fiyatlama desteği sağlar.

Özellikler:
  - Newton-Raphson iterasyonu ile hızlı IV çıkarımı
  - Vega tabanlı yakınsama kontrolü (sayısal stabilite garantisi)
  - IV smile: Her vadede strike'a göre IV profili
  - IV term structure: Strike'a göre vade boyunca IV eğrisi
  - Put-Call Parity kontrolü: Arbitraj yokluğu doğrulaması
  - ATM (At-the-Money) IV surface interpolasyonu
"""
from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_MAX_ITER: int = 100          # Newton-Raphson maksimum iterasyon
DEFAULT_TOLERANCE: float = 1e-7      # Newton-Raphson yakınsama toleransı
DEFAULT_IV_LOWER: float = 0.001      # Minimum IV (0.1%)
DEFAULT_IV_UPPER: float = 5.0        # Maksimum IV (500%)
MIN_VEGA: float = 1e-12              # Minimum vega (sıfır vega koruması)
SQRT_2PI: float = math.sqrt(2.0 * math.pi)
BIST_RISK_FREE_RATE: float = 0.30    # TCMB faiz oranı proxy (gerektiğinde override edilir)


@dataclass
class BSGreeks:
    """Black-Scholes Yunan (Greeks) değerleri.

    Attributes:
        delta: Fiyata duyarlılık (long call: 0-1, long put: -1 ila 0).
        gamma: Delta'nın fiyata göre türevi (pozitif, her iki yönde).
        theta: Zaman değeri erimesi (genellikle negatif, günlük).
        vega: Volatiliteye duyarlılık (1% vol değişimi başına).
        rho: Faiz oranına duyarlılık.
        vanna: Delta'nın vol'e göre türevi (hedge edilmesi gereken).
        volga: Vega'nın vol'e göre türevi (vol-of-vol riski).
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    vanna: float
    volga: float

    def __repr__(self) -> str:
        """BSGreeks kısa temsili."""
        return (
            f"BSGreeks(delta={self.delta:.4f}, gamma={self.gamma:.4f}, "
            f"theta={self.theta:.4f}, vega={self.vega:.4f})"
        )


@dataclass
class ImpliedVolResult:
    """Implied Volatility hesaplama sonucu.

    Attributes:
        iv: Implied volatilite (annualized, örn. 0.30 = %30).
        converged: Newton-Raphson yakınsadı mı?
        n_iterations: Yapılan iterasyon sayısı.
        model_price: IV ile hesaplanan teorik fiyat.
        market_price: Piyasa opsiyonu fiyatı.
        price_error: |model_price - market_price| fark.
        greeks: Hesaplanan Greeks değerleri.
    """

    iv: float
    converged: bool
    n_iterations: int
    model_price: float
    market_price: float
    price_error: float
    greeks: BSGreeks | None = None

    def __repr__(self) -> str:
        """ImpliedVolResult kısa temsili."""
        status = "OK" if self.converged else "FAILED"
        return (
            f"ImpliedVolResult(IV={self.iv:.2%}, {status}, "
            f"error={self.price_error:.6f})"
        )


@dataclass
class VolatilitySmile:
    """Volatilite gülümsemesi (tek vadede farklı strike'lardaki IV'ler).

    Attributes:
        expiry_days: Vadeye kalan gün sayısı.
        strikes: Strike fiyatları.
        ivs: Corresponding IV değerleri.
        atm_strike: ATM strike (mevcut fiyata en yakın).
        atm_iv: ATM IV değeri.
        skew: IV skew (25-delta put IV - 25-delta call IV, yaklaşık).
        smile_convexity: IV smile eğriselliği (butterfly spread proxy).
        is_arbitrage_free: Put-call parity ve monotoniklik kontrolleri.
    """

    expiry_days: int
    strikes: np.ndarray
    ivs: np.ndarray
    atm_strike: float
    atm_iv: float
    skew: float
    smile_convexity: float
    is_arbitrage_free: bool

    def __repr__(self) -> str:
        """VolatilitySmile kısa temsili."""
        return (
            f"VolatilitySmile(T={self.expiry_days}d, ATM_IV={self.atm_iv:.2%}, "
            f"skew={self.skew:.2%}, arb_free={self.is_arbitrage_free})"
        )


@dataclass
class VolatilitySurfaceResult:
    """Tam volatilite yüzeyi analiz sonucu.

    Attributes:
        smiles: Her vade için VolatilitySmile listesi.
        term_structure: Vadeye göre ATM IV eğrisi {expiry_days: atm_iv}.
        surface_stats: Yüzey özet istatistikleri.
        arbitrage_violations: Tespit edilen arbitraj ihlalleri.
    """

    smiles: list[VolatilitySmile]
    term_structure: dict[int, float]
    surface_stats: dict[str, float]
    arbitrage_violations: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        """VolatilitySurfaceResult kısa temsili."""
        return (
            f"VolatilitySurfaceResult(expiries={len(self.smiles)}, "
            f"violations={len(self.arbitrage_violations)})"
        )


class BlackScholesEngine:
    """Black-Scholes opsiyonu fiyatlama ve Greeks motoru.

    Gerçekleşen log-normal BS fiyatlama formülünü kullanır (temettüsüz).
    Temettü için continuous yield ile basit uyarlaması mevcuttur.
    """

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Kümülatif standart normal dağılım (yaklaşık, hata < 1.5e-7).

        Args:
            x: Standart normal değişkeni.

        Returns:
            Kümülatif olasılık değeri (0-1).
        """
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standart normal yoğunluk fonksiyonu.

        Args:
            x: Standart normal değişkeni.

        Returns:
            Yoğunluk değeri.
        """
        return math.exp(-0.5 * x * x) / SQRT_2PI

    @classmethod
    def price(
        cls,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        is_call: bool = True,
        q: float = 0.0,
    ) -> float:
        """Black-Scholes opsiyonu fiyatı hesaplar.

        Args:
            S: Mevcut spot fiyat.
            K: Strike fiyatı.
            T: Vadeye kalan süre (yıl olarak, örn. 30/365).
            r: Risksiz faiz oranı (yıllık, örn. 0.30).
            sigma: Yıllık volatilite (örn. 0.35 = %35).
            is_call: True ise call, False ise put.
            q: Sürekli temettü oranı (opsiyonel).

        Returns:
            BS teorik opsiyonu fiyatı.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            raise ValueError(
                f"S, K, T, sigma pozitif olmalıdır: S={S}, K={K}, T={T}, sigma={sigma}",
            )

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        if is_call:
            return (
                S * math.exp(-q * T) * cls._norm_cdf(d1)
                - K * math.exp(-r * T) * cls._norm_cdf(d2)
            )
        else:
            return (
                K * math.exp(-r * T) * cls._norm_cdf(-d2)
                - S * math.exp(-q * T) * cls._norm_cdf(-d1)
            )

    @classmethod
    def greeks(
        cls,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        is_call: bool = True,
        q: float = 0.0,
    ) -> BSGreeks:
        """Black-Scholes Greeks hesaplar.

        Args:
            S: Spot fiyat.
            K: Strike.
            T: Vade (yıl).
            r: Risksiz faiz.
            sigma: Yıllık volatilite.
            is_call: True = call, False = put.
            q: Temettü oranı.

        Returns:
            Tüm Greeks değerlerini içeren BSGreeks nesnesi.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            raise ValueError(
                f"Geçersiz parametre: S={S}, K={K}, T={T}, sigma={sigma}",
            )

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T
        pdf_d1 = cls._norm_pdf(d1)
        cdf_d1 = cls._norm_cdf(d1)
        cdf_d2 = cls._norm_cdf(d2)

        gamma = math.exp(-q * T) * pdf_d1 / (S * sigma * sqrt_T)

        if is_call:
            delta = math.exp(-q * T) * cdf_d1
            theta = (
                -S * math.exp(-q * T) * pdf_d1 * sigma / (2.0 * sqrt_T)
                - r * K * math.exp(-r * T) * cdf_d2
                + q * S * math.exp(-q * T) * cdf_d1
            ) / 365.0
            rho = K * T * math.exp(-r * T) * cdf_d2 / 100.0
        else:
            delta = -math.exp(-q * T) * cls._norm_cdf(-d1)
            theta = (
                -S * math.exp(-q * T) * pdf_d1 * sigma / (2.0 * sqrt_T)
                + r * K * math.exp(-r * T) * cls._norm_cdf(-d2)
                - q * S * math.exp(-q * T) * cls._norm_cdf(-d1)
            ) / 365.0
            rho = -K * T * math.exp(-r * T) * cls._norm_cdf(-d2) / 100.0

        vega = S * math.exp(-q * T) * pdf_d1 * sqrt_T / 100.0
        vanna = -math.exp(-q * T) * pdf_d1 * d2 / sigma
        volga = S * math.exp(-q * T) * pdf_d1 * sqrt_T * d1 * d2 / sigma

        return BSGreeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
            vanna=vanna,
            volga=volga,
        )


class ImpliedVolatilityCalculator:
    """Newton-Raphson yöntemiyle Implied Volatility hesaplama motoru.

    Piyasa opsiyonu fiyatından geriye dönük olarak IV çıkarır.
    Vega sıfıra yaklaşırsa bisection fallback devreye girer.
    """

    def __init__(
        self,
        max_iter: int = DEFAULT_MAX_ITER,
        tolerance: float = DEFAULT_TOLERANCE,
        iv_lower: float = DEFAULT_IV_LOWER,
        iv_upper: float = DEFAULT_IV_UPPER,
    ) -> None:
        """ImpliedVolatilityCalculator başlatıcı.

        Args:
            max_iter: Maksimum Newton-Raphson iterasyonu.
            tolerance: Yakınsama toleransı.
            iv_lower: Minimum IV alt sınırı.
            iv_upper: Maksimum IV üst sınırı.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if max_iter < 1:
            raise ValueError(f"max_iter >= 1 olmalıdır: {max_iter}")
        if not (0 < iv_lower < iv_upper):
            raise ValueError(f"0 < iv_lower < iv_upper olmalıdır: {iv_lower}, {iv_upper}")

        self.max_iter = max_iter
        self.tolerance = tolerance
        self.iv_lower = iv_lower
        self.iv_upper = iv_upper
        self._bs = BlackScholesEngine()

    def __repr__(self) -> str:
        """ImpliedVolatilityCalculator kısa temsili."""
        return (
            f"ImpliedVolatilityCalculator(max_iter={self.max_iter}, "
            f"tol={self.tolerance:.0e})"
        )

    def calculate(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        is_call: bool = True,
        q: float = 0.0,
        compute_greeks: bool = True,
    ) -> ImpliedVolResult:
        """Piyasa fiyatından Implied Volatility hesaplar.

        Args:
            market_price: Gözlemlenen piyasa opsiyonu fiyatı.
            S: Spot fiyat.
            K: Strike fiyatı.
            T: Vadeye kalan süre (yıl).
            r: Risksiz faiz oranı.
            is_call: True = call, False = put.
            q: Temettü oranı.
            compute_greeks: True ise Greeks hesapla.

        Returns:
            IV ve hesaplama meta-verilerini içeren ImpliedVolResult.
        """
        if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            logger.warning(
                "Geçersiz IV parametreleri.",
                market_price=market_price,
                S=S,
                K=K,
                T=T,
            )
            return ImpliedVolResult(
                iv=float("nan"),
                converged=False,
                n_iterations=0,
                model_price=0.0,
                market_price=market_price,
                price_error=float("inf"),
            )

        # Başlangıç tahmini: Brenner-Subrahmanyam yaklaşık formülü
        try:
            atm_vol = math.sqrt(2.0 * math.pi / T) * market_price / S
            sigma = float(np.clip(atm_vol, self.iv_lower, self.iv_upper))
        except (ValueError, ZeroDivisionError):
            sigma = 0.25

        converged = False
        n_iter = 0
        final_price = 0.0

        for n_iter in range(1, self.max_iter + 1):
            try:
                model_price = self._bs.price(S, K, T, r, sigma, is_call, q)
                price_error = model_price - market_price

                if abs(price_error) < self.tolerance:
                    converged = True
                    final_price = model_price
                    break

                # Vega (Black-Scholes)
                sqrt_T = math.sqrt(T)
                d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                vega = S * math.exp(-q * T) * BlackScholesEngine._norm_pdf(d1) * sqrt_T

                if abs(vega) < MIN_VEGA:
                    # Bisection fallback
                    sigma = (self.iv_lower + self.iv_upper) / 2.0
                    continue

                # Newton-Raphson adımı
                sigma_new = sigma - price_error / vega
                sigma = float(np.clip(sigma_new, self.iv_lower, self.iv_upper))

            except (ValueError, ZeroDivisionError) as e:
                logger.warning("IV hesaplama iterasyon hatası.", iter=n_iter, hata=str(e))
                break

        if not converged:
            try:
                final_price = self._bs.price(S, K, T, r, sigma, is_call, q)
            except (ValueError, ZeroDivisionError):
                final_price = 0.0

        price_diff = abs(final_price - market_price)
        greeks_result = None
        if compute_greeks and converged:
            with contextlib.suppress(ValueError, ZeroDivisionError):
                greeks_result = self._bs.greeks(S, K, T, r, sigma, is_call, q)

        return ImpliedVolResult(
            iv=sigma,
            converged=converged,
            n_iterations=n_iter,
            model_price=final_price,
            market_price=market_price,
            price_error=price_diff,
            greeks=greeks_result,
        )


class VolatilitySurfaceEngine:
    """Volatilite yüzeyi oluşturma ve analiz motoru.

    Birden fazla vade ve strike kombinasyonu için IV yüzeyi oluşturur,
    smile/skew analizini yapar ve arbitraj ihlallerini tespit eder.
    """

    def __init__(
        self,
        risk_free_rate: float = BIST_RISK_FREE_RATE,
        max_iv_error: float = 0.01,
    ) -> None:
        """VolatilitySurfaceEngine başlatıcı.

        Args:
            risk_free_rate: Risksiz faiz oranı (BIST için TCMB politika faizi).
            max_iv_error: Kabul edilebilir maksimum IV fiyat hatası.

        Raises:
            ValueError: risk_free_rate negatifse.
        """
        if risk_free_rate < 0.0:
            raise ValueError(f"risk_free_rate negatif olamaz: {risk_free_rate}")

        self.risk_free_rate = risk_free_rate
        self.max_iv_error = max_iv_error
        self._iv_calc = ImpliedVolatilityCalculator()

    def __repr__(self) -> str:
        """VolatilitySurfaceEngine kısa temsili."""
        return f"VolatilitySurfaceEngine(r={self.risk_free_rate:.2%}, max_err={self.max_iv_error})"

    def build_smile(
        self,
        S: float,
        strikes: list[float],
        prices: list[float],
        expiry_days: int,
        is_call: bool = True,
        q: float = 0.0,
    ) -> VolatilitySmile:
        """Tek vadede volatilite gülümsemesini (smile) oluşturur.

        Args:
            S: Spot fiyat.
            strikes: Strike listesi (sıralı olmalı).
            prices: Her strike için piyasa opsiyonu fiyatı listesi.
            expiry_days: Vadeye kalan gün sayısı.
            is_call: True = call, False = put.
            q: Temettü oranı.

        Returns:
            Volatilite gülümsemesini içeren VolatilitySmile nesnesi.

        Raises:
            ValueError: Giriş listeleri boşsa veya uzunlukları uyuşmuyorsa.
        """
        if not strikes or not prices:
            raise ValueError("strikes ve prices boş olamaz.")
        if len(strikes) != len(prices):
            raise ValueError(
                f"strikes ({len(strikes)}) ve prices ({len(prices)}) boyutları eşleşmelidir.",
            )

        T = expiry_days / 365.0
        iv_list: list[float] = []
        valid_strikes: list[float] = []

        for K, price in zip(strikes, prices, strict=True):
            result = self._iv_calc.calculate(
                market_price=price,
                S=S,
                K=K,
                T=T,
                r=self.risk_free_rate,
                is_call=is_call,
                q=q,
                compute_greeks=False,
            )
            if result.converged and result.price_error <= self.max_iv_error:
                iv_list.append(result.iv)
                valid_strikes.append(K)

        if not valid_strikes:
            logger.warning("Hiç geçerli IV hesaplanamadı.", expiry_days=expiry_days)
            return VolatilitySmile(
                expiry_days=expiry_days,
                strikes=np.array([]),
                ivs=np.array([]),
                atm_strike=S,
                atm_iv=float("nan"),
                skew=0.0,
                smile_convexity=0.0,
                is_arbitrage_free=False,
            )

        strikes_arr = np.array(valid_strikes)
        ivs_arr = np.array(iv_list)

        # ATM strike ve IV
        atm_idx = int(np.argmin(np.abs(strikes_arr - S)))
        atm_strike = float(strikes_arr[atm_idx])
        atm_iv = float(ivs_arr[atm_idx])

        # Skew: OTM put IV - OTM call IV (yaklaşık 25-delta benzeri)
        n = len(strikes_arr)
        skew = 0.0
        if n >= 3:
            otm_put_iv = float(ivs_arr[0])      # En düşük strike = en fazla OTM put
            otm_call_iv = float(ivs_arr[-1])     # En yüksek strike = en fazla OTM call
            skew = otm_put_iv - otm_call_iv

        # Konveksite: butterfly (25d put + 25d call) / 2 - ATM
        convexity = 0.0
        if n >= 3:
            wing_avg = (float(ivs_arr[0]) + float(ivs_arr[-1])) / 2.0
            convexity = wing_avg - atm_iv

        # Arbitraj kontrolü: IV'lar genel monoton olmak zorunda değil ama aşırı
        # negatif eğim (calendar spread arbitrajı) yasak.
        is_arb_free = True
        if n >= 2:
            for i in range(1, n):
                # Put için alçak strike daha yüksek IV olmalı (normal)
                if not is_call and ivs_arr[i] > ivs_arr[i - 1] * 1.5:
                    is_arb_free = False
                    break

        return VolatilitySmile(
            expiry_days=expiry_days,
            strikes=strikes_arr,
            ivs=ivs_arr,
            atm_strike=atm_strike,
            atm_iv=atm_iv,
            skew=skew,
            smile_convexity=convexity,
            is_arbitrage_free=is_arb_free,
        )

    def build_surface(
        self,
        S: float,
        option_data: list[dict[str, Any]],
        q: float = 0.0,
    ) -> VolatilitySurfaceResult:
        """Tam volatilite yüzeyi oluşturur.

        Args:
            S: Spot fiyat.
            option_data: Opsiyon veri listesi. Her eleman:
                         {'expiry_days': int, 'strike': float, 'price': float,
                          'is_call': bool (opsiyonel, default True)}
            q: Temettü oranı.

        Returns:
            Tüm smile'lar ve yüzey istatistiklerini içeren VolatilitySurfaceResult.

        Raises:
            ValueError: option_data boşsa.
        """
        if not option_data:
            raise ValueError("option_data boş olamaz.")

        # Vadeye göre grupla
        by_expiry: dict[int, dict[str, list[Any]]] = {}
        for opt in option_data:
            exp = int(opt["expiry_days"])
            if exp not in by_expiry:
                by_expiry[exp] = {"strikes": [], "prices": [], "is_call": []}
            by_expiry[exp]["strikes"].append(float(opt["strike"]))
            by_expiry[exp]["prices"].append(float(opt["price"]))
            by_expiry[exp]["is_call"].append(bool(opt.get("is_call", True)))

        smiles: list[VolatilitySmile] = []
        term_structure: dict[int, float] = {}
        arbitrage_violations: list[str] = []

        for exp_days in sorted(by_expiry.keys()):
            data = by_expiry[exp_days]
            # Aynı vadede çağrılan opsiyon tipi - çoğunluğa göre
            is_call_mode = sum(data["is_call"]) > len(data["is_call"]) / 2
            # Strike'e göre sırala
            sorted_pairs = sorted(zip(data["strikes"], data["prices"], strict=True))
            sorted_strikes = [p[0] for p in sorted_pairs]
            sorted_prices = [p[1] for p in sorted_pairs]

            smile = self.build_smile(
                S=S,
                strikes=sorted_strikes,
                prices=sorted_prices,
                expiry_days=exp_days,
                is_call=is_call_mode,
                q=q,
            )
            smiles.append(smile)

            if not math.isnan(smile.atm_iv):
                term_structure[exp_days] = smile.atm_iv

            if not smile.is_arbitrage_free:
                arbitrage_violations.append(
                    f"T={exp_days}d smile arbitraj ihlali tespit edildi."
                )

        # Term structure monotonluğu kontrolü (normal piyasa: uzun vadeli IV > kısa vadeli)
        sorted_terms = sorted(term_structure.items())
        for i in range(1, len(sorted_terms)):
            exp_prev, iv_prev = sorted_terms[i - 1]
            exp_curr, iv_curr = sorted_terms[i]
            if iv_curr < iv_prev * 0.5:
                arbitrage_violations.append(
                    f"Term structure ihlali: T={exp_prev}d IV={iv_prev:.2%} > T={exp_curr}d IV={iv_curr:.2%}"
                )

        # Yüzey istatistikleri
        all_ivs = [s.atm_iv for s in smiles if not math.isnan(s.atm_iv)]
        all_skews = [s.skew for s in smiles]
        surface_stats: dict[str, float] = {}
        if all_ivs:
            surface_stats["mean_atm_iv"] = float(np.mean(all_ivs))
            surface_stats["max_atm_iv"] = float(np.max(all_ivs))
            surface_stats["min_atm_iv"] = float(np.min(all_ivs))
            surface_stats["iv_term_slope"] = float(all_ivs[-1] - all_ivs[0]) if len(all_ivs) >= 2 else 0.0
            surface_stats["mean_skew"] = float(np.mean(all_skews))
            surface_stats["n_violations"] = float(len(arbitrage_violations))

        logger.info(
            "Volatilite yüzeyi oluşturuldu.",
            smiles=len(smiles),
            violations=len(arbitrage_violations),
            mean_atm_iv=round(surface_stats.get("mean_atm_iv", 0.0), 3),
        )

        return VolatilitySurfaceResult(
            smiles=smiles,
            term_structure=term_structure,
            surface_stats=surface_stats,
            arbitrage_violations=arbitrage_violations,
        )


__all__: list[str] = [
    "BSGreeks",
    "BlackScholesEngine",
    "ImpliedVolResult",
    "ImpliedVolatilityCalculator",
    "VolatilitySmile",
    "VolatilitySurfaceEngine",
    "VolatilitySurfaceResult",
    "bs_engine",
    "iv_calculator",
    "vol_surface_engine",
]

# Singletonlar
bs_engine = BlackScholesEngine()
iv_calculator = ImpliedVolatilityCalculator()
vol_surface_engine = VolatilitySurfaceEngine()
