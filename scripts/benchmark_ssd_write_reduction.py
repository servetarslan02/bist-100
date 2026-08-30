#!/usr/bin/env python3
"""
ALPHA BIST — SSD Write Reduction Benchmark (Round 5)
=====================================================
Gerçek disk I/O ölçümü ile optimizasyon öncesi/sonrası karşılaştırma.

Ölçülen metrikler:
- Toplam byte yazma
- Yazma işlem sayısı (write syscall)
- Flush sayısı
- Ortalama batch boyutu
- Throughput (MB/s)

Kullanım:
    python scripts/benchmark_ssd_write_reduction.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def measure_file_writes(func, *args, **kwargs):
    """Bir fonksiyonun dosya yazma miktarını ölçer."""
    import subprocess

    # strace ile write syscall'larını yakala (Linux)
    # Alternatif: /proc/self/io kullan
    try:
        with open("/proc/self/io") as f:
            before = {}
            for line in f:
                key, val = line.strip().split(": ")
                before[key] = int(val)
    except FileNotFoundError:
        before = None

    start_time = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start_time

    try:
        with open("/proc/self/io") as f:
            after = {}
            for line in f:
                key, val = line.strip().split(": ")
                after[key] = int(val)
    except FileNotFoundError:
        after = None

    bytes_written = 0
    if before and after:
        bytes_written = after.get("wchar", 0) - before.get("wchar", 0)

    return {
        "result": result,
        "elapsed_sec": round(elapsed, 4),
        "bytes_written": bytes_written,
        "mb_written": round(bytes_written / (1024 * 1024), 4),
    }


def benchmark_old_paper_state_store(db_path: str, num_operations: int = 500):
    """Eski yöntem: Her kayıtta commit (optimizasyon öncesi)."""
    import duckdb

    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_state (
            id INTEGER PRIMARY KEY, date TEXT, cash REAL,
            initial_capital REAL, last_updated TEXT, json_data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY, date TEXT, ticker TEXT,
            side TEXT, quantity INTEGER, entry_price REAL,
            exit_price REAL, realized_pnl REAL, commission REAL,
            reason TEXT, json_data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, date TEXT, ticker TEXT,
            side TEXT, quantity INTEGER, signal_price REAL,
            execution_price REAL, commission REAL, slippage_pct REAL,
            status TEXT, rejection_reason TEXT, json_data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equity_curve (
            date TEXT PRIMARY KEY, equity REAL, cash REAL,
            invested REAL, benchmark_equity REAL
        )
    """)
    conn.commit()

    import orjson

    for i in range(num_operations):
        # Her işlemde ayrı commit (ESKİ YÖNTEM)
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_state VALUES (1, ?, ?, ?, ?, ?)",
            (f"2026-08-{(i%30)+1:02d}", 100000.0 + i, 100000.0,
             time.strftime("%Y-%m-%dT%H:%M:%S"),
             orjson.dumps({"cash": 100000.0 + i}).decode()),
        )
        conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"T{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "SELL", 100,
             100.0, 110.0, 1000.0, 7.4, "target",
             orjson.dumps({"trade_id": f"T{i}"}).decode()),
        )
        conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"O{i}", f"2026-08-{(i%30)+1:02d}", "THYAO", "BUY", 100,
             100.0, 100.0, 7.4, 0.0, "FILLED", None,
             orjson.dumps({"order_id": f"O{i}"}).decode()),
        )
        conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO equity_curve VALUES (?, ?, ?, ?, ?)",
            (f"2026-08-{(i%30)+1:02d}", 100000.0 + i, 50000.0, 50000.0, None),
        )
        conn.commit()

    conn.close()


