"""ALPHA BIST — FeatureAblator ve Redundancy Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak FeatureAblator motorunu, fazlalık analizini ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (FeatureMetrics, FeatureAblationItem, FeatureRedundancyPair, AblationReport).
2. extract_feature_metrics fonksiyonunun güvenli ayrıştırma ve NaN/Inf koruma mekanizmaları.
3. Polars DataFrame üzerinde korelasyon temelli fazlalık (redundancy) analizi ve doğru eleme önerileri.
4. Hızlı analitik ablasyon motoru (run_fast_analytical_ablation) ile IC ve volatilite skorlaması.
5. FeatureAblator başlatma sınır kontrolleri ve boş öznitelik listesinde fail-closed istisnası.
6. DuckDB SSD korumalı WAL denetim izi kaydı ve Polars DataFrame ile geçmiş okuma.
7. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.feature_ablation import (
    AblationImpact,
    AblationReport,
    FeatureAblationItem,
    FeatureAblator,
    FeatureMetrics,
    FeatureRedundancyPair,
    analyze_feature_redundancy_polars,
    extract_feature_metrics,
    read_ablation_history_polars,
    save_ablation_report_to_duckdb,
)


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    metrics_orig = FeatureMetrics(
        cagr_pct=25.5,
        max_drawdown_pct=12.2,
        sharpe_ratio=1.85,
        win_rate_pct=58.0,
        calmar_ratio=2.09,
    )
    m_bytes = metrics_orig.to_orjson_bytes()
    m_restored = FeatureMetrics.from_dict(orjson.loads(m_bytes))
    assert m_restored.sharpe_ratio == 1.85
    assert m_restored.cagr_pct == 25.5
    assert "FeatureMetrics" in repr(metrics_orig)

    item_orig = FeatureAblationItem(
        feature_name="rsi_14",
        baseline_metrics=metrics_orig,
        ablated_metrics=FeatureMetrics(sharpe_ratio=1.50),
        sharpe_diff=-0.35,
        cagr_diff=-5.0,
        maxdd_diff=2.0,
        impact=AblationImpact.BENEFICIAL,
        recommendation="KEEP",
    )
    i_bytes = item_orig.to_orjson_bytes()
    i_restored = FeatureAblationItem.from_dict(orjson.loads(i_bytes))
    assert i_restored.feature_name == "rsi_14"
    assert i_restored.impact == AblationImpact.BENEFICIAL
    assert "FeatureAblationItem" in repr(item_orig)

    pair_orig = FeatureRedundancyPair(
        feature_a="sma_20",
        feature_b="ema_20",
        correlation=0.96,
        is_redundant=True,
        recommended_to_drop="ema_20",
    )
    p_bytes = pair_orig.to_orjson_bytes()
    p_restored = FeatureRedundancyPair.from_dict(orjson.loads(p_bytes))
    assert p_restored.correlation == 0.96
    assert p_restored.recommended_to_drop == "ema_20"
    assert "FeatureRedundancyPair" in repr(pair_orig)

    report_orig = AblationReport(
        study_id="abl_test_001",
        created_at="2026-09-08T12:00:00Z",
        base_features=["rsi_14", "sma_20", "ema_20"],
        baseline_metrics=metrics_orig,
        results=[item_orig],
        redundant_pairs=[pair_orig],
        recommended_drops=["ema_20"],
        retained_features=["rsi_14", "sma_20"],
    )
    r_bytes = report_orig.to_orjson_bytes()
    r_restored = AblationReport.from_dict(orjson.loads(r_bytes))
    assert r_restored.study_id == "abl_test_001"
    assert len(r_restored.results) == 1
    assert r_restored.recommended_drops == ["ema_20"]
    assert "AblationReport" in repr(report_orig)


def test_extract_feature_metrics_safe() -> None:
    """extract_feature_metrics'in güvenli ayrıştırma ve koruma mantığını test eder."""
    # None girdi
    assert extract_feature_metrics(None).sharpe_ratio == 0.0

    # Sözlük girdisi
    d_input = {
        "cagr_pct": 30.5,
        "max_drawdown_pct": "15.0",
        "sharpe_ratio": float("nan"),  # NaN koruması
        "win_rate_pct": 55.0,
    }
    extracted = extract_feature_metrics(d_input)
    assert extracted.cagr_pct == 30.5
    assert extracted.max_drawdown_pct == 15.0
    assert extracted.sharpe_ratio == 0.0  # NaN -> 0.0 olmalı

    # Alternatif anahtar isimleri
    d_alt = {"cagr": 20.0, "maxdd": 10.0, "sharpe": 1.5}
    extracted_alt = extract_feature_metrics(d_alt)
    assert extracted_alt.cagr_pct == 20.0
    assert extracted_alt.sharpe_ratio == 1.5


