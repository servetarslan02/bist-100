"""
ALPHA BIST — Benchmark Karşılaştırma Modülü

Strateji performansını benchmark (BIST 100, XU030 vb.) ile karşılaştırır.

Hesaplanan metrikler:
1. Alpha (Jensen's alpha) — stratejinin piyasaya göre fazla getirisi
2. Beta — piyasa duyarlılığı
3. Information Ratio — aktif getirinin izleme hatasına oranı
4. Tracking Error — aktif getirilerin standart sapması
5. Relative Return — strateji ile benchmark arasındaki getiri farkı
6. Up/Down Capture Ratio — piyasa yükseliş/düşüşlerinde yakalama oranı
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_BENCHMARK_NAME: str = "BIST100"
DEFAULT_PERIODS_PER_YEAR: int = 252
DEFAULT_RISK_FREE_RATE: float = 0.0
PERCENT_MULTIPLIER: float = 100.0


@dataclass
class BenchmarkComparison:
    """Benchmark karşılaştırma sonucu.

    Strateji ile benchmark arasındaki tüm performans metriklerini
    tek bir veri yapısında tutar.
    """

    benchmark_name: str
    strategy_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float
    beta: float
    information_ratio: float
    tracking_error_pct: float
    relative_return_pct: float
    up_capture_ratio: float
    down_capture_ratio: float
    correlation: float
    r_squared: float
    num_observations: int

    def __repr__(self) -> str:
        """BenchmarkComparison okunabilir temsili."""
        return (
            f"BenchmarkComparison("
            f"benchmark={self.benchmark_name!r}, "
            f"alpha={self.alpha_pct:.2f}%, "
            f"beta={self.beta:.4f}, "
            f"ir={self.information_ratio:.4f}, "
            f"n={self.num_observations})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sonucu sözlük formatında döndürür.

        Returns:
            Metriklerin yuvarlanmış değerlerini içeren sözlük
        """
        return {
            "benchmark": self.benchmark_name,
            "strategy_return_pct": round(self.strategy_return_pct, 2),
            "benchmark_return_pct": round(self.benchmark_return_pct, 2),
            "alpha_pct": round(self.alpha_pct, 4),
            "beta": round(self.beta, 4),
            "information_ratio": round(self.information_ratio, 4),
            "tracking_error_pct": round(self.tracking_error_pct, 4),
            "relative_return_pct": round(self.relative_return_pct, 2),
            "up_capture_ratio": round(self.up_capture_ratio, 2),
            "down_capture_ratio": round(self.down_capture_ratio, 2),
            "correlation": round(self.correlation, 4),
            "r_squared": round(self.r_squared, 4),
            "num_observations": self.num_observations,
        }