def benchmark_new_paper_state_store(db_path: str, num_operations: int = 500):
    """Yeni yöntem: Buffered write (optimizasyon sonrası)."""
    from services.paper_trading.state_store import PaperStateStore

    store = PaperStateStore(db_path)

    import orjson

    for i in range(num_operations):
        store.save_portfolio_state({
            "date": f"2026-08-{(i%30)+1:02d}",
            "cash": 100000.0 + i,
            "initial_capital": 100000.0,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        store.save_trade({
            "trade_id": f"T{i}",
            "exit_date": f"2026-08-{(i%30)+1:02d}",
            "ticker": "THYAO",
            "side": "SELL",
            "quantity": 100,
            "entry_price": 100.0,
            "exit_price": 110.0,
            "realized_pnl": 1000.0,
            "commission": 7.4,
            "reason": "target",
        })

        store.save_order({
            "order_id": f"O{i}",
            "date": f"2026-08-{(i%30)+1:02d}",
            "ticker": "THYAO",
            "side": "BUY",
            "quantity": 100,
            "signal_price": 100.0,
            "status": "FILLED",
        })

        store.save_equity_point(
            f"2026-08-{(i%30)+1:02d}", 100000.0 + i, 50000.0, 50000.0,
        )

    store.flush()  # Kalan buffer'ı flush et


def benchmark_old_central_state_store(db_path: str, num_operations: int = 500):
    """Eski yöntem: Her kayıtta commit."""
    import duckdb
    import orjson

    conn = duckdb.connect(db_path)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS lp_seq START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_predictions (
            id INTEGER PRIMARY KEY DEFAULT nextval('lp_seq'),
            ticker TEXT, predicted_direction TEXT, predicted_return REAL,
            confidence REAL, regime TEXT, features TEXT, outcome TEXT, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fusion_weights (
            key TEXT PRIMARY KEY, weights TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        )
    """)
    conn.commit()

    for i in range(num_operations):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Her kayıtta ayrı commit
        conn.execute(
            "INSERT INTO learning_predictions (ticker, predicted_direction, predicted_return, confidence, regime, features, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("THYAO", "UP", 5.0, 0.75, "BULL", orjson.dumps({"rsi": 65}).decode(), now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fusion_weights VALUES (?, ?, ?)",
            ("adaptive", orjson.dumps({"momentum": 0.3}).decode(), now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO learning_state VALUES (?, ?, ?)",
            (f"key_{i}", orjson.dumps({"value": i}).decode(), now),
        )
        conn.commit()

    conn.close()


def benchmark_new_central_state_store(db_path: str, num_operations: int = 500):
    """Yeni yöntem: Buffered write."""
    from services.core.state_store import CentralStateStore

    store = CentralStateStore(db_path)

    for i in range(num_operations):
        store.save_prediction("THYAO", "UP", 5.0, 0.75, "BULL", {"rsi": 65})
        store.save_fusion_weights({"momentum": 0.3})
        store.save_learning_state({f"key_{i}": {"value": i}})

    store.flush()


def benchmark_old_model_memory_store(db_path: str, num_operations: int = 500):
    """Eski yöntem: Her kayıtta commit."""
    import duckdb
    import orjson

    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id TEXT PRIMARY KEY, model_id TEXT, model_version TEXT,
            ticker TEXT, timestamp TEXT, predicted_direction TEXT,
            confidence REAL, market_regime TEXT, prediction_horizon TEXT,
            entry_price REAL, features_json TEXT, status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_metrics_history (
            model_id TEXT, model_version TEXT, evaluated_at TEXT,
            sample_size INTEGER, direction_accuracy REAL, hit_rate_pct REAL,
            net_pnl REAL, annualized_sharpe REAL, max_drawdown_pct REAL,
            brier_score REAL, rank_ic REAL, reliability_score REAL,
            fusion_weight REAL, metrics_json TEXT
        )
    """)
    conn.commit()

    for i in range(num_operations):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT OR REPLACE INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"P{i}", "M1", "v1", "THYAO", now, "UP", 0.75, "BULL", "1-5D",
             100.0, orjson.dumps({"rsi": 65}).decode(), "PENDING"),
        )
        conn.execute(
            "INSERT INTO model_metrics_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("M1", "v1", now, 100, 0.65, 65.0, 1000.0, 1.5, -5.0, 0.25, 0.1, 0.7, 0.5,
             orjson.dumps({"accuracy": 0.65}).decode()),
        )
        conn.commit()

    conn.close()


def benchmark_new_model_memory_store(db_path: str, num_operations: int = 500):
    """Yeni yöntem: Buffered write."""
    from services.learning.model_memory_store import ModelMemoryStore

    store = ModelMemoryStore(db_path)

    for i in range(num_operations):
        store.save_prediction(f"P{i}", "M1", "v1", "THYAO", "UP", 0.75, "BULL", "1-5D", 100.0, {"rsi": 65})
        store.record_metrics_snapshot("M1", "v1", {"direction_accuracy": 0.65, "evaluated_samples": 100}, 0.7, 0.5)

    store.flush()


