"""ALPHA BIST — FAZ 2: Data Layer Ölçüm ve Doğrulama Betiği.

Ölçülen Metrikler:
1. Redis Tekli İşlem vs Pipeline Batching Hızlanması
2. DuckDB Parquet Projection Pushdown (Sütun ve Satır Filtreleme) İşlem Hızı
3. DuckDB Throughput (Satır/Saniye ve Veri Hacmi)
"""

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

from services.core.duckdb_research import DuckDBResearchEngine
from services.core.redis_helper import get_cached, mget_cached, mset_cached, set_cached


def measure_phase2():
    print("=" * 80)
    print("⚡ ALPHA BIST — FAZ 2: DATA LAYER OPTİMİZASYON & ÖLÇÜMÜ")
    print("=" * 80)

    # 1. Redis Cache & Pipeline Batching Ölçümü
    n_keys = 200
    test_data = {f"bench_key_{i}": {"ticker": f"SYM_{i%647}", "price": 10.0 + i, "vol": 1000 + i} for i in range(n_keys)}

    # Tek tek yazma & okuma
    t0 = time.perf_counter()
    for k, v in test_data.items():
        set_cached(k, v, ttl=60)
        _ = get_cached(k)
    t_single_ms = (time.perf_counter() - t0) * 1000

    # Pipeline Batch yazma & okuma
    t0 = time.perf_counter()
    mset_cached(test_data, ttl=60)
    res_batch = mget_cached(list(test_data.keys()))
    t_batch_ms = (time.perf_counter() - t0) * 1000

    speedup_redis = round(t_single_ms / max(t_batch_ms, 0.001), 1)

    # 2. DuckDB Parquet Projection Pushdown Ölçümü (200,000 Satır)
    n_rows = 200_000
    df = pl.DataFrame({
        "ticker": [f"SYM_{i%647}" for i in range(n_rows)],
        "price": np.random.uniform(5.0, 500.0, n_rows).astype(np.float32),
        "volume": np.random.randint(100, 10_000_000, n_rows),
        "rsi_14": np.random.uniform(20.0, 80.0, n_rows).astype(np.float32),
        "unused_col1": np.random.randn(n_rows).astype(np.float32),
        "unused_col2": np.random.randn(n_rows).astype(np.float32),
    })

    parquet_file = "data/measure_phase2_pushdown.parquet"
    Path(parquet_file).parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(parquet_file)

    duck = DuckDBResearchEngine("data/measure_phase2_duck.duckdb")

    # Pushdown olmadan (Tüm sütunları oku)
    t0 = time.perf_counter()
    df_all = duck.query_parquet(parquet_file, "SELECT *")
    t_full_read_ms = (time.perf_counter() - t0) * 1000

    # Pushdown ile (Sadece gerekli 2 sütun ve WHERE filtresi)
    t0 = time.perf_counter()
    df_pushdown = duck.query_parquet_columns(parquet_file, columns=["ticker", "price"], where_clause="price > 250.0")
    t_pushdown_ms = (time.perf_counter() - t0) * 1000
    duck.close()

    throughput_rows_sec = int(n_rows / max(t_pushdown_ms / 1000, 0.001))
    speedup_duck = round(t_full_read_ms / max(t_pushdown_ms, 0.001), 1)

    print(f"  * Redis 200 Kayıt Tekli Gecikme:     {t_single_ms:.2f} ms")
    print(f"  * Redis 200 Kayıt Batch Gecikme:     {t_batch_ms:.2f} ms ({speedup_redis}x Kat Daha Hızlı)")
    print(f"  * DuckDB 200k Satır Full Okuma:      {t_full_read_ms:.2f} ms")
    print(f"  * DuckDB 200k Satır Pushdown Okuma:  {t_pushdown_ms:.2f} ms ({speedup_duck}x Hızlanma)")
    print(f"  * DuckDB Pushdown Verimi:            {throughput_rows_sec:,} satır/saniye")

    print("\n✅ FAZ 2 OPTİMİZASYON & ÖLÇÜMÜ BAŞARIYLA TAMAMLANDI!")


if __name__ == "__main__":
    measure_phase2()
