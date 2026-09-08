"""
ALPHA BIST — Benchmark Comparator Comprehensive Test Suite

BenchmarkComparison, BenchmarkComparator, CAPM Alpha/Beta, Information Ratio,
Tracking Error, Up/Down Capture Ratios, Equity curve karşılaştırması,
hata denetimleri ve çoklu karşılaştırma raporu üretimini doğrular.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.backtest.benchmark import (
    BenchmarkComparator,
    BenchmarkComparison,
    benchmark_comparator,
)


def test_benchmark_comparison_serialization_and_repr() -> None:
    """BenchmarkComparison to_dict ve repr doğrulaması."""
    comp = BenchmarkComparison(
        benchmark_name="BIST100",
        strategy_return_pct=25.4,
        benchmark_return_pct=15.2,
        alpha_pct=8.1234,
        beta=1.0543,
        information_ratio=1.4521,
        tracking_error_pct=4.3211,
        relative_return_pct=10.2,
        up_capture_ratio=110.5,
        down_capture_ratio=85.2,
        correlation=0.9211,
        r_squared=0.8484,
        num_observations=252,
    )

    d = comp.to_dict()
    assert d["benchmark"] == "BIST100"
    assert d["strategy_return_pct"] == 25.4
    assert d["alpha_pct"] == 8.1234
    assert d["beta"] == 1.0543
    assert "BIST100" in repr(comp)
    assert "alpha=8.12%" in repr(comp)


def test_benchmark_comparator_math_metrics() -> None:
    """Sentetik getiri serileriyle Alpha, Beta, Tracking Error hesaplamalarını doğrular."""
    rng = np.random.default_rng(42)
    N = 100
    # Benchmark getirileri
    br = rng.normal(0.0005, 0.01, N)
    # Strateji getirileri: beta=1.2 + alpha + gürültü
    sr = 0.0002 + 1.2 * br + rng.normal(0.0, 0.002, N)

    comp = BenchmarkComparator.compare(
        strategy_returns=sr,
        benchmark_returns=br,
        benchmark_name="XU100",
        risk_free_rate=0.0,
    )

    assert isinstance(comp, BenchmarkComparison)
    assert comp.benchmark_name == "XU100"
    assert 1.0 <= comp.beta <= 1.4
    assert comp.num_observations == N
    assert comp.correlation > 0.8
    assert comp.r_squared > 0.6
    assert comp.tracking_error_pct > 0.0


def test_benchmark_comparator_constant_series_handling() -> None:
    """Sabit veya 0 varyanslı dizilerde NaN oluşumunun engellendiğini doğrular."""
    sr = np.zeros(20)
    br = np.zeros(20)

    comp = BenchmarkComparator.compare(sr, br, benchmark_name="FLAT")
    assert comp.correlation == 0.0
    assert comp.r_squared == 0.0
    assert comp.beta == 1.0  # cov(br, br) == 0 durumunda fallback 1.0


def test_benchmark_comparator_from_equity_curves() -> None:
    """Equity curve listelerinden getiri hesaplama ve karşılaştırmayı doğrular."""
    strat_equity = [
        ("2025-01-01", 100_000.0),
        ("2025-01-02", 102_000.0),
        ("2025-01-03", 105_000.0),
        ("2025-01-04", 104_000.0),
        ("2025-01-05", 108_000.0),
    ]
    bench_equity = [
        ("2025-01-01", 50_000.0),
        ("2025-01-02", 50_500.0),
        ("2025-01-03", 51_000.0),
        ("2025-01-04", 50_800.0),
        ("2025-01-05", 52_000.0),
    ]

    comp = BenchmarkComparator.from_equity_curves(
        strategy_equity=strat_equity,
        benchmark_equity=bench_equity,
        benchmark_name="BIST30",
    )

    assert comp.benchmark_name == "BIST30"
    assert comp.num_observations == 4  # 5 equity noktası -> 4 getiri
    assert comp.strategy_return_pct > 0
    assert comp.benchmark_return_pct > 0


def test_benchmark_comparator_equity_curve_errors() -> None:
    """Yetersiz equity noktası veya sıfır tabanlı equity durumunda ValueError fırlatılmasını doğrular."""
    with pytest.raises(ValueError, match="en az 2 veri noktası"):
        BenchmarkComparator.from_equity_curves([("2025-01-01", 100.0)], [("2025-01-01", 100.0)])

    with pytest.raises(ValueError, match="sıfır olamaz"):
        BenchmarkComparator.from_equity_curves(
            [("2025-01-01", 0.0), ("2025-01-02", 100.0)],
            [("2025-01-01", 50.0), ("2025-01-02", 52.0)],
        )


def test_benchmark_comparator_input_validations() -> None:
    """Boş getiri serilerinde veya 2'den az elemanda ValueError fırlatılmasını doğrular."""
    with pytest.raises(ValueError, match="boş olamaz"):
        BenchmarkComparator.compare(np.array([]), np.array([0.01]))

    with pytest.raises(ValueError, match="en az 2 gözlem gerekli"):
        BenchmarkComparator.compare(np.array([0.01]), np.array([0.02]))


def test_generate_report() -> None:
    """generate_report metodunun özet istatistikleri ve doğru json yapısını ürettiğini doğrular."""
    # Boş durum
    assert "error" in BenchmarkComparator.generate_report([])

    c1 = BenchmarkComparison(
        benchmark_name="BIST100",
        strategy_return_pct=20.0,
        benchmark_return_pct=10.0,
        alpha_pct=5.0,
        beta=1.0,
        information_ratio=1.2,
        tracking_error_pct=3.0,
        relative_return_pct=10.0,
        up_capture_ratio=105.0,
        down_capture_ratio=90.0,
        correlation=0.85,
        r_squared=0.72,
        num_observations=50,
    )
    c2 = BenchmarkComparison(
        benchmark_name="BIST30",
        strategy_return_pct=20.0,
        benchmark_return_pct=12.0,
        alpha_pct=7.5,
        beta=0.9,
        information_ratio=1.6,
        tracking_error_pct=2.5,
        relative_return_pct=8.0,
        up_capture_ratio=110.0,
        down_capture_ratio=80.0,
        correlation=0.90,
        r_squared=0.81,
        num_observations=50,
    )

    report = BenchmarkComparator.generate_report([c1, c2])
    assert len(report["benchmarks"]) == 2
    assert report["summary"]["best_alpha"]["benchmark"] == "BIST30"
    assert report["summary"]["best_alpha"]["alpha_pct"] == 7.5
    assert report["summary"]["best_information_ratio"]["benchmark"] == "BIST30"
    assert report["summary"]["best_information_ratio"]["ir"] == 1.6
    assert isinstance(report["summary"]["avg_correlation"], float)
    assert repr(benchmark_comparator).startswith("BenchmarkComparator")