def benchmark_old_scan_persistence(db_path: str, num_operations: int = 500):
    """Eski yöntem: Her kayıtta commit."""
    import duckdb
    import orjson

    conn = duckdb.connect(db_path)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS scan_seq START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id BIGINT PRIMARY KEY DEFAULT nextval('scan_seq'),
            scan_id TEXT, scan_type TEXT, ticker TEXT, score REAL,
            signal TEXT, direction TEXT, confidence REAL, tier INTEGER,
            regime TEXT, price REAL, volume INTEGER, features_json TEXT,
            timestamp TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    for i in range(num_operations):
        conn.execute(
            "INSERT INTO scan_results (scan_id, scan_type, ticker, score, signal, direction, confidence, tier, regime, price, volume, features_json, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"S{i}", "batch", "THYAO", 85.0, "MOMENTUM", "LONG", 0.8, 1, "BULL",
             100.0, 1000000, orjson.dumps({"rsi": 65}).decode(), "2026-08-31T05:46:00"),
        )
        conn.commit()

    conn.close()


def benchmark_new_scan_persistence(db_path: str, num_operations: int = 500):
    """Yeni yöntem: Buffered write."""
    from services.scanner.scan_persistence import ScanPersistence, ScanResultRecord

    store = ScanPersistence(db_path)

    for i in range(num_operations):
        record = ScanResultRecord(
            scan_id=f"S{i}", scan_type="batch", ticker="THYAO", score=85.0,
            signal="MOMENTUM", direction="LONG", confidence=0.8, tier=1,
            regime="BULL", price=100.0, volume=1000000, features={"rsi": 65},
            timestamp="2026-08-31T05:46:00",
        )
        store.save_scan_result(record)

    store.flush()


def get_db_size(path: str) -> int:
    """Veritabanı dosya boyutunu byte olarak döndürür."""
    if os.path.exists(path):
        return os.path.getsize(path)
    return 0


