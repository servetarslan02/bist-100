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

import contextlib
import functools
import math
import os
from typing import Any, Callable, Final, Sequence

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

try:
    from services.core.otel import otel_trace
except ImportError:
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("alpha-bist.metrics_math")

        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                @functools.wraps(func)
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    with tracer.start_as_current_span(span_name):
                        return func(*args, **kwargs)
                return wrapper
            return decorator
    except ImportError:
        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                @functools.wraps(func)
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)
                return wrapper
            return decorator

logger = structlog.get_logger(__name__)

DEFAULT_PERIODS_PER_YEAR: Final[int] = 252
DEFAULT_RISK_FREE_RATE: Final[float] = 0.0
DEFAULT_CONFIDENCE_LEVEL: Final[float] = 0.95


def _to_clean_numpy(values: np.ndarray | pl.Series | pl.DataFrame | Sequence[float]) -> np.ndarray:
    """Girdiyi NaN/Sonsuz değerlerden arındırılmış 1 boyutlu float64 NumPy dizisine dönüştürür.

    Args:
        values: NumPy dizisi, Polars DataFrame/Series veya sayı dizisi.

    Returns:
        Yalnızca geçerli sonlu sayıları içeren np.ndarray.
    """
    try:
        if isinstance(values, pl.DataFrame):
            numeric_cols = [col for col, dtype in zip(values.columns, values.dtypes, strict=False) if dtype.is_numeric()]
            if not numeric_cols:
                return np.array([], dtype=np.float64)
            arr = values.select(numeric_cols).to_numpy().flatten().astype(np.float64)
        elif isinstance(values, pl.Series):
            arr = values.drop_nulls().to_numpy().astype(np.float64)
        else:
            arr = np.asarray(values, dtype=np.float64)
    except Exception:
        cleaned: list[float] = []
        if isinstance(values, pl.DataFrame):
            for row in values.to_dicts():
                for v in row.values():
                    try:
                        fv = float(v)
                        if math.isfinite(fv):
                            cleaned.append(fv)
                    except (ValueError, TypeError):
                        continue
        elif hasattr(values, "to_list"):
            for v in values.to_list():
                try:
                    fv = float(v)
                    if math.isfinite(fv):
                        cleaned.append(fv)
                except (ValueError, TypeError):
                    continue
        else:
            try:
                for v in values:  # type: ignore[union-attr]
                    try:
                        fv = float(v)
                        if math.isfinite(fv):
                            cleaned.append(fv)
                    except (ValueError, TypeError):
                        continue
            except Exception:
                pass
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


@otel_trace("metrics_math.calculate_omega_ratio")
def calculate_omega_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    threshold: float = 0.0,
) -> float:
    """Omega Oranını (Eşik üstü kazançların eşik altı kayıplara kümülatif oranı) hesaplar.

    Non-normal ve asimetrik BIST getiri dağılımlarında Sharpe oranına göre çok daha üstün bir risk-getiri metriğidir.

    Args:
        returns: Dönemsel getiri serisi.
        threshold: Asgari kabul edilebilir getiri eşiği (varsayılan: 0.0).

    Returns:
        Omega oranı (kayıp yoksa 100.0 ile sınırlandırılır).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) == 0:
        return 0.0

    excess = arr - threshold
    upside = float(np.sum(np.maximum(0.0, excess)))
    downside = float(np.sum(np.maximum(0.0, -excess)))

    if downside <= 1e-12:
        return 100.0 if upside > 0.0 else 1.0

    omega = upside / downside
    return float(min(100.0, omega)) if math.isfinite(omega) else 1.0


@otel_trace("metrics_math.calculate_tail_ratio")
def calculate_tail_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
) -> float:
    """Kuyruk Oranını (Tail Ratio, 95. persentil / |5. persentil|) hesaplar.

    Dağılımın sağ kuyruk (büyük kazanç) potansiyelinin sol kuyruk (büyük kayıp) riskine oranını ölçer.

    Args:
        returns: Dönemsel getiri serisi.

    Returns:
        Kuyruk oranı (1.0 üstü pozitif asimetriyi, 1.0 altı negatif kuyruk riskini gösterir).
    """
    arr = _to_clean_numpy(returns)
    if len(arr) < 5:
        return 1.0

    p95 = float(np.percentile(arr, 95))
    p5 = float(np.percentile(arr, 5))

    abs_p5 = abs(p5)
    if abs_p5 <= 1e-12:
        return 10.0 if p95 > 0 else 1.0

    ratio = p95 / abs_p5
    return float(max(0.0, min(50.0, ratio))) if math.isfinite(ratio) else 1.0


@otel_trace("metrics_math.calculate_information_ratio")
def calculate_information_ratio(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    benchmark_returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Bilgi Oranını (Information Ratio, Alfa / Takip Hatası) hesaplar.

    Args:
        returns: Portföy getiri serisi.
        benchmark_returns: Karşılaştırma ölçütü (ör: XU100) getiri serisi.
        periods_per_year: Yıllık periyot sayısı.

    Returns:
        Yıllıklandırılmış Bilgi Oranı (IR).
    """
    r_arr = _to_clean_numpy(returns)
    b_arr = _to_clean_numpy(benchmark_returns)

    min_len = min(len(r_arr), len(b_arr))
    if min_len < 2 or periods_per_year <= 0:
        return 0.0

    active_return = r_arr[:min_len] - b_arr[:min_len]
    tracking_error = float(np.std(active_return, ddof=1))

    if tracking_error <= 1e-12 or not math.isfinite(tracking_error):
        return 0.0

    mean_active = float(np.mean(active_return))
    ir = (mean_active / tracking_error) * math.sqrt(periods_per_year)
    return float(ir) if math.isfinite(ir) else 0.0


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
    except Exception as exc:
        logger.debug("metrics_math_ic_hesaplama_hatasi", hata=str(exc))
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

    try:
        from scipy import stats

        res = stats.spearmanr(s_clean, a_clean)
        corr = float(getattr(res, "statistic", getattr(res, "correlation", 0.0)))
        return corr if math.isfinite(corr) else 0.0
    except Exception:
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


