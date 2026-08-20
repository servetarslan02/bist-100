"""
ALPHA BIST — Teknoloji Benchmark'ları
Her teknolojinin değerini kanıtlamak için gerçek benchmark'lar.

Çalıştırma:
    python benchmarks/tech_benchmarks.py
"""

import time
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def benchmark_json_serialization():
    """ORJSON vs json — API response hız karşılaştırması."""
    import json as stdlib_json
    import orjson

    # Test data — gerçekçi API response'u
    data = {
        "signals": [
            {
                "ticker": f"THYAO{i}",
                "score": 0.85 + i * 0.01,
                "regime": "BULL",
                "features": {"momentum": 0.12, "rsi": 65.4, "volume_ratio": 1.3},
                "timestamp": "2026-08-21T04:58:00Z",
            }
            for i in range(1000)
        ],
        "metadata": {"total": 1000, "page": 1, "timestamp": "2026-08-21T04:58:00Z"},
    }

    # Warmup
    for _ in range(100):
        stdlib_json.dumps(data)
        orjson.dumps(data)

    # Benchmark json
    iterations = 10000
    start = time.perf_counter()
    for _ in range(iterations):
        stdlib_json.dumps(data)
    json_time = time.perf_counter() - start

    # Benchmark orjson
    start = time.perf_counter()
    for _ in range(iterations):
        orjson.dumps(data)
    orjson_time = time.perf_counter() - start

    speedup = json_time / orjson_time

    return {
        "test": "JSON Serialization (ORJSON vs json)",
        "json_time_s": round(json_time, 4),
        "orjson_time_s": round(orjson_time, 4),
        "speedup": f"{speedup:.1f}x",
        "iterations": iterations,
        "data_size": f"{len(str(data))} chars",
    }


def benchmark_dataframe():
    """Polars vs Pandas — DataFrame işlem hız karşılaştırması."""
    try:
        import polars as pl
        import pandas as pd
        import numpy as np

        # Test data — BIST benzeri OHLCV verisi
        n_rows = 100_000
        dates = pd.date_range("2020-01-01", periods=n_rows, freq="min")
        np.random.seed(42)
        data = {
            "date": dates,
            "ticker": np.random.choice(["THYAO", "GARAN", "ASELS", "KCHOL", "SAHOL"], n_rows),
            "open": np.random.uniform(100, 200, n_rows),
            "high": np.random.uniform(100, 200, n_rows),
            "low": np.random.uniform(100, 200, n_rows),
            "close": np.random.uniform(100, 200, n_rows),
            "volume": np.random.randint(100000, 10000000, n_rows),
        }

        # Pandas benchmark
        start = time.perf_counter()
        for _ in range(10):
            df_pd = pd.DataFrame(data)
            result_pd = df_pd.groupby("ticker").agg(
                {"close": "mean", "volume": "sum", "high": "max", "low": "min"}
            )
        pandas_time = time.perf_counter() - start

        # Polars benchmark
        start = time.perf_counter()
        for _ in range(10):
            df_pl = pl.DataFrame(data)
            result_pl = (
                df_pl.lazy()
                .group_by("ticker")
                .agg(
                    [
                        pl.col("close").mean(),
                        pl.col("volume").sum(),
                        pl.col("high").max(),
                        pl.col("low").min(),
                    ]
                )
                .collect()
            )
        polars_time = time.perf_counter() - start

        speedup = pandas_time / polars_time

        return {
            "test": "DataFrame Processing (Polars vs Pandas)",
            "pandas_time_s": round(pandas_time, 4),
            "polars_time_s": round(polars_time, 4),
            "speedup": f"{speedup:.1f}x",
            "rows": n_rows,
            "iterations": 10,
        }
    except ImportError as e:
        return {"test": "DataFrame Processing", "error": str(e)}