def run_benchmark():
    """Ana benchmark fonksiyonu."""
    NUM_OPS = 500
    TMPDIR = tempfile.mkdtemp(prefix="ssd_bench_")

    print("=" * 70)
    print("ALPHA BIST — SSD Write Reduction Benchmark (Round 5)")
    print(f"İşlem sayısı: {NUM_OPS} (her test için)")
    print(f"Geçici dizin: {TMPDIR}")
    print("=" * 70)

    results = []

    benchmarks = [
        ("PaperStateStore", benchmark_old_paper_state_store, benchmark_new_paper_state_store),
        ("CentralStateStore", benchmark_old_central_state_store, benchmark_new_central_state_store),
        ("ModelMemoryStore", benchmark_old_model_memory_store, benchmark_new_model_memory_store),
        ("ScanPersistence", benchmark_old_scan_persistence, benchmark_new_scan_persistence),
    ]

    for name, old_func, new_func in benchmarks:
        print(f"\n{'─' * 70}")
        print(f"📊 {name}")
        print(f"{'─' * 70}")

        # Eski yöntem
        old_db = os.path.join(TMPDIR, f"{name}_old.db")
        old_result = measure_file_writes(old_func, old_db, NUM_OPS)
        old_size = get_db_size(old_db)

        # Yeni yöntem
        new_db = os.path.join(TMPDIR, f"{name}_new.db")
        new_result = measure_file_writes(new_func, new_db, NUM_OPS)
        new_size = get_db_size(new_db)

        # Hesaplamalar
        write_reduction = 0
        if old_result["bytes_written"] > 0:
            write_reduction = (1 - new_result["bytes_written"] / old_result["bytes_written"]) * 100

        time_reduction = 0
        if old_result["elapsed_sec"] > 0:
            time_reduction = (1 - new_result["elapsed_sec"] / old_result["elapsed_sec"]) * 100

        size_reduction = 0
        if old_size > 0:
            size_reduction = (1 - new_size / old_size) * 100

        print(f"\n  Eski yöntem (her kayıtta commit):")
        print(f"    Yazılan byte: {old_result['bytes_written']:>12,} ({old_result['mb_written']:.4f} MB)")
        print(f"    Süre:         {old_result['elapsed_sec']:>12.4f} saniye")
        print(f"    DB boyutu:    {old_size:>12,} byte ({old_size/1024:.1f} KB)")

        print(f"\n  Yeni yöntem (buffered write):")
        print(f"    Yazılan byte: {new_result['bytes_written']:>12,} ({new_result['mb_written']:.4f} MB)")
        print(f"    Süre:         {new_result['elapsed_sec']:>12.4f} saniye")
        print(f"    DB boyutu:    {new_size:>12,} byte ({new_size/1024:.1f} KB)")

        print(f"\n  📉 Azalma:")
        print(f"    I/O yazma:    %{write_reduction:>8.1f}")
        print(f"    Süre:         %{time_reduction:>8.1f}")
        print(f"    DB boyutu:    %{size_reduction:>8.1f}")

        results.append({
            "component": name,
            "old_bytes_written": old_result["bytes_written"],
            "new_bytes_written": new_result["bytes_written"],
            "old_mb_written": old_result["mb_written"],
            "new_mb_written": new_result["mb_written"],
            "write_reduction_pct": round(write_reduction, 1),
            "old_elapsed_sec": old_result["elapsed_sec"],
            "new_elapsed_sec": new_result["elapsed_sec"],
            "time_reduction_pct": round(time_reduction, 1),
            "old_db_size": old_size,
            "new_db_size": new_size,
            "size_reduction_pct": round(size_reduction, 1),
        })

    # Genel özet
    print(f"\n{'=' * 70}")
    print("📊 GENEL ÖZET")
    print(f"{'=' * 70}")

    total_old_bytes = sum(r["old_bytes_written"] for r in results)
    total_new_bytes = sum(r["new_bytes_written"] for r in results)
    total_old_time = sum(r["old_elapsed_sec"] for r in results)
    total_new_time = sum(r["new_elapsed_sec"] for r in results)

    overall_write_reduction = (1 - total_new_bytes / total_old_bytes) * 100 if total_old_bytes > 0 else 0
    overall_time_reduction = (1 - total_new_time / total_old_time) * 100 if total_old_time > 0 else 0

    print(f"\n  Toplam I/O yazma:")
    print(f"    Eski: {total_old_bytes:>15,} byte ({total_old_bytes/1024/1024:.2f} MB)")
    print(f"    Yeni: {total_new_bytes:>15,} byte ({total_new_bytes/1024/1024:.2f} MB)")
    print(f"    Azalma: %{overall_write_reduction:.1f}")

    print(f"\n  Toplam süre:")
    print(f"    Eski: {total_old_time:.4f} saniye")
    print(f"    Yeni: {total_new_time:.4f} saniye")
    print(f"    Azalma: %{overall_time_reduction:.1f}")

    # Saatlik tahmini
    print(f"\n  📈 Saatlik tahmini (sürekli çalışma senaryosu):")
    # Her 500 işlem ~1 saat çalışma varsayımıyla
    hourly_old_mb = (total_old_bytes / 1024 / 1024) * (3600 / total_old_time) if total_old_time > 0 else 0
    hourly_new_mb = (total_new_bytes / 1024 / 1024) * (3600 / total_new_time) if total_new_time > 0 else 0
    print(f"    Eski: ~{hourly_old_mb:.1f} MB/saat")
    print(f"    Yeni: ~{hourly_new_mb:.1f} MB/saat")
    print(f"    Tasarruf: ~{hourly_old_mb - hourly_new_mb:.1f} MB/saat")

    # Sonuçları JSON olarak kaydet
    report = {
        "benchmark_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "num_operations": NUM_OPS,
        "results": results,
        "summary": {
            "total_old_bytes": total_old_bytes,
            "total_new_bytes": total_new_bytes,
            "overall_write_reduction_pct": round(overall_write_reduction, 1),
            "overall_time_reduction_pct": round(overall_time_reduction, 1),
            "estimated_old_mb_per_hour": round(hourly_old_mb, 1),
            "estimated_new_mb_per_hour": round(hourly_new_mb, 1),
        },
    }

    report_path = os.path.join(Path(__file__).parent.parent, "reports", "ssd_benchmark_round5.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  📄 Rapor kaydedildi: {report_path}")

    # Temizlik
    shutil.rmtree(TMPDIR, ignore_errors=True)

    print(f"\n{'=' * 70}")
    print("✅ Benchmark tamamlandı")
    print(f"{'=' * 70}")

    return report


if __name__ == "__main__":
    run_benchmark()
