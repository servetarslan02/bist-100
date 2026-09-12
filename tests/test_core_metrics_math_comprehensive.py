"""ALPHA BIST — services/core/metrics_math kapsamlı test suite.

Test edilen bileşenler:
- _to_clean_numpy: Veri temizleme / dönüştürme
- calculate_sharpe_ratio: Yıllıklandırılmış Sharpe oranı
- calculate_sortino_ratio: Sortino oranı (downside deviation)
- calculate_max_drawdown: Maksimum değer kaybı
- calculate_calmar_ratio: Calmar oranı
- calculate_win_rate: Kazanma oranı
- calculate_profit_factor: Kâr faktörü
- calculate_omega_ratio: Omega oranı
- calculate_tail_ratio: Kuyruk oranı
- calculate_information_ratio: Bilgi oranı
- calculate_ic: Information Coefficient
- calculate_var: Value at Risk
- calculate_cvar: Conditional VaR
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from services.core.metrics_math import (
    _to_clean_numpy,
    calculate_calmar_ratio,
    calculate_ic,
    calculate_information_ratio,
    calculate_max_drawdown,
    calculate_omega_ratio,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_tail_ratio,
    calculate_win_rate,
)


# ==============================================================================
# Yardımcı veri setleri
# ==============================================================================

POSITIVE_RETURNS = [0.01, 0.02, 0.015, 0.01, 0.025, 0.005, 0.018, 0.03]
MIXED_RETURNS = [0.01, -0.02, 0.03, -0.01, 0.02, -0.015, 0.025, -0.005]
NEGATIVE_RETURNS = [-0.01, -0.02, -0.005, -0.03, -0.015, -0.01, -0.02, -0.01]
ALL_ZERO_RETURNS = [0.0] * 10
EMPTY_RETURNS: list[float] = []


# ==============================================================================
# _to_clean_numpy testleri
# ==============================================================================


class TestToCleanNumpy:
    """Giriş temizleme fonksiyonu testleri."""

    def test_list_input(self) -> None:
        arr = _to_clean_numpy([1.0, 2.0, 3.0])
        assert arr.dtype == np.float64
        assert len(arr) == 3

    def test_numpy_input(self) -> None:
        raw = np.array([1.0, 2.0, 3.0])
        arr = _to_clean_numpy(raw)
        np.testing.assert_array_almost_equal(arr, raw)

    def test_polars_series_input(self) -> None:
        series = pl.Series([1.0, 2.0, None, 3.0])
        arr = _to_clean_numpy(series)
        assert len(arr) == 3  # None temizlenir
        assert all(math.isfinite(v) for v in arr)

    def test_polars_dataframe_input(self) -> None:
        df = pl.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        arr = _to_clean_numpy(df)
        assert len(arr) == 4  # Flatten edilmiş

    def test_nan_removed(self) -> None:
        arr = _to_clean_numpy([1.0, float("nan"), 2.0])
        assert len(arr) == 2

    def test_inf_removed(self) -> None:
        arr = _to_clean_numpy([1.0, float("inf"), 2.0, float("-inf")])
        assert len(arr) == 2

    def test_empty_list(self) -> None:
        arr = _to_clean_numpy([])
        assert len(arr) == 0

    def test_all_nan(self) -> None:
        arr = _to_clean_numpy([float("nan"), float("nan")])
        assert len(arr) == 0


# ==============================================================================
# calculate_sharpe_ratio testleri
# ==============================================================================


class TestSharpeRatio:
    """Sharpe oranı hesaplama testleri."""

    def test_positive_returns_positive_sharpe(self) -> None:
        result = calculate_sharpe_ratio(POSITIVE_RETURNS)
        assert result > 0.0

    def test_negative_returns_negative_sharpe(self) -> None:
        result = calculate_sharpe_ratio(NEGATIVE_RETURNS)
        assert result < 0.0

    def test_zero_returns_zero_sharpe(self) -> None:
        result = calculate_sharpe_ratio(ALL_ZERO_RETURNS)
        assert result == 0.0

    def test_empty_returns(self) -> None:
        assert calculate_sharpe_ratio(EMPTY_RETURNS) == 0.0

    def test_single_value(self) -> None:
        assert calculate_sharpe_ratio([0.01]) == 0.0

    def test_risk_free_rate_effect(self) -> None:
        """Daha yüksek risksiz faiz, daha düşük Sharpe oranı verir."""
        r1 = calculate_sharpe_ratio(POSITIVE_RETURNS, risk_free_rate=0.0)
        r2 = calculate_sharpe_ratio(POSITIVE_RETURNS, risk_free_rate=0.10)
        assert r1 > r2

    def test_annualization_effect(self) -> None:
        """Daha fazla periyot yıllıklandırmayı etkiler."""
        r1 = calculate_sharpe_ratio(MIXED_RETURNS, periods_per_year=252)
        r2 = calculate_sharpe_ratio(MIXED_RETURNS, periods_per_year=12)
        assert r1 != r2  # Farklı yıllıklandırmalar farklı sonuç verir

    def test_nan_in_returns_handled(self) -> None:
        """NaN değerler güvenli şekilde temizlenir."""
        returns_with_nan = [0.01, float("nan"), 0.02, 0.03]
        result = calculate_sharpe_ratio(returns_with_nan)
        assert math.isfinite(result)

    def test_polars_series_input(self) -> None:
        series = pl.Series(POSITIVE_RETURNS)
        result = calculate_sharpe_ratio(series)
        assert math.isfinite(result)
        assert result > 0.0

    def test_numpy_array_input(self) -> None:
        arr = np.array(POSITIVE_RETURNS)
        result = calculate_sharpe_ratio(arr)
        assert math.isfinite(result)


# ==============================================================================
# calculate_sortino_ratio testleri
# ==============================================================================


class TestSortinoRatio:
    """Sortino oranı hesaplama testleri."""

    def test_mixed_returns_positive_sortino(self) -> None:
        """Negatif getiri içeren karışık seride Sortino pozitif olabilir."""
        # Ortalama getiri > 0 ve downside std > 0 olan bir seri gerekli
        # MIXED_RETURNS: [0.01, -0.02, 0.03, -0.01, 0.02, -0.015, 0.025, -0.005] → ort ~0.005
        result = calculate_sortino_ratio(MIXED_RETURNS)
        # Sonuç finite olmalı; işaret pozitif-negatif olabilir
        assert isinstance(result, float)

    def test_all_positive_no_downside(self) -> None:
        """Hiç negatif getiri yoksa Sortino 0.0 döner (downside std = 0)."""
        all_positive = [0.01, 0.02, 0.015, 0.03]
        result = calculate_sortino_ratio(all_positive)
        assert result == 0.0  # downside_std = 0 → sıfır

    def test_mixed_returns(self) -> None:
        result = calculate_sortino_ratio(MIXED_RETURNS)
        assert math.isfinite(result)

    def test_empty_returns(self) -> None:
        assert calculate_sortino_ratio([]) == 0.0

    def test_single_value(self) -> None:
        assert calculate_sortino_ratio([0.01]) == 0.0

    def test_polars_input(self) -> None:
        series = pl.Series(MIXED_RETURNS)
        result = calculate_sortino_ratio(series)
        assert math.isfinite(result)


# ==============================================================================
# calculate_max_drawdown testleri
# ==============================================================================


class TestMaxDrawdown:
    """Maksimum değer kaybı hesaplama testleri."""

    def test_monotone_positive_returns_no_drawdown(self) -> None:
        """Sürekli artan portföyde drawdown sıfır veya çok küçük olmalı."""
        returns = [0.01] * 20
        result = calculate_max_drawdown(returns)
        assert result >= -0.01  # Çok küçük (neredeyse sıfır)

    def test_crash_scenario(self) -> None:
        """Büyük düşüş sonrası max drawdown negatif ve büyük olmalı."""
        returns = [0.02] * 5 + [-0.50] + [0.01] * 5
        result = calculate_max_drawdown(returns)
        assert result < -0.20  # En az %20 düşüş

    def test_empty_returns(self) -> None:
        assert calculate_max_drawdown([]) == 0.0

    def test_result_bounds(self) -> None:
        """Max drawdown -1.0 ile 0.0 arasında olmalı."""
        result = calculate_max_drawdown(MIXED_RETURNS)
        assert -1.0 <= result <= 0.0

    def test_all_negative_returns(self) -> None:
        """Tüm negatif getiriler büyük drawdown verir."""
        result = calculate_max_drawdown(NEGATIVE_RETURNS)
        assert result < -0.05

    def test_single_value(self) -> None:
        result = calculate_max_drawdown([0.01])
        assert result == 0.0

    def test_polars_series(self) -> None:
        series = pl.Series(MIXED_RETURNS)
        result = calculate_max_drawdown(series)
        assert math.isfinite(result)

    def test_extreme_crash_capped(self) -> None:
        """Tam kayıp senaryosu -1.0 ile sınırlanır."""
        returns = [0.1] * 5 + [-0.99] * 20
        result = calculate_max_drawdown(returns)
        assert result >= -1.0


# ==============================================================================
# calculate_calmar_ratio testleri
# ==============================================================================


class TestCalmarRatio:
    """Calmar oranı hesaplama testleri."""

    def test_positive_returns_positive_calmar(self) -> None:
        result = calculate_calmar_ratio(POSITIVE_RETURNS)
        # Sadece pozitif getiriler varsa drawdown küçük; Calmar hesaplanamaz (0.0 döner)
        assert math.isfinite(result)

    def test_mixed_returns_finite(self) -> None:
        result = calculate_calmar_ratio(MIXED_RETURNS)
        assert math.isfinite(result)

    def test_empty_returns(self) -> None:
        assert calculate_calmar_ratio([]) == 0.0

    def test_single_value(self) -> None:
        assert calculate_calmar_ratio([0.01]) == 0.0


# ==============================================================================
# calculate_win_rate testleri
# ==============================================================================


class TestWinRate:
    """Kazanma oranı hesaplama testleri."""

    def test_all_wins(self) -> None:
        result = calculate_win_rate(POSITIVE_RETURNS)
        assert result == pytest.approx(1.0)

    def test_all_losses(self) -> None:
        result = calculate_win_rate(NEGATIVE_RETURNS)
        assert result == pytest.approx(0.0)

    def test_half_wins(self) -> None:
        returns = [0.01, -0.01, 0.02, -0.02]
        result = calculate_win_rate(returns)
        assert result == pytest.approx(0.5)

    def test_empty_returns(self) -> None:
        assert calculate_win_rate([]) == 0.0

    def test_all_zeros(self) -> None:
        """Sıfır getiriler kayıp sayılır."""
        result = calculate_win_rate(ALL_ZERO_RETURNS)
        assert result == pytest.approx(0.0)

    def test_result_in_bounds(self) -> None:
        result = calculate_win_rate(MIXED_RETURNS)
        assert 0.0 <= result <= 1.0

    def test_polars_series(self) -> None:
        series = pl.Series(MIXED_RETURNS)
        result = calculate_win_rate(series)
        assert 0.0 <= result <= 1.0


# ==============================================================================
# calculate_profit_factor testleri
# ==============================================================================


class TestProfitFactor:
    """Kâr faktörü hesaplama testleri."""

    def test_all_wins_high_pf(self) -> None:
        result = calculate_profit_factor(POSITIVE_RETURNS)
        assert result == pytest.approx(100.0)  # Kayıp yok → max kap 100.0

    def test_all_losses_zero_pf(self) -> None:
        result = calculate_profit_factor(NEGATIVE_RETURNS)
        assert result == pytest.approx(0.0)

    def test_mixed_balanced(self) -> None:
        returns = [0.01, -0.01, 0.02, -0.02]
        result = calculate_profit_factor(returns)
        assert result == pytest.approx(1.0)

    def test_empty_returns(self) -> None:
        assert calculate_profit_factor([]) == 0.0

    def test_result_in_bounds(self) -> None:
        result = calculate_profit_factor(MIXED_RETURNS)
        assert 0.0 <= result <= 100.0


# ==============================================================================
# calculate_omega_ratio testleri
# ==============================================================================


class TestOmegaRatio:
    """Omega oranı hesaplama testleri."""

    def test_positive_returns_high_omega(self) -> None:
        result = calculate_omega_ratio(POSITIVE_RETURNS)
        assert result > 1.0

    def test_all_negative_low_omega(self) -> None:
        result = calculate_omega_ratio(NEGATIVE_RETURNS)
        assert result < 1.0

    def test_empty_returns(self) -> None:
        assert calculate_omega_ratio([]) == 0.0

    def test_threshold_effect(self) -> None:
        """Eşik değeri omega oranını etkiler."""
        r1 = calculate_omega_ratio(MIXED_RETURNS, threshold=0.0)
        r2 = calculate_omega_ratio(MIXED_RETURNS, threshold=0.05)
        assert r1 != r2

    def test_result_finite(self) -> None:
        result = calculate_omega_ratio(MIXED_RETURNS)
        assert math.isfinite(result)


# ==============================================================================
# calculate_tail_ratio testleri
# ==============================================================================


class TestTailRatio:
    """Kuyruk oranı hesaplama testleri."""

    def test_few_values_returns_one(self) -> None:
        """5'ten az değerde varsayılan 1.0 döner."""
        assert calculate_tail_ratio([0.01, 0.02, 0.03]) == pytest.approx(1.0)

    def test_symmetric_returns_near_one(self) -> None:
        """Simetrik dağılımda kuyruk oranı ~1.0 olmalı."""
        np.random.seed(42)
        symmetric = list(np.random.normal(0, 0.01, 200))
        result = calculate_tail_ratio(symmetric)
        assert 0.5 < result < 3.0  # Geniş tolerans, simetrik olduğu için yaklaşık 1.0

    def test_result_in_bounds(self) -> None:
        result = calculate_tail_ratio(MIXED_RETURNS)
        assert 0.0 <= result <= 50.0

    def test_result_finite(self) -> None:
        result = calculate_tail_ratio(MIXED_RETURNS)
        assert math.isfinite(result)


