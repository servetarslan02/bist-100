#!/usr/bin/env python3
"""
ALPHA BIST — SSD Write Benchmark v2 (Doğru Ölçüm)
===================================================
DuckDB commit sayısı + dosya boyutu + elapsed time ölçümü.
/proc/self/io yerine doğrudan DB commit sayısını sayar.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def count_file_writes(func, *args, **kwargs):
    """Dosya yazma sayısını ve boyutunu ölçer (monkey-patch ile)."""
    import duckdb

    write_count = [0]
    total_bytes = [0]

    # DuckDB connect ve commit'i wrap et
    original_connect = duckdb.connect

    def patched_connect(*a, **kw):
        conn = original_connect(*a, **kw)
        original_execute = conn.execute

        def counted_execute(sql, *params):
            write_count[0] += 1
            return original_execute(sql, *params)

        conn.execute = counted_execute

        if hasattr(conn, 'commit'):
            original_commit = conn.commit

            def counted_commit():
                total_bytes[0] += 1  # Her commit = 1 write operation
                return original_commit()

            conn.commit = counted_commit

        return conn

    duckdb.connect = patched_connect

    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start

    duckdb.connect = original_connect

    return {
        "result": result,
        "elapsed": round(elapsed, 4),
        "write_count": write_count[0],
        "commit_count": total_bytes[0],
    }


def benchmark_old(db_path, n=500):
    """Eski: her kayıtta commit."""
    import duckdb
    import orjson

    conn = duckdb.connect(db_path)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS s1 START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t1 (
            id INTEGER PRIMARY KEY DEFAULT nextval('s1'),
            ticker TEXT, direction TEXT, ret REAL, conf REAL,
            regime TEXT, features TEXT, created TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t2 (
            id TEXT PRIMARY KEY, date TEXT, ticker TEXT, side TEXT,
            qty INTEGER, price REAL, data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t3 (
            id TEXT PRIMARY KEY, date TEXT, ticker TEXT, side TEXT,
            qty INTEGER, price REAL, data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t4 (
            date TEXT PRIMARY KEY, equity REAL, cash REAL, invested REAL
        )
    """)
    conn.commit()

    for i in range(n):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        # 4 ayrı kayıt, her biri ayrı commit
        conn.execute("INSERT INTO t1 (ticker,direction,ret,conf,regime,features,created) VALUES (?,?,?,?,?,?,?)",
                     ("THYAO", "UP", 5.0, 0.75, "BULL", orjson.dumps({"rsi": 65}).decode(), now))
        conn.commit()
        conn.execute("INSERT OR REPLACE INTO t2 VALUES (?,?,?,?,?,?,?)",
                     (f"T{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "SELL", 100, 110.0, "{}"))
        conn.commit()
        conn.execute("INSERT OR REPLACE INTO t3 VALUES (?,?,?,?,?,?,?)",
                     (f"O{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "BUY", 100, 100.0, "{}"))
        conn.commit()
        conn.execute("INSERT OR REPLACE INTO t4 VALUES (?,?,?,?)",
                     (f"2026-08-{(i%30)+1:02d}", 100000.0+i, 50000.0, 50000.0))
        conn.commit()

    conn.close()


def benchmark_new(db_path, n=500):
    """Yeni: buffered write (batch 20, flush 30s)."""
    import duckdb
    import orjson

    buffer = []
    BUFFER_SIZE = 20

    conn = duckdb.connect(db_path)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS s1 START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t1 (
            id INTEGER PRIMARY KEY DEFAULT nextval('s1'),
            ticker TEXT, direction TEXT, ret REAL, conf REAL,
            regime TEXT, features TEXT, created TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t2 (
            id TEXT PRIMARY KEY, date TEXT, ticker TEXT, side TEXT,
            qty INTEGER, price REAL, data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t3 (
            id TEXT PRIMARY KEY, date TEXT, ticker TEXT, side TEXT,
            qty INTEGER, price REAL, data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t4 (
            date TEXT PRIMARY KEY, equity REAL, cash REAL, invested REAL
        )
    """)
    conn.commit()
    conn.close()

    def buffered_exec(sql, params):
        buffer.append((sql, params))
        if len(buffer) >= BUFFER_SIZE:
            flush()

    def flush():
        if not buffer:
            return
        conn = duckdb.connect(db_path)
        for sql, params in buffer:
            conn.execute(sql, params)
        conn.commit()
        conn.close()
        buffer.clear()

    for i in range(n):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        buffered_exec("INSERT INTO t1 (ticker,direction,ret,conf,regime,features,created) VALUES (?,?,?,?,?,?,?)",
                      ("THYAO", "UP", 5.0, 0.75, "BULL", orjson.dumps({"rsi": 65}).decode(), now))
        buffered_exec("INSERT OR REPLACE INTO t2 VALUES (?,?,?,?,?,?,?)",
                      (f"T{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "SELL", 100, 110.0, "{}"))
        buffered_exec("INSERT OR REPLACE INTO t3 VALUES (?,?,?,?,?,?,?)",
                      (f"O{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "BUY", 100, 100.0, "{}"))
        buffered_exec("INSERT OR REPLACE INTO t4 VALUES (?,?,?,?)",
                      (f"2026-08-{(i%30)+1:02d}", 100000.0+i, 50000.0, 50000.0))

    flush()


def benchmark_old_json(db_path, n=500):
    """Eski: her kayıtta JSON dosyaya yaz."""
    import orjson

    data = {"records": []}
    for i in range(n):
        data["records"].append({
            "ticker": "THYAO", "direction": "UP", "confidence": 0.75,
            "rsi": 65, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        # Her kayıtta dosyaya yaz (ESKİ YÖNTEM)
        with open(db_path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())


def benchmark_new_json(db_path, n=500):
    """Yeni: batch yaz (sadece sonunda)."""
    import orjson

    data = {"records": []}
    for i in range(n):
        data["records"].append({
            "ticker": "THYAO", "direction": "UP", "confidence": 0.75,
            "rsi": 65, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    # Tek seferde yaz (YENİ YÖNTEM)
    with open(db_path, "w") as f:
        f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())


def run():
    N = 500
    TMPDIR = tempfile.mkdtemp(prefix="ssd_bench2_")

    print("=" * 70)
    print("ALPHA BIST — SSD Write Benchmark v2 (Gerçek Ölçüm)")
    print(f"İşlem sayısı: {N} | Geçici dizin: {TMPDIR}")
    print("=" * 70)

    all_results = []

    # ─── Test 1: DuckDB Commit Sayısı ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 1: DuckDB Commit Sayısı Ölçümü")
    print(f"{'─' * 70}")

    old_db = os.path.join(TMPDIR, "old_duck.db")
    new_db = os.path.join(TMPDIR, "new_duck.db")

    old_r = count_file_writes(benchmark_old, old_db, N)
    new_r = count_file_writes(benchmark_new, new_db, N)

    old_size = os.path.getsize(old_db) if os.path.exists(old_db) else 0
    new_size = os.path.getsize(new_db) if os.path.exists(new_db) else 0

    commit_reduction = (1 - new_r["commit_count"] / old_r["commit_count"]) * 100 if old_r["commit_count"] > 0 else 0
    time_reduction = (1 - new_r["elapsed"] / old_r["elapsed"]) * 100 if old_r["elapsed"] > 0 else 0
    size_reduction = (1 - new_size / old_size) * 100 if old_size > 0 else 0

    print("\n  Eski (her kayıtta commit):")
    print(f"    Commit sayısı: {old_r['commit_count']:>8}")
    print(f"    Execute sayısı: {old_r['write_count']:>8}")
    print(f"    Süre: {old_r['elapsed']:>12.4f} s")
    print(f"    DB boyutu: {old_size:>12,} byte ({old_size/1024:.1f} KB)")

    print(f"\n  Yeni (buffered, batch={20}):")
    print(f"    Commit sayısı: {new_r['commit_count']:>8}")
    print(f"    Execute sayısı: {new_r['write_count']:>8}")
    print(f"    Süre: {new_r['elapsed']:>12.4f} s")
    print(f"    DB boyutu: {new_size:>12,} byte ({new_size/1024:.1f} KB)")

    print("\n  📉 Azalma:")
    print(f"    Commit sayısı: %{commit_reduction:>8.1f}")
    print(f"    Süre:          %{time_reduction:>8.1f}")
    print(f"    DB boyutu:     %{size_reduction:>8.1f}")

    all_results.append({
        "test": "DuckDB Commit",
        "old_commits": old_r["commit_count"],
        "new_commits": new_r["commit_count"],
        "commit_reduction_pct": round(commit_reduction, 1),
        "old_time": old_r["elapsed"],
        "new_time": new_r["elapsed"],
        "time_reduction_pct": round(time_reduction, 1),
        "old_size": old_size,
        "new_size": new_size,
        "size_reduction_pct": round(size_reduction, 1),
    })

    # ─── Test 2: JSON Dosya Yazma ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 2: JSON Dosya Yazma Sayısı")
    print(f"{'─' * 70}")

    old_json = os.path.join(TMPDIR, "old.json")
    new_json = os.path.join(TMPDIR, "new.json")

    start = time.perf_counter()
    benchmark_old_json(old_json, N)
    old_json_time = time.perf_counter() - start

    start = time.perf_counter()
    benchmark_new_json(new_json, N)
    new_json_time = time.perf_counter() - start

    old_json_size = os.path.getsize(old_json) if os.path.exists(old_json) else 0
    new_json_size = os.path.getsize(new_json) if os.path.exists(new_json) else 0

    print("\n  Eski (her kayıtta dosyaya yaz):")
    print(f"    Yazma sayısı: {N}")
    print(f"    Süre: {old_json_time:.4f} s")
    print(f"    Dosya boyutu: {old_json_size:,} byte")

    print("\n  Yeni (tek seferde batch yaz):")
    print("    Yazma sayısı: 1")
    print(f"    Süre: {new_json_time:.4f} s")
    print(f"    Dosya boyutu: {new_json_size:,} byte")

    json_write_reduction = (1 - 1 / N) * 100
    json_time_reduction = (1 - new_json_time / old_json_time) * 100 if old_json_time > 0 else 0

    print("\n  📉 Azalma:")
    print(f"    Yazma sayısı: %{json_write_reduction:.1f} ({N} → 1)")
    print(f"    Süre:         %{json_time_reduction:.1f}")

    all_results.append({
        "test": "JSON Dosya Yazma",
        "old_writes": N,
        "new_writes": 1,
        "write_reduction_pct": round(json_write_reduction, 1),
        "old_time": round(old_json_time, 4),
        "new_time": round(new_json_time, 4),
        "time_reduction_pct": round(json_time_reduction, 1),
    })

    # ─── Test 3: Debounce Etkisi ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 3: Debounce Etkisi (60s interval)")
    print(f"{'─' * 70}")

    from services.core.debounce import should_save

    # 100 çağrı, 60s debounce
    calls = 100
    allowed = 0
    for i in range(calls):
        if should_save("bench_debounce", 60.0):
            allowed += 1

    debounce_reduction = (1 - allowed / calls) * 100

    print(f"\n  {calls} çağrı yapıldı, 60s debounce ile:")
    print(f"    Gerçek yazma: {allowed}")
    print(f"    Atlanan: {calls - allowed}")
    print(f"    Azalma: %{debounce_reduction:.1f}")

    all_results.append({
        "test": "Debounce (60s)",
        "total_calls": calls,
        "actual_writes": allowed,
        "skipped": calls - allowed,
        "reduction_pct": round(debounce_reduction, 1),
    })

    # ─── Test 4: VirtualPortfolio Debounce ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 4: VirtualPortfolio save_to_store Debounce (30s)")
    print(f"{'─' * 70}")

    from services.core.debounce import _last_writes
    _last_writes.pop("virtual_portfolio_save", None)

    calls = 50
    allowed = 0
    for i in range(calls):
        if should_save("virtual_portfolio_save", 30.0):
            allowed += 1

    vp_reduction = (1 - allowed / calls) * 100

    print(f"\n  {calls} save_to_store çağrısı, 30s debounce ile:")
    print(f"    Gerçek yazma: {allowed}")
    print(f"    Atlanan: {calls - allowed}")
    print(f"    Azalma: %{vp_reduction:.1f}")

    all_results.append({
        "test": "VirtualPortfolio Debounce (30s)",
        "total_calls": calls,
        "actual_writes": allowed,
        "skipped": calls - allowed,
        "reduction_pct": round(vp_reduction, 1),
    })

    # ─── Genel Özet ───
    print(f"\n{'=' * 70}")
    print("📊 GENEL ÖZET — ROUND 5 SSD OPTİMİZASYON SONUÇLARI")
    print(f"{'=' * 70}")

    print(f"\n  {'Bileşen':<30} {'Eski':>12} {'Yeni':>12} {'Azalma':>10}")
    print(f"  {'─'*30} {'─'*12} {'─'*12} {'─'*10}")

    for r in all_results:
        if r["test"] == "DuckDB Commit":
            print(f"  {'DuckDB commit sayısı':<30} {r['old_commits']:>12} {r['new_commits']:>12} {'%'+str(r['commit_reduction_pct']):>10}")
            print(f"  {'DuckDB süre (s)':<30} {r['old_time']:>12.4f} {r['new_time']:>12.4f} {'%'+str(r['time_reduction_pct']):>10}")
        elif r["test"] == "JSON Dosya Yazma":
            print(f"  {'JSON yazma sayısı':<30} {r['old_writes']:>12} {r['new_writes']:>12} {'%'+str(r['write_reduction_pct']):>10}")
        elif "Debounce" in r["test"]:
            print(f"  {r['test']:<30} {r['total_calls']:>12} {r['actual_writes']:>12} {'%'+str(r['reduction_pct']):>10}")

    # Saatlik tahmini
    print("\n  📈 Saatlik SSD Yazma Tahmini:")
    # 500 işlem ~ gerçek senaryoda saatte ~2000 kayıt varsayımı
    scale = 2000 / N
    old_hourly_commits = all_results[0]["old_commits"] * scale
    new_hourly_commits = all_results[0]["new_commits"] * scale
    print(f"    Eski: ~{old_hourly_commits:.0f} commit/saat")
    print(f"    Yeni: ~{new_hourly_commits:.0f} commit/saat")
    print(f"    Tasarruf: ~{old_hourly_commits - new_hourly_commits:.0f} commit/saat")

    # Rapor kaydet
    report = {
        "benchmark_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "num_operations": N,
        "results": all_results,
        "summary": {
            "duckdb_commit_reduction_pct": all_results[0]["commit_reduction_pct"],
            "json_write_reduction_pct": all_results[1]["write_reduction_pct"],
            "debounce_60s_reduction_pct": all_results[2]["reduction_pct"],
            "debounce_30s_reduction_pct": all_results[3]["reduction_pct"],
        },
    }

    report_path = os.path.join(Path(__file__).parent.parent, "reports", "ssd_benchmark_v2.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  📄 Rapor: {report_path}")

    shutil.rmtree(TMPDIR, ignore_errors=True)

    print(f"\n{'=' * 70}")
    print("✅ Benchmark tamamlandı")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    run()
