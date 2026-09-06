"""ALPHA BIST — Finansal ve İstatistiksel Metrikler Kütüphanesi (Metrics Math).

Platform genelinde (Backtest, Model Eğitimi, Risk Motoru) kullanılan merkezi matematiksel ve finansal metrikler:
- Sharpe Oranı (Yıllıklandırılmış aşırı getiri / volatilite)
- Sortino Oranı (Aşağı yönlü risk / yarı-volatilite — Root Mean Square Downside Deviation)
- Calmar Oranı (Yıllıklandırılmış getiri / azami değer kaybı)
- Maksimum Drawdown (Zirveden dibe en büyük yüzdesel kayıp — Wealth Index korumalı)
- Kazanma Oranı (Win Rate) ve Kâr Faktörü (Profit Factor)
- Information Coefficient (IC) ve Rank IC (Spearman sıralama korelasyonu)
- Riske Maruz Değer (VaR 95) ve Koşullu Riske Maruz Değer (CVaR 95)
- Polars Series/DataFrame doğrudan uyumu ve özet raporlama
"""

from __future__ import annotations

import functools
import math
from typing import Any, Callable, Final, Sequence

import numpy as np
import polars as pl
from opentelemetry import trace

tracer = trace.get_tracer("alpha-bist.metrics_math")

DEFAULT_PERIODS_PER_YEAR: Final[int] = 252
DEFAULT_RISK_FREE_RATE: Final[float] = 0.0
DEFAULT_CONFIDENCE_LEVEL: Final[float] = 0.95


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def _to_clean_numpy(values: np.ndarray | pl.Series | pl.DataFrame | Sequence[float]) -> np.ndarray:
    """Girdiyi NaN/Sonsuz değerlerden arındırılmış 1 boyutlu float64 NumPy dizisine dönüştürür.

    Args:
        values: NumPy dizisi, Polars DataFrame/Series veya sayı dizisi.

    Returns:
        Yalnızca geçerli sonlu sayıları içeren np.ndarray.
    """
    try:
        if isinstance(values, pl.DataFrame):
            arr = values.to_numpy().flatten().astype(np.float64)
        elif isinstance(values, pl.Series):
            arr = values.drop_nulls().to_numpy().astype(np.float64)
        else:
            arr = np.asarray(values, dtype=np.float64)
    except (ValueError, TypeError):
        cleaned: list[float] = []
        raw_list = values.to_list() if hasattr(values, "to_list") else values
        for v in raw_list:
            try:
                fv = float(v)
                if math.isfinite(fv):
                    cleaned.append(fv)
            except (ValueError, TypeError):
                continue
        return np.array(cleaned, dtype=np.float64)

    if arr.ndim > 1:
        arr = arr.flatten()

    mask = np.isfinite(arr)
    return arr[mask]


@otel_trace("metrics_math.calculate_sharpe_ratio")
def calculate_sharpe_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Yıllıklandırılmış Sharpe Oranını hesaplar.

    Args:
        returns: Dönemsel getiri serisi (yüzde veya oran).
        risk_free_rate: Yıllık risksiz faiz oranı (varsayılan: 0.0).
        periods_per_year: Yıllık işlem dönemi sayısı (BIST için varsayılan: 252).

    Returns:
        Yıllıklandırılmış Sharpe oranı (yetersiz veri veya 0 volatilitede 0.0).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) < 2 or periods_per_year <= 0:
        return 0.0

    rf_per_period = float(risk_free_rate) / float(periods_per_year)
    excess_returns = arr - rf_per_period
    std_dev = float(np.std(excess_returns, ddof=1))

    if std_dev <= 1e-12 or not math.isfinite(std_dev):
        return 0.0

    mean_excess = float(np.mean(excess_returns))
    sharpe = (mean_excess / std_dev) * math.sqrt(periods_per_year)
    return float(sharpe) if math.isfinite(sharpe) else 0.0