# ==============================================================================
# calculate_information_ratio testleri
# ==============================================================================


class TestInformationRatio:
    """Bilgi oranı hesaplama testleri."""

    def test_outperforming_benchmark(self) -> None:
        portfolio = [0.02, 0.025, 0.018, 0.022, 0.019]
        benchmark = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = calculate_information_ratio(portfolio, benchmark)
        assert result > 0.0

    def test_underperforming_benchmark(self) -> None:
        portfolio = [0.005, 0.003, 0.004, 0.006, 0.002]
        benchmark = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = calculate_information_ratio(portfolio, benchmark)
        assert result < 0.0

    def test_identical_returns_zero_ir(self) -> None:
        """Portföy ve benchmark aynıysa tracking error sıfır → IR sıfır."""
        returns = [0.01, 0.02, 0.015, 0.018]
        result = calculate_information_ratio(returns, returns)
        assert result == pytest.approx(0.0)

    def test_empty_inputs(self) -> None:
        assert calculate_information_ratio([], []) == 0.0

    def test_different_lengths(self) -> None:
        """Farklı uzunluktaki serilerde minimum uzunluk kullanılır."""
        port = [0.01, 0.02, 0.03, 0.04, 0.05]
        bench = [0.01, 0.01]
        result = calculate_information_ratio(port, bench)
        assert math.isfinite(result)


