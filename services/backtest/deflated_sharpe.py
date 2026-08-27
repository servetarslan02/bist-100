"""
ALPHA BIST — Deflated Sharpe Ratio & Multiple Testing Correction

Birden fazla strateji test ettiğinizde, şans eseri yüksek Sharpe çıkabilir.
Deflated Sharpe bu düzeltmeyi yapar.

Referanslar:
- "The Deflated Sharpe Ratio" (Bailey & López de Prado, 2014)
- BACKTEST-NIHAI-SPEC.md - Section 6
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from scipy import stats

logger = structlog.get_logger()


@dataclass
class DeflatedSharpeResult:
    """Deflated Sharpe sonucu."""
    observed_sharpe: float
    expected_max_sharpe: float
    std_max_sharpe: float
    deflated_sharpe: float
    num_strategies_tested: int
    num_observations: int
    skewness: float
    kurtosis: float
    p_value: float
    is_significant: bool  # p < 0.05
    confidence_level: str  # high | medium | low | not_significant

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_sharpe": round(self.observed_sharpe, 4),
            "expected_max_sharpe": round(self.expected_max_sharpe, 4),
            "std_max_sharpe": round(self.std_max_sharpe, 4),
            "deflated_sharpe": round(self.deflated_sharpe, 4),
            "num_strategies_tested": self.num_strategies_tested,
            "num_observations": self.num_observations,
            "skewness": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
            "p_value": round(self.p_value, 6),
            "is_significant": self.is_significant,
            "confidence_level": self.confidence_level,
        }


class DeflatedSharpeCalculator:
    """
    Deflated Sharpe Ratio hesaplayıcı.

    Multiple testing düzlemesini uygular:
    - N strateji test ettiyseniz
    - En iyisinin Sharpe'sı SR ise
    - Deflated Sharpe, SR'ın "gerçek" istatistiksel anlamlılığını verir
    """

    @staticmethod
    def compute_expected_max_sharpe(
        num_strategies: int,
        num_observations: int,
        skewness: float = 0.0,
        kurtosis: float = 3.0,
        periods_per_year: int = 1,
    ) -> tuple[float, float]:
        """
        N stratejiden beklenen max Sharpe'ı hesapla.

        Args:
            num_strategies: Test edilen strateji sayısı
            num_observations: Gözlem sayısı (trading days)
            skewness: Getiri dağılımının çarpıklığı
            kurtosis: Getiri dağılımının basıklığı
            periods_per_year: observed_sharpe'ın yıllıklaştırma çarpanı
                (örn. günlük veri için 252). observed_sharpe yıllıklaştırılmış
                geliyorsa (per_period_SR * sqrt(periods_per_year)), bu
                fonksiyonun döndürdüğü expected_max_sr/std_max_sr de AYNI
                birimde olmalı — aksi halde deflated_sharpe birim
                uyuşmazlığından dolayı ~periods_per_year kat şişer/küçülür.
                Varsayılan 1 = per-period (yıllıklaştırılmamış) birim.

        Returns:
            (expected_max_sharpe, std_max_sharpe)
        """
        # Euler-Mascheroni sabiti
        euler_mascheroni = 0.5772156649

        # Standart normal'in N gözleminin max'ının beklenen değeri.
        # Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio",
        # Denklem 5-6: E[max Z_1..Z_N] ≈ (1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e))
        # (Önceki sqrt(2·ln(N)) yaklaşımı Monte Carlo ile doğrulandığında
        # sistematik olarak ~0.13-0.2 düşük çıkıyordu — bu da deflated_sr'ı
        # olduğundan yüksek gösterip DSR'ın asıl amacı olan 'çoklu-test/
        # şans eseri iyi görünen stratejileri eleme' işlevini zayıflatıyordu.)
        if num_strategies <= 1:
            return 0.0, 1.0

        from scipy.stats import norm as _norm
        n = num_strategies
        expected_max_z = (
            (1 - euler_mascheroni) * _norm.ppf(1 - 1.0 / n)
            + euler_mascheroni * _norm.ppf(1 - 1.0 / (n * np.e))
        )

        # Sharpe'a dönüştür (sqrt(T) ile ölçekle, periods_per_year ile
        # observed_sharpe'la AYNI birime getir)
        annualization = np.sqrt(periods_per_year)
        sqrt_t = np.sqrt(num_observations)
        expected_max_sr = expected_max_z * annualization / sqrt_t

        # Standart sapma
        std_max_sr = annualization / sqrt_t

        # Higher-order moments düzeltmesi
        if skewness != 0 or kurtosis != 3.0:
            # Cornish-Fisher expansion
            skew_adj = skewness / 6 * (expected_max_z**2 - 1)
            kurt_adj = (kurtosis - 3) / 24 * (expected_max_z**3 - 3 * expected_max_z)
            expected_max_sr += (skew_adj + kurt_adj) * annualization / sqrt_t

        return expected_max_sr, std_max_sr

    @staticmethod
    def compute_deflated_sharpe(
        observed_sharpe: float,
        num_strategies: int,
        num_observations: int,
        skewness: float = 0.0,
        kurtosis: float = 3.0,
        periods_per_year: int = 1,
    ) -> DeflatedSharpeResult:
        """
        Deflated Sharpe Ratio hesapla.

        Args:
            observed_sharpe: Gözlemlenen Sharpe
            num_strategies: Test edilen strateji sayısı
            num_observations: Gözlem sayısı
            skewness: Getiri çarpıklığı
            kurtosis: Getiri basıklığı
            periods_per_year: observed_sharpe yıllıklaştırılmışsa (örn.
                günlük veriden sqrt(252) ile ölçeklenmişse) buraya 252
                verilmeli — aksi halde expected_max_sr/std_max_sr farklı
                birimde hesaplanır ve deflated_sharpe ~periods_per_year
                kat şişer/küçülür. observed_sharpe zaten per-period ise
                varsayılan 1 kullanılır.

        Returns:
            DeflatedSharpeResult
        """
        expected_max_sr, std_max_sr = DeflatedSharpeCalculator.compute_expected_max_sharpe(
            num_strategies, num_observations, skewness, kurtosis, periods_per_year
        )

        # Deflated Sharpe = (SR - E[max_SR]) / Std[max_SR]
        deflated_sr = (observed_sharpe - expected_max_sr) / std_max_sr if std_max_sr > 0 else 0.0

        # p-value (one-tailed test)
        p_value = 1 - stats.norm.cdf(deflated_sr)

        # Confidence level
        if p_value < 0.01:
            confidence = "high"
        elif p_value < 0.05:
            confidence = "medium"
        elif p_value < 0.10:
            confidence = "low"
        else:
            confidence = "not_significant"

        result = DeflatedSharpeResult(
            observed_sharpe=observed_sharpe,
            expected_max_sharpe=expected_max_sr,
            std_max_sharpe=std_max_sr,
            deflated_sharpe=deflated_sr,
            num_strategies_tested=num_strategies,
            num_observations=num_observations,
            skewness=skewness,
            kurtosis=kurtosis,
            p_value=p_value,
            is_significant=p_value < 0.05,
            confidence_level=confidence,
        )

        logger.info("Deflated Sharpe computed",
                    observed=round(observed_sharpe, 3),
                    deflated=round(deflated_sr, 3),
                    p_value=round(p_value, 4),
                    confidence=confidence)

        return result

    @staticmethod
    def from_returns(
        returns: np.ndarray,
        num_strategies: int = 1,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ) -> DeflatedSharpeResult:
        """
        Getiri serisinden doğrudan Deflated Sharpe hesapla.

        Args:
            returns: Getiri serisi
            num_strategies: Test edilen strateji sayısı
            risk_free_rate: Risksiz faiz oranı (yıllık)
            periods_per_year: Yıllık periyot sayısı

        Returns:
            DeflatedSharpeResult
        """
        if len(returns) < 2:
            return DeflatedSharpeResult(
                observed_sharpe=0, expected_max_sharpe=0, std_max_sharpe=1,
                deflated_sharpe=0, num_strategies_tested=num_strategies,
                num_observations=len(returns), skewness=0, kurtosis=3,
                p_value=1, is_significant=False, confidence_level="not_significant",
            )

        # Annualized Sharpe
        daily_rf = risk_free_rate / periods_per_year
        excess_returns = returns - daily_rf
        mean_excess = np.mean(excess_returns)
        std_excess = np.std(excess_returns, ddof=1)

        observed_sharpe = (mean_excess / std_excess * np.sqrt(periods_per_year)) if std_excess > 0 else 0

        # Moments
        skewness = float(stats.skew(returns))
        kurtosis = float(stats.kurtosis(returns, fisher=False))  # Excess kurtosis + 3

        return DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=observed_sharpe,
            num_strategies=num_strategies,
            num_observations=len(returns),
            skewness=skewness,
            kurtosis=kurtosis,
            periods_per_year=periods_per_year,
        )


class ProbabilisticSharpeRatio:
    """
    Probabilistic Sharpe Ratio (PSR).

    Sharpe'ın istatistiksel olarak sıfırdan farklı olma olasılığını hesaplar.
    """

    @staticmethod
    def compute(
        observed_sharpe: float,
        benchmark_sharpe: float,
        num_observations: int,
        skewness: float = 0.0,
        kurtosis: float = 3.0,
    ) -> float:
        """
        PSR hesapla: P(SR > benchmark_SR).

        Args:
            observed_sharpe: Gözlemlenen Sharpe
            benchmark_sharpe: Karşılaştırma Sharpe'ı (genellikle 0)
            num_observations: Gözlem sayısı
            skewness: Çarpıklık
            kurtosis: Basıklık

        Returns:
            PSR olasılığı (0-1)
        """
        if num_observations < 2:
            return 0.0

        # Sharpe'ın standart hatası
        sr_std = np.sqrt(
            (1 - skewness * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2)
            / (num_observations - 1)
        )

        if sr_std <= 0:
            return 0.0

        # Z skoru
        z = (observed_sharpe - benchmark_sharpe) / sr_std

        # PSR = Φ(z)
        psr = stats.norm.cdf(z)

        return float(psr)

    @staticmethod
    def from_returns(
        returns: np.ndarray,
        benchmark_sharpe: float = 0.0,
        periods_per_year: int = 252,
    ) -> dict[str, Any]:
        """Getiri serisinden PSR hesapla."""
        if len(returns) < 2:
            return {"psr": 0.0, "observed_sharpe": 0.0}

        mean_ret = np.mean(returns)
        std_ret = np.std(returns, ddof=1)
        observed_sharpe = (mean_ret / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0

        skewness = float(stats.skew(returns))
        kurtosis = float(stats.kurtosis(returns, fisher=False))

        psr = ProbabilisticSharpeRatio.compute(
            observed_sharpe, benchmark_sharpe, len(returns), skewness, kurtosis
        )

        return {
            "psr": round(psr, 4),
            "observed_sharpe": round(observed_sharpe, 4),
            "benchmark_sharpe": benchmark_sharpe,
            "skewness": round(skewness, 4),
            "kurtosis": round(kurtosis, 4),
            "observations": len(returns),
        }


# Singleton
deflated_sharpe = DeflatedSharpeCalculator()
probabilistic_sharpe = ProbabilisticSharpeRatio()
