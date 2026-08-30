import time
import sys
import numpy as np

# 1. SERİLEŞTİRME TESTİ: orjson vs standart json
print("=" * 80)
print("1. SERİLEŞTİRME HIZ TESTİ: orjson vs standart json (650 Hisse Piyasa Paketi)")
print("=" * 80)

# 650 hisselik zengin piyasa derinlik simülasyonu
market_payload = [
    {
        "ticker": f"BIST_{i}",
        "price": 100.0 + (i * 0.15),
        "change_pct": 2.34,
        "volume": 1540200 + (i * 1000),
        "score": 78.5,
        "rsi": 64.2,
        "features": [np.random.rand() for _ in range(17)],
        "timestamp": "2026-08-30T10:00:00Z"
    }
    for i in range(650)
]

import json
import orjson

# Standart json benchmark
t0 = time.perf_counter()
for _ in range(100):
    raw = json.dumps(market_payload)
    parsed = json.loads(raw)
t_json = (time.perf_counter() - t0) * 1000

# orjson benchmark
t0 = time.perf_counter()
for _ in range(100):
    raw_b = orjson.dumps(market_payload)
    parsed_b = orjson.loads(raw_b)
t_orjson = (time.perf_counter() - t0) * 1000

speedup_json = t_json / max(t_orjson, 1e-4)
print(f"  * Standart json süresi (100 döngü) : {t_json:.2f} ms")
print(f"  * Rust tabanlı orjson süresi (100 döngü): {t_orjson:.2f} ms")
print(f"  🚀 orjson KAZANCI: {speedup_json:.1f}x KAT DAHA HIZLI!")


# 2. VERİTABANI ANALİTİK TESTİ: DuckDB vs SQLite (100,000 Satır Mum Verisi)
print("\n" + "=" * 80)
print("2. VERİTABANI ANALİTİK TESTİ: DuckDB vs SQLite (100,000 Satır Agregasyon & Filtreleme)")
print("=" * 80)

import sqlite3
import duckdb

# Bellek içi SQLite
sqlite_conn = sqlite3.connect(":memory:")
sqlite_cur = sqlite_conn.cursor()
sqlite_cur.execute("CREATE TABLE candles (ticker TEXT, date TEXT, close REAL, volume REAL)")
rows = [(f"TICK_{i % 50}", f"2026-01-{(i % 28) + 1:02d}", 100.0 + (i % 50), 50000.0 + (i % 1000)) for i in range(100_000)]
sqlite_cur.executemany("INSERT INTO candles VALUES (?, ?, ?, ?)", rows)
sqlite_conn.commit()

# SQLite Analitik Sorgu (Group by, Avg, Max, Count)
t0 = time.perf_counter()
for _ in range(20):
    sqlite_cur.execute("SELECT ticker, AVG(close), MAX(close), SUM(volume) FROM candles WHERE close > 120 GROUP BY ticker")
    _ = sqlite_cur.fetchall()
t_sqlite = (time.perf_counter() - t0) * 1000
sqlite_conn.close()

# Bellek içi DuckDB
duck_conn = duckdb.connect(":memory:")
duck_conn.execute("CREATE TABLE candles (ticker VARCHAR, date VARCHAR, close DOUBLE, volume DOUBLE)")
duck_conn.executemany("INSERT INTO candles VALUES (?, ?, ?, ?)", rows)

# DuckDB Kolonsal Analitik Sorgu
t0 = time.perf_counter()
for _ in range(20):
    _ = duck_conn.execute("SELECT ticker, AVG(close), MAX(close), SUM(volume) FROM candles WHERE close > 120 GROUP BY ticker").fetchall()
t_duck = (time.perf_counter() - t0) * 1000
duck_conn.close()

speedup_db = t_sqlite / max(t_duck, 1e-4)
print(f"  * SQLite sorgu süresi (20 döngü) : {t_sqlite:.2f} ms")
print(f"  * Kolonsal DuckDB süresi (20 döngü): {t_duck:.2f} ms")
print(f"  🚀 DuckDB KAZANCI: {speedup_db:.1f}x KAT DAHA HIZLI!")


# 3. VERİ İŞLEME TESTİ: Polars vs Pandas (100,000 Satır Teknik Feature Hesaplama)
print("\n" + "=" * 80)
print("3. VERİ MOTORU TESTİ: Polars vs Pandas (100,000 Satır Rolling SMA & Volatilite)")
print("=" * 80)

import pandas as pd
import polars as pl

prices = np.random.randn(100_000).cumsum() + 100

# Pandas
t0 = time.perf_counter()
for _ in range(10):
    df_pd = pd.DataFrame({"close": prices})
    df_pd["sma20"] = df_pd["close"].rolling(20).mean()
    df_pd["std20"] = df_pd["close"].rolling(20).std()
    df_pd["ret"] = df_pd["close"].pct_change()
t_pandas = (time.perf_counter() - t0) * 1000

# Polars
t0 = time.perf_counter()
for _ in range(10):
    df_pl = pl.DataFrame({"close": prices})
    df_pl = df_pl.with_columns([
        pl.col("close").rolling_mean(20).alias("sma20"),
        pl.col("close").rolling_std(20).alias("std20"),
        pl.col("close").pct_change().alias("ret")
    ])
t_polars = (time.perf_counter() - t0) * 1000

speedup_df = t_pandas / max(t_polars, 1e-4)
print(f"  * Pandas işlem süresi (10 döngü): {t_pandas:.2f} ms")
print(f"  * Rust tabanlı Polars süresi (10 döngü): {t_polars:.2f} ms")
print(f"  🚀 Polars KAZANCI: {speedup_df:.1f}x KAT DAHA HIZLI!")
print("=" * 80)