def benchmark_ml_training():
    """LightGBM vs CatBoost vs XGBoost — Training hız karşılaştırması."""
    try:
        import lightgbm as lgb
        import xgboost as xgb
        from catboost import CatBoostClassifier
        import numpy as np
        from sklearn.datasets import make_classification

        # Test data — BIST benzeri classification
        X, y = make_classification(
            n_samples=50000,
            n_features=100,
            n_informative=50,
            n_redundant=20,
            n_classes=2,
            random_state=42,
        )

        # Split
        split = int(0.8 * len(X))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        results = {"test": "ML Training (LightGBM vs CatBoost vs XGBoost)", "models": {}}

        # LightGBM
        start = time.perf_counter()
        lgb_train = lgb.Dataset(X_train, y_train)
        lgb_val = lgb.Dataset(X_val, y_val, reference=lgb_train)
        params = {"objective": "binary", "metric": "auc", "verbose": -1, "n_jobs": -1}
        model_lgb = lgb.train(params, lgb_train, num_boost_round=100, valid_sets=[lgb_val])
        lgb_time = time.perf_counter() - start
        lgb_pred = model_lgb.predict(X_val)
        lgb_auc = _compute_auc(y_val, lgb_pred)
        results["models"]["lightgbm"] = {
            "time_s": round(lgb_time, 4),
            "auc": round(lgb_auc, 4),
        }

        # XGBoost
        start = time.perf_counter()
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dval = xgb.DMatrix(X_val, label=y_val)
        params_xgb = {"objective": "binary:logistic", "eval_metric": "auc", "nthread": -1}
        model_xgb = xgb.train(params_xgb, dtrain, num_boost_round=100, evals=[(dval, "val")], verbose_eval=False)
        xgb_time = time.perf_counter() - start
        xgb_pred = model_xgb.predict(dval)
        xgb_auc = _compute_auc(y_val, xgb_pred)
        results["models"]["xgboost"] = {
            "time_s": round(xgb_time, 4),
            "auc": round(xgb_auc, 4),
        }

        # CatBoost
        start = time.perf_counter()
        model_cb = CatBoostClassifier(iterations=100, verbose=0, eval_metric="AUC")
        model_cb.fit(X_train, y_train, eval_set=(X_val, y_val))
        cb_time = time.perf_counter() - start
        cb_pred = model_cb.predict_proba(X_val)[:, 1]
        cb_auc = _compute_auc(y_val, cb_pred)
        results["models"]["catboost"] = {
            "time_s": round(cb_time, 4),
            "auc": round(cb_auc, 4),
        }

        # Ensemble (simple average)
        ensemble_pred = (lgb_pred + xgb_pred + cb_pred) / 3
        ensemble_auc = _compute_auc(y_val, ensemble_pred)
        results["ensemble"] = {
            "auc": round(ensemble_auc, 4),
            "improvement_vs_best_single": f"{(ensemble_auc - max(lgb_auc, xgb_auc, cb_auc)) * 100:.2f}%",
        }

        return results
    except ImportError as e:
        return {"test": "ML Training", "error": str(e)}


def _compute_auc(y_true, y_pred):
    """AUC hesapla (scikit-learn olmadan)."""
    try:
        from sklearn.metrics import roc_auc_score
        return roc_auc_score(y_true, y_pred)
    except ImportError:
        # Manuel AUC hesaplama (basit)
        n = len(y_true)
        pos = sum(1 for y in y_true if y == 1)
        neg = n - pos
        if pos == 0 or neg == 0:
            return 0.5

        # Sort by prediction
        pairs = sorted(zip(y_pred, y_true), reverse=True)
        tp = 0
        fp = 0
        auc = 0.0
        prev_pred = None
        for pred, label in pairs:
            if prev_pred is not None and pred != prev_pred:
                auc += tp * (fp - (fp - (1 if label == 0 else 0)))
            if label == 1:
                tp += 1
            else:
                fp += 1
            prev_pred = pred
        auc += tp * (fp - 0)
        return auc / (pos * neg)


def run_all_benchmarks():
    """Tüm benchmark'ları çalıştır."""
    print("=" * 60)
    print("ALPHA BIST — Teknoloji Benchmark'ları")
    print("=" * 60)
    print()

    results = []

    # 1. JSON Serialization
    print("1. JSON Serialization (ORJSON vs json)...")
    r1 = benchmark_json_serialization()
    results.append(r1)
    print(f"   json: {r1['json_time_s']}s | orjson: {r1['orjson_time_s']}s | Hız: {r1['speedup']}")
    print()

    # 2. DataFrame Processing
    print("2. DataFrame Processing (Polars vs Pandas)...")
    r2 = benchmark_dataframe()
    results.append(r2)
    if "error" not in r2:
        print(f"   pandas: {r2['pandas_time_s']}s | polars: {r2['polars_time_s']}s | Hız: {r2['speedup']}")
    else:
        print(f"   Hata: {r2['error']}")
    print()

    # 3. ML Training
    print("3. ML Training (LightGBM vs CatBoost vs XGBoost)...")
    r3 = benchmark_ml_training()
    results.append(r3)
    if "error" not in r3:
        for name, data in r3["models"].items():
            print(f"   {name}: {data['time_s']}s | AUC: {data['auc']}")
        print(f"   Ensemble AUC: {r3['ensemble']['auc']} | İyileştirme: {r3['ensemble']['improvement_vs_best_single']}")
    else:
        print(f"   Hata: {r3['error']}")
    print()

    # Save results
    output_path = "benchmarks/benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Sonuçlar kaydedildi: {output_path}")

    return results


if __name__ == "__main__":
    run_all_benchmarks()
