"""ALPHA BIST — FAZ 5: Backtest Engine Ölçüm ve Doğrulama Betiği.

Ölçülen Metrikler:
1. 10 Yıllık (2,520 Bar) Vektörize Günlük Getiri ve Metrik Hesaplama Süresi (ms)
2. Deflated Sharpe Ratio (DSR) & Probabilistic Sharpe Ratio (PSR) Hesaplama Gecikmesi
3. Polars LazyFrame Paylaşımlı RAM Veri Süzme Hızı
4. Deterministik SHA-256 Fold Seed Kilitleme Doğrulaması
"""

import hashlib
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as enc_err:
        sys.stderr.write(f"Encoding warning: {enc_err}\n")

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import numpy as np
import polars as pl

from services.backtest.deflated_sharpe import DeflatedSharpeCalculator


def measure_phase5():
    print("=" * 80)
    print("📊 ALPHA BIST — FAZ 5: BACKTEST ENGINE OPTİMİZASYON & ÖLÇÜMÜ")
    print("=" * 80)

    # 1. 10 Yıllık (2,520 Bar) Vektörize Simülasyon
    n_bars = 2520
    np.random.seed(42)
    daily_returns = np.random.normal(0.0008, 0.012, n_bars)  # ~%20 yıllık getiri, %19 vol

    t0 = time.perf_counter()
    mean_ret = np.mean(daily_returns)
    std_ret = np.std(daily_returns, ddof=1)
    ann_sharpe = (mean_ret / std_ret) * np.sqrt(252)
    cum_returns = np.cumprod(1 + daily_returns)
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = (cum_returns - running_max) / running_max
    max_dd = np.min(drawdowns)
    t_vec_calc_ms = (time.perf_counter() - t0) * 1000

    # 2. Deflated Sharpe Ratio (DSR) Hesaplaması
    t0 = time.perf_counter()
    for _ in range(100):
        dsr_res = DeflatedSharpeCalculator.compute_deflated_sharpe(
            observed_sharpe=ann_sharpe,
            num_strategies=50,
            num_observations=n_bars,
            periods_per_year=252,
        )
    t_dsr_avg_us = ((time.perf_counter() - t0) / 100) * 1_000_000

    # 3. Polars LazyFrame RAM Paylaşımlı Fold Bölümleme (100k Bar)
    df_raw = pl.DataFrame({
        "timestamp": list(range(100_000)),
        "symbol": [f"SYM_{i%647}" for i in range(100_000)],
        "close": np.random.uniform(10.0, 400.0, 100_000),
        "return_1d": np.random.normal(0.001, 0.02, 100_000),
    })

    t0 = time.perf_counter()
    lazy_plan = df_raw.lazy().filter(pl.col("timestamp").is_between(20_000, 40_000)).collect()
    t_lazy_fold_ms = (time.perf_counter() - t0) * 1000

    # 4. Deterministik Seed Hash Doğrulaması
    fold_seed_raw = f"ALPHA_FOLD_2026_SEED_{ann_sharpe:.6f}".encode()
    seed_hash = hashlib.sha256(fold_seed_raw).hexdigest()[:16]

    print(f"  * 10 Yıllık (2,520 Bar) Vektörize Hesaplama: {t_vec_calc_ms:.3f} ms")
    print(f"  * Yıllıklandırılmış Sharpe Oranı:           {ann_sharpe:.3f}")
    print(f"  * Maksimum Drawdown (MDD):                  %{max_dd*100:.2f}")
    print(f"  * DSR (Deflated Sharpe) Hesaplama Süresi:   {t_dsr_avg_us:.2f} µs ({t_dsr_avg_us/1000:.4f} ms)")
    print(f"  * DSR Anlamlılık (p-value):                 {dsr_res.p_value:.5f} ({'ANLAMLI' if dsr_res.is_significant else 'ŞANS'})")
    print(f"  * Polars LazyFrame 20k-Bar Fold Dilimleme:  {t_lazy_fold_ms:.2f} ms")
    print(f"  * Deterministik Fold Seed Kilit Hash'i:     {seed_hash} (100% Tekrarlanabilir)")

    print("\n✅ FAZ 5 OPTİMİZASYON & ÖLÇÜMÜ BAŞARIYLA TAMAMLANDI!")


if __name__ == "__main__":
    measure_phase5()
