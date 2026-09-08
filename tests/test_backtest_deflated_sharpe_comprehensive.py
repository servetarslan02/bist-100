"""ALPHA BIST — Deflated Sharpe ve Probabilistic Sharpe Kapsamlı Test Paketi.

services/backtest/deflated_sharpe.py modülünün tüm işlevlerini ve uç durumlarını sınar:
1. DeflatedSharpeResult dataclass doğrulaması (to_dict, __repr__, güven seviyeleri).
2. DeflatedSharpeCalculator.compute_expected_max_sharpe (n<=1 veya obs<2 sınırları, Euler-Mascheroni, Cornish-Fisher skew/kurtosis düzeltmeleri).
3. DeflatedSharpeCalculator.compute_deflated_sharpe (tekil strateji vs çoklu test cezası, p-değeri ve anlamlılık).
4. DeflatedSharpeCalculator.from_returns (deterministik numpy getiri dizisi, risksiz faiz oranı, yetersiz gözlem guardı).
5. ProbabilisticSharpeRatio.compute (sıfır/negatif varyans guardları, obs<2, Z-skoru ve PSR olasılık hesabı).
6. ProbabilisticSharpeRatio.from_returns (istatistiksel momentler, getiri serisi işleme).
7. Modül seviyesi singleton ve sabitlerin doğrulanması.
"""

from __future__ import annotations

import numpy as np

from services.backtest.deflated_sharpe import (
    DEFAULT_BENCHMARK_SHARPE,
    DEFAULT_PERIODS_PER_YEAR,
    EULER_MASCHERONI,
    DeflatedSharpeCalculator,
    DeflatedSharpeResult,
    ProbabilisticSharpeRatio,
    deflated_sharpe,
    probabilistic_sharpe,
)


def test_deflated_sharpe_result_dataclass():
    """DeflatedSharpeResult alanları, to_dict ve __repr__ doğrulaması."""
    res = DeflatedSharpeResult(
        observed_sharpe=1.85432,
        expected_max_sharpe=1.12345,
        std_max_sharpe=0.45678,
        deflated_sharpe=1.60012,
        num_strategies_tested=50,
        num_observations=504,
        skewness=-0.2543,
        kurtosis=3.4567,
        p_value=0.04215,
        is_significant=True,
        confidence_level="medium",
    )

    repr_str = repr(res)
    assert "observed=1.8543" in repr_str
    assert "deflated=1.6001" in repr_str
    assert "confidence='medium'" in repr_str

    d = res.to_dict()
    assert d["observed_sharpe"] == 1.8543
    assert d["expected_max_sharpe"] == 1.1235
    assert d["num_strategies_tested"] == 50
    assert d["num_observations"] == 504
    assert d["is_significant"] is True
    assert d["confidence_level"] == "medium"


def test_compute_expected_max_sharpe_boundaries():
    """Strateji sayısı <= 1 veya gözlem < 2 olduğunda sınır değerler (0.0, 1.0) dönmeli."""
    exp_sr, std_sr = DeflatedSharpeCalculator.compute_expected_max_sharpe(
        num_strategies=1, num_observations=252
    )
    assert exp_sr == 0.0
    assert std_sr == 1.0

    exp_sr_zero, std_sr_zero = DeflatedSharpeCalculator.compute_expected_max_sharpe(
        num_strategies=10, num_observations=1
    )
    assert exp_sr_zero == 0.0
    assert std_sr_zero == 1.0


def test_compute_expected_max_sharpe_with_moments():
    """Çoklu stratejide strateji sayısı arttıkça beklenen max Sharpe yükselmeli."""
    # 5 strateji vs 100 strateji
    sr_5, std_5 = DeflatedSharpeCalculator.compute_expected_max_sharpe(
        num_strategies=5, num_observations=252, periods_per_year=252
    )
    sr_100, std_100 = DeflatedSharpeCalculator.compute_expected_max_sharpe(
        num_strategies=100, num_observations=252, periods_per_year=252
    )

    assert sr_100 > sr_5
    assert std_100 > 0

    # Cornish-Fisher düzeltmesi (aşırı negatif çarpıklık veya yüksek basıklık)
    sr_skew, _ = DeflatedSharpeCalculator.compute_expected_max_sharpe(
        num_strategies=10,
        num_observations=252,
        skewness=-1.5,
        kurtosis=6.0,
        periods_per_year=252,
    )
    assert isinstance(sr_skew, float)


