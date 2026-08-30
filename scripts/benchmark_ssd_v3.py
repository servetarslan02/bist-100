#!/usr/bin/env python3
"""
ALPHA BIST — SSD Write Benchmark v3 (Basit & Doğru Ölçüm)
==========================================================
DuckDB commit sayısı + dosya boyutu + elapsed time ölçümü.
Monkey-patch yok, doğrudan sayaç ile.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def benchmark_old(db_path, n=500):
    """Eski: her kayıtta commit. Returns (commit_count, elapsed)."""
    import duckdb
    import orjson

    commits = 0
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
    commits += 1

    start = time.perf_counter()
    for i in range(n):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute("INSERT INTO t1 (ticker,direction,ret,conf,regime,features,created) VALUES (?,?,?,?,?,?,?)",
                     ("THYAO", "UP", 5.0, 0.75, "BULL", orjson.dumps({"rsi": 65}).decode(), now))
        conn.commit(); commits += 1
        conn.execute("INSERT OR REPLACE INTO t2 VALUES (?,?,?,?,?,?,?)",
                     (f"T{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "SELL", 100, 110.0, "{}"))
        conn.commit(); commits += 1
        conn.execute("INSERT OR REPLACE INTO t3 VALUES (?,?,?,?,?,?,?)",
                     (f"O{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "BUY", 100, 100.0, "{}"))
        conn.commit(); commits += 1
        conn.execute("INSERT OR REPLACE INTO t4 VALUES (?,?,?,?)",
                     (f"2026-08-{(i%30)+1:02d}", 100000.0+i, 50000.0, 50000.0))
        conn.commit(); commits += 1
    elapsed = time.perf_counter() - start
    conn.close()
    return commits, elapsed


def benchmark_new(db_path, n=500, batch_size=20):
    """Yeni: buffered write. Returns (commit_count, elapsed)."""
    import duckdb
    import orjson

    commits = 0
    buffer = []

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
    commits += 1
    conn.close()

    def flush():
        nonlocal commits
        if not buffer:
            return
        conn = duckdb.connect(db_path)
        for sql, params in buffer:
            conn.execute(sql, params)
        conn.commit()
        commits += 1
        conn.close()
        buffer.clear()

    start = time.perf_counter()
    for i in range(n):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        buffer.append(("INSERT INTO t1 (ticker,direction,ret,conf,regime,features,created) VALUES (?,?,?,?,?,?,?)",
                       ("THYAO", "UP", 5.0, 0.75, "BULL", orjson.dumps({"rsi": 65}).decode(), now)))
        buffer.append(("INSERT OR REPLACE INTO t2 VALUES (?,?,?,?,?,?,?)",
                       (f"T{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "SELL", 100, 110.0, "{}")))
        buffer.append(("INSERT OR REPLACE INTO t3 VALUES (?,?,?,?,?,?,?)",
                       (f"O{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "BUY", 100, 100.0, "{}")))
        buffer.append(("INSERT OR REPLACE INTO t4 VALUES (?,?,?,?)",
                       (f"2026-08-{(i%30)+1:02d}", 100000.0+i, 50000.0, 50000.0)))
        if len(buffer) >= batch_size * 4:  # 4 tablo * batch_size
            flush()
    flush()
    elapsed = time.perf_counter() - start
    return commits, elapsed


def benchmark_old_json(db_path, n=500):
    """Eski: her kayıtta JSON dosyaya yaz."""
    import orjson
    data = {"records": []}
    start = time.perf_counter()
    for i in range(n):
        data["records"].append({"ticker": "THYAO", "i": i, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
        with open(db_path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
    return n, time.perf_counter() - start


def benchmark_new_json(db_path, n=500):
    """Yeni: tek seferde batch yaz."""
    import orjson
    data = {"records": []}
    start = time.perf_counter()
    for i in range(n):
        data["records"].append({"ticker": "THYAO", "i": i, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    with open(db_path, "w") as f:
        f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
    return 1, time.perf_counter() - start


def run():
    N = 500
    TMPDIR = tempfile.mkdtemp(prefix="ssd_bench3_")

    print("=" * 70)
    print("ALPHA BIST — SSD Write Benchmark v3 (Gerçek Ölçüm)")
    print(f"İşlem sayısı: {N} | Batch size: 20")
    print("=" * 70)

    results = []

    # ─── Test 1: DuckDB ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 1: DuckDB — Her kayıtta commit vs Buffered Write")
    print(f"{'─' * 70}")

    old_db = os.path.join(TMPDIR, "old.db")
    new_db = os.path.join(TMPDIR, "new.db")

    old_commits, old_time = benchmark_old(old_db, N)
    new_commits, new_time = benchmark_new(new_db, N)

    old_size = os.path.getsize(old_db)
    new_size = os.path.getsize(new_db)

    commit_red = (1 - new_commits / old_commits) * 100
    time_red = (1 - new_time / old_time) * 100 if old_time > 0 else 0
    size_red = (1 - new_size / old_size) * 100 if old_size > 0 else 0

    print(f"\n  {'Metrik':<25} {'Eski':>15} {'Yeni':>15} {'Azalma':>12}")
    print(f"  {'─'*25} {'─'*15} {'─'*15} {'─'*12}")
    print(f"  {'Commit sayısı':<25} {old_commits:>15} {new_commits:>15} {'%'+f'{commit_red:.1f}':>12}")
    print(f"  {'Süre (s)':<25} {old_time:>15.4f} {new_time:>15.4f} {'%'+f'{time_red:.1f}':>12}")
    print(f"  {'DB boyutu (KB)':<25} {old_size/1024:>15.1f} {new_size/1024:>15.1f} {'%'+f'{size_red:.1f}':>12}")

    results.append({"test": "DuckDB", "old_commits": old_commits, "new_commits": new_commits,
                     "commit_reduction": round(commit_red, 1), "old_time": round(old_time, 4),
                     "new_time": round(new_time, 4), "time_reduction": round(time_red, 1)})

    # ─── Test 2: JSON ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 2: JSON Dosya — Her kayıtta yaz vs Batch yaz")
    print(f"{'─' * 70}")

    old_json = os.path.join(TMPDIR, "old.json")
    new_json = os.path.join(TMPDIR, "new.json")

    old_writes, old_jtime = benchmark_old_json(old_json, N)
    new_writes, new_jtime = benchmark_new_json(new_json, N)

    write_red = (1 - new_writes / old_writes) * 100
    jtime_red = (1 - new_jtime / old_jtime) * 100 if old_jtime > 0 else 0

    print(f"\n  {'Metrik':<25} {'Eski':>15} {'Yeni':>15} {'Azalma':>12}")
    print(f"  {'─'*25} {'─'*15} {'─'*15} {'─'*12}")
    print(f"  {'Yazma sayısı':<25} {old_writes:>15} {new_writes:>15} {'%'+f'{write_red:.1f}':>12}")
    print(f"  {'Süre (s)':<25} {old_jtime:>15.4f} {new_jtime:>15.4f} {'%'+f'{jtime_red:.1f}':>12}")

    results.append({"test": "JSON", "old_writes": old_writes, "new_writes": new_writes,
                     "write_reduction": round(write_red, 1), "old_time": round(old_jtime, 4),
                     "new_time": round(new_jtime, 4), "time_reduction": round(jtime_red, 1)})

    # ─── Test 3: Debounce ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 3: Debounce Etkisi")
    print(f"{'─' * 70}")

    from services.core.debounce import _last_writes

    for interval_name, interval_sec in [("60s", 60.0), ("30s", 30.0), ("120s", 120.0)]:
        key = f"bench_{interval_name}"
        _last_writes.pop(key, None)
        from services.core.debounce import should_save
        calls = 100
        allowed = sum(1 for _ in range(calls) if should_save(key, interval_sec))
        red = (1 - allowed / calls) * 100
        print(f"  Debounce {interval_name}: {calls} çağrı → {allowed} yazma (azalma: %{red:.0f})")
        results.append({"test": f"Debounce {interval_name}", "calls": calls, "writes": allowed, "reduction": round(red, 1)})

    # ─── Test 4: Batch Size Etkisi ───
    print(f"\n{'─' * 70}")
    print("📊 TEST 4: Batch Size Etkisi (DuckDB)")
    print(f"{'─' * 70}")

    for bs in [1, 5, 10, 20, 50]:
        db = os.path.join(TMPDIR, f"bs_{bs}.db")
        commits, elapsed = benchmark_new(db, N, bs)
        size = os.path.getsize(db) / 1024
        print(f"  Batch={bs:>3}: {commits:>4} commit, {elapsed:.4f}s, {size:.1f} KB")
        results.append({"test": f"Batch size {bs}", "commits": commits, "time": round(elapsed, 4), "size_kb": round(size, 1)})

    # ─── Genel Özet ───
    print(f"\n{'=' * 70}")
    print("📊 GENEL ÖZET — ROUND 5 SSD OPTİMİZASYON SONUÇLARI")
    print(f"{'=' * 70}")

    duckdb_result = results[0]
    json_result = results[1]

    print(f"\n  1. DuckDB Commit Azalması:")
    print(f"     Eski: {duckdb_result['old_commits']} commit")
    print(f"     Yeni: {duckdb_result['new_commits']} commit")
    print(f"     ➜ %{duckdb_result['commit_reduction']} azalma")

    print(f"\n  2. JSON Dosya Yazma Azalması:")
    print(f"     Eski: {json_result['old_writes']} yazma")
    print(f"     Yeni: {json_result['new_writes']} yazma")
    print(f"     ➜ %{json_result['write_reduction']} azalma")

    print(f"\n  3. Debounce Etkisi (60s interval):")
    debounce_result = [r for r in results if r['test'] == 'Debounce 60s'][0]
    print(f"     100 çağrı → {debounce_result['writes']} gerçek yazma")
    print(f"     ➜ %{debounce_result['reduction']} azalma")

    print(f"\n  4. Batch Size Karşılaştırması:")
    for r in results:
        if r['test'].startswith('Batch size'):
            print(f"     {r['test']}: {r['commits']} commit, {r['time']}s")

    # Saatlik tahmini
    print(f"\n  📈 Saatlik Tahmini (sürekli çalışma):")
    scale = 2000 / N
    old_hourly = duckdb_result['old_commits'] * scale
    new_hourly = duckdb_result['new_commits'] * scale
    print(f"     Eski: ~{old_hourly:.0f} commit/saat")
    print(f"     Yeni: ~{new_hourly:.0f} commit/saat")
    print(f"     Tasarruf: ~{old_hourly - new_hourly:.0f} commit/saat")

    # Rapor
    report = {
        "benchmark_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "num_operations": N,
        "batch_size": 20,
        "results": results,
        "summary": {
            "duckdb_commit_reduction_pct": duckdb_result['commit_reduction'],
            "json_write_reduction_pct": json_result['write_reduction'],
            "debounce_60s_reduction_pct": debounce_result['reduction'],
        },
    }

    report_path = os.path.join(Path(__file__).parent.parent, "reports", "ssd_benchmark_v3.json")
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