class BenchmarkComparator:
    """
    Benchmark karşılaştırma motoru.

    Strateji getirilerini benchmark ile karşılaştırır
    ve risk-ayarlı performans metrikleri hesaplar.
    """

    def __repr__(self) -> str:
        """BenchmarkComparator okunabilir temsili."""
        return f"BenchmarkComparator(default_benchmark={DEFAULT_BENCHMARK_NAME}, periods={DEFAULT_PERIODS_PER_YEAR})"

    @staticmethod
    def compare(
        strategy_returns: np.ndarray,
        benchmark_returns: np.ndarray,
        benchmark_name: str = DEFAULT_BENCHMARK_NAME,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
    ) -> BenchmarkComparison:
        """
        Strateji ve benchmark getirilerini karşılaştır.

        Args:
            strategy_returns: Strateji getiri serisi (günlük ondalık)
            benchmark_returns: Benchmark getiri serisi (günlük ondalık)
            benchmark_name: Benchmark adı
            risk_free_rate: Risksiz faiz (yıllık)
            periods_per_year: Yıllık periyot (default: 252 iş günü)

        Returns:
            BenchmarkComparison nesnesi

        Raises:
            ValueError: Getiri serileri boşsa veya tek gözlem içeriyorsa
        """
        # Girdi doğrulama
        if len(strategy_returns) == 0 or len(benchmark_returns) == 0:
            raise ValueError("Getiri serileri boş olamaz")

        # Uzunlukları hizala
        min_len = min(len(strategy_returns), len(benchmark_returns))
        sr = strategy_returns[:min_len]
        br = benchmark_returns[:min_len]

        if min_len < 2:
            raise ValueError(
                f"Karşılaştırma için en az 2 gözlem gerekli, {min_len} sağlandı"
            )

        # Toplam getiriler
        strategy_total = (np.prod(1 + sr) - 1) * 100
        benchmark_total = (np.prod(1 + br) - 1) * 100

        # Günlük risksiz faiz
        daily_rf = risk_free_rate / periods_per_year

        # Alpha ve Beta (CAPM)
        excess_sr = sr - daily_rf
        excess_br = br - daily_rf

        cov_matrix = np.cov(excess_sr, excess_br)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 1.0
        alpha = (np.mean(excess_sr) - beta * np.mean(excess_br)) * periods_per_year * 100

        # Korelasyon ve R-kare
        corr_matrix = np.corrcoef(sr, br)
        correlation = corr_matrix[0, 1]
        # Sabit dizi durumunda NaN oluşabilir
        if np.isnan(correlation):
            correlation = 0.0
        r_squared = correlation**2

        # İzleme hatası
        active_returns = sr - br
        tracking_error = np.std(active_returns, ddof=1) * np.sqrt(periods_per_year) * 100

        # Bilgi oranı
        active_std = np.std(active_returns, ddof=1)
        information_ratio = (
            (np.mean(active_returns) / active_std * np.sqrt(periods_per_year))
            if active_std > 0
            else 0.0
        )

        # Göreceli getiri
        relative_return = strategy_total - benchmark_total

        # Yukarı yakalama: benchmark pozitifken strateji/benchmark oranı
        up_days = br > 0
        down_days = br < 0
        up_mean_br = np.mean(br[up_days]) if up_days.sum() > 0 else 0.0
        up_mean_sr = np.mean(sr[up_days]) if up_days.sum() > 0 else 0.0
        up_capture = (
            (up_mean_sr / up_mean_br * 100)
            if up_mean_br > 0
            else 0.0
        )

        down_mean_br = np.mean(br[down_days]) if down_days.sum() > 0 else 0.0
        down_mean_sr = np.mean(sr[down_days]) if down_days.sum() > 0 else 0.0
        down_capture = (
            (down_mean_sr / down_mean_br * 100)
            if down_mean_br != 0
            else 0.0
        )

        result = BenchmarkComparison(
            benchmark_name=benchmark_name,
            strategy_return_pct=strategy_total,
            benchmark_return_pct=benchmark_total,
            alpha_pct=alpha,
            beta=beta,
            information_ratio=information_ratio,
            tracking_error_pct=tracking_error,
            relative_return_pct=relative_return,
            up_capture_ratio=up_capture,
            down_capture_ratio=down_capture,
            correlation=correlation,
            r_squared=r_squared,
            num_observations=min_len,
        )

        logger.info("benchmark_karsilastirma: benchmark=%s, alpha=%s%%, beta=%s, ir=%s", benchmark_name, f"{alpha:.2f}", f"{beta:.2f}", f"{information_ratio:.2f}")

        return result

    @staticmethod
    def from_equity_curves(
        strategy_equity: list[tuple[str, float]],
        benchmark_equity: list[tuple[str, float]],
        benchmark_name: str = "BIST100",
    ) -> BenchmarkComparison:
        """
        Equity curve'lerden karşılaştırma yapar.

        Args:
            strategy_equity: [(tarih, değer), ...] formatında strateji equity serisi
            benchmark_equity: [(tarih, değer), ...] formatında benchmark equity serisi
            benchmark_name: Benchmark adı

        Returns:
            BenchmarkComparison nesnesi

        Raises:
            ValueError: Equity serileri yetersiz veri içeriyorsa
        """
        if len(strategy_equity) < 2 or len(benchmark_equity) < 2:
            raise ValueError("Equity curve en az 2 veri noktası içermeli")

        strategy_values = np.array([e[1] for e in strategy_equity], dtype=np.float64)
        benchmark_values = np.array([e[1] for e in benchmark_equity], dtype=np.float64)

        # Sıfır değerde bölünme kontrolü
        strategy_denom = strategy_values[:-1]
        benchmark_denom = benchmark_values[:-1]

        if np.any(strategy_denom == 0) or np.any(benchmark_denom == 0):
            raise ValueError("Equity curve değerleri sıfır olamaz (bölünme hatası)")

        strategy_returns = np.diff(strategy_values) / strategy_denom
        benchmark_returns = np.diff(benchmark_values) / benchmark_denom

        return BenchmarkComparator.compare(strategy_returns, benchmark_returns, benchmark_name)

    @staticmethod
    def generate_report(
        comparisons: list[BenchmarkComparison],
    ) -> dict[str, Any]:
        """
        Çoklu benchmark karşılaştırma raporu oluşturur.

        Args:
            comparisons: BenchmarkComparison nesneleri listesi

        Returns:
            Rapor sözlüğü: her benchmark'ın metrikleri + özet istatistikler
        """
        if not comparisons:
            return {"error": "Karşılaştırma sağlanmadı"}

        best_alpha = max(comparisons, key=lambda c: c.alpha_pct)
        best_ir = max(comparisons, key=lambda c: c.information_ratio)

        return {
            "benchmarks": [c.to_dict() for c in comparisons],
            "summary": {
                "best_alpha": {
                    "benchmark": best_alpha.benchmark_name,
                    "alpha_pct": round(best_alpha.alpha_pct, 2),
                },
                "best_information_ratio": {
                    "benchmark": best_ir.benchmark_name,
                    "ir": round(best_ir.information_ratio, 2),
                },
                "avg_correlation": round(np.mean([c.correlation for c in comparisons]), 4),
            },
        }


# Singleton
benchmark_comparator = BenchmarkComparator()

__all__ = [
    "BenchmarkComparison",
    "BenchmarkComparator",
    "benchmark_comparator",
    "DEFAULT_BENCHMARK_NAME",
    "DEFAULT_PERIODS_PER_YEAR",
    "DEFAULT_RISK_FREE_RATE",
    "PERCENT_MULTIPLIER",
]