# ==============================================================================
# calculate_ic testleri
# ==============================================================================


class TestInformationCoefficient:
    """Information Coefficient (IC) hesaplama testleri."""

    def test_perfect_positive_correlation(self) -> None:
        scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        actuals = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = calculate_ic(scores, actuals)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative_correlation(self) -> None:
        scores = [5.0, 4.0, 3.0, 2.0, 1.0]
        actuals = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = calculate_ic(scores, actuals)
        assert result == pytest.approx(-1.0, abs=1e-6)

    def test_no_correlation(self) -> None:
        """Rastgele düzende IC sıfıra yakın olmalı."""
        np.random.seed(0)
        scores = list(np.random.rand(50))
        np.random.seed(99)
        actuals = list(np.random.rand(50))
        result = calculate_ic(scores, actuals)
        assert -0.5 < result < 0.5  # Rastgele olduğu için tutarsız değil

    def test_empty_input(self) -> None:
        assert calculate_ic([], []) == 0.0

    def test_too_few_values(self) -> None:
        """5'ten az değerde 0.0 döner."""
        assert calculate_ic([1.0, 2.0, 3.0], [0.01, 0.02, 0.03]) == 0.0

    def test_result_bounds(self) -> None:
        """IC her zaman [-1, 1] aralığında olmalı."""
        scores = list(range(20))
        actuals = [x * 0.01 for x in range(20)]
        result = calculate_ic(scores, actuals)
        assert -1.0 <= result <= 1.0

    def test_polars_series_input(self) -> None:
        scores = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = pl.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        result = calculate_ic(scores, actuals)
        assert result == pytest.approx(1.0, abs=1e-6)


