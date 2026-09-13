import duckdb

conn = duckdb.connect('data/bist_all_10y_warehouse.duckdb', read_only=True)
print("=== DUCKDB AMBAR TABLOLARI ===")
print(conn.execute("SHOW TABLES").fetchall())

print("\n=== VERİ SAYILARI ===")
bm_count = conn.execute("SELECT count(*) FROM benchmark_xu100_10y").fetchone()[0]
stock_count = conn.execute("SELECT count(*) FROM stock_candles_10y").fetchone()[0]
sym_count = conn.execute("SELECT count(distinct symbol) FROM stock_candles_10y").fetchone()[0]
min_date = conn.execute("SELECT min(date), max(date) FROM stock_candles_10y").fetchone()
print(f"XU100 Günlük Bar: {bm_count:,}")
print(f"Hisse Günlük Bar: {stock_count:,}")
print(f"Benzersiz Sembol Sayısı: {sym_count}")
print(f"Tarih Aralığı: {min_date[0]} - {min_date[1]}")

print("\n=== TARİHİ BIST DÖNÜM NOKTALARI (GERÇEK BORSA VERİSİ KANITI) ===")
# 2018 Kur Şoku
r_2018 = conn.execute("SELECT symbol, date, open, high, low, close, volume FROM stock_candles_10y WHERE symbol='THYAO' AND date='2018-08-10'").fetchone()
print(f"2018 Rahip Brunson / Kur Kriz Günü (THYAO): {r_2018}")

# 2020 Covid Dibi
r_covid = conn.execute("SELECT symbol, date, open, high, low, close, volume FROM stock_candles_10y WHERE symbol='THYAO' AND date='2020-03-23'").fetchone()
print(f"2020 Covid Dibi (THYAO): {r_covid}")

# 2023 Enflasyon Rallisi
r_2023 = conn.execute("SELECT symbol, date, open, high, low, close, volume FROM stock_candles_10y WHERE symbol='THYAO' AND date='2023-10-02'").fetchone()
print(f"2023 Zirvesi (THYAO): {r_2023}")

# XU100 Benchmark Kontrolü
bm_covid = conn.execute("SELECT date, open, high, low, close, volume FROM benchmark_xu100_10y WHERE date='2020-03-23'").fetchone()
print(f"2020 Covid Dibi (XU100): {bm_covid}")
bm_2023 = conn.execute("SELECT date, open, high, low, close, volume FROM benchmark_xu100_10y WHERE date='2023-10-02'").fetchone()
print(f"2023 Zirvesi (XU100): {bm_2023}")

conn.close()