@otel_trace("metrics_math.calculate_sortino_ratio")
def calculate_sortino_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Yıllıklandırılmış Sortino Oranını hesaplar (Aşağı yönlü sapma formülasyonu).

    Args:
        returns: Dönemsel getiri serisi.
        risk_free_rate: Yıllık risksiz faiz oranı.
        periods_per_year: Yıllık periyot sayısı.

    Returns:
        Yıllıklandırılmış Sortino oranı.
    """
    arr = _to_clean_numpy(returns)
    if len(arr) < 2 or periods_per_year <= 0:
        return 0.0

    rf_per_period = float(risk_free_rate) / float(periods_per_year)
    excess_returns = arr - rf_per_period

    # Aşağı yönlü sapma: tüm dönemler üzerinden negatif sapmaların karelerinin ortalaması
    downside_diff = np.minimum(0.0, excess_returns)
    downside_variance = float(np.mean(downside_diff**2))
    downside_std = math.sqrt(downside_variance)

    if downside_std <= 1e-12 or not math.isfinite(downside_std):
        return 0.0

    mean_excess = float(np.mean(excess_returns))
    sortino = (mean_excess / downside_std) * math.sqrt(periods_per_year)
    return float(sortino) if math.isfinite(sortino) else 0.0


@otel_trace("metrics_math.calculate_max_drawdown")
def calculate_max_drawdown(returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float]) -> float:
    """Maksimum Değer Kaybını (Max Drawdown) hesaplar (negatif oran, örn: -0.15 = %15 kayıp).

    Args:
        returns: Dönemsel getiri serisi.

    Returns:
        Maksimum drawdown oranı (<= 0.0).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) == 0:
        return 0.0

    # Varlık endeksini sıfır altına düşmeyecek şekilde koru
    growth_factors = np.maximum(0.0, 1.0 + arr)
    wealth_index = np.cumprod(growth_factors)
    peak = np.maximum.accumulate(wealth_index)

    valid_peak = np.where(peak > 1e-12, peak, 1.0)
    drawdowns = (wealth_index - valid_peak) / valid_peak
    max_dd = float(np.min(drawdowns))
    return max(-1.0, min(0.0, max_dd)) if math.isfinite(max_dd) else 0.0


@otel_trace("metrics_math.calculate_calmar_ratio")
def calculate_calmar_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Yıllıklandırılmış Calmar Oranını hesaplar (Yıllık Getiri / |Max Drawdown|).

    Args:
        returns: Getiri dizisi.
        periods_per_year: Yıllık periyot sayısı.

    Returns:
        Calmar oranı.
    """
    arr = _to_clean_numpy(returns)
    if len(arr) < 2:
        return 0.0

    max_dd = abs(calculate_max_drawdown(arr))
    if max_dd <= 1e-12:
        return 0.0

    ann_return = float(np.mean(arr) * periods_per_year)
    calmar = ann_return / max_dd
    return float(calmar) if math.isfinite(calmar) else 0.0


@otel_trace("metrics_math.calculate_win_rate")
def calculate_win_rate(returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float]) -> float:
    """Kazanma Oranını (Win Rate, karlı işlem yüzdesi) hesaplar.

    Args:
        returns: İşlem veya dönem getirileri.

    Returns:
        0.0 ile 1.0 arasında kazanma oranı.
    """
    arr = _to_clean_numpy(returns)
    if len(arr) == 0:
        return 0.0

    wins = int(np.sum(arr > 0.0))
    return float(wins / len(arr))


@otel_trace("metrics_math.calculate_profit_factor")
def calculate_profit_factor(returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float]) -> float:
    """Kâr Faktörünü (Brüt Kârlar / Brüt Zararlar) hesaplar.

    Args:
        returns: Getiriler dizisi.

    Returns:
        Kâr faktörü (zarar yoksa 100.0 ile sınırlandırılır).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) == 0:
        return 0.0

    gross_profit = float(np.sum(arr[arr > 0.0]))
    gross_loss = float(abs(np.sum(arr[arr < 0.0])))

    if gross_loss <= 1e-12:
        return 100.0 if gross_profit > 0.0 else 0.0

    pf = gross_profit / gross_loss
    return float(min(100.0, pf)) if math.isfinite(pf) else 0.0


@otel_trace("metrics_math.calculate_ic")
def calculate_ic(
    scores: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    actuals: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
) -> float:
    """Information Coefficient (IC) — Model tahmin skoru ve gerçekleşen getiri korelasyonu.

    Args:
        scores: Model tahmin puanları veya sıralamaları.
        actuals: Gerçekleşen getiri değerleri.

    Returns:
        -1.0 ile 1.0 arasında Pearson korelasyon katsayısı.
    """
    s_arr = _to_clean_numpy(scores)
    a_arr = _to_clean_numpy(actuals)

    min_len = min(len(s_arr), len(a_arr))
    if min_len < 5:
        return 0.0

    s_clean = s_arr[:min_len]
    a_clean = a_arr[:min_len]

    std_s = float(np.std(s_clean))
    std_a = float(np.std(a_clean))

    if std_s <= 1e-12 or std_a <= 1e-12:
        return 0.0

    try:
        ic = float(np.corrcoef(s_clean, a_clean)[0, 1])
        return ic if math.isfinite(ic) else 0.0
    except Exception:
        return 0.0