def test_compute_deflated_sharpe_confidence_tiers():
    """Deflated Sharpe p-değerine göre farklı güven kademeleri üretmeli."""
    # Yüksek anlamlılık (high confidence, p < 0.01)
    res_high = DeflatedSharpeCalculator.compute_deflated_sharpe(
        observed_sharpe=3.5,
        num_strategies=2,
        num_observations=500,
        periods_per_year=252,
    )
    assert res_high.is_significant is True
    assert res_high.confidence_level in ("high", "medium")

    # Çok fazla strateji denendiğinde (overfitting cezası: p >= 0.10 -> not_significant)
    res_insignificant = DeflatedSharpeCalculator.compute_deflated_sharpe(
        observed_sharpe=1.0,
        num_strategies=5000,
        num_observations=100,
        periods_per_year=252,
    )
    assert res_insignificant.is_significant is False
    assert res_insignificant.confidence_level == "not_significant"


def test_deflated_sharpe_from_returns():
    """Deterministik getiri dizisinden doğrudan DSR hesaplama."""
    # Yetersiz veri durumu
    insufficient = DeflatedSharpeCalculator.from_returns(np.array([0.01]))
    assert insufficient.num_observations == 1
    assert insufficient.is_significant is False
    assert insufficient.confidence_level == "not_significant"

    # Deterministik pozitif getiri serisi (seed sabit)
    np.random.seed(42)
    # Günlük ortalama %0.1 getiri, %1 volatilite
    returns = np.random.normal(loc=0.001, scale=0.01, size=252)

    res_single = DeflatedSharpeCalculator.from_returns(returns, num_strategies=1, risk_free_rate=0.0)
    assert res_single.num_observations == 252
    assert res_single.observed_sharpe > 0

    # Aynı getiriyi 100 strateji arasından seçilmiş gibi test ettiğimizde p-value yükselmeli
    res_multi = DeflatedSharpeCalculator.from_returns(returns, num_strategies=100, risk_free_rate=0.0)
    assert res_multi.deflated_sharpe < res_single.deflated_sharpe
    assert res_multi.p_value > res_single.p_value


def test_probabilistic_sharpe_ratio():
    """ProbabilisticSharpeRatio (PSR) hesaplayıcı sınır ve formül doğrulaması."""
    # Yetersiz gözlem (< 2)
    psr_zero = ProbabilisticSharpeRatio.compute(observed_sharpe=1.5, num_observations=1)
    assert psr_zero == 0.0

    # Normal durum: Sharpe=1.5, 252 gün, benchmark=0 -> Yüksek PSR (> 0.95)
    psr_val = ProbabilisticSharpeRatio.compute(
        observed_sharpe=1.5,
        benchmark_sharpe=0.0,
        num_observations=252,
        skewness=0.0,
        kurtosis=3.0,
    )
    assert 0.95 <= psr_val <= 1.0

    # Negatif Sharpe -> Düşük PSR (< 0.5)
    psr_neg = ProbabilisticSharpeRatio.compute(
        observed_sharpe=-0.5,
        benchmark_sharpe=0.0,
        num_observations=252,
    )
    assert psr_neg < 0.5

    # Sayısal guard: aşırı çarpıklık/basıklık ile varyans_term <= 0
    # skewness * sr > 1 + (kurtosis - 1)/4 * sr^2
    psr_guard = ProbabilisticSharpeRatio.compute(
        observed_sharpe=5.0,
        skewness=100.0,
        kurtosis=1.0,
        num_observations=252,
    )
    assert psr_guard == 0.0


def test_probabilistic_sharpe_from_returns():
    """Getiri dizisinden PSR hesaplama ve sözlük çıktısı testi."""
    empty_res = ProbabilisticSharpeRatio.from_returns(np.array([]))
    assert empty_res["psr"] == 0.0

    np.random.seed(42)
    daily_returns = np.random.normal(loc=0.0015, scale=0.012, size=500)
    psr_dict = ProbabilisticSharpeRatio.from_returns(daily_returns, benchmark_sharpe=0.0)

    assert "psr" in psr_dict
    assert "observed_sharpe" in psr_dict
    assert psr_dict["observations"] == 500
    assert 0.0 <= psr_dict["psr"] <= 1.0
    assert "skewness" in psr_dict
    assert "kurtosis" in psr_dict


def test_singletons_and_constants():
    """Modül seviyesi singleton ve sabitlerin varlığı ve temsilleri."""
    assert isinstance(deflated_sharpe, DeflatedSharpeCalculator)
    assert repr(deflated_sharpe) == "DeflatedSharpeCalculator()"

    assert isinstance(probabilistic_sharpe, ProbabilisticSharpeRatio)
    assert repr(probabilistic_sharpe) == "ProbabilisticSharpeRatio()"

    assert EULER_MASCHERONI > 0.57
    assert DEFAULT_PERIODS_PER_YEAR == 252
    assert DEFAULT_BENCHMARK_SHARPE == 0.0