def evaluate_strategy_viability(
    returns_or_summary: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    min_sharpe: float = 1.0,
    max_drawdown: float = -0.25,
    min_profit_factor: float = 1.2,
    min_win_rate: float = 0.40,
) -> tuple[bool, str, dict[str, float]]:
    """Strateji performans metriklerini kurumsal risk kapılarına göre otomatik değerlendirir (Self-Healing / Kural 6).

    Tam otomatik BIST sisteminde, backtest veya model yürütme sonuçlarının canlıya çıkmaya uygun olup olmadığını
    denetler.

    Args:
        returns_or_summary: Getiri serisi veya metrics_summary_to_polars çıktısı DataFrame.
        min_sharpe: Kabul edilebilir asgari Sharpe oranı (varsayılan: 1.0).
        max_drawdown: İzin verilen en büyük azami kayıp eşiği (örn: -0.25 = en fazla %25 düşüş).
        min_profit_factor: Asgari kâr faktörü (varsayılan: 1.2).
        min_win_rate: Asgari kazanma oranı (varsayılan: 0.40).

    Returns:
        (uygun_mu, gerekce, metrikler_sozlugu) üçlüsü.
    """
    if isinstance(returns_or_summary, pl.DataFrame) and "sharpe_ratio" in returns_or_summary.columns:
        row = returns_or_summary.to_dicts()[0]
        sharpe = float(row.get("sharpe_ratio", 0.0))
        max_dd = float(row.get("max_drawdown", 0.0))
        profit_factor = float(row.get("profit_factor", 0.0))
        win_rate = float(row.get("win_rate", 0.0))
        sortino = float(row.get("sortino_ratio", 0.0))
        calmar = float(row.get("calmar_ratio", 0.0))
    else:
        arr = _to_clean_numpy(returns_or_summary)
        sharpe = calculate_sharpe_ratio(arr)
        max_dd = calculate_max_drawdown(arr)
        profit_factor = calculate_profit_factor(arr)
        win_rate = calculate_win_rate(arr)
        sortino = calculate_sortino_ratio(arr)
        calmar = calculate_calmar_ratio(arr)

    metrics_dict = {
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "max_drawdown": round(max_dd, 3),
        "profit_factor": round(profit_factor, 3),
        "win_rate": round(win_rate, 3),
    }

    if max_dd < max_drawdown:
        return (
            False,
            f"Risk İhlali: Azami değer kaybı (%{max_dd*100:.1f}) izin verilen sınırı (%{max_drawdown*100:.1f}) aştı",
            metrics_dict,
        )

    if sharpe < min_sharpe:
        return (
            False,
            f"Performans Yetersiz: Sharpe oranı ({sharpe:.2f}) asgari eşiğin ({min_sharpe:.2f}) altında",
            metrics_dict,
        )

    if profit_factor < min_profit_factor:
        return (
            False,
            f"Kârlılık Yetersiz: Kâr faktörü ({profit_factor:.2f}) asgari eşiğin ({min_profit_factor:.2f}) altında",
            metrics_dict,
        )

    if win_rate < min_win_rate:
        return (
            False,
            f"Kazanma Oranı Yetersiz: Kazanma oranı (%{win_rate*100:.1f}) asgari eşiğin (%{min_win_rate*100:.1f}) altında",
            metrics_dict,
        )

    return True, "Strateji tüm kurumsal quant ve risk kriterlerini karşıladı", metrics_dict


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
    return pl.DataFrame(
        {
            "sharpe_ratio": pl.Series([calculate_sharpe_ratio(arr, risk_free_rate, periods_per_year)], dtype=pl.Float64),
            "sortino_ratio": pl.Series([calculate_sortino_ratio(arr, risk_free_rate, periods_per_year)], dtype=pl.Float64),
            "max_drawdown": pl.Series([calculate_max_drawdown(arr)], dtype=pl.Float64),
            "calmar_ratio": pl.Series([calculate_calmar_ratio(arr, periods_per_year)], dtype=pl.Float64),
            "win_rate": pl.Series([calculate_win_rate(arr)], dtype=pl.Float64),
            "profit_factor": pl.Series([calculate_profit_factor(arr)], dtype=pl.Float64),
            "omega_ratio": pl.Series([calculate_omega_ratio(arr)], dtype=pl.Float64),
            "tail_ratio": pl.Series([calculate_tail_ratio(arr)], dtype=pl.Float64),
            "var_95": pl.Series([var_95], dtype=pl.Float64),
            "cvar_95": pl.Series([cvar_95], dtype=pl.Float64),
            "total_periods": pl.Series([len(arr)], dtype=pl.Int64),
        }
    )


