#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Scale Benchmark (Production)

Ölçekler: 100 / 500 / 1000 hisse × 1 yıl (252 iş günü, hizalı takvim).

Ölçümler (her ölçekte, panel ve mümkünse legacy yol):
- Toplam süre (wall)
- scans/sec
- Feature hesaplama süresi (engine instrumentation)
- Peak memory (tracemalloc + RSS delta)
- CPU kullanımı (%)

Legacy yol 100 hisseden sonra günler sürer → 500/1000 için ölçülen
per-scan maliyetten ekstrapolasyon yapılır ve açıkça işaretlenir.

Çıktı: reports/scale_benchmark.json + reports/scale_benchmark.md
"""

import os
import resource
import sys
import time
from datetime import datetime, timedelta

import orjson

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import polars as pl
import psutil

from services.backtest.engine_v4 import BacktestConfig, BacktestEngineV4

SCALES = [100, 500, 1000]
DAYS = 252
LOOKBACK = 60
LEGACY_MAX_SCALE = 100  # legacy yol yalnızca bu ölçeğe kadar gerçek çalıştırılır


def make_aligned_market(n_stocks, n_days, seed=42) -> Any:
    """Gerçek BIST gibi: tüm hisseler aynı işlem takvimini paylaşır."""
    rng = np.random.RandomState(seed)
    pl.date_range(
        datetime(2026, 8, 14) - timedelta(days=n_days * 2), datetime(2026, 8, 14), timedelta(days=1), eager=True
    ).tail(n_days)
    market = {}
    for i in range(n_stocks):
        trend = rng.uniform(-0.001, 0.002)
        vol = rng.uniform(0.01, 0.025)
        close = 100 * np.exp(np.cumsum(rng.randn(n_days) * vol + trend))
        high = close * (1 + np.abs(rng.randn(n_days) * 0.008))
        low = close * (1 - np.abs(rng.randn(n_days) * 0.008))
        volume = rng.randint(50000, 500000, n_days).astype(float)
        market[f"STOCK{i:04d}"] = pl.DataFrame(
            {
                "Open": close * (1 + rng.randn(n_days) * 0.002),
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            }
        )
    return market


def measure(engine, market) -> Any:
    """Tek run ölçümü."""
    proc = psutil.Process()
    rss_before = proc.memory_info().rss
    peak_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB (Linux)
    cpu_before = proc.cpu_times()

    t0 = time.perf_counter()
    result = engine.run(market, persist=False)
    wall = time.perf_counter() - t0

    cpu_after = proc.cpu_times()
    rss_after = proc.memory_info().rss
    peak_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    cpu_time = (cpu_after.user - cpu_before.user) + (cpu_after.system - cpu_before.system)
    return {
        "wall_seconds": round(wall, 2),
        "total_scans": result.total_scans,
        "scans_per_second": round(result.total_scans / max(wall, 1e-9), 1),
        "trades": result.trades_executed,
        "feature_seconds": round(engine._last_feature_seconds, 2),
        "panel_seconds": round(engine._last_panel_seconds, 2),
        "scalar_fallbacks": engine._last_scalar_fallbacks,
        # ru_maxrss: çekirdek tarafından tutulan GERÇEK peak RSS (süreç geneli).
        # Run içi tepe artışı: peak_after - peak_before (yeni tepe oluştuysa).
        "peak_rss_mb": round(peak_after / 1024, 1),
        "peak_run_delta_mb": round(max(0, peak_after - peak_before) / 1024, 1),
        "rss_delta_mb": round((rss_after - rss_before) / 1e6, 1),
        "cpu_percent": round(cpu_time / max(wall, 1e-9) * 100, 1),
        "total_return_pct": result.metrics.total_return_pct,
    }


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 78)
    logger.info("  ALPHA BIST — Scale Benchmark (100/500/1000 hisse × 1 yıl)")
    logger.info("=" * 78)

    report = {"date": datetime.now().isoformat(), "days": DAYS, "lookback": LOOKBACK, "scales": {}}

    legacy_cost_per_scan = None  # 100 hisseden ölçülen gerçek maliyet

    for scale in SCALES:
        logger.info(f"\n--- {scale} hisse × {DAYS} gün ---")
        market = make_aligned_market(scale, DAYS)
        cfg = BacktestConfig(lookback_days=LOOKBACK, initial_capital=100000)
        entry = {}

        # --- Panel (yeni) yol: her ölçekte gerçek ölçüm ---
        engine_new = BacktestEngineV4(cfg, use_panel_features=True)
        entry["panel"] = measure(engine_new, market)
        logger.info(
            f"  PANEL : {entry['panel']['wall_seconds']:>8.2f}s | "
            f"{entry['panel']['scans_per_second']:>10,.0f} scans/s | "
            f"feature {entry['panel']['feature_seconds']:.2f}s | "
            f"peak {entry['panel']['peak_rss_mb']:.0f}MB | "
            f"CPU %{entry['panel']['cpu_percent']:.0f}"
        )

        # --- Legacy yol: 100 hisseye kadar gerçek, sonrası ekstrapolasyon ---
        if scale <= LEGACY_MAX_SCALE:
            engine_old = BacktestEngineV4(cfg, use_panel_features=False)
            entry["legacy"] = measure(engine_old, market)
            legacy_cost_per_scan = entry["legacy"]["wall_seconds"] / max(entry["legacy"]["total_scans"], 1)
            logger.info(
                f"  LEGACY: {entry['legacy']['wall_seconds']:>8.2f}s | "
                f"{entry['legacy']['scans_per_second']:>10,.0f} scans/s | "
                f"feature {entry['legacy']['feature_seconds']:.2f}s | "
                f"peak {entry['legacy']['peak_rss_mb']:.0f}MB | "
                f"CPU %{entry['legacy']['cpu_percent']:.0f}"
            )

            # Eşdeğerlilik doğrulaması (aynı veri)
            same = (
                entry["legacy"]["total_scans"] == entry["panel"]["total_scans"]
                and entry["legacy"]["trades"] == entry["panel"]["trades"]
                and entry["legacy"]["total_return_pct"] == entry["panel"]["total_return_pct"]
            )
            entry["equivalence_verified"] = same
            logger.info(f"  EŞDEĞERLİK: {'✓ BİREBİR' if same else '✗ FARK VAR'}")
        else:
            # Ekstrapolasyon: ölçülen per-scan maliyeti × beklenen scan sayısı
            est_scans = entry["panel"]["total_scans"]  # aynı kontrol akışı → aynı scan sayısı
            est_wall = legacy_cost_per_scan * est_scans
            entry["legacy_extrapolated"] = {
                "wall_seconds": round(est_wall, 1),
                "total_scans": est_scans,
                "scans_per_second": round(est_scans / max(est_wall, 1e-9), 1),
                "note": (
                    f"100 hisse ölçümünden ekstrapolasyon "
                    f"({legacy_cost_per_scan * 1000:.2f} ms/scan); gerçek çalıştırma yapılmadı"
                ),
            }
            logger.info(f"  LEGACY: ~{est_wall:,.0f}s (ekstrapolasyon, {legacy_cost_per_scan * 1000:.2f} ms/scan)")

        if "legacy" in entry:
            entry["speedup"] = round(entry["legacy"]["wall_seconds"] / max(entry["panel"]["wall_seconds"], 1e-9), 1)
        else:
            entry["speedup"] = round(
                entry["legacy_extrapolated"]["wall_seconds"] / max(entry["panel"]["wall_seconds"], 1e-9), 1
            )
        logger.info(f"  HIZLANMA: ~{entry['speedup']}×")

        report["scales"][str(scale)] = entry
        del market

    os.makedirs("reports", exist_ok=True)
    with open("reports/scale_benchmark.json", "w") as f:
        f.write(orjson.dumps(report, option=orjson.OPT_INDENT_2).decode())

    # Markdown özet
    lines = [
        "# ALPHA BIST — Scale Benchmark\n",
        f"Tarih: {report['date']} | {DAYS} gün | lookback={LOOKBACK}\n",
        "| Ölçek | Yol | Süre | scans/s | Feature süresi | Peak mem | CPU |",
        "|---|---|---|---|---|---|---|",
    ]
    for scale, e in report["scales"].items():
        p = e["panel"]
        lines.append(
            f"| {scale}h/1y | **panel (yeni)** | {p['wall_seconds']}s | {p['scans_per_second']:,} | "
            f"{p['feature_seconds']}s | {p['peak_rss_mb']}MB | %{p['cpu_percent']} |"
        )
        if "legacy" in e:
            l = e["legacy"]
            lines.append(
                f"| {scale}h/1y | legacy (eski) | {l['wall_seconds']}s | {l['scans_per_second']:,} | "
                f"{l['feature_seconds']}s | {l['peak_rss_mb']}MB | %{l['cpu_percent']} |"
            )
        else:
            l = e["legacy_extrapolated"]
            lines.append(
                f"| {scale}h/1y | legacy (eski, ekstra.) | ~{l['wall_seconds']:,.0f}s | {l['scans_per_second']:,} | - | - | - |"
            )
        lines.append(f"| {scale}h/1y | **hızlanma** | **~{e['speedup']}×** | | | | |")
    with open("reports/scale_benchmark.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    logger.info("\nRapor: reports/scale_benchmark.json, reports/scale_benchmark.md")
    return report


if __name__ == "__main__":
    main()