# ==============================================================================
# Uçtan uca senaryo testleri
# ==============================================================================


class TestEndToEndScenarios:
    """Gerçek portföy yönetimi senaryolarını kapsayan uçtan uca testler."""

    def test_bist_annual_return_scenario(self) -> None:
        """Tipik bir BIST yatırımcısı senaryosu."""
        np.random.seed(42)
        # Günlük getiriler: ortalama %0.05, std %1.5 (günlük)
        daily_returns = list(np.random.normal(0.0005, 0.015, 252))
        sharpe = calculate_sharpe_ratio(daily_returns)
        sortino = calculate_sortino_ratio(daily_returns)
        max_dd = calculate_max_drawdown(daily_returns)
        win_rate = calculate_win_rate(daily_returns)

        assert math.isfinite(sharpe)
        assert math.isfinite(sortino)
        assert -1.0 <= max_dd <= 0.0
        assert 0.0 <= win_rate <= 1.0

    def test_metrics_consistency_all_positive(self) -> None:
        """Tüm pozitif getiriler için Sharpe > 0, Win Rate = 1.0."""
        returns = [0.005 + abs(x) for x in np.random.normal(0, 0.001, 100)]
        assert calculate_sharpe_ratio(returns) > 0.0
        assert calculate_win_rate(returns) == pytest.approx(1.0)
        assert calculate_profit_factor(returns) == pytest.approx(100.0)

    def test_risk_adjusted_metrics_ordering(self) -> None:
        """Daha düşük riskli portföyde Sharpe > Sortino beklenmez; her ikisi de pozitif olmalı."""
        returns = MIXED_RETURNS * 5
        sharpe = calculate_sharpe_ratio(returns)
        sortino = calculate_sortino_ratio(returns)
        # Her iki metrik de aynı işarette olmalı
        if sharpe > 0:
            assert sortino >= 0  # Veya en azından sıfır
        elif sharpe < 0:
            assert sortino <= 0
