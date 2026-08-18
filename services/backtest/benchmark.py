"""
ALPHA BIST — Benchmark Comparison Module

Strateji performansını benchmark (BIST 100, XU030 vb.) ile karşılaştırır.

Metrikler:
1. Alpha (Jensen's alpha)
2. Beta (piyasa duyarlılığı)
3. Information Ratio
4. Tracking Error
5. Relative Return
6. Up/Down Capture Ratio
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class BenchmarkComparison:
    """Benchmark karşılaştırma sonucu."""
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

    def to_dict(self) -> Dict[str, Any]:
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

    @staticmethod
    def compare(
        strategy_returns: np.ndarray,
        benchmark_returns: np.ndarray,
        benchmark_name: str = "BIST100",
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ) -> BenchmarkComparison:
        """
        Strateji ve benchmark getirilerini karşılaştır.

        Args:
            strategy_returns: Strateji getiri serisi
            benchmark_returns: Benchmark getiri serisi
            benchmark_name: Benchmark adı
            risk_free_rate: Risksiz faiz (yıllık)
            periods_per_year: Yıllık periyot

        Returns:
            BenchmarkComparison
        """
        # Align lengths
        min_len = min(len(strategy_returns), len(benchmark_returns))
        sr = strategy_returns[:min_len]
        br = benchmark_returns[:min_len]

        if min_len < 2:
            return BenchmarkComparison(
                benchmark_name=benchmark_name,
                strategy_return_pct=0, benchmark_return_pct=0,
                alpha_pct=0, beta=1, information_ratio=0,
                tracking_error_pct=0, relative_return_pct=0,
                up_capture_ratio=0, down_capture_ratio=0,
                correlation=0, r_squared=0, num_observations=0,
            )

        # Total returns
        strategy_total = (np.prod(1 + sr) - 1) * 100
        benchmark_total = (np.prod(1 + br) - 1) * 100

        # Annualized returns
        years = min_len / periods_per_year
        strategy_annual = ((1 + strategy_total / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
        benchmark_annual = ((1 + benchmark_total / 100) ** (1 / years) - 1) * 100 if years > 0 else 0

        # Daily risk-free
        daily_rf = risk_free_rate / periods_per_year

        # Alpha and Beta (CAPM)
        excess_sr = sr - daily_rf
        excess_br = br - daily_rf

        cov_matrix = np.cov(excess_sr, excess_br)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 1.0
        alpha = (np.mean(excess_sr) - beta * np.mean(excess_br)) * periods_per_year * 100

        # Correlation and R-squared
        correlation = np.corrcoef(sr, br)[0, 1]
        r_squared = correlation ** 2

        # Tracking error
        active_returns = sr - br
        tracking_error = np.std(active_returns, ddof=1) * np.sqrt(periods_per_year) * 100

        # Information ratio
        information_ratio = (
            (np.mean(active_returns) / np.std(active_returns, ddof=1) * np.sqrt(periods_per_year))
            if np.std(active_returns, ddof=1) > 0 else 0
        )

        # Relative return
        relative_return = strategy_total - benchmark_total

        # Up/Down capture ratio
        up_days = br > 0
        down_days = br < 0

        if up_days.sum() > 0:
            up_capture = np.mean(sr[up_days]) / np.mean(br[up_days]) * 100 if np.mean(br[up_days]) > 0 else 0
        else:
            up_capture = 0

        if down_days.sum() > 0:
            down_capture = np.mean(sr[down_days]) / np.mean(br[down_days]) * 100 if np.mean(br[down_days]) != 0 else 0
        else:
            down_capture = 0

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

        logger.info("Benchmark comparison complete",
                    benchmark=benchmark_name,
                    alpha=f"{alpha:.2f}%",
                    beta=f"{beta:.2f}",
                    info_ratio=f"{information_ratio:.2f}")

        return result

    @staticmethod
    def from_equity_curves(
        strategy_equity: List[Tuple[str, float]],
        benchmark_equity: List[Tuple[str, float]],
        benchmark_name: str = "BIST100",
    ) -> BenchmarkComparison:
        """Equity curve'lerden karşılaştırma yap."""
        # Convert to returns
        strategy_values = [e[1] for e in strategy_equity]
        benchmark_values = [e[1] for e in benchmark_equity]

        strategy_returns = np.diff(strategy_values) / strategy_values[:-1]
        benchmark_returns = np.diff(benchmark_values) / benchmark_values[:-1]

        return BenchmarkComparator.compare(
            strategy_returns, benchmark_returns, benchmark_name
        )

    @staticmethod
    def generate_report(
        comparisons: List[BenchmarkComparison],
    ) -> Dict[str, Any]:
        """Çoklu benchmark karşılaştırma raporu."""
        if not comparisons:
            return {"error": "No comparisons provided"}

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
                "avg_correlation": round(
                    np.mean([c.correlation for c in comparisons]), 4
                ),
            },
        }


# Singleton
benchmark_comparator = BenchmarkComparator()
