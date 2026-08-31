"""ALPHA BIST — FAZ 0: Baseline Profiling (Mevcut Sistem Durumu Ölçümü).

Bu betik hiçbir şeyi değiştirmeden, mevcut sistemin gerçek performans metriklerini ölçer:
1. Canlı Piyasa Verisi Çekme (647 hisse)
2. 70 Kanonik Feature Hesaplama Süresi
3. ML Modelleri Çıkarım Süreleri (LightGBM, CatBoost, XGBoost)
4. Portföy Tahsis Motoru Yürütme Süresi (AutonomousConvictionEngine)
5. Veritabanı ve Önbellek Erişim Gecikmeleri
6. RAM & CPU Kaynak Kullanımı
7. Çıktıyı 'data/baseline_profile.json' dosyasına kaydetme
"""

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import structlog

from services.portfolio.autonomous_conviction_engine import (
    AutonomousConvictionEngine,
    CandidateAsset,
)
from services.scanner.bist_ml_scanner import bist_ml_scanner

logger = structlog.get_logger(__name__)


def measure_system_resources():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return {
        "process_ram_mb": round(mem_info.rss / (1024 * 1024), 2),
        "system_cpu_pct": psutil.cpu_percent(interval=0.1),
        "total_ram_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 2),
    }


def profile_feature_and_market_data():
    print("  [1/4] Canlı Piyasa ve 70 Feature Hesaplama Süresi Ölçülüyor...")
    t0 = time.perf_counter()
    live_rows = bist_ml_scanner._fetch_live_scanner_data()
    dur_data_fetch = time.perf_counter() - t0

    # 647 hisse için 70 feature ve tarama süresi
    t0 = time.perf_counter()
    opps = bist_ml_scanner.scan_all_opportunities(limit=50, force_warehouse=False)
    dur_full_scan = time.perf_counter() - t0

    return {
        "num_stocks_fetched": len(live_rows),
        "data_fetch_seconds": round(dur_data_fetch, 4),
        "full_scan_70_features_seconds": round(dur_full_scan, 4),
        "avg_feature_calc_per_stock_ms": round((dur_full_scan / max(len(live_rows), 1)) * 1000, 2),
        "opportunities_generated": len(opps),
    }


def profile_ml_inference_latency():
    print("  [2/4] ML Modelleri Çıkarım (Inference) Gecikmeleri Ölçülüyor...")
    bist_ml_scanner.load_models()

    # 647 hisse için 70 feature sentetik matris
    n_stocks = 647
    def _get_model_features(model):
        if model is None:
            return [f"f_{i}" for i in range(70)]
        if hasattr(model, "feature_name_"):
            return list(model.feature_name_)
        if hasattr(model, "booster_") and hasattr(model.booster_, "feature_name"):
            return list(model.booster_.feature_name())
        if hasattr(model, "feature_names_in_"):
            return list(model.feature_names_in_)
        if hasattr(model, "feature_name") and callable(model.feature_name):
            return list(model.feature_name())
        return [f"f_{i}" for i in range(70)]

    feat_names = _get_model_features(bist_ml_scanner.models.get("lightgbm", None))
    sample_df = pd.DataFrame(np.random.randn(n_stocks, len(feat_names)), columns=feat_names)

    timings = {}

    # LightGBM
    if "lightgbm" in bist_ml_scanner.models:
        t0 = time.perf_counter()
        for _ in range(5):
            _ = bist_ml_scanner.models["lightgbm"].predict(sample_df)
        timings["lightgbm_batch_647_ms"] = round(((time.perf_counter() - t0) / 5) * 1000, 2)
    else:
        timings["lightgbm_batch_647_ms"] = None

    # CatBoost
    if "catboost" in bist_ml_scanner.models:
        t0 = time.perf_counter()
        for _ in range(5):
            _ = bist_ml_scanner.models["catboost"].predict(sample_df)
        timings["catboost_batch_647_ms"] = round(((time.perf_counter() - t0) / 5) * 1000, 2)
    else:
        timings["catboost_batch_647_ms"] = None

    # XGBoost
    if "xgboost" in bist_ml_scanner.models:
        t0 = time.perf_counter()
        for _ in range(5):
            _ = bist_ml_scanner.models["xgboost"].predict(sample_df)
        timings["xgboost_batch_647_ms"] = round(((time.perf_counter() - t0) / 5) * 1000, 2)
    else:
        timings["xgboost_batch_647_ms"] = None

    return timings


def profile_portfolio_allocation():
    print("  [3/4] Portföy Tahsis Motoru (AutonomousConvictionEngine) Ölçülüyor...")
    engine = AutonomousConvictionEngine()

    # 100 aday hisse
    candidates = [
        CandidateAsset(
            ticker=f"STOCK_{i}",
            confidence_score=0.50 + (i % 50) / 100.0,
            expected_return=0.10 + (i % 30) / 100.0,
            volatility=0.20 + (i % 15) / 100.0,
            sector="SANAYI" if i % 2 == 0 else "BANKA",
            current_price=10.0 + i,
        )
        for i in range(100)
    ]

    t0 = time.perf_counter()
    for _ in range(10):
        plan = engine.allocate_conviction_portfolio(candidates, market_regime="SIDEWAYS")
    dur = (time.perf_counter() - t0) / 10

    return {
        "portfolio_allocation_duration_ms": round(dur * 1000, 2),
        "selected_positions": plan.num_positions,
        "cash_weight_pct": round(plan.cash_weight * 100, 2),
    }


def profile_cache_and_store():
    print("  [4/4] Veritabanı ve Önbellek Erişim Gecikmeleri Ölçülüyor...")
    from services.core.redis_helper import get_cached, set_cached

    # Redis Latency
    t0 = time.perf_counter()
    for i in range(50):
        set_cached(f"test_key_{i}", {"val": i}, ttl=60)
        _ = get_cached(f"test_key_{i}")
    redis_dur_ms = round(((time.perf_counter() - t0) / 50) * 1000, 3)

    return {
        "redis_roundtrip_ms": redis_dur_ms,
    }


def run_full_baseline_profile():
    print("=" * 80)
    print("ALPHA BIST — FAZ 0: BASELINE PROFILING (MEVCUT DURUM ÖLÇÜMÜ)")
    print("=" * 80)

    res_init = measure_system_resources()
    feature_metrics = profile_feature_and_market_data()
    ml_metrics = profile_ml_inference_latency()
    portfolio_metrics = profile_portfolio_allocation()
    cache_metrics = profile_cache_and_store()
    res_final = measure_system_resources()

    baseline_report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "resources_start": res_init,
        "resources_end": res_final,
        "feature_and_market_data": feature_metrics,
        "ml_inference": ml_metrics,
        "portfolio_engine": portfolio_metrics,
        "cache_and_storage": cache_metrics,
    }

    out_path = Path("data/baseline_profile.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(baseline_report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"✅ FAZ 0 TAMAMLANDI: Temel Profil Raporu Kaydedildi -> {out_path}")
    print("=" * 80)
    print(json.dumps(baseline_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run_full_baseline_profile()