@otel_trace("metrics_math.calculate_rank_ic")
def calculate_rank_ic(
    scores: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    actuals: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
) -> float:
    """Rank Information Coefficient (Rank IC) — Sıralama bazlı Spearman korelasyonu.

    Args:
        scores: Tahmin skorları.
        actuals: Gerçekleşen getiriler.

    Returns:
        -1.0 ile 1.0 arasında Spearman sıra korelasyon katsayısı.
    """
    s_arr = _to_clean_numpy(scores)
    a_arr = _to_clean_numpy(actuals)

    min_len = min(len(s_arr), len(a_arr))
    if min_len < 5:
        return 0.0

    s_clean = s_arr[:min_len]
    a_clean = a_arr[:min_len]

    rank_s = np.argsort(np.argsort(s_clean)).astype(float)
    rank_a = np.argsort(np.argsort(a_clean)).astype(float)

    return calculate_ic(rank_s, rank_a)


@otel_trace("metrics_math.calculate_var_cvar")
def calculate_var_cvar(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> tuple[float, float]:
    """Riske Maruz Değer (VaR) ve Koşullu Riske Maruz Değeri (CVaR/Expected Shortfall) hesaplar.

    Args:
        returns: Dönemsel getiri serisi.
        confidence_level: Güven düzeyi (örn: 0.95 = %95 güven).

    Returns:
        (VaR, CVaR) demeti (pozitif kayıp oranları olarak, örn. (0.02, 0.035)).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) < 5:
        return 0.0, 0.0

    alpha = 1.0 - float(confidence_level)
    var_percentile = float(np.percentile(arr, alpha * 100))
    var_val = float(abs(var_percentile)) if var_percentile < 0 else 0.0

    tail_losses = arr[arr <= var_percentile]
    cvar_val = float(abs(np.mean(tail_losses))) if len(tail_losses) > 0 else var_val

    return var_val, cvar_val


def metrics_summary_to_polars(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> pl.DataFrame:
    """Tüm temel performans metriklerini tek bir Polars DataFrame olarak özetler (GEMINI.md Kural 2).

    Args:
        returns: Dönemsel getiri dizisi.
        risk_free_rate: Risksiz faiz oranı.
        periods_per_year: Yıllık periyot sayısı.

    Returns:
        Tüm metrikleri içeren tek satırlık Polars DataFrame.
    """
    arr = _to_clean_numpy(returns)
    var_95, cvar_95 = calculate_var_cvar(arr, DEFAULT_CONFIDENCE_LEVEL)
    return pl.DataFrame({
        "sharpe_ratio": pl.Series([calculate_sharpe_ratio(arr, risk_free_rate, periods_per_year)], dtype=pl.Float64),
        "sortino_ratio": pl.Series([calculate_sortino_ratio(arr, risk_free_rate, periods_per_year)], dtype=pl.Float64),
        "max_drawdown": pl.Series([calculate_max_drawdown(arr)], dtype=pl.Float64),
        "calmar_ratio": pl.Series([calculate_calmar_ratio(arr, periods_per_year)], dtype=pl.Float64),
        "win_rate": pl.Series([calculate_win_rate(arr)], dtype=pl.Float64),
        "profit_factor": pl.Series([calculate_profit_factor(arr)], dtype=pl.Float64),
        "var_95": pl.Series([var_95], dtype=pl.Float64),
        "cvar_95": pl.Series([cvar_95], dtype=pl.Float64),
        "total_periods": pl.Series([len(arr)], dtype=pl.Int64),
    })


__all__: Final[list[str]] = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_PERIODS_PER_YEAR",
    "DEFAULT_RISK_FREE_RATE",
    "calculate_calmar_ratio",
    "calculate_ic",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_rank_ic",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_var_cvar",
    "calculate_win_rate",
    "metrics_summary_to_polars",
    "otel_trace",
]