def export_metrics_to_orjson_bytes(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> bytes:
    """Tüm temel performans metriklerini orjson serileştirilmiş ikili bayt dizisi olarak döndürür."""
    df = metrics_summary_to_polars(returns, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year)
    return orjson.dumps(df.to_dicts()[0], default=str)


def clear_strategy_metrics_duckdb(db_path: str = "data/strategy_metrics.duckdb") -> None:
    """DuckDB strateji performans defterindeki tüm kayıtları siler."""
    if not os.path.exists(db_path):
        return

    with duckdb.connect(db_path) as con:
        con.execute("PRAGMA checkpoint_threshold='4MB'")
        con.execute("PRAGMA wal_autocheckpoint='2MB'")
        con.execute("DROP TABLE IF EXISTS strategy_performance_ledger")


def export_metrics_to_duckdb(
    returns: np.ndarray | pl.Series | pl.DataFrame | Sequence[float],
    strategy_id: str,
    db_path: str = "data/strategy_metrics.duckdb",
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> int:
    """Hesaplanan strateji metriklerini kalıcı DuckDB tablosuna kaydeder (GEMINI.md Kural 5 & Kural 6).

    Args:
        returns: Getiri dizisi.
        strategy_id: Model veya strateji kimliği.
        db_path: Hedef DuckDB dosya yolu.
        periods_per_year: Yıllık periyot sayısı.

    Returns:
        Kaydedilen kayıt sayısı (başarılı ise 1).
    """
    df = metrics_summary_to_polars(returns, periods_per_year=periods_per_year)
    target = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(target) if os.path.dirname(target) else ".", exist_ok=True)
    if os.path.exists(target) and os.path.getsize(target) == 0:
        with contextlib.suppress(OSError):
            os.remove(target)

    with duckdb.connect(target) as con:
        con.execute("PRAGMA checkpoint_threshold='4MB'")
        con.execute("PRAGMA wal_autocheckpoint='2MB'")
        con.execute("""
            CREATE TABLE IF NOT EXISTS strategy_performance_ledger (
                strategy_id VARCHAR NOT NULL,
                sharpe_ratio DOUBLE,
                sortino_ratio DOUBLE,
                max_drawdown DOUBLE,
                calmar_ratio DOUBLE,
                win_rate DOUBLE,
                profit_factor DOUBLE,
                omega_ratio DOUBLE,
                tail_ratio DOUBLE,
                var_95 DOUBLE,
                cvar_95 DOUBLE,
                total_periods BIGINT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_strategy_metrics_id ON strategy_performance_ledger (strategy_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_strategy_metrics_rec ON strategy_performance_ledger (recorded_at);")
        row = df.to_dicts()[0]
        query = (
            "INSERT INTO strategy_performance_ledger ("
            "strategy_id, sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio, "
            "win_rate, profit_factor, omega_ratio, tail_ratio, var_95, cvar_95, total_periods"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        con.execute(
            query,
            [
                str(strategy_id),
                row["sharpe_ratio"],
                row["sortino_ratio"],
                row["max_drawdown"],
                row["calmar_ratio"],
                row["win_rate"],
                row["profit_factor"],
                row.get("omega_ratio", 0.0),
                row.get("tail_ratio", 0.0),
                row["var_95"],
                row["cvar_95"],
                row["total_periods"],
            ],
        )
    return 1


# Geriye dönük uyumluluk takma adları
calculate_sharpe = calculate_sharpe_ratio
calculate_sortino = calculate_sortino_ratio

__all__: Final[list[str]] = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_PERIODS_PER_YEAR",
    "DEFAULT_RISK_FREE_RATE",
    "calculate_calmar_ratio",
    "calculate_ic",
    "calculate_information_ratio",
    "calculate_max_drawdown",
    "calculate_omega_ratio",
    "calculate_profit_factor",
    "calculate_rank_ic",
    "calculate_sharpe",
    "calculate_sharpe_ratio",
    "calculate_sortino",
    "calculate_sortino_ratio",
    "calculate_tail_ratio",
    "calculate_var_cvar",
    "calculate_win_rate",
    "clear_strategy_metrics_duckdb",
    "evaluate_strategy_viability",
    "export_metrics_to_duckdb",
    "export_metrics_to_orjson_bytes",
    "metrics_summary_to_polars",
    "otel_trace",
]