def test_analyze_feature_redundancy_polars() -> None:
    """Polars DataFrame üzerinde korelasyon analizini ve fazlalık tespitini doğrular."""
    t = np.linspace(0, 10, 100)
    feat1 = np.sin(t)
    feat2 = np.sin(t) + np.random.normal(0, 0.01, size=100)  # Aşırı benzer (corr ~ 0.99)
    feat3 = np.cos(t)  # Bağımsız

    df = pl.DataFrame(
        {
            "feat_sin": feat1,
            "feat_sin_copy": feat2,
            "feat_cos": feat3,
        }
    )

    pairs = analyze_feature_redundancy_polars(df, features=["feat_sin", "feat_sin_copy", "feat_cos"], threshold=0.85)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.is_redundant is True
    assert pair.correlation > 0.85
    assert {pair.feature_a, pair.feature_b} == {"feat_sin", "feat_sin_copy"}

    # Boş veya geçersiz durumlarda boş liste dönmeli
    assert analyze_feature_redundancy_polars(pl.DataFrame(), ["a", "b"]) == []
    assert analyze_feature_redundancy_polars(df, ["feat_sin"]) == []


def test_run_fast_analytical_ablation() -> None:
    """Hızlı analitik ablasyon ile IC ve volatilite skorlamasını test eder."""
    ablator = FeatureAblator(base_features=["feat_a", "feat_b"])

    np.random.seed(42)
    n = 100
    y = np.random.normal(0, 1, n)
    feat_strong = y * 0.8 + np.random.normal(0, 0.2, n)  # Güçlü IC
    feat_weak = np.random.normal(0, 1, n)  # Zayıf IC
    feat_flat = np.full(n, 5.0)  # Sıfır varyans

    df = pl.DataFrame(
        {
            "feat_strong": feat_strong,
            "feat_weak": feat_weak,
            "feat_flat": feat_flat,
        }
    )

    results = ablator.run_fast_analytical_ablation(df, target_returns=y)
    assert len(results) == 2  # feat_flat atlanmalı
    assert results[0]["feature"] == "feat_strong"
    assert results[0]["status"] == "STRONG"
    assert results[0]["information_coefficient"] > 0.5


def test_feature_ablator_initialization_validation() -> None:
    """FeatureAblator başlatılırken boş liste verildiğinde fail-closed istisnası üretildiğini test eder."""
    with pytest.raises(ValueError, match="base_features listesi bos olamaz"):
        FeatureAblator(base_features=[])

    # Yinelenen öznitelikler tekilleştirilmeli
    ablator = FeatureAblator(base_features=["a", "b", "a"])
    assert len(ablator.base_features) == 2
    assert "FeatureAblator" in repr(ablator)


def test_duckdb_wal_save_and_polars_read(tmp_path: Path) -> None:
    """DuckDB WAL ile rapor kaydı ve Polars ile geri okumayı test eder."""
    db_file = str(tmp_path / "ablation_audit.duckdb")

    report = AblationReport(
        study_id="abl_duck_01",
        created_at="2026-09-08T12:00:00Z",
        base_features=["f1", "f2"],
        baseline_metrics=FeatureMetrics(cagr_pct=20.0, sharpe_ratio=1.5),
        results=[],
        redundant_pairs=[],
        recommended_drops=["f2"],
        retained_features=["f1"],
    )

    save_ablation_report_to_duckdb(report, db_path=db_file)

    df_hist = read_ablation_history_polars(db_path=db_file, limit=10)
    assert isinstance(df_hist, pl.DataFrame)
    assert df_hist.height == 1
    assert df_hist["study_id"][0] == "abl_duck_01"
    assert df_hist["baseline_sharpe"][0] == 1.5


def test_thread_safety_ablator() -> None:
    """Çoklu thread ile eşzamanlı hızlı analitik ablasyon çalıştırma güvenliğini test eder."""
    ablator = FeatureAblator(base_features=["f1", "f2"])
    np.random.seed(123)
    y = np.random.normal(0, 1, 50)
    df = pl.DataFrame({"f1": y + 0.1, "f2": y * 0.5})

    def worker(idx: int) -> int:
        res = ablator.run_fast_analytical_ablation(df, target_returns=y)
        return len(res)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            assert f.result() == 2
